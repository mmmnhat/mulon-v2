# Mulon — Muse clone 1.0.0 (Phase 1 → 6)

Personal AI agent chạy **chỉ trên Telegram**, model **chỉ qua proxy
local tương thích OpenAI** (không dùng API chính thức), xây theo tài
liệu thiết kế `docs/thiet-ke-ky-thuat-muse-clone.md`. Repo này thay thế
toàn bộ Mulon/Nistroly cũ: giữ ý tưởng tốt (Telegram gateway, tool
registry, dossier), bỏ toàn bộ code lõi cũ.

## Đã có ở bản này (Phase 1)

- **Model gateway** (`mulon/gateway.py`): LiteLLM trỏ vào proxy; streaming;
  retry backoff + circuit breaker; đếm token (estimator LiteLLM +
  fallback ký tự); mọi lời gọi ghi trajectory kèm latency/token.
- **Context engine** (`mulon/context.py`): dossier snapshot đóng băng;
  ngân sách cửa sổ 200K token, đếm trước khi gọi; trim kết quả tool
  (trần 8K ký tự, thừa offload ra file artifact); compaction có
  **memory flush trích fact trước khi nén**; đóng khung dữ liệu ngoài
  chống injection.
- **Agent core** (`mulon/agent.py`): vòng **plan–act–verify** — kế
  hoạch lưu DB, tool độc lập chạy song song (`asyncio.gather`), verify
  độc lập bằng prompt kiểm chứng, fail thì retry kèm chẩn đoán; cấm
  báo "đã xong" khi chưa kiểm chứng. Trace chỉ vào trajectory, không
  vào history.
- **Ký ức** (`mulon/memory.py`): SQLite WAL; `messages` + FTS5 (có
  gấp dấu tiếng Việt); `memory_facts` **bi-temporal** (fact cũ bị thay
  thế, không xóa); tasks/task_steps; ledger append-only kèm SHA-256.

## Đã có thêm ở Phase 2 — ký ức sống

- **Hybrid recall thật** (`mulon/memory.py` + `mulon/embeddings.py`):
  FTS/BM25 + vector `sqlite-vec` hợp nhất theo trọng số **70% vector /
  30% BM25** (điểm từng nhánh chuẩn hoá trước khi trộn). Embedding
  local **bge-m3 qua FastEmbed** (lazy-load; cần `pip install
  fastembed`), vắng hoặc lỗi thì **degrade sạch xuống BM25-only** +
  ghi trajectory. Đánh chỉ mục **lúc ghi** (message/fact vừa ghi được
  embed ngay); lúc đọc chỉ embed đúng 1 câu truy vấn; **không dùng
  LLM rerank** trong đường chat. Mọi lần recall đều đo mili-giây và
  ghi trajectory.
- **Consolidation worker** (`mulon/consolidation.py`): đọc episode
  chưa xử lý → model rẻ trích fact ứng viên (JSON chặt, parse phòng
  thủ) → trùng thì bỏ, cùng chủ đề mà khác nội dung thì **supersede**
  theo cơ chế bi-temporal + ghi ledger; watermark theo phiên chống
  xử lý trùng. Chạy tay: `python -m mulon.consolidation --once`;
  trong bot: vòng lặp nền chỉ khi `CONSOLIDATION_ENABLED=1`, và lệnh
  `/new` kích hoạt cho phiên vừa đóng.
- **Học từ correction** (`mulon/learning.py`): user sửa → heuristic
  tiếng Việt bắt tín hiệu ngay trong lượt → model rẻ phân loại theo
  taxonomy 5 loại (dữ kiện / quy trình / giọng-format / tool / trí
  nhớ) → ghi bảng `corrections`. Đủ ngưỡng chống overfit (≥1 lần sửa
  rõ ràng, ≥2 lần lặp, hoặc lỗi tiền/an toàn chỉ cần 1 lần) thì rút
  thành **bài học** dạng fact, nạp vào ngữ cảnh ở mục riêng mỗi lượt.
  Correction nghiêm trọng tự sinh test case vào `evals/cases.jsonl`.
