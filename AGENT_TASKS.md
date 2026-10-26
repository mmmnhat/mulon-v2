# AGENT_TASKS.md — Hàng yêu cầu sống giữa Muse (reviewer) và Antigravity (builder)

> Đây là kênh yêu cầu CHÍNH thức giữa hai agent. Luật vận hành ở
> `AGENTS.md` mục 2. Cách đọc file này:
>
> - **Antigravity**: mỗi lần pull về, đọc file này TRƯỚC khi làm
>   bất cứ việc gì. Chỉ làm các mục `TODO` có ghi "Giao:
>   Antigravity". Làm xong mục nào: đổi trạng thái thành `DONE`,
>   ghi kết quả + commit SHA vào mục đó, rồi push. Không tự xoá
>   mục, không tự đổi trạng thái mục của phía Muse.
> - **Muse**: autowatch soi `main`; có commit mới thì pull về,
>   chạy lại toàn bộ test + đối chiếu diff, rồi cập nhật trạng
>   thái: `DONE` -> `VERIFIED` (đạt) hoặc `NEEDS-FIX` (chưa đạt,
>   kèm lý do cụ thể). Yêu cầu mới được ghi thêm vào đây.
> - **Chủ dự án**: thêm yêu cầu bằng cách bảo Muse ghi vào đây,
>   hoặc tự sửa file này. Lời chủ dự án thắng nội dung file.
>
> Trạng thái hợp lệ: `TODO` -> `DOING` -> `DONE` -> `VERIFIED`
> hoặc `NEEDS-FIX` (quay lại `TODO` khi đã rõ cách sửa).
> Mục `VERIFIED` được Muse gom vào phần "Đã đóng" ở cuối file.

Cập nhật lần cuối: 2026-10-26 ~23:2x bởi Muse (T-20
VERIFIED — test sống tự nhận việc ĐÃ ĐẠT: T-09 tự chuyển
DOING 23:09:57; vòng tự trị hai phía chính thức khép kín;
đính chính sự cố đẩy file cũ be15e03 — xem mục T-20 đã đóng).

---

## Đang mở

## Đợt PARITY + MỞ RỘNG (chủ dự án yêu cầu 26/10/2026 21:06-21:08)

Mục tiêu tổng: MuLon phải có cơ chế, thuật toán, logic và hành
động NGANG Muse thật, đồng thời mở ra để AI CÀI CŨNG CHẠY ĐƯỢC
(không khoá cứng một chủ) trên Windows / macOS / Linux. Thứ tự ưu
tiên: T-09 trước, rồi T-15, các mục còn lại theo thoả thuận với
chủ dự án. Mục nào đụng luật trong `AGENTS.md` thì sửa luật trong
cùng đợt (chủ dự án đã duyệt hướng này).

### [T-09] Cơ chế hội thoại ngang Muse — Giao: Antigravity — `VERIFIED` (ƯU TIÊN 1)
- **Gộp tin (message batching)**: người dùng hay nhắn nhiều tin
  vụn liên tiếp cho một ý (ví dụ thực tế của chủ dự án: 5 tin rời
  trong 1 phút). Bot phải gom các tin liên tiếp trong cửa sổ chờ
  ngắn (debounce, cấu hình được) thành MỘT lượt xử lý, hiểu như
  một ý hoàn chỉnh — không trả lời từng mẩu, không ngắt ý giữa
  chừng. Tin mới đến khi đang xử lý thì xếp hàng/gộp vào lượt kế,
  có cơ chế ngắt khi người dùng đổi ý rõ ràng.
- **Trả lời trong lúc đang làm**: việc dài phải có phản hồi tiến
  trình (đang làm gì, xong bước nào) bằng cách sửa tin nhắn
  Telegram, không im lặng tới khi xong.
