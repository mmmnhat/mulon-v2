# CHANGELOG

## 1.2.0 — Mini App modal phong cách Muse + policy nấc "hỏi" + menu lệnh

- **Khối 1 — Menu lệnh:** bot đăng ký toàn bộ lệnh hiện có + `/menu`
  bằng `set_my_commands` lúc khởi động (mô tả tiếng Việt; lỗi đăng
  ký chỉ log warning). `/menu` gửi MỘT tin teaser kèm nút mở Mini
  App; thiếu cấu hình app thì trả hướng dẫn ngắn + lệnh chính.
- **Khối 2 — Policy 3 nấc + ApprovalBroker:** verdict mở rộng
  allow/ask/deny (bí danh ask: prompt/confirm; file cũ allow/deny
  chạy nguyên). `mulon/approvals.py`: broker mở yêu cầu -> chờ
  quyết định từ mọi đường (inline/Mini App), timeout 60s = hết
  hạn, "duyệt và nhớ" ghi rule lớp session. Agent phát event
  `approval_requested`, payload chỉ có tóm tắt args an toàn.
- **Khối 3 — Bề mặt Telegram:** nút mở app là **Direct Link**
  `https://t.me/<bot>/<WEBAPP_APP_NAME>?startapp=...&mode=compact`
  (nút web_app inline chỉ chạy trong DM nên không dùng); thẻ duyệt
  luôn kèm inline dự phòng Duyệt/Chặn/Duyệt và nhớ; quyết định
  xong — kể cả hết hạn — bot **tự xóa tin thẻ**, ghi 1 dòng vào
  topic Lịch sử & Hệ thống; người lạ bấm nút bị từ chối. Placeholder
  của lượt chỉ hiện MỘT dòng trạng thái (≤1 edit/1,2s).
- **Khối 4 — Mini App:** server aiohttp cùng process (bind
  127.0.0.1, cổng `WEBAPP_PORT` 8320) phục vụ 1 file HTML tĩnh +
  API JSON. Mọi `/api/*` khóa bằng `X-Telegram-Init-Data` (HMAC
  chuẩn Telegram, auth_date ≤ 1h, user.id == ALLOWED_USER_ID);
  Vault chỉ lộ nhãn + ref. Giao diện "tờ hồ sơ agent" giống app
  Muse: header avatar + trạng thái sống, 5 tab Việc · Phê duyệt
  · Lịch · Hồ sơ · Cài đặt; tab active là pill trắng trên nền
  segmented xám, đất nung `#D97757` chỉ cho nút hành động chính.
- **Khối 5 — Hồ sơ:** version 1.2.0, CHANGELOG này, README mục
  "Bảng điều khiển (Mini App)" + biến WEBAPP_* vào bảng cấu hình,
  `.env.example` hướng dẫn BotFather 3 bước, test `test_v12_*`.