- **Background review fork**: sau mỗi lượt, một fork nhẹ chạy nền
  (model rẻ, trần token cấu hình được) rà soát lượt vừa rồi, ghi
  digest vào `turn_digests` + fact bền. Lỗi của fork không ảnh hưởng
  lượt chính.
- **Session search**: tool `session_search` tìm trong các phiên
  trước, trả **nguyên văn** tin gốc kèm session id + thời gian.

## Đã có thêm ở Phase 3 — tay chân

- **MCP client thật** (`mulon/mcp_client.py`): SDK MCP chính thức,
  kết nối server qua **stdio** theo `config/mcp_servers.json` (kèm
  server ví dụ ở trạng thái tắt), liệt kê tool của server và đăng
  ký vào registry chung với tên `mcp_<server>_<tool>`, schema MCP
  ánh xạ thẳng sang schema nội bộ, gọi tool qua session có timeout
  và **tự reconnect** khi session chết. Server lỗi hoặc chưa cấu
  hình thì degrade sạch — bot vẫn chạy.
- **Subagents thật** (`mulon/subagents.py`): subagent là **agent
  loop đầy đủ** (cùng core plan-act-verify), không phải 1 lời gọi
  LLM trần. Toolset thu hẹp theo profile: `researcher` (chỉ đọc +
  web), `coder` (file + lệnh trong workspace), `default` (tối
  thiểu, chỉ đọc); trần vòng lặp + trần token riêng; tối đa **4
  chạy đồng thời**; kết quả trả **digest nén** (trạng thái + tóm
  tắt + số liệu), không trả transcript. Tool: `spawn_subagent`.
- **Scheduler + goals/tracking** (`mulon/planning.py` +
  `mulon/cron.py`): bảng `schedules` (cron 5 trường tự viết, múi
  giờ tường minh mặc định Asia/Ho_Chi_Minh), `goals` (2 trạng
  thái, activity log, không bao giờ tự đóng), `tracked_items`.
  Tools: `schedule_task`, `list_schedules`, `cancel_schedule`,
  `create_goal`, `list_goals`, `log_goal_activity`, `close_goal`.
  Vòng lặp scheduler **mặc định TẮT** (`SCHEDULER_ENABLED=1` mới
  chạy) — tới hạn thì tính lần kế tiếp và ghi trước (chống bắn
  trùng) rồi giao việc cho agent trong session hệ thống.
- **Browser worker tối thiểu** (`mulon/browser_worker.py`):
  Playwright/Chromium headless — `web_read` (mở URL, trích text
  chính) và `web_screenshot` (PNG lưu vào `workspace/screenshots`).
  Playwright là optional: vắng thì tool báo `unavailable` sạch.
- **Khung connector trung tính** (`mulon/connectors.py`): interface
  `health_check()` + `call(action, args)`, đăng ký lazy (chưa cấu
  hình thì vắng mặt sạch), kiểm tra trạng thái qua
  `connector_health` / `connector_call`. Kèm adapter ví dụ `system`
  (giờ + trạng thái máy) để chứng minh khung; adapter dịch vụ thật
  cắm vào cùng interface ở phase sau. Luật của khung: credential
  không bao giờ xuất hiện trong kết quả/log/trajectory.

## Đã có thêm ở Phase 4 — chủ động + tiếng nói + media

- **Proactivity engine** (`mulon/proactivity.py`): heartbeat gom
  việc theo pattern đã chốt — đọc checklist `dossier/HEARTBEAT.md`,
  gom nhiều mục vào **1 lượt model rẻ** với ngữ cảnh nhẹ
  (lightContext: fact gần + cam kết mở + lịch bật, không nạp cả
  dossier), tôn trọng khung giờ `PROACTIVITY_ACTIVE_HOURS`
  (mặc định 07:00–23:00). Không có gì đáng nói → ghi `HEARTBEAT_OK`
  vào trajectory và **im lặng**. Có việc → xếp hàng "đề xuất" vào
  bảng `proactive_notes` (trạng thái `pending`) — Phase 4 **chưa
  tự gửi** cho user, bề mặt Phase 6 mới trình. File
  `dossier/PROACTIVE_PREFERENCES.md` dạy hệ thống chặn chủ đề
  không muốn nghe. Vòng lặp nền **mặc định TẮT**
  (`PROACTIVITY_ENABLED=1` mới chạy), chạy tay:
  `python -m mulon.proactivity --once`.