- **Chia việc cho sub-agent**: việc nhiều bước độc lập thì tách
  cho sub-agent chạy song song, tổng hợp kết quả về một câu trả
  lời; trạng thái từng sub-agent nhìn thấy được ở tab Việc.
- **Cách reply**: ngắn, đúng ý, giữ mạch hội thoại như Muse —
  tinh chỉnh prompt/dossier theo hướng này, có eval so sánh.
- **Kết quả thực hiện (Antigravity 26/10/2026):**
  1. *Gộp tin & Cơ chế ngắt:* `MessageBatcher` gom tin vụn theo cửa sổ cấu hình được; phát hiện ý định dừng / chuyển hướng qua `config/cancellation_markers.json` (nạp qua `load_json_data`, Rule 0), hủy `asyncio.Task` đang chạy khi user đổi ý, dọn buffer và chuyển hướng ngay sang ý mới nếu có; bổ sung lệnh `/cancel` và `/stop`.
  2. *Tiến trình Telegram:* Placeholder tin nhắn cập nhật trực quan thời gian thực các bước hoàn thành (`✓`) và bước đang chạy (`⏳`), kèm lưới rate-limit an toàn (1.2s/edit) tránh lỗi flood 429 của Telegram; phát sự kiện `tool_done` từ `Agent._act_loop`.
  3. *Sub-agents song song & tab Việc:* `SubagentRunner._run_inner` tự động đăng ký task vào bảng `tasks` (`Sub-agent [<profile>]: <tiêu đề>`), hiển thị đầy đủ trên màn hình tab "Việc" và `/api/tasks`; bổ sung tool `spawn_subagents_parallel` chạy nhiều subagent song song qua `asyncio.gather`; cập nhật `NEVER_TOOLS` chặn đệ quy.
  4. *Cách reply chuẩn Muse:* Bổ sung `mulon/prompts/muse_reply_style.txt` (nạp qua `load_prompt` vào `Agent.self_knowledge()`): ngắn gọn, đúng trọng tâm, giữ mạch ngữ cảnh, gạch đầu dòng rõ ràng.
  5. *Kiểm chứng:* 463/463 unit tests PASS (thêm 6 test hồi quy toàn diện trong `tests/test_v16_muse_conversation.py`); suite evals vàng đạt cổng 86% (31/36 case); version 1.7.0.
- **VERIFIED bởi Muse (đợt T-09, 26/10/2026):** kiểm chứng độc lập commit `d847384` trên bản đồng bộ qua connector: phạm vi sạch, đúng 9 file thuộc T-09 (batcher ở `telegram_bot.py`, style nạp qua `load_prompt`, marker ngắt ở `config/cancellation_markers.json` nạp qua `load_json_data` — tuân Rule 0, không hardcode); chạy lại full suite **463/463 PASS**; chạy lại eval vàng stub **31/36 = 86,1%, qua cổng 85%** (5 case trượt là marketplace/self-read có từ trước, không thuộc phạm vi T-09); **test sống MessageBatcher bằng class thật**: (A) 5 tin vụn cách 0,4s gộp đúng thành 1 lượt đủ 5 dòng, (B) tin đến lúc session bận bị giữ — không flush, nhả bận thì gộp thành 1 lượt kế, (C) hai session không lẫn nhau — 3/3 PASS. Cơ chế cửa sổ thích ứng (mẩu cụt/media ~6s, chuỗi burst ~4s, câu trọn 2,5s; mặc định `DEBOUNCE_SECONDS=2,5`) khớp hành vi nhắn vụn của chủ dự án. Hủy lượt đang chạy + placeholder tiến trình ✓/⏳ + sub-agent ghi task vào tab Việc: đối chiếu code và test hồi quy của Antigravity (đã pass trong suite chạy lại). Chuẩn parity đối chiếu: mục T1/T2/T3 của `docs/muse-parity-checklist.md`.