- **Bổ sung cuối 1.2.0 (chưa phát hành):** (1) Chọn **màu chủ
  đề** trong Cài đặt → Giao diện: 7 họ màu (Tím Mulon mặc định,
  Xanh dương, Hồng, Đào, Xanh lá, Chì, Đất nung) — chỉ đổi hue
  của lớp nhận diện 30% (3 token `--lav*`), `--clay` giữ vai
  trò ngữ nghĩa cho Duyệt/CTA; áp ngay bằng localStorage + lưu
  server (kv) để đồng bộ đa thiết bị qua `POST
  /api/profile/theme`. (2) Thẻ **Thiết bị & hệ thống** trong
  Cài đặt: tình trạng THẬT của máy đang chạy Mulon (hostname,
  HĐH, phiên bản, uptime, kiểm tra TCP proxy 8317, scheduler/
  heartbeat) + phiên Telegram đang xem qua `/api/state.system`
  — Mulon không ghép thiết bị nên không có danh sách thiết bị.
  (3) Thẻ duyệt có **dòng phạm vi + lý do** theo chuẩn thẻ cấp
  quyền của Muse: dòng phạm vi suy từ tool/nhóm thật — “Duyệt”
  chỉ áp cho lần này, “Duyệt và nhớ” áp cho đúng công cụ đó tới
  hết phiên (rule lớp session), không lan sang việc khác; dòng
  lý do là lời agent tự giải thích (lời dẫn của model ở lượt gọi
  tool, trường `reason` tùy chọn qua broker) — chat hiện 1 dòng
  cắt gọn, Mini App hiện bản đầy đủ mở rộng/thu gọn được; không
  có lý do thì thẻ vẫn dựng bình thường. (4) **Rà thiết kế
  Mini App theo chuẩn skill `mobile-app-ui-design`** (chỉ
  hình thức + tương tác hiển thị, không đổi hành vi/API):
  typography co từ 6 cỡ/3 weight về **4 cỡ (20/15/13/11) /
  2 weight (400/600)** — hết chữ dưới 11px; mọi khoảng về
  lưới 8pt (bội 4/8); mọi vùng chạm ≥44px (segmented quyền
  36→44, nút phụ 40→44, toggle vùng bấm cao 44 giữ track
  51×31, link "Mở rộng" cao 44); trạng thái pressed +
  `:focus-visible` cho mọi phần tử bấm được; cụm nút quyết
  của thẻ duyệt dính đáy viewport (vùng ngón cái); Peak-End
  — duyệt xong/việc xong có avatar state `done` + toast xác
  nhận, tab Phê duyệt có thẻ trống dạng khẳng định; empty
  state Lịch sử/Kết nối có thêm câu hướng dẫn. `DESIGN.md`
  ghi lại thang chữ/khoảng mới và các mục Vùng ngón cái,
  Peak-End, micro-interaction. (5) **Nhãn lời thường trong
  Mini App** (vá sau rà render thật): thẻ chờ duyệt + lịch sử
  phê duyệt trong app từng lộ tên tool thô (`run_command`,
  `send_message`, `github_push`) — `/api/state` nay gắn
  `action_label` dùng lại đúng `tool_action_label` của thẻ
  duyệt trên chat (bổ sung nhãn cho `send_message`,
  `github_push`), tên thô chỉ còn ở dòng chi tiết; màn Quyền
  hiện nhãn nhóm tiếng Việt qua `group_labels` (dùng lại
  `GROUP_SCOPE_LABELS`) thay key thô (`file`, `shell`…), và
  bỏ hẳn jargon "lớp phiên/lớp host" — câu dưới toggle "Lưu
  bền" cùng note của màn Quyền viết lại bằng lời thường giữ
  nguyên nghĩa. Không có nhãn thì frontend fallback về tên
  thô, không bịa nhãn. (6) **Vòng sửa thiết kế theo feedback
  user sau render thật** (chỉ `index.html` + `DESIGN.md`,
  không đổi hành vi/API): bỏ toàn bộ pill/tag trạng thái
  (tag "Cần duyệt", pill kết quả lịch sử, pill ở màn Hệ
  thống) — trạng thái thành chữ thường theo thang mực +
  tối đa 1 ký hiệu mảnh (✓/✕/·); xóa hệ màu trạng thái
  xanh/vàng/đỏ khỏi mọi danh sách (ô icon thống nhất tint
  trung tính ấm `--surface2` + glyph `--ink2`, gỡ
  `--tint-ok`/`--tint-warn`/`--tint-blue`, toggle bật =
  `--lav`, chấm timeline trung tính/tím, note trung tính);
  **bỏ hẳn đất nung/clay** — đất nung là màu của Muse,
  không phải của Mulon: accent 10% nay là bậc đậm nhất của
  chính hue nhận diện đang chọn (`--accent` suy từ
  deep/press của theme; theme "Đất nung" gỡ khỏi `THEMES`
  + `THEME_KEYS`, còn 6 họ màu; theme đã lưu `clay` tự rơi
  về lavender); cắt sub text rườm rà (menu Cài đặt hết sub
  mô tả, hàng việc chỉ còn sub khi đang chạy/lỗi, note
  Quyền/Hệ thống/Vault rút gọn giữ nguyên nghĩa); thu kích
  thước tổng thể ~15% (avatar 76→52, compact 32; hàng
  56→52; ô icon 36→32; nút chính 48→44 gọn padding); dựng
  lại phân cấp — thang chữ nới bậc trên cùng 20→22, thẻ
  duyệt lấy tiêu đề hành động lớn làm điểm neo (rose thu
  về 1 chấm nhỏ, bỏ viền rose), chữ `--lav-deep` của các
  theme nới đậm đạt tương phản trên tint (dark dùng base
  trên tint tối). `DESIGN.md` ghi lại kỷ luật mới ở mục
  "Kỷ luật trạng thái & phân cấp". Test frontend cập nhật
  theo chủ đích mới: khẳng định không còn `#D97757`, không
  pill trạng thái, không biến thể ô icon sơn màu; test
  theme còn 6 khóa.

## 1.1.1

- Vá gom tin: tin đến trong lúc session bận được giữ và drain vào
  lượt đang chờ lock — không còn nứt thành nhiều lượt chồng nhau.

## 1.1.0

- Chat phụ bằng topic tự do: `/chatphu`, `/chatphu_list`,
  `/dongchat`, `/chatphu_dong`, `/chatphu_mo` (SideChatRegistry).

## 1.0.1

- Vá nghi lễ BOOTSTRAP gãy đầu–cuối: nạp + render BOOTSTRAP.md
  khi còn pending, `/start` trích đúng mục câu hỏi, file tools
  ghi được vào thư mục dossier.

## 1.0.0

- Đủ 6 phase theo tài liệu thiết kế: lõi plan–act–verify, ký ức
  hybrid + học correction, MCP/subagent/scheduler, proactivity +
  voice + media + skills, eval vàng + backup + báo cáo, bề mặt
  group forum (Feed/Ideas/Library/Vault/quyền).
