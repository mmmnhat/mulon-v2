# Tài liệu kỹ thuật chi tiết cho AI agent dev (MuLon)

> Tài liệu này bổ sung cho `AGENTS.md` ở gốc repo. `AGENTS.md` là
> LUẬT; file này là SỔ TAY KỸ THUẬT: kiến trúc nằm ở đâu, dữ liệu
> nằm ở đâu, muốn đổi một thứ thì sửa file nào. **Đọc cả hai trước
> khi sửa code.** Mọi con số trong file này được trích từ code thật
> tại version 1.6.4 (26/10/2026) — khi code đổi, cập nhật file này
> trong cùng commit.

## 0. Nguyên tắc số 0: KHÔNG HARDCODE BẤT CỨ GÌ

Đây là nguyên tắc quan trọng nhất của dự án, do chủ dự án yêu cầu
trực tiếp. "Hardcode" nghĩa là: một giá trị có thể thay đổi theo
máy, theo người, theo phiên chạy, theo thời gian, hoặc theo quyết
định của chủ dự án — mà lại bị gõ chết vào file `.py`.

Trước khi viết bất kỳ giá trị cụ thể nào vào code, tự hỏi 4 câu:

1. Giá trị này có đổi nếu chạy trên máy khác không?
2. Có đổi nếu người dùng là người khác không?
3. Có đổi theo phiên/tunnel/thời gian không?
4. Chủ dự án có thể muốn đổi nó mà không cần lập trình viên không?

**Một câu trả lời "có" => giá trị đó KHÔNG được nằm trong code.**
Tra bảng ở mục 5 để biết nó phải nằm ở đâu.

Lịch sử thật (đừng lặp lại — đợt vá 1.6.4 ngày 26/10/2026 chỉ để
gỡ những thứ này):

- Email cá nhân của chủ dự án gõ chết trong `telegram_bot.py` khi
  gọi auth probe của Google MCP.
- Một URL tunnel trycloudflare (URL tạm, sống vài giờ) gõ chết
  trong `config/mcp_servers.json` làm `GOOGLE_OAUTH_REDIRECT_URI`
  => OAuth chết mỗi lần tunnel đổi.
- 93 symlink `skills/*` trỏ path tuyệt đối `/Users/<user>/...`
  commit lên repo => máy khác gãy toàn bộ.
- 155 chuỗi từ khóa router + 76 marker học tập + danh sách nguồn
  tin + 9 prompt hệ thống nhúng trong `.py` => đổi hành vi là phải
  sửa code, chạy lại deploy.

## 1. Bản đồ kiến trúc

Luồng một tin nhắn:

```
Telegram user
  -> mulon/telegram_bot.py  (aiogram, bề mặt duy nhất; auth _is_allowed)
  -> mulon/agent.py         (Agent: classify_intent -> fast path | task path)
       -> mulon/context.py  (dựng context: dossier + memory recall + history)
       -> mulon/gateway.py  (ModelGateway: MỌI lời gọi LLM đi qua đây)
       |     -> proxy local 127.0.0.1:8317 (LiteLLM) -> model
       -> mulon/tools.py    (ToolRegistry: tool lõi + connector + MCP)
       -> verify loop (VERIFY_SYSTEM, tối đa verify_max_retries lần)
  -> trả lời + ghi memory (mulon/memory.py) + trajectory (đã redact)
```

Boot (`mulon/main.py`): init DB -> nạp dossier -> dựng registry ->
policy -> agent -> bot -> (tuỳ chọn) Mini App server, MCP manager,
feed runner, proactivity, consolidation. Mọi thành phần phụ đều
**degrade**: thiếu thì log + tắt phần đó, bot vẫn chạy.

Module theo nhóm (trích docstring của chính file — mở file ra đọc
tiếp trước khi sửa):

