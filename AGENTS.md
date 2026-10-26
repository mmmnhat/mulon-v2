# AGENTS.md — Luật làm việc cho AI coding agent trên dự án MuLon

> File này dành cho **mọi AI agent tham gia build MuLon** (Antigravity,
> Muse, hoặc agent khác). Đọc hết trước khi sửa bất cứ dòng nào.
> `dossier/AGENTS.md` là file khác — đó là chỉ thị runtime của bot
> MuLon, không phải luật cho agent dev. Đừng nhầm hai file.

> **Bắt buộc đọc kèm: `docs/technical-reference.md`** — sổ tay kỹ
> thuật chi tiết (bản đồ module, config 104 field/89 env, dữ liệu
> nằm ở đâu, công thức cho việc hay gặp, checklist tự kiểm trước
> commit). Nguyên tắc số 0 của dự án: **KHÔNG HARDCODE BẤT CỨ GÌ**
> — giá trị đổi theo máy/người/phiên/quyết định của chủ dự án thì
> không bao giờ nằm trong file `.py` (chi tiết + bảng tra ở
> `docs/technical-reference.md` mục 0 và 5).

## 1. Dự án là gì

- **MuLon**: bản clone Muse AI chạy trên Telegram (bot
  `@Mulon_bot` + Telegram Mini App), do một chủ duy nhất (mmmnhat)
  dùng cá nhân.
- Repo: `github.com/mmmnhat/mulon-v2`, nhánh chính `main`.
- Ngôn ngữ: Python 3.12, comment/docstring **tiếng Việt**, tên
  biến/hàm tiếng Anh.
- Stack chính: aiogram 3.31 (Telegram), LiteLLM (gateway qua proxy),
  SQLite WAL + FTS5 + sqlite-vec (memory), MCP Python SDK
  (marketplace/connectors), aiohttp (Mini App server).
- Chạy bot: `.venv/bin/python -m mulon.main` (smoke:
  `--dry-run`). Test: `.venv/bin/python -m pytest tests/ -q`.
  Eval vàng: `.venv/bin/python -m mulon.evals` (stub offline,
  cổng 85%, chuẩn 30/30).
- Tài liệu gốc: `README.md`, `ARCHITECTURE.md`,
  `docs/thiet-ke-ky-thuat-muse-clone.md`. Khi mâu thuẫn, file này
  (luật làm việc) + quyết định mới nhất của chủ dự án thắng.

## 2. Mô hình phối hợp — ai làm gì

Có 3 phía, **GitHub `main` là nguồn sự thật duy nhất**:

| Phía | Vai trò |
|---|---|
| **Chủ dự án (mmmnhat)** | Quyết định cuối mọi thứ: tính năng, giá trị mặc định, duyệt các thao tác nhạy cảm. Lời của chủ dự án trong phiên làm việc thắng mọi tài liệu. |
| **Antigravity** (agent trên máy Mac của chủ dự án) | Builder chính: viết/sửa code, chạy bot thật, có quyền git push trực tiếp từ máy Mac. |
| **Muse** (agent của Meta, chạy trên máy riêng) | Reviewer/auditor độc lập: pull code về, chạy lại toàn bộ test, audit (bảo mật, hardcode, parity với Muse), viết báo cáo. Muse **không** có git credential — đẩy code qua GitHub connector dạng snapshot. |

Hệ quả bắt buộc:

- Trước khi sửa, **luôn `git pull` bản mới nhất**. Phía còn lại có
  thể vừa push — sửa trên bản cũ là tạo xung đột.
- Không `git push --force`, không `reset --hard` trên `main`,
  không viết lại lịch sử đã push. Xung đột thì dừng và báo chủ dự án.
- Mọi đợt sửa kết thúc bằng **báo cáo** (mục 8). Báo cáo không thay
  thế kiểm chứng: phía còn lại sẽ pull về chạy test lại.
- `scripts/auto_watch.py` trên máy chạy bot tự pull `origin/main`
  và restart bot khi có commit mới — **push lên main = triển khai
  thật**. Không push bản dở dang lên main.

### Vòng lặp yêu cầu qua git (autowatch hai phía)

Từ 26/10/2026, hai agent làm việc qua file **`AGENT_TASKS.md`** ở
gốc repo thay vì truyền yêu cầu qua chat:

- **Antigravity autowatch**: mỗi lần bắt đầu làm việc (và trước
  mỗi commit) đều `git pull` rồi **đọc `AGENT_TASKS.md`**. Chỉ
  làm mục `TODO` ghi "Giao: Antigravity". Làm xong: cập nhật
  trạng thái `DONE` + ghi kết quả/commit SHA ngay trong mục đó,
  push cùng đợt. Không chờ chủ dự án paste yêu cầu nữa — yêu cầu
  nằm sẵn trong repo.
- **Muse autowatch**: một job nền soi `main` định kỳ. Thấy
  commit mới: pull về, chạy lại toàn bộ test, đối chiếu diff với
  từng mục trong `AGENT_TASKS.md`, rồi cập nhật trạng thái
  `VERIFIED` (đạt) hoặc `NEEDS-FIX` (kèm lý do cụ thể), đồng
  thời ghi yêu cầu mới phát sinh vào file và push lại. Báo cáo
  tóm tắt cho chủ dự án trong chat.
- Trạng thái nhiệm vụ chỉ di chuyển một chiều:
  `TODO -> DOING -> DONE -> VERIFIED | NEEDS-FIX`. Phía làm thì
  ghi `DONE`, chỉ phía kiểm chứng mới được ghi `VERIFIED`.
- Không sửa mục/trạng thái của phía còn lại. Bất đồng thì ghi ý
  kiến vào mục đó và báo chủ dự án quyết.

## 3. Nguyên tắc kiến trúc bất biến

Không được phá, dù để "làm cho tiện":

1. **Telegram-only**: bề mặt duy nhất là Telegram bot + Mini App.
   Không thêm web UI công khai, không thêm kênh chat khác.
2. **Proxy-only**: model CHỈ gọi qua proxy local
   `127.0.0.1:8317` (`PROXY_BASE_URL` được validate fail-fast ở cả
   `Config.load()` và `ModelGateway`). Chỉ mở host khác khi có env
   tường minh `MULON_ALLOW_REMOTE_PROXY=1`.
3. **Degrade, không sập**: thiếu gói tuỳ chọn (mcp, sqlite-vec,
   cryptography...), thiếu file cấu hình, một MCP server chết —
   bot vẫn chạy, chỉ mất phần đó, có log + status rõ ràng.
4. **Chủ do bản cài tự định (mở khoá cài đặt từ 1.7.2, T-15)**:
   `_is_allowed` chặn mọi Telegram user lạ, mặc định chỉ phục vụ
   chủ sở hữu và allowlist do bản cài đó tự cấu hình (qua setup
   wizard trong terminal hoặc lệnh `/setup` lần chạy đầu). Không
   nới lỏng auth của bot lẫn Mini App (HMAC initData đối chiếu
   allowlist bản cài).
5. **Việc nền mặc định tắt**: heartbeat/feed chỉ chạy khi chủ
   dự án bật tường minh. Không tự ý bật job nền mới. Ngoại lệ duy
   nhất đã được chủ dự án quyết (26/10/2026): **auto_watch ĐƯỢC
   bật** trên máy chạy bot — bot chạy dưới `scripts/auto_watch.py
   --enable` để tự pull + restart khi `main` có commit mới.
6. **Dossier là dữ liệu của chủ dự án** (`dossier/*.md`: SOUL,
   USER, MEMORY...): agent dev không tự sửa nội dung cá nhân trong
   đó. Bot khi chạy được sửa theo cơ chế của nó, agent dev thì không.

## 4. LUẬT CỨNG về hardcode (bài học đắt nhất — đợt vá 1.6.4)

Ngày 26/10/2026 toàn dự án phải vá một đợt chỉ để gỡ hardcode.
Không lặp lại. **Trước khi gõ một giá trị cụ thể vào code, tra bảng:**