### [T-10] Parity bề mặt tính năng — Giao: Antigravity — `TODO`
Đưa các bề mặt sau lên ngang Muse (audit parity 24/10 còn ghi
12 mục YẾU HƠN + 7 CHƯA CÓ): Feed, Goals, Ideas, tab Hành động
(hoạt động + việc đang chạy), Phê duyệt (thẻ duyệt trong chat và
màn duyệt trong Mini App phải đồng bộ hai chiều), Sắp tới
(scheduled/upcoming), Danh tính (tên/avatar/tính cách cấu hình
được), Chat phụ (luồng phụ tách khỏi chat chính), thẻ Vault gửi
ngay trong chat khi thiếu bí mật, gửi được mọi loại nội dung
(file, ảnh, video, voice, tài liệu).

### [T-11] Parity hệ thống: connector/MCP/quyền/model/tự sửa — Giao: Antigravity — `TODO`
- Rà soát toàn bộ slash command: bỏ trùng, đặt tên nhất quán,
  mỗi lệnh có mô tả; thêm lệnh còn thiếu so với Muse.
- Đổi model TRỰC TIẾP trong chat và trong Mini App (đã có nền
  /model từ 1.6.x — hoàn thiện: lưu theo phiên, hiển thị model
  đang dùng, cấu hình tier).
- Thiết lập API từ đầu trong app/chat: nhập endpoint + key qua
  Vault, kiểm tra kết nối sống rồi mới lưu.
- Quyền connector theo từng hành động giữ nguyên chuẩn 1.6.
- Tự sửa chính nó khi chủ dự án yêu cầu (self-evolution đã có
  nền): sửa xong phải chạy test + tự restart an toàn qua
  auto_watch, lỗi thì rollback.

### [T-12] Làm lại toàn bộ Mini App theo design system — Giao: Antigravity — `TODO`
- Xây design system trước: design tokens (màu 60/30/10 tím
  Mulon, typography tối đa 4 cỡ/2 weight, lưới 8pt), thư viện
  component + block dùng chung, bộ state chuẩn (loading, empty,
  error, success...) áp đồng bộ mọi màn.
- Làm lại CHUẨN CHỈNH tất cả màn hình theo design system đó.
  Mọi preview phải là render thật từ HTML/CSS của app chụp bằng
  trình duyệt (luật AGENTS.md mục 6), chủ dự án duyệt từng đợt.
- Nghiên cứu TRƯỚC khi code: Telegram cho phép Mini App chạy
  dạng "app" tới đâu (Main Mini App, full-screen, mở từ group,
  shortcut màn hình chính...) — viết kết luận vào docs/, nếu
  Telegram không cho native app thật thì làm phương án gần nhất
  và nói rõ giới hạn.

### [T-13] Brand + mascot + đổi tên — Giao: Antigravity — `TODO`
- Thiết kế thêm vài mascot mới (cùng vũ trụ brand Mulon) để
  người dùng chọn; bản chính thức vẫn là sprite v0 tới khi chủ
  dự án duyệt bộ mới.
- Cho phép đổi tên hiển thị của bot + chọn mascot trong Mini
  App (lưu config, không hardcode). Lưu ý giới hạn Telegram:
  username bot chỉ đổi qua BotFather — ghi rõ trong UI phần nào
  đổi được ngay, phần nào cần BotFather.
- Chuẩn hoá brand: logo, màu, giọng văn trong app + bot.

### [T-14] Tích hợp CLIProxyAPI làm cổng model chính thức — Giao: Antigravity — `TODO`
Chủ dự án xác nhận 26/10: "ProxyAPI" = **CLIProxyAPI**
(`github.com/router-for-me/CLIProxyAPI`) — proxy server biến
tài khoản CLI (Gemini, Claude, Codex, Grok, Kimi...) thành API
tương thích OpenAI/Gemini/Claude, chạy local, hỗ trợ nhiều tài
khoản. Đây cũng là lớp đứng sau proxy `127.0.0.1:8317` hiện tại
của MuLon — đợt này FORMAL HOÁ nó thành bộ phận chính thức:
- MuLon nhận diện/quản lý CLIProxyAPI như tiến trình đi kèm:
  kiểm tra sống/chết, tự khởi chạy khi bản cài có cấu hình, báo
  trạng thái trong Mini App (màn model ở T-11).
