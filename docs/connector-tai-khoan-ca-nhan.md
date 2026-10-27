# Tài liệu Kỹ thuật: Connector Tài khoản Cá nhân (Zalo & Telegram MTProto)

> Mục tiêu: Parity tính năng với Muse thật (T-22.1 — Parity Connector tài khoản cá nhân).
> Cung cấp khả năng kết nối tài khoản Zalo cá nhân và Telegram cá nhân của chính người dùng
> thông qua quét mã QR an toàn, không cần mật khẩu.

---

## 1. Tổng quan Kiến trúc

MuLon bổ sung hai connector tích hợp sẵn (built-in) dành cho tài khoản cá nhân:
- **`zalo_personal`**: Tương tác với tài khoản Zalo cá nhân thông qua cơ chế Zalo Web (thư viện `zca-js` chạy qua Node bridge).
- **`telegram_personal`**: Tương tác với tài khoản Telegram cá nhân thông qua giao thức MTProto (thư viện `telethon` Python).

### Nguyên tắc bất biến
1. **Dùng tài khoản của chính người cài**: Không dùng tài khoản chia sẻ hay tài khoản bot bên thứ ba.
2. **Bảo mật phiên đăng nhập qua Vault**:
   - Phiên đăng nhập (Session string của Telethon hoặc Cookies/IMEI của Zalo Web) chỉ lưu trữ an toàn trong Vault của bản cài (`telegram_personal:session`, `zalo_personal:session`).
   - Tuyệt đối không lưu vào git repo, không ghi log, không in ra trajectory và không xuất hiện trong nội dung chat.
3. **Phân quyền theo từng hành động (Policy Engine)**:
   - Các thao tác đọc (`read_messages`, `get_messages`, `list_dialogs`, `find_user`): mặc định **Cho phép (allow)**.
   - Các thao tác gửi (`send_message`, `send_file`): mặc định **Hỏi trước (ask)** qua thẻ phê duyệt `ApprovalBroker`.
4. **Bảo vệ dữ liệu ngoài (External Data Guard)**:
   - Toàn bộ nội dung tin nhắn và tệp nhận từ người khác qua Zalo và Telegram cá nhân đều bắt buộc đi qua hàm `frame_external`, đảm bảo LLM xem đây là dữ liệu tham khảo, không bị tấn công prompt injection.
5. **Degrade sạch sẽ (Graceful Degradation)**:
   - Nếu môi trường máy cài chưa có Node.js hoặc thư viện `telethon`: bot vẫn khởi động và hoạt động bình thường 100%, connector báo trạng thái chưa sẵn sàng kèm hướng dẫn cài đặt.

---

## 2. Chi tiết Connector Zalo cá nhân (`zalo_personal`)

### Thư viện & Cơ chế
- Sử dụng thư viện `zca-js` (Unofficial Zalo API) tương tác với Zalo Web.
- Giao tiếp giữa Python và Node.js thông qua tiến trình con `mulon/bridges/zalo_bridge.mjs` sử dụng giao thức JSON-line trên stdin/stdout (tương tự kiến trúc MCP stdio).

### Các hành động hỗ trợ
- `qr_login`: Khởi tạo phiên đăng nhập QR. Người dùng mở app Zalo trên điện thoại quét mã QR.
- `login_session`: Tái sử dụng phiên cookies/imei đã lưu trong Vault mà không cần quét lại mã.
- `read_messages` / `get_messages`: Đọc tin nhắn gần nhất từ hội thoại (được đóng khung `frame_external`).
- `send_message`: Gửi tin nhắn văn bản đến người dùng hoặc nhóm (type: `user` hoặc `group`).
- `send_file`: Gửi tệp đính kèm hoặc hình ảnh.
- `find_user`: Tìm kiếm thông tin người dùng theo số điện thoại.
- `listen`: Lắng nghe tin nhắn mới theo thời gian thực.
- `disconnect` / `logout`: Đăng xuất và dọn dẹp sạch sẽ session trong Vault.

### Giới hạn quan trọng
- **KHÔNG hỗ trợ đăng nhật ký / bài viết**: Zalo Web cá nhân không cung cấp API đăng bài viết lên dòng thời gian. Tính năng này yêu cầu Zalo Official Account (Zalo OA API) và nằm ngoài phạm vi connector cá nhân. Giới hạn này được hiển thị rõ ràng trên Mini App và thông điệp hướng dẫn.

---

## 3. Chi tiết Connector Telegram cá nhân (`telegram_personal`)

### Thư viện & Cơ chế
- Sử dụng thư viện `telethon` với `StringSession`.
- Kết nối trực tiếp qua giao thức MTProto client (Userbot).
- Kênh **HOÀN TOÀN ĐỘC LẬP** với Bot API (`aiogram`) của MuLon — hai tiến trình chạy song song không can thiệp lẫn nhau.
- Có khả năng đọc và tương tác trong các nhóm/kênh mà tài khoản cá nhân tham gia ngay cả khi bot `@Mulon_bot` không có mặt trong nhóm đó.

### Các hành động hỗ trợ
- `qr_login`: Bắt đầu phiên đăng nhập QR Telethon, trả về URL `tg://login?token=...`.
- `read_messages` / `get_messages`: Đọc tin nhắn từ bất kỳ hội thoại nào mà tài khoản tham gia (được đóng khung `frame_external`).
- `list_dialogs`: Xem danh sách tất cả hội thoại (người dùng, nhóm, kênh).
- `send_message`: Gửi tin nhắn từ tài khoản cá nhân.
- `send_file`: Gửi tệp đính kèm.
- `listen`: Lắng nghe tin nhắn mới qua sự kiện Telethon.
- `disconnect` / `logout`: Ngắt kết nối và xoá session khỏi Vault.

### Cảnh báo rủi ro
- **Rủi ro Userbot**: Telegram có chính sách kiểm soát tần suất tự động hoá của tài khoản người dùng cá nhân. Người dùng cần giữ tần suất gửi tin ở mức bình thường, tránh spam hàng loạt để không bị Telegram hạn chế tạm thời tài khoản. Cảnh báo này luôn được ghi chú trên cả chat và Mini App.

---

## 4. Bề mặt Sử dụng

### 1. Telegram Chat Bot
- `/zalo status`: Kiểm tra trạng thái kết nối Zalo.
- `/zalo qr`: Khởi tạo và nhận mã QR đăng nhập Zalo.
- `/zalo disconnect`: Đăng xuất và ngắt kết nối Zalo.
- `/telethon status` (hoặc `/telegram_user status`): Kiểm tra trạng thái Telegram cá nhân.
- `/telethon qr`: Nhận link/mã QR đăng nhập MTProto cá nhân.
- `/telethon disconnect`: Ngắt kết nối Telegram cá nhân.

### 2. Telegram Mini App
- Truy cập tab **Cài đặt** -> **Công cụ kết nối**.
- Các thẻ `zalo_personal` và `telegram_personal` hiển thị trạng thái kết nối trực quan.
- Nút **Quét QR** để kết nối và nút **Ngắt** để xoá phiên.

---

## 5. Hướng dẫn cài đặt bổ sung cho máy chủ

Nếu máy chủ cài đặt MuLon muốn kích hoạt đầy đủ 100% cả 2 connector:
1. **Telegram cá nhân**:
   ```bash
   pip install telethon
   ```
2. **Zalo cá nhân**:
   - Đảm bảo máy đã cài đặt Node.js (phiên bản 18+).
   - Cài đặt thư viện bridge:
     ```bash
     cd mulon/bridges
     npm install
     ```