| Nhóm | File | Trách nhiệm |
|---|---|---|
| Lõi agent | `agent.py` | Vòng lặp plan-act-verify, router intent, fast/task path |
| | `context.py` | Context engine: dossier + recall + history, trim tool result |
| | `gateway.py` | Model gateway: alias model, circuit breaker, đóng gói multimodal, đếm token |
| | `tools.py` | ToolRegistry + tool lõi (file, web, lệnh...), neo đường dẫn + denylist |
| | `planning.py` | Scheduler + goals/tracking |
| | `subagents.py` | Subagent theo profile |
| | `approvals.py` | ApprovalBroker: thẻ duyệt giữa agent và bề mặt |
| | `policy.py` | Policy engine 2 lớp (quyền theo tool/hành động) |
| Trí nhớ | `memory.py` | SQLite WAL + FTS5 + fact bi-temporal (valid_from/to, supersedes) |
| | `embeddings.py` | Hybrid recall vector + BM25 (70/30 theo config) |
| | `consolidation.py` | Worker chắt lọc ký ức nền |
| | `learning.py` | Học từ correction của user (marker ở file JSON, mục 5) |
| Bề mặt | `telegram_bot.py` | Handler Telegram: tin nhắn, ảnh, voice, lệnh, thẻ duyệt, OAuth callback |
| | `webapp_server.py` | Backend Mini App (aiohttp, chỉ bind localhost, HMAC initData) |
| | `webapp/` | Frontend Mini App (HTML/CSS/JS thuần) |
| | `surfaces.py` | Logic bề mặt group/forum, side chat |
| | `voice.py` | Voice 2 chiều: Whisper nghe + TTS trả lời |
| Kết nối | `mcp_client.py` | MCP client stdio + streamable HTTP, nạp `config/mcp_servers.json` |
| | `marketplace.py` | Chợ MCP: catalog, cài/gỡ, smoke test, ghi `mcp_servers.json` |
| | `marketplace_providers.py` / `marketplace_store.py` | Nguồn catalog / sổ bền của chợ |
| | `connectors.py` | Khung connector trung tính |
| | `google_conn.py` | Connector Google đời cũ (chỉ chạy khi `GOOGLE_LEGACY_CONNECTORS=1`; đường chính nay là google-workspace MCP) |
| Nội dung | `feed.py` | Feed engine: thu thập nguồn, chấm tin cậy, viết bài |
| | `feed_auto.py` | Runner Feed theo lịch (cron trong config) |
| | `websearch.py` | Search (Bing/DDG) + đọc trang cho collector |
| | `browser_worker.py` | Browser worker tối thiểu cho tool |
| | `media_tools.py` | Media: ffmpeg trên máy + sinh ảnh (proxy hoặc endpoint ngoài qua config) |
| Hệ thống | `config.py` | `Config`: 104 field, nạp từ env/.env — xem mục 4 |
| | `datafiles.py` | Loader dữ liệu: `load_json_data`, `load_prompt` — xem mục 5 |
| | `vault.py` | Secure Vault: secret mã hoá tuỳ chọn, file 0600 |
| | `hooks.py` | Hook subsystem: polling script trong `hooks/<id>/` (dữ liệu runtime, KHÔNG commit hook cá nhân) |
| | `ideas.py` | Thẻ ý tưởng có hạn sống |
| | `proactivity.py` | Heartbeat gom việc chủ động |
| | `cron.py` | Cron 5 trường tự viết |
| | `skills.py` | SkillCatalog: quét `skills/` + kho máy (`~/.agents/skills`, `~/.openclaw/skills`, `~/.hermes/skills`) |
| | `library.py` | Kho file agent tạo cho user + share link (token lưu dạng hash) |
| | `evals.py` | Eval vàng offline (stub) + cổng chất lượng |
| | `backup.py`, `report.py`, `tracing.py` | Sao lưu/khôi phục, báo cáo sức khoẻ, Langfuse tuỳ chọn |
| | `evolution.py` | Tool tự tiến hoá: bot tự đọc/sửa code của nó (vẫn qua denylist + duyệt) |

## 2. Dữ liệu nằm ở đâu (ngoài code)

