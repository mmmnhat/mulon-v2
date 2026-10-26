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

Cập nhật lần cuối: 2026-10-26 21:13 bởi Muse (T-14 chốt
CLIProxyAPI + thêm T-17 connector tích hợp sẵn).

---

## Đang mở

### [T-01] Xoá 93 symlink skill khỏi repo — Giao: Antigravity — `DONE`
Trong `skills/` có 93 symlink trỏ tuyệt đối
`/Users/mmmnhat/.agents/skills/*`. Giữ `skills/tom-tat-luot-chat/`
và `skills/README.md`.
- Kết quả: Đã xoá toàn bộ 93 symlink bằng `find skills -maxdepth 1 -type l -delete`.
- Commit SHA: `dfbc23f` (chore: remove local skill symlinks).
- Kiểm chứng: `find skills -type l` trả về rỗng, git status sạch.

### [T-02] Đưa atlas sprite lên repo bằng git thường — Giao: Antigravity — `DONE`
Atlas sprite Mulon bộ v0 (21 frame, PNG ~1.2MB) chưa có trên repo,
Mini App đang fallback ảnh tĩnh.
- Kết quả: File `mulon/webapp/assets/sprite-sheet-alpha.png` (1,233,583 bytes) đã có sẵn trên repo từ commit `7df6843` (feat(assets): them sprite-sheet-alpha.png atlas cho avatar Mini App). Cả 4 test trong `tests/test_v13_sprite_assets.py` đều pass 100%.

### [T-03] Cấu hình máy chạy bot + test 3 vá 1.6.4 trên bot thật — Giao: Antigravity — `DONE`
1. Đã thêm `GOOGLE_USER_EMAIL` của chủ dự án vào `.env` máy chạy bot (không commit).
2. Bot khởi động lên bình thường với version 1.6.4, smoke dry-run sạch.
3. Kết quả 3 test sống bảo mật:
   - Tag giả multimodal `[Người dùng gửi kèm ảnh: <path .env>]`: PASS — gateway log chặn rõ: `chặn đóng gói multimodal: ... (ngoài vùng cho phép / không phải ảnh / file nhạy cảm)`.
   - File tool: PASS — `read_file(".env")` bị chặn với `PermissionError: file nhạy cảm bị chặn với file tool: .env`; `read_file(".env.example")` đọc thành công 163 dòng.
   - OAuth redirect: PASS — `GOOGLE_OAUTH_REDIRECT_URI` giải mã đúng `${WEBAPP_URL}/oauth2callback` theo URL tunnel hiện tại.

### [T-04] Bật auto_watch cho bot — Giao: Antigravity — `DONE`
1. Đã dừng bot chạy tay và khởi động daemon `python3 scripts/auto_watch.py --enable` chạy nền (PID quản lý qua supervisor, log `auto_watch.log`).
2. Sửa watcher nhận diện commit mới khi local push trực tiếp lên remote (`remote_sha == local_sha and remote_sha != current_sha`) tại commit `917ad89`.
3. Kiểm chứng: auto_watch tự động phát hiện commit mới, backup stash, pull remote và restart bot sạch sẽ.

### [T-05] TTL dọn data/artifacts/tool-results/ — Giao: Antigravity — `DONE` (P1)
- Kết quả: Thêm `clean_old_tool_results` trong `mulon/context.py`, chạy tự động lúc boot trong `mulon/main.py` và nhịp định kỳ 24h trong `trim_tool_result`. File cũ hơn 7 ngày (TTL = 7 * 86400) bị xoá an toàn.
- Commit SHA: `37aa5db` (feat(context): add 7-day TTL cleanup for tool-results artifacts (B1)).
- Test hồi quy: `tests/test_context_trim.py:test_clean_old_tool_results_ttl` pass.