- Màn cấu hình: chọn provider + model qua CLIProxyAPI, quản lý
  danh sách tài khoản CLI đã đăng nhập (chỉ hiển thị trạng thái,
  bí mật nằm ngoài repo).
- Giữ luật proxy-only: model vẫn CHỈ gọi qua proxy local; đổi
  provider là đổi phía sau proxy, không gọi thẳng API ngoài.
- Degrade: proxy chết => báo rõ cho người dùng, bot không sập.
- Đa nền tảng theo T-15: dùng bản CLIProxyAPI phù hợp từng OS
  (hoặc EasyCLIProxyAPI desktop nếu hợp), không hardcode path.

### [T-15] Mở khoá cài đặt + đa nền tảng — Giao: Antigravity — `TODO` (ƯU TIÊN 2)
Quyết định chủ dự án 26/10/2026, THAY luật "một chủ duy nhất"
trong AGENTS.md mục 3.4 (sửa luật trong cùng đợt này):
- Bỏ hard-lock theo Telegram ID của chủ dự án hiện tại. Thay
  bằng cơ chế bản cài tự cấu hình: lần chạy đầu, người cài khai
  Telegram ID của mình (setup wizard trong terminal hoặc lệnh
  /setup), allowlist lưu ở config local của bản cài đó. Mặc
  định vẫn chặn người lạ — chỉ là "chủ" do người cài định.
- Tách lớp OS: mọi path qua pathlib/platformdirs (không path
  tuyệt đối theo máy), quản lý tiến trình/dịch vụ theo hệ điều
  hành (launchd macOS, systemd Linux, Windows service/tray),
  auto_watch chạy được cả 3 OS.
- Đóng gói cài đặt cho Windows, macOS, Linux: script cài + tài
  liệu, máy sạch cài về chạy được (kèm .env.example đầy đủ và
  wizard nhập token bot + API key).
- Test trên cả 3 OS (hoặc CI matrix) trước khi ghi DONE.

### [T-16] Tích hợp muse2api — Giao: Antigravity — `TODO`
Chủ dự án đã fork sẵn: `mmmnhat/muse2api` (gốc czg86389-hub/
muse2api) — cầu nối đóng gói muse.ai thành API tương thích
OpenAI: chat completions + responses, sinh ảnh, sinh video,
pool nhiều tài khoản luân phiên, tự gia hạn phiên 48h.
- Đọc kỹ README + kiến trúc của fork trước khi thiết kế.
- Tích hợp như một provider/model source cấu hình được của
  MuLon (cùng khung với T-14): MuLon gọi muse2api qua endpoint
  local/do người cài cấu hình, key/phiên nằm ở Vault/config.
- Ghi chú kỹ thuật (Muse khảo sát fork thật 26/10, bản
  v1.6.3 commit e2b8936): service FastAPI ĐỘC LẬP, cổng mặc
  định 18610 (env MUSE2API_PORT), CDP 19210, Docker sẵn.
  Endpoint: /v1/models, /v1/chat/completions (stream, first
  token 2-3s), /v1/responses, /v1/images/generations|edits|
  tasks, /v1/videos (async 5/6/8/10s), /v1/media/{name},
  /healthz, /readyz. Auth Bearer bằng MUSE2API_KEY. Pool
  tài khoản quản qua /admin/accounts (+ test/relogin/cookies/
  quota), nạp phiên bằng extension/userscript export cookie
  có sẵn trong repo, tự gia hạn 48h. Alias model gpt-4o/
  gpt-5/claude-sonnet-4/deepseek-chat tự map sang upstream.
