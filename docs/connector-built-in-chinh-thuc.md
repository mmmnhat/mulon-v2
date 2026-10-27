# Built-in Connectors: Google Workspace, Facebook Page, Instagram Business, Threads Official, TikTok (T-17)

Tài liệu này mô tả chi tiết 5 connector tích hợp sẵn (built-in) chính thức của MuLon theo tiêu chuẩn nhiệm vụ **T-17**:
1. **Google Workspace**: Gmail, Google Calendar, Google Drive, Google Docs, Google Sheets.
2. **Facebook Page**: Meta Business Graph API cho Fanpage.
3. **Instagram Business / Creator**: Meta Graph API cho tài khoản chuyên nghiệp.
4. **Threads Official**: Meta Threads Publishing & Insights API chính thức.
5. **TikTok**: TikTok Content Display & Posting API chính thức.

---

## 1. Nguyên tắc kiến trúc & Bảo mật bất biến

1. **Built-in chính thức**: Cài MuLon là có sẵn, không phải là tiện ích cài thêm từ Marketplace.
2. **Tài khoản chính chủ người cài**: Sử dụng OAuth hoặc token riêng của người dùng cài đặt MuLon.
3. **Không hardcode bất kỳ bí mật nào**: Mọi token, secret, refresh token, page id được lưu trữ an toàn trong **Kho bí mật (Secure Vault)** của bản cài.
4. **Bảo vệ dữ liệu ngoài**: Toàn bộ nội dung văn bản lấy từ bên ngoài (bài viết, email, sự kiện, tệp, bảng tính, bình luận, video, bio) đều được bọc tự động qua thẻ phân lập `<external_data>` (`frame_external`) để chống Prompt Injection.
5. **Phân quyền Action-Level Policy 3 nấc**:
   - Các hành động đọc (`search`, `read`, `list`, `get`, `insights`): Mặc định `allow`.
   - Mọi hành động ghi (`send`, `upload`, `create`, `delete`, `publish`, `reply`, `append`, `update`): Mặc định `ask` (buộc phải phê duyệt trước khi thực thi).
6. **Cơ chế Degrade không sập**: Nếu một connector chưa được cấu hình hoặc token hết hạn, connector đó trả về trạng thái suy giảm (`ok: False` kèm hướng dẫn tiếng Việt rõ ràng), toàn bộ hệ thống bot và các connector khác vẫn hoạt động bình thường.
7. **Cấm stub giả mạo**: Không bao giờ trả `ok: True` giả vờ khi không có transport hoặc token thực tế.

---

## 2. Google Workspace (Gmail, Calendar, Drive, Docs, Sheets)

- **Module**: `mulon/google_conn.py`
- **Ủy quyền chung**: Dùng chung 1 luồng OAuth2 của người cài qua `GoogleAuth`.
- **Nhãn lưu trữ Vault**:
  - `google:client_id`: Client ID từ Google Cloud Console.
  - `google:client_secret`: Client Secret.
  - `google:refresh_token`: Token làm mới dài hạn (tự động lưu khi người dùng hoàn tất OAuth).
  - `google:account_email`: Email tài khoản đã ủy quyền.

### Danh sách hành động (Actions):
- **Gmail (`gmail`)**:
  - `search` (Đọc - allow): Tìm kiếm email theo query Gmail (`is:unread`, `from:boss`).
  - `read` (Đọc - allow): Đọc chi tiết nội dung email theo `id`.
  - `send` (Ghi - ask): Gửi email tới người nhận.
  - `feed_snapshot` (Đọc - allow): Điểm tin email nổi bật cho Feed chủ động.
- **Google Calendar (`gcalendar`)**:
  - `list_events` (Đọc - allow): Xem danh sách sự kiện theo khoảng thời gian (`time_min`, `time_max`).
  - `create_event` (Ghi - ask): Tạo sự kiện mới với `summary`, `start`, `end`.
  - `delete_event` (Ghi - ask): Xóa sự kiện theo `event_id`.