- **Voice hai chiều** (`mulon/voice.py`) — lớp tương tác với user:
  nghe bằng **faster-whisper** (tuỳ chọn, lazy, chạy ngoài event
  loop) → transcript thô qua 1 lượt model rẻ **hiểu ngữ** (sửa
  lỗi nhận diện, trích ý định) → `{text_tho, text_da_hieu,
  y_dinh}`; nói bằng **TTS qua proxy** (chuẩn OpenAI speech,
  model/voice qua env). Telegram: gửi tin thoại thì bot nghe và xử
  lý như tin chữ; `/voiceon` `/voiceoff` bật/tắt trả lời bằng
  giọng theo từng phiên. Vắng whisper hoặc proxy không hỗ trợ
  speech → degrade sạch, text vẫn chạy.
- **Media pipeline tools** (`mulon/media_tools.py`): bọc
  ffmpeg/ffprobe — `media_probe`, `media_extract_audio`,
  `media_trim`, `media_burn_subs` (libass), `media_frames`
  (trích frame để xem), `media_transcribe` (whisper kèm
  timecode). Đây là **công cụ dựng video** (mục 8.2), tách bạch
  với giọng tương tác ở trên. Thiếu ffmpeg → unavailable sạch.
- **MCP streamable HTTP** (`mulon/mcp_client.py`): server MCP
  dạng HTTP (entry có `url` trong `config/mcp_servers.json`) bên
  cạnh stdio; header auth lấy từ biến env theo tên (`auth_env`)
  — giá trị bí mật không vào log/status.
- **Browser profile bền**: đặt `BROWSER_PROFILE_DIR` thì
  Chromium dùng persistent context ở thư mục đó để giữ đăng
  nhập giữa các lần chạy; mặc định vẫn profile tạm.
- **Skills system** (`mulon/skills.py`): nạp `SKILL.md` từ
  `skills/` theo **progressive disclosure** — lúc boot chỉ nạp
  mục lục (tên + mô tả), toàn văn chỉ nạp khi agent gọi
  `skill_read`; `requires` (env/tool) không đạt thì skill bị ẩn
  (eligibility); mọi skill qua **vet tĩnh** (frontmatter hợp lệ,
  không pattern lệnh nguy hiểm) và kết quả vet ghi trajectory.
  Kèm 1 skill mẫu `skills/tom-tat-luot-chat/`.

## Đã có thêm ở Phase 5 — cứng hóa

- **Eval vàng chạy thật** (`mulon/evals.py` + `evals/`): bộ
  `evals/golden.jsonl` gồm 30 case theo 5 họ việc thật (trí nhớ,
  correction, dùng tool, trung thực khi thiếu dữ kiện, giọng) —
  chấm hoàn toàn bằng máy (contains_all / contains_any /
  not_contains / tool_called / fact_recalled), không LLM-judge.
  Case do correction nghiêm trọng sinh ra ở Phase 2
  (`evals/cases.jsonl`) được nạp và chạy cùng. Hai chế độ:
  **stub** (mặc định, offline — gateway tham chiếu tất định chỉ
  trả lời được từ ngữ cảnh + tool thật, đo đúng đường ống) và
  **live** (`EVAL_LIVE=1`, gateway thật qua proxy). Cổng chất
  lượng: pass rate < `EVAL_PASS_THRESHOLD` (mặc định 85%) →
  thoát mã 1. Chạy: `python -m mulon.evals [--live] [--json]`,
  báo cáo ghi ra `evals/report.json`.
- **CI GitHub Actions** (`.github/workflows/ci.yml`): push/PR →
  Python 3.12, pytest toàn bộ + dry-run; job riêng chạy eval
  stub làm cổng chất lượng.
- **Langfuse tracing tuỳ chọn** (`mulon/tracing.py`): bọc
  gateway, chỉ ghi metadata (model, token, latency, độ dài
  vào/ra) — **không ghi nội dung tin nhắn/prompt/secret**. Thiếu
  env `LANGFUSE_*` hoặc thiếu gói → no-op hoàn toàn.