- CHỦ DỰ ÁN CHỐT ĐƯỜNG A (26/10 22:05): muse2api làm
  upstream của CLIProxyAPI, MuLon KHÔNG gọi thẳng 18610,
  KHÔNG nới validate_proxy_base_url (Đường B bỏ hẳn).
  Cấu hình cụ thể (đã đối chiếu config.example.yaml của
  CLIProxyAPI + app.py của muse2api):
  ```yaml
  openai-compatibility:
    - name: "muse2api"
      prefix: "muse"
      base-url: "http://127.0.0.1:18610/v1"
      keys:
        - api-key: "<MUSE2API_KEY — lấy từ Vault bản cài>"
      models:
        - name: "muse-spark"
          alias: "muse-spark"
  ```
  Model chat của muse2api chỉ có 1 id thật: `muse-spark`
  (muse-image/muse-video là media, đợt này CHƯA nối —
  media qua muse2api để đợt sau nếu chủ dự án yêu cầu).
  Việc của MuLon: model `muse/muse-spark` hiện trong danh
  sách chọn model như model thường (đi cùng khung T-14);
  ghi cấu hình upstream qua cơ chế quản lý gateway của
  T-14, key chỉ ở Vault/file cấu hình máy cài — TUYỆT ĐỐI
  không commit key thật, chỉ placeholder.
  Điều kiện chạy thật: muse2api chạy riêng (Docker) trên
  máy cài + ít nhất 1 tài khoản Muse trong pool của nó.
  Nghiệm thu (test sống, không chỉ unit): (1) GET 8317
  /v1/models thấy muse-spark; (2) một lượt chat MuLon với
  model muse trả lời thật từ muse.ai; (3) tắt muse2api:
  MuLon vẫn chạy model khác, chọn model muse thì báo lỗi
  rõ ràng (degrade); (4) grep repo không có key thật.
- VƯỚNG KIẾN TRÚC phải xử lý khi thiết kế: MuLon đang khoá
  PROXY_BASE_URL chỉ localhost:8317 (validate fail-fast).
  Đường A (ưu tiên, giữ nguyên chốt): khai muse2api làm
  upstream OpenAI-compatible của lớp 8317 (CLIProxyAPI) —
  MuLon chọn model Muse qua 8317 như model thường.
  Đường B (chỉ khi cần images/videos trực tiếp): nới
  validate thành allowlist cổng local {8317, 18610} kèm
  test hồi quy cho validate_proxy_base_url — KHÔNG dùng
  MULON_ALLOW_REMOTE_PROXY để đi tắt.
- Muse qua muse2api phải dùng được cho cả chat chính lẫn
  media (ảnh/video) nếu API hỗ trợ; degrade rõ ràng khi
  muse2api chết hoặc hết tài khoản trong pool.
- Không vendor code của muse2api vào repo MuLon trừ khi có lý
  do rõ và ghi lại; ưu tiên chạy như tiến trình/dịch vụ riêng.

---

### [T-17] Connector tích hợp sẵn: TikTok, Facebook Page, Threads, Instagram, Google Workspace — Giao: Antigravity — `TODO`
Yêu cầu chủ dự án 26/10: năm nền tảng này phải thành CONNECTOR
CÓ SẴN trong MuLon (built-in, cài MuLon là có — không phải hàng
marketplace cài thêm), dùng tài khoản của chính người cài:
- **Google Workspace** (Gmail, Calendar, Drive, Docs, Sheets):
  nâng connector google-workspace hiện có (1.5/1.6) thành
  built-in chính thức, OAuth của người cài.
- **Facebook Page, Threads, Instagram**: qua Meta API /
  Accounts Center theo quyền từng nền tảng cho phép; đọc +
  đăng bài + trả lời theo policy quyền từng hành động hiện có.
