# Kết nối Google cho Mulon (Gmail + Google Calendar) — 1.5.0

Mulon đọc/gửi Gmail và đọc/ghi Google Calendar bằng tài khoản
Google của chính bạn, qua OAuth2. Làm 1 lần ~10 phút. Sau đó
bấm **Kết nối** trong Mini App là xong; refresh token nằm
trong Vault trên máy của bạn, Mulon tự làm mới, không hỏi lại.

## Bước 1 — Tạo project + bật API

1. Vào https://console.cloud.google.com → tạo project mới
   (tên gì cũng được, vd `mulon`).
2. **APIs & Services → Library** → bật **Gmail API** và
   **Google Calendar API**.

## Bước 2 — Màn hình đồng ý (OAuth consent screen)

1. **APIs & Services → OAuth consent screen** → chọn
   **External** → điền tên app (vd `Mulon`), email hỗ trợ là
   email của bạn.
2. Ở mục **Test users**: thêm chính email Google của bạn.
   (App ở chế độ Testing là đủ dùng cho 1 người; token phải
   làm mới ủy quyền sau ~7 ngày nếu Google yêu cầu — khi đó
   chỉ cần bấm Kết nối lại trong Mini App.)

## Bước 3 — Tạo OAuth client

1. **APIs & Services → Credentials → Create Credentials →
   OAuth client ID**.
2. Loại ứng dụng: **Web application** nếu Mini App của bạn có
   `WEBAPP_URL` công khai; **Desktop app** nếu bạn chạy bot
   thuần local không tunnel.
3. **Authorized redirect URIs** — thêm ĐÚNG URI này (sai 1 ký
   tự là Google báo `redirect_uri_mismatch`):
   - Có WEBAPP_URL: `https://<WEBAPP_URL của bạn>/google/callback`
   - Thuần local: `http://127.0.0.1:8320/google/callback`
     (8320 = `WEBAPP_PORT` mặc định; đổi nếu bạn đổi cổng).
4. Tạo xong, ghi lại **Client ID** và **Client secret**.

## Bước 4 — Đưa credential vào Mulon (2 cách, chọn 1)

- **Cách A (khuyên dùng) — qua Vault trong Mini App:** mở
  Mini App → Cài đặt → Kho lưu trữ an toàn → Thêm bí mật mới
  2 lần với nhãn ĐÚNG:
  - nhãn `google:client_id` — giá trị: Client ID
  - nhãn `google:client_secret` — giá trị: Client secret
- **Cách B — qua .env:** đặt `GOOGLE_CLIENT_ID` /
  `GOOGLE_CLIENT_SECRET` rồi khởi động lại bot.

## Bước 5 — Kết nối

Mini App → Cài đặt → Công cụ kết nối: 2 hàng **gmail** và
**gcalendar** hiện "Chưa kết nối" kèm nút **Kết nối** → bấm →
trình duyệt mở trang Google → chọn tài khoản + đồng ý → thấy
trang "Đã kết nối Google" là xong. Quay lại Mini App, 2 hàng
chuyển "Đã kết nối · <email của bạn>".

Từ đây nhờ Mulon trong chat được ngay, vd: "đọc hộp thư hôm
nay có gì quan trọng", "tìm mail của ngân hàng tháng này",
"tuần này lịch của anh có gì", "tạo lịch họp mai 9h với đội".

## Quyền & an toàn

- Scope Mulon xin: đọc/tìm/gán nhãn Gmail (`gmail.modify`),
  gửi thư (`gmail.send`), đọc/ghi sự kiện lịch
  (`calendar.events`). Không xin quyền xoá thư vĩnh viễn,
  không đụng Drive.
- Đặt mức quyền riêng cho từng connector ở Mini App →
  Cài đặt → Quyền → mục "Connector & server MCP": khuyên đặt
  **Hỏi** cho `gmail` và `gcalendar` nếu bạn muốn duyệt trước
  mỗi lần Mulon gọi (gửi thư/tạo lịch sẽ qua thẻ duyệt).
- Ngắt kết nối: nút **Ngắt kết nối** ở màn Công cụ kết nối
  (xoá refresh token khỏi Vault). Muốn thu hồi triệt để phía
  Google: https://myaccount.google.com/permissions → gỡ app.