```
mulon-v2/
  .env                  bí mật + cấu hình theo máy (KHÔNG commit; mẫu: .env.example)
  config/
    policy.json         quyền theo nhóm/tool/hành động (default + groups + tools)
    mcp_servers.json    MCP server đang cài (marketplace ghi file này)
    marketplace_curated.json  catalog curated (có content_sha256)
    intent_hints.json   router: tool_hints(155) long_hints(9) action_promises(12) followup_hints(10)
    learning_markers.json     strong(31) weak(28) critical(17) category_hints(5 nhóm)
    feed_sources.json   news_domains(21) official_suffixes low_signal_tlds stopwords(34)
    mcp_fallbacks.json  14 công thức cài MCP quen thuộc (KNOWN_MCP_FALLBACKS cũ)
  mulon/prompts/*.txt   9 prompt hệ thống (mục 5)
  dossier/*.md          persona + ký ức runtime của bot (dữ liệu chủ dự án)
  data/                 DB, vault, artifact... (runtime, gitignore)
  workspace/            workspace runtime của bot (gitignore)
  hooks/<id>/           hook runtime theo máy (gitignore, trừ README)
```

## 3. Chạy và kiểm chứng

```bash
.venv/bin/python -m mulon.main --dry-run   # smoke: nạp config, không cần token
.venv/bin/python -m mulon.main             # chạy bot thật
.venv/bin/python -m pytest tests/ -q       # TOÀN BỘ test (1.6.4: 446)
.venv/bin/python -m mulon.evals            # eval vàng stub (chuẩn 30/30, cổng 85%)
```

- Sửa module nào thì chạy test của module đó trước, nhưng commit
  chỉ khi **toàn bộ** suite xanh.
- Đụng agent loop/router/prompt: bắt buộc chạy thêm evals.
- Test dùng fixture `cfg` trong `tests/conftest.py` (Config trỏ
  vào tmp dir) — viết test mới theo mẫu sẵn có trong thư mục
  `tests/`, một hành vi một test, tên test nói rõ hành vi.

## 4. Config: `mulon/config.py`

- `Config` có **104 field**, `Config.load()` nạp `.env` (dotenv)
  rồi đọc **89 biến env**. Thêm field mới PHẢI đủ 3 nơi:
  (1) khai báo field + default trong dataclass, (2) gán trong
  `Config.load()` qua `_env/_env_bool/_env_int/_env_float`,
  (3) ghi vào `.env.example` (comment tiếng Việt, không giá trị thật).
- Nhóm field chính: proxy/model (`PROXY_BASE_URL`, `MODEL_BRAIN`,
  `MODEL_CHEAP`, `MODEL_ESCALATED` — 3 tier PHẢI khác default),
  Telegram (`TELEGRAM_BOT_TOKEN`, `ALLOWED_USER_ID`,
  `BOT_USERNAME`), đường dẫn (`MULON_DB_PATH`, `MULON_DOSSIER_DIR`,
  `MULON_WORKSPACE_DIR`, `MULON_ARTIFACT_DIR`, `POLICY_PATH`,
  `MCP_CONFIG_PATH`, `SKILLS_DIR`), ngân sách context/task
  (`CONTEXT_WINDOW_TOKENS`, `HISTORY_TOKEN_BUDGET`,
  `MAX_TASK_SECONDS`, `VERIFY_MAX_RETRIES`...), tính năng nền —
  mặc định TẮT (`SCHEDULER_ENABLED`, `CONSOLIDATION_ENABLED`,
  `PROACTIVITY_ENABLED`, `IDEAS_AUTO_ENABLED`), Feed
  (`FEED_AUTO_CRON`, `FEED_QUIET_HOURS`,
  `FEED_MAX_POSTS_PER_DAY`...), Google (`GOOGLE_CLIENT_ID`,
  `GOOGLE_CLIENT_SECRET`, `GOOGLE_USER_EMAIL`,
  `GOOGLE_LEGACY_CONNECTORS`), media (`IMAGE_GEN_ENDPOINT`,
  `IMAGE_GEN_MODEL`), Mini App (`WEBAPP_URL`, `WEBAPP_APP_NAME`,
  `WEBAPP_PORT`), Vault (`VAULT_PATH`, `VAULT_PORT`,
  `VAULT_ENCRYPTION_KEY`), marketplace (`MARKETPLACE_ENABLED`,
  `MARKETPLACE_CATALOG_URL`...).
- Múi giờ: hằng `DEFAULT_TIMEZONE` trong `config.py` — module
  khác import về dùng, không gõ lại chuỗi `"Asia/Ho_Chi_Minh"`.