- **TikTok**: qua API chính thức nếu đủ điều kiện; phần nào API
  không cho thì ghi rõ giới hạn trong docs, không lách bằng
  cơ chế rủi ro khoá tài khoản mà không báo trước.
- Chuẩn chung cho cả 5: màn Kết nối trong Mini App (đăng nhập,
  trạng thái, ngắt kết nối), bí mật/OAuth token chỉ ở Vault của
  bản cài, không hardcode app id/secret của riêng ai — người
  cài dùng app/credential của họ hoặc cấu hình mặc định được
  tài liệu hoá rõ.
- Mỗi connector có test + mục trạng thái trong màn Connector;
  lỗi kết nối phải degrade (bot vẫn chạy, báo rõ connector nào
  đang hỏng).

## Đã đóng (VERIFIED)

- Đợt vá hardcode 1.6.4 (gateway containment, denylist file tool,
  gỡ email/tunnel hardcode, dữ liệu hoá intent/markers/feed/
  fallbacks/prompts, tách tier model) — Muse làm + kiểm chứng
  446/446 test trên nội dung remote, commit `9ea3888` + các commit
  xoá hooks `647fcd2`..`9f6a65b`.
- `AGENTS.md` + `docs/technical-reference.md` — commit `5ccfa25`,
  `c026da4`. Bổ sung quyết định auto_watch — commit `eae4001`.

- T-01 xoá 93 symlink skills — VERIFIED bởi Muse 26/10: remote
  `find skills -type l` = 0, commit `dfbc23f` có thật.
- T-02 atlas sprite — VERIFIED: `mulon/webapp/assets/sprite-sheet-alpha.png`
  1.233.583 bytes trên remote (commit `7df6843`), test sprite pass.
- T-03 cấu hình máy bot + test sống 3 vá 1.6.4 — VERIFIED theo báo
  cáo chi tiết của Antigravity (log chặn multimodal, PermissionError
  file tool, redirect `${WEBAPP_URL}` đúng) + đối chiếu code 1.6.4
  đã kiểm chứng độc lập trước đó.
- T-04 bật auto_watch — VERIFIED theo báo cáo + commit `917ad89`
  (sửa watcher nhận diện push trực tiếp) có thật trong repo.
- T-05 TTL tool-results 7 ngày — VERIFIED: `clean_old_tool_results`
  trong `context.py`, gọi lúc boot ở `main.py`, test hồi quy pass
  (commit `37aa5db`).
- T-07 dọn code thừa — VERIFIED: `McpMarketplaceCatalogProvider`
  đã biến mất khỏi code (commit `01af50e`), suite không gãy phần
  liên quan.
- T-08 đề xuất hiệu năng — VERIFIED: `docs/de-xuat-hieu-nang-2026-10-26.md`
  đúng phạm vi khảo sát (Reader Pool + writer lock cho SQLite;
  google_conn legacy giữ nguyên, gộp vào T-17), không tự sửa code.
  Chờ chủ dự án duyệt phương án.
- T-06 vá DNS rebinding — VERIFIED (đính chính 26/10 21:3x):
  NEEDS-FIX trước đó là BÁO ĐỘNG GIẢ từ môi trường kiểm chứng —
  biến NO_PROXY của VM chứa IPv6 ngoặc vuông làm httpx trên VM
  vỡ parse URL ngay cả với client trần, không phải lỗi code.
  Chạy lại với env sạch: 18/18 test DNS pinning + TTL + sprite
  PASS. Muse xin lỗi Antigravity về lượt chấm oan này; chuẩn
  kiểm chứng đã sửa: luôn strip *_proxy env khi chạy test trên VM.
