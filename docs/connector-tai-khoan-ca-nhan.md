# Tài liệu Kỹ thuật: Connector Tài khoản Cá nhân (Zalo, Telegram MTProto, Facebook, Instagram DM, Threads DM)

> Mục tiêu: Parity tính năng với Muse thật (T-22.1, T-22.2, T-22.3 — Parity Connector tài khoản cá nhân).
> Cung cấp khả năng kết nối tài khoản Zalo cá nhân, Telegram cá nhân, Facebook cá nhân, tin nhắn Instagram (Direct Messages), và tin nhắn Threads của chính người dùng.

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

## 4. Chi tiết Connector Facebook cá nhân (`facebook_personal`)

> Chi tiết báo cáo khảo sát kỹ thuật độc lập xem tại `docs/nghien-cuu-facebook-ca-nhan.md`.

### Cơ chế & Đăng nhập
- Sử dụng phiên Web Cookies (`c_user`, `xs`, `fr`, `datr`).
- Người dùng trích xuất chuỗi cookies từ trình duyệt thực tế đang chạy trên cùng máy cài bot (chia sẻ cùng IP/ASN mạng gia đình).
- Phiên cookie được lưu an toàn qua Vault (`facebook_personal:session`).

### Các hành động hỗ trợ
- `configure` / `connect`: Nhập và kiểm tra chuỗi cookie phiên (`c_user`, `xs`).
- `check_session`: Kiểm tra tính hợp lệ của cookie.
- **Danh tính & Quan hệ**:
  - `get_profile` / `get_me`: Đọc thông tin trang cá nhân (`id`, `name`, `profile_url`, `bio`).
  - `get_friends` / `list_friends`: Đọc danh sách bạn bè.
  - `view_user_profile`: Xem trang cá nhân / timeline người khác theo `user_id` (nội dung bọc qua `frame_external`).
- **Bảng tin (Feed)**:
  - `read_feed` / `read_news_feed`: Đọc các bài viết gần nhất trên Bảng tin chính (bọc `frame_external`).
  - `read_friends_feed`: Đọc các bài viết từ bạn bè (bọc `frame_external`).
- **Nhóm (Groups)**:
  - `list_groups`: Liệt kê **TOÀN BỘ nhóm tài khoản đang tham gia** (kể cả nhóm kín/ẩn bí mật).
  - `get_group_detail`: Xem chi tiết nhóm (tên, luật, số thành viên, mức riêng tư public/closed/secret).
  - `read_group_posts`: Đọc bài viết trong nhóm (bọc `frame_external`).
  - `search_groups`: Tìm kiếm nhóm theo từ khóa.
- **Bài viết & Tương tác**:
  - `read_post`: Đọc chi tiết bài viết (bọc `frame_external`).
  - `read_comments`: Đọc bình luận bài viết (bọc `frame_external`).
  - `read_reactions`: Đọc reaction (like, love, haha, wow, sad, angry).
  - `write_comment`: Viết bình luận lên bài viết (phân quyền `ask` duyệt từng lần; yêu cầu transport thật, cấm stub ok).
  - `reply_comment`: Trả lời bình luận (phân quyền `ask` duyệt từng lần; yêu cầu transport thật).
  - `create_post`: Đăng bài viết lên trang cá nhân (phân quyền `ask` duyệt từng lần; yêu cầu transport thật).
- **Fanpage đang quản lý**:
  - `list_pages`: Liệt kê các Fanpage người dùng đang quản lý.
  - `get_page_insights`: Xem số liệu thống kê, reach, tương tác của Page.
  - `create_page_draft`: Tạo bài viết nháp trên Page (phân quyền `ask`).
  - `create_page_post`: Đăng bài trực tiếp lên Page (phân quyền `ask`).
- **Sự kiện (Events)**:
  - `search_events`: Tìm kiếm sự kiện theo từ khóa.
  - `get_event_detail`: Xem chi tiết sự kiện (thời gian, địa điểm, mô tả bọc `frame_external`).
- **Story**:
  - `read_stories`: Đọc tin Story đang hoạt động (caption bọc `frame_external`).
- **Đã lưu (Saved)**:
  - `list_saved`: Xem danh sách bài viết / liên kết đã lưu.
  - `save_item`: Lưu mục vào Saved (phân quyền `ask`).
  - `unsave_item`: Bỏ lưu mục (phân quyền `ask`).
- **Marketplace**:
  - `search_marketplace`: Tìm kiếm sản phẩm Marketplace theo từ khóa / danh mục (bọc `frame_external`).
  - `get_my_marketplace_listings`: Xem danh sách tin đăng Marketplace của tôi.