- `validate_proxy_base_url()`: fail-fast nếu proxy không phải
  localhost:8317 (trừ khi `MULON_ALLOW_REMOTE_PROXY=1`). KHÔNG nới.

## 5. Dữ liệu hoá thay vì hardcode — cách dùng loader

`mulon/datafiles.py` là đường duy nhất để code lấy dữ liệu/prompt:

```python
from .datafiles import load_json_data, load_prompt

_DATA = load_json_data("intent_hints.json", {})      # đọc config/intent_hints.json, lỗi -> fallback + log
TOOL_HINTS = tuple(_DATA.get("tool_hints", ()))
VERIFY_SYSTEM = load_prompt("verify_system")          # đọc mulon/prompts/verify_system.txt nguyên văn
```

- Loader có cache theo tiến trình; sửa file JSON/txt xong phải
  restart bot mới có hiệu lực (đúng ý đồ: dữ liệu đổi không cần
  sửa code, nhưng vẫn qua restart có kiểm soát).
- 9 prompt hiện có trong `mulon/prompts/`: `verify_system`
  (agent), `extract_system` (consolidation), `classify_system`
  (learning), `proactivity_check_system`, `voice_understand_system`,
  `feed_default_brief`, `feed_template`, `feed_legacy_system`,
  `feed_pipeline_system` (feed). Prompt mới => tạo `.txt` mới +
  `load_prompt`, KHÔNG viết chuỗi prompt trong `.py`.
- `config/mcp_servers.json`: giá trị env của server được phép
  dùng placeholder `${BIẾN}` — `mcp_client.load_server_configs`
  mở rộng từ environ (và `WEBAPP_URL` được MCPManager cầu từ
  Config sang). Biến thiếu => key đó bị bỏ + log cảnh báo. Điển
  hình: `"GOOGLE_OAUTH_REDIRECT_URI": "${WEBAPP_URL}/oauth2callback"`.
- Muốn thêm từ khóa intent/marker/nguồn Feed/server fallback:
  **sửa file JSON tương ứng ở mục 2, không sửa code.** Cấu trúc
  từng file ghi ở đầu mục 2 — giữ nguyên schema, chỉ thêm phần tử.

## 6. Công thức cho việc hay gặp

**Thêm một tool mới** (`tools.py` + module sở hữu):
đăng ký `ToolSpec` vào `ToolRegistry` (tên snake_case, group,
timeout, handler async trả dict có `ok`), khai quyền trong
`config/policy.json` nếu là tool ghi/xoá, thêm test gọi qua
registry. Tool đọc/ghi file PHẢI qua `_resolve_for_file_tool`
(neo workspace/dossier/project_root + denylist) — không tự mở
đường dẫn thô.

**Thêm một MCP server vào fallback**: thêm entry vào
`config/mcp_fallbacks.json` theo mẫu 14 entry sẵn có
(`command`, `args`, `package{ecosystem,name,version,pinned}`,
`setup_requirements`, `warnings`). Không thêm vào code.

**Đổi hành vi trả lời của bot**: sửa prompt `.txt` tương ứng
(mục 5) hoặc brief/taste trong dossier (qua cơ chế của bot) —
không nhúng câu chữ vào handler.

**Đổi model**: env `MODEL_BRAIN/MODEL_CHEAP/MODEL_ESCALATED`.
Tên model lạ được chuẩn hoá qua bản đồ alias
`gateway.py: _MODEL_ALIASES` — thêm model đời mới thì thêm alias
ở đó (đây là bảng giao thức, chấp nhận nằm trong code).

**Thêm biến cấu hình**: đủ 3 nơi theo mục 4.

**Sửa Mini App**: sửa `mulon/webapp/`, chụp render thật bằng
trình duyệt để đối chiếu (luật ở `AGENTS.md` mục 6).

## 7. Bảo mật — các chốt đã có, không tháo