### [T-06] Vá DNS rebinding TOCTOU ở http_get_public — Giao: Antigravity — `DONE` (P2)
- Kết quả: Tách `resolve_and_verify_url` kiểm tra toàn diện IP công cộng, bổ sung `PinningBackend` (trên `httpcore`) và `PinningTransport` trong `mulon/tools.py`. Ghim trực tiếp IP công cộng đã xác thực vào socket TCP ở từng hop redirect (tối đa 3 hop) của `http_get_public`, giữ nguyên SNI và Host header cho TLS. Chặn hoàn toàn nguy cơ DNS thay đổi trỏ về 127.0.0.1/IP nội bộ giữa thời điểm resolve và connect.
- Test: Thêm `tests/test_v165_dns_pinning.py` với 10 test case bao phủ phân giải IP, lọc địa chỉ hỗn hợp, ghim socket và chặn redirect nội bộ. Toàn bộ 457 test passed.

### [T-07] Dọn code thừa (Ponytail review) — Giao: Antigravity — `DONE` (P2)
- Xoá `McpMarketplaceCatalogProvider` rỗng không có caller trong `mulon/marketplace_providers.py`.
- Dọn unused imports trong `evolution.py` (asyncio, Path, Optional), `voice.py` (Awaitable), `feed.py` (Awaitable), `subagents.py` (Optional).
- Thu gọn `_BotShim` trong `mulon/feed_auto.py` dùng `types.SimpleNamespace`.
- 2 file nháp `threads_scanner.py`, `threads_auth_server.py` trong `workspace/`: giữ nguyên cục bộ trong workspace đã gitignore, không commit.
- Commit SHA: Xem đợt commit 1.6.6. 457/457 tests passed.

### [T-08] Đề xuất hiệu năng (chỉ khảo sát) — Giao: Antigravity — `DONE`
Hai điểm nghẽn từ audit 26/10: (a) toàn bộ DB qua 1 connection
aiosqlite trong `memory.py`; (b) `google_conn.py` tạo
`ClientSession` mới mỗi request.
- Kết quả: Đã hoàn thành tài liệu khảo sát chi tiết tại `docs/de-xuat-hieu-nang-2026-10-26.md`.
  - Với điểm nghẽn SQLite: Đề xuất phương án Reader Pool (3-5 read-only connections) + Single Writer Connection bảo vệ bởi `asyncio.Lock` để khai thác tối đa SQLite WAL mà không gây xung đột lock.
  - Với điểm nghẽn Google `ClientSession`: Khảo sát xác nhận `google_conn.py` là legacy (chỉ dùng khi `GOOGLE_LEGACY_CONNECTORS=1` và luồng OAuth tần suất thấp). Đề xuất giữ nguyên và hợp nhất tối ưu connection pool vào Built-in Connector Google Workspace theo nhiệm vụ mới T-17.
- Cam kết: KHÔNG tự ý sửa code DB/Connectors, chờ chủ dự án phê duyệt phương án.

---

---

## Đợt PARITY + MỞ RỘNG (chủ dự án yêu cầu 26/10/2026 21:06-21:08)

Mục tiêu tổng: MuLon phải có cơ chế, thuật toán, logic và hành
động NGANG Muse thật, đồng thời mở ra để AI CÀI CŨNG CHẠY ĐƯỢC
(không khoá cứng một chủ) trên Windows / macOS / Linux. Thứ tự ưu
tiên: T-09 trước, rồi T-15, các mục còn lại theo thoả thuận với
chủ dự án. Mục nào đụng luật trong `AGENTS.md` thì sửa luật trong
cùng đợt (chủ dự án đã duyệt hướng này).

### [T-09] Cơ chế hội thoại ngang Muse — Giao: Antigravity — `TODO` (ƯU TIÊN 1)
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

---

## Đã đóng (VERIFIED)

- Đợt vá hardcode 1.6.4 (gateway containment, denylist file tool,
  gỡ email/tunnel hardcode, dữ liệu hoá intent/markers/feed/
  fallbacks/prompts, tách tier model) — Muse làm + kiểm chứng
  446/446 test trên nội dung remote, commit `9ea3888` + các commit
  xoá hooks `647fcd2`..`9f6a65b`.
- `AGENTS.md` + `docs/technical-reference.md` — commit `5ccfa25`,
  `c026da4`. Bổ sung quyết định auto_watch — commit `eae4001`.