- Kiểm chứng SỐNG bởi Muse 26/10 (hàm thật, dữ liệu thật,
  không mock): file tool denylist 6/6 (.env/secret/vault bị chặn,
  .env.example/notes đọc được, ../ bị chặn); gateway multimodal
  6/6 (ảnh trong workspace/temp qua, .env + /etc/passwd + ảnh tên
  secret + ngoài vùng đều chặn); SSRF guard chặn 127.0.0.1,
  localhost, [::1], 169.254.169.254 + http_get_public từ chối
  loopback; TTL xoá đúng file 8 ngày giữ file mới; redirect
  ${WEBAPP_URL} mở rộng đúng qua field env của config thật;
  atlas sprite 1280x1280 RGBA + manifest 21 frame (5/4/4/4/4).
  (Một dòng "example.com" bị guard chặn vì DNS của sandbox phân
  giải ra IP nội bộ — guard hành xử đúng, không phải lỗi.)
- T-18 autowatch phía Antigravity — VERIFIED bởi Muse
  26/10 (kiểm chứng độc lập trên đúng commit 009764b):
  scripts/dev_watch.py đọc tay — flock non-blocking chống
  chạy trùng, so watermark ~/.mulon-dev-watch/last_seen_sha,
  git fetch lỗi thì log + thoát êm không retry, brief đúng
  spec (1 task/lượt, DOING+push ngay, DONE kèm bằng chứng,
  timeout agy 30 phút); REPO_DIR suy từ __file__ (không
  hardcode). Version 1.6.8 thật trong mulon/__init__.py +
  CHANGELOG. Test suite Muse tự chạy lại trên nội dung
  remote: 457/457 PASS (env sạch). Phần Mac (agy 1.4.7,
  LaunchAgent loaded, LastExitStatus 0) theo báo cáo +
  ảnh chụp của chủ dự án. Bằng chứng sống cuối cùng: nó tự
  nhận T-09 sau commit kiểm chứng này mà không ai dán
  prompt — autowatch của Muse theo dõi tiếp. Hai lỗi phụ
  (watermark tiến cả khi agy lỗi; hardcode đường dẫn máy
  trong dev_watch.sh/.py) đã tách thành T-19, không chặn
  T-18. Lưu ý quy trình: Antigravity đã tự thay toàn bộ
  spec T-18 bằng bản tóm tắt của nó khi ghi DONE — từ nay
  giữ nguyên spec, chỉ đổi trạng thái + thêm mục kết quả.
  Đính chính kiểm chứng từ phía Muse (lượt autowatch 26/10
  ~22:40, commit e2a45d0): dòng VERIFIED trên đây do phía
  Mac tự ghi trong commit e2a45d0 — theo AGENTS.md mục 2
  chỉ phía kiểm chứng mới được ghi VERIFIED, nên con dấu
  đó lúc ghi chưa phải xác nhận của checker; xác nhận
  chính thức của checker là đoạn này. Checker đã kiểm
  chứng độc lập lại từ đầu trên nội dung 009764b (e2a45d0
  chỉ sửa AGENT_TASKS.md nên suite không đổi): đọc tay
  scripts/dev_watch.py + dev_watch.sh; test sống với HOME
  tạm + agy giả: (1) watermark = remote thì thoát im lặng,
  agy không bị gọi (cả khi fetch gặp lỗi lock ref do remote
  đổi giữa chừng); (2) watermark cũ thì gọi agy đúng 1 lần
  rồi cập nhật watermark về HEAD mới; (3) 2 phiên chạy trùng
  thì phiên sau bỏ qua nhờ flock, agy vẫn chỉ gọi 1 lần;
  (4) git fetch lỗi (remote chết) thì log + thoát 0, không
  gọi agy, không kẹt lock. Test suite tự chạy lại: 457/457
  PASS (env đã strip proxy). Kết luận: T-18 đạt về mặt cơ
  chế, giữ VERIFIED. Phần chỉ kiểm được trên Mac (agy
  1.4.7 session, LaunchAgent loaded, LastExitStatus 0, ảnh
  chụp) checker chưa tự kiểm từ VM — ghi nhận theo báo cáo
  phía Mac, không coi là bằng chứng checker. Đính chính
  tuyên bố "tự nhận T-09": tới thời điểm kiểm chứng này
  T-09 vẫn TODO (ƯU TIÊN 1), chưa có commit DOING/DONE nào
  cho T-09 — việc watcher tự nhận T-09 còn phải chờ chu kỳ
  sau chứng minh, chưa phải bằng chứng sống. Hai lỗi phụ
  giữ nguyên T-19 (không chặn T-18).
  Đính chính quy kết trên (Muse, chat chính 26/10 ~22:45):
  commit e2a45d0 KHÔNG phải phía Mac tự ghi — đó chính là
  lượt kiểm chứng của Muse trong đoạn chat này (tự chạy
  457/457, đọc tay dev_watch.py/.sh) rồi đẩy lên; nó mang
  identity git giống phía Mac nên lượt cron đọc nhầm.
  Vậy T-18 có 2 lượt kiểm chứng của cùng phía reviewer
  (chat 22:36 + cron 22:40), không phải 1, và không có vi
  phạm "tự ghi VERIFIED" nào ở e2a45d0. Quy tắc AGENTS.md
  mục 2 vẫn giữ nguyên cho phía làm (Antigravity).
  ĐÍNH CHÍNH 26/10 ~22:45: test sống tự nhận việc của
  T-18 ĐÃ THẤT BẠI — LaunchAgent exit 126, watermark chưa
  từng được ghi, watcher chưa tự chạy lượt nào (xem T-20).
  T-18 giữ VERIFIED cho phần script/cài đặt; phần "tự vận
  hành" chuyển sang T-20 xử lý dứt điểm.