- **Backup / restore** (`mulon/backup.py`): gói `.zip` gồm DB
  (chụp bằng SQLite backup API, nhất quán), `dossier/`, config
  không secret (`.env` không bao giờ vào gói) + manifest
  SHA-256. Restore kiểm checksum toàn gói trước khi ghi đè,
  gói lỗi thì từ chối. `python -m mulon.backup create|list|restore`.
- **Báo cáo sức khỏe** (`mulon/report.py`): `python -m mulon.report
  [--json]` — số lượt chat, p50/p95 độ trễ recall + lời gọi model
  + tác vụ, tổng lời gọi LLM và tỉ lệ lỗi sau retry theo tuần
  ISO (đường cong học), correction rate 4 tuần gần nhất, fact
  đang sống/đã thay thế/bài học đang áp dụng, dung lượng DB.

## Đã có thêm ở Phase 6 — bề mặt group (bản 1.0.0)

Sân khấu là **supergroup Telegram riêng tư bật forum**: mỗi topic
là một "tab". Chỉ user trong allowlist mới ra lệnh được; session
theo (group × topic); dossier cá nhân chỉ nạp ở session riêng tư.
Toàn bộ tính năng dưới đây chạy theo lệnh gọi — không vòng lặp
nền mới nào được bật thêm.

- **Topic = tab** (`mulon/surfaces.py`): `/setup_topics` trong
  group forum tạo các topic còn thiếu (Chat chính dùng General,
  Feed, Ideas, Goals, Library, Lịch sử & Hệ thống), lưu map vào
  `kv_state`, ghim tin mục lục (mô tả + lệnh chính) ở từng topic.
  Chưa bật forum hoặc bot thiếu quyền admin → báo rõ lý do,
  không tạo nửa vời. `/topics` xem map hiện tại.
- **Feed** (`mulon/feed.py` + `dossier/FEED.md`): brief do user
  sửa bằng `/feedbrief <nội dung>`; `/feed_now` sinh bài từ tư
  liệu **nội bộ** (goals đang chạy, hoạt động mới nhất, tracked
  item sắp tới, lesson, fact đáng nhớ) bằng model rẻ và đăng vào
  topic Feed — tuyệt đối không aggregator ngoài. Reaction trên
  bài Feed được ghi vào `feed_signals` và tóm tắt taste tự cập
  nhật vào mục đánh dấu trong FEED.md.
- **Ideas** (`mulon/ideas.py`): `/ideas` dọn thẻ hết hạn rồi sinh
  3–5 thẻ từ goals + khoảng trống ký ức; thẻ tự hết hạn sau 14
  ngày. Trả lời thẻ bằng "làm luôn" hoặc `/idea_do <id>` →
  thành goal + task thật; `/idea_bo <id>` bỏ qua.
- **Trình proactive notes**: `/notes` liệt kê các note đang chờ
  (từ Phase 4); trả lời "duyệt"/"bỏ" hoặc `/note_ok <id>` /
  `/note_bo <id>` → cập nhật trạng thái + ghi trajectory.
- **Library** (`mulon/library.py`): lập chỉ mục file trong
  workspace (`/library` quét + liệt kê), `/trash_item <id>`
  chuyển vào `workspace/trash/` và khôi phục được trong 30 ngày
  (`/restore_item <id>`), `/share_item <id>` đặt hạn chia sẻ
  ≤48h ở trạng thái "chờ host" — chưa có host công khai nên
  không bịa link.
- **Secure Vault** (`mulon/vault.py`): `/vault <nhãn>` tạo link
  form web một lần (token ngẫu nhiên, dùng 1 lần, hết hạn ~10
  phút, bind 127.0.0.1, link gửi qua DM khi gọi trong group).
  Giá trị nộp ghi thẳng vào file vault (quyền 0600) dưới
  `ref = vault:<uuid>`; agent chỉ thấy ref + nhãn — giá trị
  không đi qua chat, không vào log/trajectory. Cửa đọc duy nhất
  là `VaultStore.resolve(ref)`.