- **Google Drive (`gdrive`)**:
  - `list_files` / `search_files` (Đọc - allow): Tìm kiếm và xem danh sách tệp/thư mục.
  - `get_file` (Đọc - allow): Xem thông tin chi tiết của tệp.
  - `create_folder` (Ghi - ask): Tạo thư mục mới.
  - `upload_file` (Ghi - ask): Tải tệp lên Google Drive.
  - `delete_file` (Ghi - ask): Xóa tệp khỏi Google Drive.
  - `share_file` (Ghi - ask): Chia sẻ quyền truy cập cho email hoặc công khai (`reader`/`writer`).
- **Google Docs (`gdocs`)**:
  - `get_document` (Đọc - allow): Đọc nội dung văn bản đầy đủ của tài liệu.
  - `search_docs` (Đọc - allow): Tìm kiếm tài liệu Docs theo tiêu đề.
  - `create_document` (Ghi - ask): Tạo mới tài liệu Docs với tiêu đề tùy chọn.
  - `append_text` (Ghi - ask): Chèn thêm văn bản vào cuối tài liệu.
- **Google Sheets (`gsheets`)**:
  - `get_spreadsheet` (Đọc - allow): Xem cấu trúc các trang tính (sheets).
  - `read_sheet_values` (Đọc - allow): Đọc dữ liệu ô tính theo dải (range, ví dụ `Sheet1!A1:D10`).
  - `append_rows` (Ghi - ask): Thêm dòng dữ liệu mới vào bảng tính.
  - `update_cells` (Ghi - ask): Cập nhật giá trị ô tính.
  - `create_spreadsheet` (Ghi - ask): Tạo bảng tính mới.

---

## 3. Facebook Page (Meta Business Graph API)

- **Module**: `mulon/social_connectors.py:FacebookPageConnector`
- **Nhãn lưu trữ Vault**:
  - `facebook_page:access_token`: Page Access Token được cấp từ Meta Developer App / Meta Business Suite.
  - `facebook_page:page_id`: ID của Fanpage Facebook.
  - `facebook_page:page_name`: Tên Fanpage.

### Danh sách hành động:
- `get_page_info` (Đọc - allow): Xem thông tin trang (tên, thể loại, mô tả, số lượt thích/theo dõi).
- `read_page_feed` (Đọc - allow): Đọc các bài viết trên Bảng tin Fanpage kèm số lượt chia sẻ, bình luận, cảm xúc.
- `read_page_posts` (Đọc - allow): Xem danh sách bài đăng chính thức của Page.
- `read_post_comments` (Đọc - allow): Đọc các bình luận dưới bài viết.
- `get_page_insights` (Đọc - allow): Xem các chỉ số tương tác, lượt tiếp cận (`page_impressions`, `page_engaged_users`).
- `publish_post` (Ghi - ask): Đăng bài viết mới trực tiếp lên Fanpage.
- `create_draft_post` (Ghi - ask): Tạo bài viết nháp trên Fanpage.
- `reply_comment` (Ghi - ask): Trả lời bình luận của người dùng.
- `delete_post` (Ghi - ask): Xóa bài viết khỏi Fanpage.

---

## 4. Instagram Business / Creator (Meta Graph API)

- **Module**: `mulon/social_connectors.py:InstagramBusinessConnector`
- **Nhãn lưu trữ Vault**:
  - `instagram_business:access_token`: User / Page Access Token có quyền truy cập Instagram Professional.
  - `instagram_business:account_id`: Instagram Business Account ID.
  - `instagram_business:username`: Tên người dùng Instagram (`@handle`).

### Danh sách hành động:
- `get_profile` (Đọc - allow): Xem thông tin hồ sơ tài khoản (bio, số người theo dõi, số bài đăng).
- `list_media` (Đọc - allow): Xem danh sách bài đăng ảnh/video/Reel kèm số like và bình luận.
- `get_media_detail` (Đọc - allow): Xem chi tiết một bài đăng cụ thể.
- `read_comments` (Đọc - allow): Đọc các bình luận dưới bài đăng Instagram.
- `get_insights` (Đọc - allow): Xem thống kê lượt hiển thị và tiếp cận (`impressions`, `reach`).
- `publish_photo` (Ghi - ask): Xuất bản bài đăng ảnh qua quy trình 2 bước container chính thức.
- `publish_reel` (Ghi - ask): Xuất bản video ngắn Reel qua quy trình video container.
- `reply_comment` (Ghi - ask): Trả lời bình luận của khán giả.
- `delete_comment` (Ghi - ask): Xóa bình luận không phù hợp.

