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

Cập nhật lần cuối: 2026-10-26 21:2x bởi Muse (kiểm chứng
đợt Antigravity 1.6.5-1.6.7: T-01..T-05, T-07, T-08 VERIFIED;
T-06 NEEDS-FIX 1 test DNS pinning).

---

## Đang mở

### [T-06] Vá DNS rebinding TOCTOU ở http_get_public — Giao: Antigravity — `NEEDS-FIX` (P2)
- Antigravity báo DONE (commit `78276cd` + `01af50e`, PinningBackend/
  PinningTransport trong `mulon/tools.py`, 10 test trong
  `tests/test_v165_dns_pinning.py`, báo 457/457 trên máy Mac).
- Muse kiểm chứng độc lập 26/10 21:2x trên VM Linux: **456 passed,
  1 FAILED** — `test_real_httpx_client_instrumented_with_pinning`
  chết `httpx.InvalidURL: Invalid port: ':1]'`. Dấu hiệu đường ghim
  IP xử lý host/IPv6 chưa đúng (chuỗi dạng `[::1]` bị parse lẫn
  port) hoặc test chưa hermetic (còn một lượt resolve thật phụ
  thuộc DNS môi trường). Trên Mac pass nên cần: (1) xác định gốc —
  sửa parse IPv6 (ngoặc vuông) nếu là lỗi code, hoặc mock nốt lượt
  resolve còn hở nếu là lỗi test; (2) chạy lại test này trên cả
  Mac lẫn một môi trường Linux sạch. Đạt khi test xanh ở cả hai.

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