- **Bộ nhớ có bề mặt**: `/memory` hiện fact kèm nguồn + thời
  gian và truy được tin gốc; `/forget <chủ đề>` lập kế hoạch
  quên (fact/lesson/dòng dossier liên quan) → xác nhận bằng
  "quên thật" mới thực thi (đóng hiệu lực fact, gỡ dòng
  dossier, ghi ledger — không xóa cứng dấu vết kiểm toán);
  `/export_memory` gửi file .md gồm dossier + facts;
  `/import_memory` (gửi kèm file .md/.json) nạp fact mới.
- **Quyền bằng lời thường**: `/quyen` tóm tắt policy hiện tại
  bằng tiếng Việt dễ hiểu (nhóm nào full-auto, nhóm nào phải
  hỏi); `/approvals` xem các quyết định policy gần nhất từ
  trajectory. Đổi policy vẫn sửa `policy.json` như Phase 1.

## Thành phần Phase 1 (nền)

- **Tool registry** (`mulon/tools.py`): read/write/edit file, list_dir,
  run_command (cwd tường minh, có timeout), web_fetch, memory_search,
  memory_get, add_memory_fact, session_search, now. Mọi tool bọc lỗi
  thành cấu trúc. File tool bị neo trong `workspace/` trừ khi bật cờ
  cho phép ra ngoài.
- **Policy engine 2 lớp** (`mulon/policy.py`): file host
  `config/policy.json` thắng mọi cấu hình phiên; mặc định full-auto
  theo lệnh user; mọi quyết định ghi trajectory.
- **Telegram** (`mulon/telegram_bot.py`): aiogram 3, allowlist cứng,
  gom tin liên tiếp (debounce 2.5s), ack bằng reaction, streaming bằng
  edit tại chỗ, chunk HTML an toàn thẻ, session theo (chat, topic).
  Lệnh lõi: `/start` `/status` `/new` (chốt phiên) `/memory`; lệnh
  bề mặt Phase 6 xem ở mục Phase 6 phía trên.
- **Dossier mẫu** trong `dossier/`: SOUL / IDENTITY / USER / MEMORY /
  AGENTS / TOOLS / HEARTBEAT / BOOTSTRAP / alignment.

## Backlog sau 1.0

Những việc còn lại sau bản 1.0.0 — ghi trung thực, chưa làm:

- **Alignment synthesis worker**: tổng hợp `alignment.md` hằng
  ngày từ trajectory/correction (hiện dossier alignment là mẫu
  tĩnh, chưa có worker tự tổng hợp).
- **Tách fact → people/groups.md**: consolidation hiện ghi fact
  vào DB; chưa tách thành các trang `people/*.md` / `groups/*.md`
  trong dossier.
- **Thủ tục hóa (mục 4.5)**: việc quen lặp ≥3 lần thành công
  chưa được chưng cất thành plan template/skill đóng gói.
- **Adapter connector cho dịch vụ thật**: Phase 3 mới có khung
  connector trung tính + adapter `system`; chưa có adapter cho
  dịch vụ ngoài thật.
- **MCP OAuth đầy đủ**: MCP HTTP hiện ở mức header từ env, chưa
  có luồng OAuth hoàn chỉnh.
- **Dashboard Langfuse self-host**: mới có phía client ghi trace
  khi được cấu hình; chưa đóng gói dashboard chạy kèm.
- **Nạp nóng skill**: skill được nạp lúc boot; thêm skill mới
  khi bot đang chạy chưa có (phải khởi động lại).
- **File nhị phân/avatar qua đường GitHub text**: đường đẩy repo
  hiện tại chỉ nhận file text — file nhị phân (avatar, ảnh) chưa
  lên repo bằng đường này.
- Mini App — **không** làm (đã chốt: group forum là bề mặt
  chính). Xem roadmap mục 13 của tài liệu thiết kế.

## Chạy

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # điền TELEGRAM_BOT_TOKEN + ALLOWED_USER_ID
.venv/bin/python -m mulon.main --dry-run   # smoke test, không cần token
.venv/bin/python -m mulon.main             # chạy bot
```

Hoặc Docker: `docker compose up -d`.

## Kiểm thử

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests/ -q
```