---

## 5. Threads Official (Meta Threads API)

- **Module**: `mulon/social_connectors.py:ThreadsOfficialConnector`
- **Nhãn lưu trữ Vault**:
  - `threads_official:access_token`: Threads User Access Token.
  - `threads_official:user_id`: Threads User ID.
  - `threads_official:username`: Username Threads.

### Danh sách hành động:
- `get_profile` (Đọc - allow): Xem thông tin trang cá nhân Threads (ảnh đại diện, bio).
- `list_threads` (Đọc - allow): Xem danh sách bài viết Threads đã đăng.
- `get_thread_detail` (Đọc - allow): Xem nội dung chi tiết bài viết Threads.
- `read_replies` (Đọc - allow): Đọc các bài trả lời / hội thoại thảo luận.
- `get_thread_insights` (Đọc - allow): Xem số liệu chi tiết (lượt xem views, likes, replies, reposts, quotes).
- `publish_thread` (Ghi - ask): Đăng bài viết mới lên Threads (hỗ trợ kèm ảnh).
- `reply_thread` (Ghi - ask): Trả lời bài viết trên Threads.
- `delete_thread` (Ghi - ask): Xóa bài viết Threads.

---

## 6. TikTok (TikTok Content Display & Posting API)

- **Module**: `mulon/social_connectors.py:TikTokConnector`
- **Nhãn lưu trữ Vault**:
  - `tiktok:access_token`: TikTok User Access Token.
  - `tiktok:open_id`: Định danh Open ID của nhà sáng tạo.
  - `tiktok:client_key`: Client Key của TikTok Developer App.
  - `tiktok:display_name`: Tên hiển thị của kênh TikTok.

### Danh sách hành động:
- `get_creator_info` / `get_user_info` (Đọc - allow): Xem thông tin tài khoản nhà sáng tạo, avatar, bio, số người theo dõi, số lượt thích.
- `list_videos` (Đọc - allow): Xem danh sách video đã tải lên kèm thời lượng, link xem, số lượt xem và tương tác.
- `get_video_stats` (Đọc - allow): Tra cứu số liệu thống kê lượt xem, thích, bình luận, chia sẻ của video.
- `share_video_draft` (Ghi - ask): Tải video lên dưới dạng Bản nháp (Inbox Draft).
- `post_video` (Ghi - ask): Đăng video trực tiếp lên trang cá nhân TikTok.

### Giới hạn chính thức của TikTok:
> **Lưu ý quan trọng**: TikTok Content Posting API yêu cầu ứng dụng phải được TikTok Partner Review duyệt quyền `video.publish` cho tính năng Direct Post. Đối với tài khoản phát triển thông thường, MuLon sẽ chuyển video sang chế độ **Bản nháp (Inbox Draft)** trên ứng dụng di động TikTok của nhà sáng tạo để xác nhận thủ công, bảo vệ an toàn 100% cho kênh.

---

## 7. Lệnh tương tác nhanh trên Telegram Bot

- `/google`: Xem tổng quan trạng thái Google Workspace (Gmail, Calendar, Drive, Docs, Sheets).
- `/google drive`: Xem danh sách 5 tập tin gần nhất trên Google Drive.
- `/google_auth`: Lấy đường link ủy quyền OAuth2 cho Google Workspace.
- `/fbpage`: Xem trạng thái kết nối Fanpage Facebook.
- `/fbpage feed`: Xem danh sách 5 bài viết gần nhất trên Fanpage.
- `/tiktok`: Xem trạng thái kết nối tài khoản nhà sáng tạo TikTok.
- `/tiktok videos`: Xem danh sách 5 video gần nhất trên kênh TikTok.