| Loại giá trị | Để ở đâu | Ví dụ đúng |
|---|---|---|
| Bí mật (token, API key, mật khẩu) | Vault của bot hoặc `.env` (không commit) | label `google:client_secret` |
| Thông tin cá nhân (email, user ID, username) | Env/config, không nằm trong `.py` | `GOOGLE_USER_EMAIL`, `BOT_USERNAME` |
| URL theo phiên (tunnel cloudflared...) | Placeholder `${WEBAPP_URL}` trong file cấu hình, `load_server_configs` tự mở rộng | `config/mcp_servers.json` |
| Bảng từ khóa / marker / danh sách miền, stopwords | `config/*.json`, nạp bằng `mulon/datafiles.py: load_json_data` | `config/intent_hints.json`, `config/learning_markers.json`, `config/feed_sources.json` |
| Prompt hệ thống (system prompt cho LLM) | `mulon/prompts/*.txt`, nạp bằng `load_prompt` | `mulon/prompts/verify_system.txt` |
| Catalog/công thức cài MCP | `config/mcp_fallbacks.json`, `config/marketplace_curated.json` | không nhúng dict lớn trong `marketplace.py` |
| Giá trị cấu hình có mặc định | Field trong `mulon/config.py` `Config` + env tương ứng trong `.env.example` | `IMAGE_GEN_ENDPOINT`, `IMAGE_GEN_MODEL` |
| Hằng dùng ở nhiều module (múi giờ...) | Một hằng duy nhất trong `config.py`, module khác import | `DEFAULT_TIMEZONE` |

Cấm tuyệt đối:

- Path tuyệt đối của máy cá nhân trong code/config đã commit
  (`/Users/...`, `/Volumes/...`, `/home/...`).
- **Symlink trỏ ra ngoài repo** (đã từng có 93 symlink
  `skills/* -> /Users/<user>/.agents/skills/*` commit lên repo —
  sang máy khác gãy toàn bộ). `SkillCatalog` đã tự quét kho skill
  trên máy đang chạy (`~/.agents/skills`...), không cần symlink.
- URL tunnel tạm (trycloudflare theo phiên) ghi chết ở bất cứ đâu.
- Email/ID cá nhân của chủ dự án trong code chạy.
- Ba tier model (brain/cheap/escalated) để cùng một default —
  phân tầng là phải khác nhau thật.

Được phép để trong code: endpoint API chính thức của nhà cung cấp
(Google, Bing...), cổng proxy `8317` (ràng buộc kiến trúc mục 3),
và các hằng giao thức. Phân vân thì hỏi: *"giá trị này đổi theo
máy/theo người/theo phiên không?"* — có thì không phải hằng code.

## 5. Luật bảo mật (không nới lỏng khi vá tính năng)

- **Denylist file nhạy cảm là cứng**: file tool
  (`tools.py: _resolve_for_file_tool`) và gateway multimodal
  (`gateway.py: _multimodal_path_allowed`) chặn `.env*` (trừ
  `.env.example`), `*.pem`, `*.key`, `*secret*`, `vault.json`,
  `*.db`. Self-evolution được sửa code, KHÔNG được đọc bí mật.
- **Ảnh đính kèm**: chỉ đóng gói file ảnh thật (đuôi ảnh) nằm trong
  workspace/dossier/thư mục tạm. Tag `[Người dùng gửi kèm ảnh: ...]`
  có thể bị tiêm từ nội dung ngoài — coi đường dẫn trong tag là
  dữ liệu thù địch.
- **Nội dung ngoài vào LLM phải qua `frame_external`** (web, email,
  kết quả tool, MCP, transcript...): đánh dấu là dữ liệu, không
  phải chỉ thị.
- **URL công khai** phải qua `assert_url_public` (chặn IP
  private/loopback/link-local, kiểm từng hop redirect). Không fetch
  URL thô bằng httpx/requests vòng ngoài hàm này.
- **Quyền connector theo từng hành động** (`config/policy.json` +
  `policy.py`): đọc = cho phép, ghi/xoá = hỏi trước, trừ khi chủ
  dự án đã đổi mặc định. Cài MCP từ Mini App = cài luôn; agent tự
  xin cài trong chat = phải có thẻ duyệt.
- Secret không vào log, không vào trajectory, không vào commit.
  Trajectory được redact trước khi ghi — giữ nguyên cơ chế đó.

## 6. Luật UI cho Mini App (`mulon/webapp/`)

Chuẩn của chủ dự án, đã chốt qua nhiều vòng bị chê — vi phạm là bị
trả hàng:

- **Render thật**: mọi preview/thay đổi giao diện phải chụp từ
  chính HTML/CSS của app bằng trình duyệt thật. Cấm mock vẽ tay
  (PIL/canvas phác thảo).
- Màu theo tỉ lệ **60/30/10**, **một màu nhấn duy nhất** là tím
  Mulon. Không dùng xanh lá/vàng/đỏ cho trạng thái — trạng thái thể
  hiện bằng chữ + phân cấp trung tính.