| Chốt | Ở đâu | Ghi chú |
|---|---|---|
| Denylist file nhạy cảm | `tools._resolve_for_file_tool`, `library._denied_reason` | `.env*` (trừ `.env.example`), `*.pem`, `*.key`, `*secret*`, `vault.json`, `*.db` |
| Containment ảnh multimodal | `gateway._multimodal_path_allowed` | chỉ đuôi ảnh + trong workspace/dossier/temp |
| Chặn SSRF | `tools.assert_url_public` + `websearch`/`browser_worker` | kiểm DNS + từng hop redirect |
| Khung nội dung ngoài | `context.frame_external` | mọi kết quả tool/web/email/MCP vào LLM đều đóng khung |
| Proxy fail-fast | `config.validate_proxy_base_url` | localhost:8317 |
| Share token dạng hash | `library.py` | DB chỉ giữ SHA-256 |
| Vault 0600 + Fernet tuỳ chọn | `vault.py` | bật bằng `VAULT_ENCRYPTION_KEY` + gói `cryptography` |
| Auth Mini App | `webapp_server.py` | HMAC-SHA256 initData của Telegram |
| Quyền theo hành động | `config/policy.json` + `policy.py` + `approvals.py` | ghi/xoá = hỏi trước |

## 8. Tự kiểm trước khi commit (bắt buộc chạy, dán kết quả vào báo cáo)

```bash
# 1. Không còn hardcode cá nhân/tạm lọt vào bản sửa:
grep -rn "/Users/\|/Volumes/\|@gmail\.com\|trycloudflare" mulon/ config/ \
  --include="*.py" --include="*.json" | grep -v __pycache__
# (kết quả phải rỗng — chuỗi trycloudflare trong câu chữ giao diện
#  nói về tunnel nói chung thì chấp nhận, URL cụ thể thì không)
find . -type l -not -path "./.venv/*"   # phải rỗng: không symlink ra ngoài repo

# 2. Không lọt bí mật:
git status --short                      # không có .env, *.db, data/, hooks cá nhân
git diff --cached | grep -i "api_key\|token.*=.*['\"][A-Za-z0-9]\{16,\}" 

# 3. Chất lượng:
.venv/bin/python -m pytest tests/ -q    # 100% pass
.venv/bin/python -m mulon.evals         # khi đụng agent loop/prompt
grep -n "__version__" mulon/__init__.py # đã bump + CHANGELOG đã ghi
```

## 9. Những chỗ CỐ Ý không "dữ liệu hoá" (đừng sửa nhầm)

- Endpoint API chính thức (Google OAuth/API, Bing, DuckDuckGo):
  hằng giao thức của nhà cung cấp, để trong module sở hữu.
- Cổng `8317` và host `127.0.0.1`: ràng buộc kiến trúc proxy-only.
- Sentinel `"local-proxy"` trong `config.py`: giá trị đánh dấu
  "key giả của proxy local" — `media_tools` dựa vào nó để phân
  biệt key thật. Không coi là API key hợp lệ ở bất cứ đâu khác.
- Bản đồ alias model (`gateway._MODEL_ALIASES`): bảng giao thức
  với proxy, xem mục 6.
- Schema SQL trong `memory.py` (kể cả default múi giờ trong DDL):
  là cấu trúc dữ liệu, không phải cấu hình vận hành.

## 10. Lỗi hay gặp của agent mới vào dự án

- Sửa trên bản cũ chưa pull => xung đột với phía còn lại. Luôn
  pull trước (xem `AGENTS.md` mục 2).
- Push thẳng lên `main` bản dở => auto_watch triển khai ngay lên
  bot đang chạy. Chưa xanh test thì không push.
- Thêm dependency vào `requirements.txt` tuỳ tiện: dự án ghim dải
  version đã kiểm chứng (đặc biệt pydantic <2.14 vì aiogram) và
  nhiều gói là TUỲ CHỌN (vắng thì degrade) — thêm dependency cứng
  mới phải hỏi chủ dự án.
- Viết lại cả file lớn (2.000+ dòng: `marketplace.py`,
  `telegram_bot.py`, `webapp_server.py`, `memory.py`) thay vì sửa
  đúng chỗ: dễ làm mất thay đổi của phía còn lại và vỡ test ngầm.
- Tự ý "dọn" dossier/workspace/data của máy chạy bot: đó là dữ
  liệu sống của chủ dự án, không phải rác.
