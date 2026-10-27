# Spike & Hướng dẫn Browser Bridge: Tin nhắn Threads & Instagram (T-22.3)

## Vì sao cần Browser Bridge

API chính thức của Meta (cả Threads lẫn Instagram Web thông thường không qua Graph API Business) không mở endpoint gửi tin nhắn trực tiếp cá nhân (DM).
- Connector `threads_messages` và `instagram_messages` trước đây có các nhánh trả `sent: True` hoặc `reacted: True` giả khi không có session runner — tin nhắn chưa hề gửi đi.
- Browser Bridge là đường gửi thật duy nhất cho tài khoản cá nhân: dùng Chromium với profile đã đăng nhập sẵn của người cài, tự động mở hộp thư web, tìm hội thoại có sẵn, soạn tin/thả reaction và xác minh thật qua DOM.
- Khi không có transport (không session runner, không browser bridge), connector bắt buộc trả lỗi trung thực:
  `{"ok": False, "unsupported": True, "error": "..."}` chống báo thành công giả.

## Khắc phục cổng phiên Cookie (Phiên bản v1.7.33)

Trước đây, connector yêu cầu phải có cookie (`sessionid`) trong Vault trước khi kiểm tra Bridge. Nếu người cài chỉ cấu hình `BROWSER_PROFILE_DIR` (đã đăng nhập Chromium) mà chưa trích xuất cookie dán vào Vault, hệ thống sẽ chặn trước khi Bridge được gọi.
- **Giải pháp**: Logic đã được tách biệt (`has_session or self._browser_bridge is not None`). Nếu người cài đã cấu hình profile trình duyệt (`BROWSER_PROFILE_DIR`), Bridge được phép thực thi trực tiếp mà không cần dán cookie vào Vault.
- Nếu muốn dùng cả tính năng đọc hộp thư / tin nhắn qua session runner HTTP: thực hiện thêm bước cấu hình cookie trong Mini App hoặc qua Vault (`instagram_messages:configure`, `threads_messages:configure`).

## Cách thiết lập trên máy Mac (Người cài làm 1 lần)

1. **Cài đặt Playwright**:
   ```bash
   pip install playwright && playwright install chromium
   ```
2. **Tạo Profile Chromium đăng nhập**:
   - Mở Chromium với profile riêng (đặt tại một thư mục cố định, ví dụ `~/.mulon-browser-profile` hoặc đường dẫn tùy chọn).
   - Đăng nhập Threads (`https://www.threads.net`) và Instagram (`https://www.instagram.com`) 1 lần bằng tài khoản của chủ sở hữu.
   - Đóng hoàn toàn trình duyệt.
   - *Lưu ý*: Bot KHÔNG tự động đăng nhập và KHÔNG lưu mật khẩu — bước này do người cài thực hiện thủ công bằng tay.
3. **Cấu hình biến môi trường**:
   Thêm vào file `.env`:
   ```bash
   BROWSER_PROFILE_DIR="/path/to/your/browser-profile"
   # Tùy chọn (đã có mặc định):
   # THREADS_WEB_BASE_URL="https://www.threads.net"
   # INSTAGRAM_WEB_BASE_URL="https://www.instagram.com"
   ```
4. **Kiểm tra gửi tin nhắn & Thả Reaction**:
   - Nhắn bot gửi 1 DM thử vào một hội thoại ĐÃ CÓ từ trước (Threads áp dụng Strict Parity Guard: cấm mở DM mới tới người lạ bằng @handle).
   - Lệnh gửi tin nhắn và reaction đều qua cơ chế kiểm duyệt (`PolicyEngine`: verdict `ask` cho `send_message`, `send_reaction`). Chủ bấm Duyệt thì thao tác mới diễn ra trên trình duyệt.
   - **Xác thực kết quả thật**: Bridge chỉ trả thành công khi xác nhận được nội dung tin nhắn hoặc reaction đã hiển thị trên DOM của trình duyệt. Nếu không thấy, sẽ trả lỗi chi tiết.

## Bộ Selector linh hoạt (`config/*_web_selectors.json`)

Tất cả selector DOM đều được tách ra file cấu hình, không hardcode trong mã nguồn:
- Threads: `config/threads_web_selectors.json`
- Instagram: `config/instagram_web_selectors.json`

Khi Meta thay đổi giao diện web, chỉ cần cập nhật selector trong các file JSON này mà không cần sửa code.