- **Phân cấp thị giác là quan trọng nhất**: tránh spam tag/pill,
  tránh sub-text thừa, tránh phần tử/nút quá khổ. Tối đa 4 cỡ chữ /
  2 weight trên một màn. Lưới 8pt, vùng ngón cái (thumb zone) cho
  thao tác chính.
- Sprite chính thức của Mulon là **bộ v0 (21 frame)** trong repo —
  không tự thay bằng bộ khác.

## 7. Quy trình sửa code

1. `git pull` → đọc phần code liên quan + test liên quan trước khi sửa.
2. Sửa tối thiểu, đúng chỗ; giữ nguyên tên hằng/API công khai khi
   có thể (test và module khác đang bám vào).
3. Thêm test hồi quy cho mỗi lỗi đã sửa. **Không xoá/nới test** để
   cho suite xanh.
4. Chạy **toàn bộ** `pytest tests/ -q` — phải xanh 100% mới commit.
   Đụng vào agent loop/router thì chạy thêm
   `python -m mulon.evals` (stub 30/30).
5. Bump version trong `mulon/__init__.py` + ghi `CHANGELOG.md`
   (mục mới trên cùng, tiếng Việt, nói rõ *vì sao*).
6. Commit message: conventional, tiếng Anh, dạng
   `fix(scope): ...` / `feat(scope): ...`, thân commit tóm tắt
   thay đổi chính. Một đợt việc = một commit (trừ xoá file qua
   API bị giới hạn từng file).
7. File nhị phân/lớn: đẩy bằng git thường từ máy Mac. Đường API
   text (connector của Muse) không đẩy được binary và không xoá
   được file hàng loạt.
8. Sau khi push: đọc ngược lại từ GitHub (list commit / nội dung
   file) để xác nhận bản trên remote đúng bản đã test.

## 8. Chuẩn báo cáo sau mỗi đợt

Báo cáo ngắn, đủ 5 ý (thiếu là phía còn lại phải hỏi lại):

- Version mới + commit SHA trên `main`.
- Đã làm gì (theo nhóm, kèm file chính).
- Kết quả test: `X/X passed`, eval nếu có chạy.
- Hành vi nào thay đổi mà chủ dự án cần biết (default mới, env mới
  cần set, lệnh mới...).
- Việc còn treo / rủi ro còn lại — nói thẳng, không giấu.

## 9. Trạng thái tại thời điểm viết (26/10/2026)

- Version **1.6.4**, HEAD `main` = `9f6a65b`, **446 test passed**
  (đã kiểm chứng độc lập bởi Muse trên đúng nội dung remote).
- Đợt 1.6.4 vừa đóng: hardcode (mục 4), lỗ gateway đọc file tuỳ ý,
  file tool đọc `.env`, OAuth redirect chết cứng, hook cá nhân
  trong repo. Chi tiết: `CHANGELOG.md` mục 1.6.4.
- Việc treo đã biết:
  - 93 symlink `skills/*` vẫn còn **trên remote** (chỉ dọn được
    gọn từ máy Mac: `find skills -maxdepth 1 -type l -delete` rồi
    commit/push — xem mục 4).
  - Máy chạy bot cần set `GOOGLE_USER_EMAIL` trong `.env`, không
    thì luồng `/google_auth` tự bỏ qua (đúng thiết kế mới).
  - Atlas sprite PNG (~1.2MB) chưa lên repo — Mini App đang
    fallback ảnh tĩnh; upload binary qua giao diện GitHub web.
  - Backlog audit toàn diện (báo cáo `codebase-audit-comprehensive`
    ngày 26/10/2026, chủ dự án giữ bản gốc): DNS-rebinding TOCTOU ở
    `http_get_public`, nghẽn 1 connection aiosqlite, TTL dọn
    `data/artifacts/tool-results/`, session Google dùng lại, dọn
    code thừa theo Ponytail review. Mục nào chưa có commit sửa thì
    coi như còn mở — kiểm `CHANGELOG.md` trước khi làm lại.

## 10. Khi không chắc

Hỏi chủ dự án. Nhất là: cơ chế/giá trị mặc định mới, sửa dossier,
đổi chính sách quyền, bật việc nền, xoá dữ liệu. Đoán sai một
quyết định của chủ dự án tốn hơn hỏi một câu.