- **Messenger**:
  - `read_messages` / `get_messages`: Đọc tin nhắn Messenger (bọc `frame_external`).
  - `send_message`: Gửi tin nhắn Messenger (phân quyền `ask`).
- `disconnect`: Xoá sạch session cookies, thông tin cache và cờ checkpoint khỏi Vault.

### Cơ chế Checkpoint Guard (Tự ngắt bảo vệ)
- Meta không hỗ trợ API chính thức cho tài khoản cá nhân và có hệ thống quét bot tự động.
- Để bảo vệ tài khoản người dùng tối đa, connector tích hợp **Checkpoint Guard**:
  - Khi phát hiện mã phản hồi 302 chuyển hướng tới `/checkpoint/` hoặc chuỗi nhận diện khóa tài khoản, connector **lập tức ngắt kết nối**, bật cờ `checkpoint_detected` trong Vault (`facebook_personal:checkpoint`).
  - Dừng toàn bộ các request tiếp theo để ngăn chặn nguy cơ bị khóa tài khoản vĩnh viễn do spam request lặp lại.
  - Cảnh báo người dùng qua Telegram bot và Mini App để người dùng mở trình duyệt xử lý thủ công.

---

## 5. Chi tiết Connector Tin nhắn Instagram (`instagram_messages`)

> Tiền lệ phía Muse: Kết nối TIN NHẮN tách riêng với kết nối bài đăng/nội dung (T-17). Người dùng có thể đã nối Instagram (bài đăng) mà chưa nối tin nhắn.

### Cơ chế & Đăng nhập
- Kết nối bằng phiên cookie (`sessionid`, `ds_user_id`, `csrftoken`) hoặc Token Meta Accounts Center.
- Phiên được lưu trữ an toàn trong Vault (`instagram_messages:session`), thông tin tài khoản tại `instagram_messages:user_info`.
- Tích hợp **Checkpoint Guard** tự ngắt khi phát hiện checkpoint (`instagram_messages:checkpoint`).

### Các hành động hỗ trợ
- `configure` / `connect`: Cấu hình phiên đăng nhập.
- `check_session`: Kiểm tra trạng thái phiên.
- `read_inbox` / `get_inbox`: Đọc hộp thư với tuỳ chọn thư mục `inbox`, `pending` (yêu cầu chờ), `spam`. Toàn bộ nội dung trích đoạn bọc bảo vệ bằng `frame_external`.
- `read_messages` / `get_messages`: Đọc tin nhắn chi tiết trong 1 hội thoại (`thread_id`). Bọc `frame_external`.
- `search_messages`: Tìm kiếm tin nhắn theo từ khóa `query`. Bọc `frame_external`.
- `send_message`: Gửi tin nhắn văn bản vào hội thoại có sẵn hoặc người nhận (phân quyền `ask`).
- `send_file`: Gửi tệp đính kèm hoặc hình ảnh vào hội thoại (phân quyền `ask`).
- `send_reaction`: Thả reaction emoji vào tin nhắn (phân quyền `ask`).
- `disconnect`: Đăng xuất và dọn dẹp sạch Vault.

---

## 6. Chi tiết Connector Tin nhắn Threads (`threads_messages`)

> Tiền lệ phía Muse: Kết nối TIN NHẮN tách riêng với kết nối bài đăng/nội dung (T-17).

### Cơ chế & Đăng nhập
- Kết nối bằng phiên cookie (`sessionid`, `token`).
- Lưu trữ an toàn trong Vault (`threads_messages:session`).

### GIỚI HẠN CỨNG BẮT BUỘC (Strict Parity Guard)
- **Chỉ nhắn được người ĐÃ có hội thoại từ trước** (hoặc đã nhắn cho mình trước).
- **Tuyệt đối KHÔNG mở DM mới tới người lạ chỉ bằng @handle.**
- Khi có yêu cầu gửi tin nhắn tới người chưa từng có hội thoại, connector **từ chối ngay lập tức** kèm thông báo lỗi giải thích rõ giới hạn, tuyệt đối không nuốt lỗi im lặng.

### Các hành động hỗ trợ
- `configure` / `connect`: Cấu hình phiên đăng nhập.
- `read_inbox` / `get_inbox`: Đọc hộp thư (`inbox`, `pending`). Bọc `frame_external`.
- `read_messages` / `get_messages`: Đọc tin nhắn hội thoại (`thread_id`). Bọc `frame_external`.
- `send_message`: Gửi tin nhắn vào hội thoại đã có từ trước (phân quyền `ask`). Kiểm tra nghiêm ngặt giới hạn cứng.
- `send_reaction`: Thả reaction emoji vào tin nhắn (phân quyền `ask`).
- `disconnect`: Đăng xuất và dọn dẹp sạch Vault.