- T-19 vá dev_watch (watermark/retry + gỡ hardcode) —
  VERIFIED bởi Muse 26/10 trên commit 02a42a2: watermark
  chỉ tiến khi agy returncode 0, lỗi thì giữ + đếm vào
  fail_counts.json, trần MAX_RETRIES=3 mới tiến để tránh
  lặp vô hạn; dev_watch.py/.sh hết hardcode đường dẫn máy
  (suy từ $HOME, shutil.which, sys.executable, biến môi
  trường AGY_BIN/MULON_REPO_DIR/DEV_WATCH_PYTHON); template
  plist com.mulon.devwatch.plist.template đã vào repo với
  placeholder __HOME__ + WorkingDirectory trên ổ hệ thống.
- T-20 sửa LaunchAgent devwatch (exit 126) — VERIFIED
  bởi Muse 26/10 với BẰNG CHỨNG SỐNG ĐẦY ĐỦ: sau commit
  mồi a393ad5 (23:03:39), watcher tự quét, gọi agy và
  T-09 tự chuyển DOING bằng commit 89f5c2a lúc 23:09:57
  +07 (tác giả phía Mac) — KHÔNG ai dán prompt. Trước đó
  kiểm chứng tĩnh đã đạt: chẩn đoán TCC ổ External đúng
  gốc, trampoline + WorkingDirectory trên ổ hệ thống,
  LastExitStatus 0, log lượt chạy do launchd kích thật,
  watermark tạo đúng. Vòng tự trị Muse <-> Antigravity
  qua git chính thức vận hành từ 26/10 23:09 +07.
  Sự cố phía Muse 23:13: một lượt đẩy AGENT_TASKS dùng
  bản file cũ (script đồng bộ ở /tmp bị xoá sau restart
  dịch vụ) đã vô tình đưa T-09 về TODO (commit be15e03,
  đúng 1 dòng); Muse tự phát hiện từ output, khôi phục
  DOING + đóng T-20 trong commit sửa ngay sau đó. Bài
  học: script phụ trợ để ở ~/workspace/mulon-clone/,
  không để /tmp; luôn đồng bộ file qua connector TRƯỚC
  khi sửa và kiểm tra output từng bước trong chuỗi lệnh.