---

## 6.2. Chi tiết Connector Threads cá nhân — Nội dung & Bài viết (`threads_personal`) - T-30

> Khác biệt với `threads_messages` (chỉ chuyên DM), `threads_personal` phụ trách toàn bộ bề mặt nội dung, bài đăng, bảng tin và tương tác Threads.

### Nguyên tắc kết nối ưu tiên API chính thức
1. **Ưu tiên API Threads chính thức (Graph API)**:
   - Sử dụng Graph API User Token lưu trong Vault (`threads_personal:token`).
   - Hỗ trợ các hành động: `get_profile`, `list_posts`, `get_post`, `get_post_replies`, `get_insights`, `create_post`, `create_reply`.
2. **Fallback phiên Web Cookie (`threads_personal:session`) cho endpoint Web-Only**:
   - Meta Graph API chưa hỗ trợ một số endpoint người dùng cá nhân (Feed, Xu hướng, Tìm kiếm, Gợi ý feed).
   - Connector tự động fallback sang phiên Web Cookie cho:
     * `read_feed`: Đọc Bảng tin Threads cá nhân.
     * `get_trends`: Xem các chủ đề xu hướng.
     * `search_posts`: Tìm kiếm bài đăng theo từ khóa.
     * `set_feed_suggestions`: Điều chỉnh gợi ý chủ đề Bảng tin (phân quyền `ask`).
3. **Kỷ luật & Bảo mật (T-30)**:
   - Đọc = allow, Ghi (`create_post`, `create_reply`, `set_feed_suggestions`) = ask duyệt từng lần.
   - Toàn bộ nội dung bên ngoài bọc qua `frame_external`.
   - CẤM trả `ok: True` stub khi không có transport thực tế — trả `unsupported: True` rõ ràng.

---

## 7. Bề mặt Sử dụng

### 1. Telegram Chat Bot
- `/zalo status`: Kiểm tra trạng thái kết nối Zalo.
- `/zalo qr`: Khởi tạo và nhận mã QR đăng nhập Zalo.
- `/zalo disconnect`: Đăng xuất và ngắt kết nối Zalo.
- `/telethon status` (hoặc `/telegram_user status`): Kiểm tra trạng thái Telegram cá nhân.
- `/telethon qr`: Nhận link/mã QR đăng nhập MTProto cá nhân.
- `/telethon disconnect`: Ngắt kết nối Telegram cá nhân.
- `/facebook status`: Kiểm tra trạng thái kết nối Facebook, phát hiện checkpoint và xem cảnh báo rủi ro.
- `/facebook connect <cookies>`: Kết nối Facebook cá nhân bằng chuỗi cookie web.
- `/facebook groups`: Liệt kê danh sách nhóm Facebook đã tham gia (kể cả kín/ẩn).
- `/facebook feed`: Đọc tóm tắt Bảng tin Facebook gần nhất.
- `/facebook disconnect`: Đăng xuất và ngắt kết nối Facebook cá nhân.
- `/instagram status`: Kiểm tra trạng thái kết nối tin nhắn Instagram.
- `/instagram connect <cookies/session>`: Kết nối tin nhắn Instagram bằng chuỗi cookie/sessionid.
- `/instagram inbox [pending|spam]`: Xem tóm tắt hộp thư tin nhắn Instagram.
- `/instagram disconnect`: Đăng xuất và ngắt kết nối tin nhắn Instagram.
- `/threads status`: Kiểm tra trạng thái tin nhắn và nội dung Threads.
- `/threads connect <cookies/session>`: Kết nối phiên Threads.
- `/threads inbox [pending]`: Xem tóm tắt hộp thư tin nhắn Threads.
- `/threads posts`: Xem các bài đăng Threads gần nhất.
- `/threads disconnect`: Đăng xuất và ngắt kết nối Threads.

### 2. Telegram Mini App
- Truy cập tab **Cài đặt** -> **Công cụ kết nối**.
- Các thẻ `zalo_personal`, `telegram_personal`, `facebook_personal`, `instagram_messages`, `threads_messages`, và `threads_personal` hiển thị trạng thái kết nối trực quan.
- Thẻ `threads_personal` hiển thị chế độ hoạt động (Graph API, Web Session hoặc Hybrid) và trạng thái phân quyền.

---

## 8. Hướng dẫn cài đặt bổ sung cho máy chủ

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
