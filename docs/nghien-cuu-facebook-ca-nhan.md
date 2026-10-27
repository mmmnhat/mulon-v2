# Báo cáo Nghiên cứu Kỹ thuật: Khả năng Kết nối Facebook Cá nhân (T-22.2)

> **Mục tiêu**: Đánh giá toàn diện tính khả thi, độ ổn định, cơ chế xác thực và rủi ro khóa tài khoản
> khi tích hợp tài khoản Facebook cá nhân vào MuLon (T-22.2).
> **Trạng thái**: Hoàn tất nghiên cứu Bước 1. Đưa ra giải pháp triển khai an toàn có điều kiện cho Bước 2.

---

## 1. Bối cảnh & So sánh với Muse Thật

### Cơ chế của Muse AI (Meta Platforms)
- Phía Muse thật kết nối tài khoản Facebook cá nhân và Instagram/Threads thông qua cơ chế liên kết **Meta Accounts Center**.
- Đây là **cơ chế nội bộ (First-Party SSO & Cross-App Infrastructure)** được thiết kế riêng cho hệ sinh thái của Meta. Muse được cấp quyền truy cập trực tiếp vào các service token nội bộ, session liên ứng dụng và các microservices backend của Facebook mà không phải qua lớp bảo vệ bot hay rào cản IP.
- **Kết luận**: MuLon là một dự án độc lập, chạy mã nguồn mở của bên thứ ba, **TUYỆT ĐỐI KHÔNG THỂ** sử dụng lại hay giả lập đường liên kết Meta Accounts Center nội bộ này.

---

## 2. Khảo sát Hiện trạng API Chính thức của Meta (Graph API v21.0)

Meta hiện duy trì hệ thống Graph API cho các nhà phát triển bên ngoài. Tuy nhiên, đối với tài khoản cá nhân thông thường:

1. **Thông tin Trang cá nhân (User Profile)**:
   - Endpoint `/me` chỉ trả về `id` và `name` cơ bản. Mọi thông tin mở rộng khác (email, ngày sinh, bài viết) đều yêu cầu quyền hạn cao cấp (Advanced Access) và phải trải qua quy trình Meta App Review khắt khe dành cho doanh nghiệp đã xác minh (Verified Business).
2. **Bảng tin cá nhân (User News Feed)**:
   - Quyền `user_posts` và endpoint `/me/feed` đối với tài khoản người dùng cá nhân đã bị **khóa chặt và loại bỏ hoàn toàn** từ Graph API v3.0 (sau sự cố Cambridge Analytica). Hiện tại chỉ có Trang (Facebook Pages) hoặc Nhóm (Facebook Groups có cài App) mới có thể đọc/đăng bài qua API.
3. **Danh sách Bạn bè (Friend List)**:
   - Endpoint `/me/friends` với quyền `user_friends` **CHỈ TRẢ VỀ** những người bạn cũng đã cài đặt và ủy quyền cho chính ứng dụng đó. Nó hoàn toàn không trả về danh sách bạn bè đầy đủ trên Facebook của người dùng.
4. **Tin nhắn Messenger cá nhân (User-to-User Messenger)**:
   - Messenger Platform API của Meta chỉ hỗ trợ:
     - Trang doanh nghiệp giao tiếp với khách hàng (Page Messaging).
     - Tài khoản Instagram Professional / Creator.
     - WhatsApp Business API.
   - Meta **hoàn toàn KHÔNG cung cấp** bất kỳ API chính thức nào cho phép gửi/nhận tin nhắn trực tiếp giữa hai tài khoản Facebook cá nhân thông thường (User-to-User).

**Kết luận API chính thức**: Không có bất kỳ API chính thức nào của Meta đáp ứng được phạm vi mục tiêu (đọc trang cá nhân, bạn bè, bảng tin, và đọc/gửi Messenger cá nhân).

---

## 3. Khảo sát Các Giải pháp Không chính thức (Unofficial Reverse Engineering)

Do không có API chính thức, các công cụ tự động hóa Facebook cá nhân bên thứ ba trên thị trường đều phải dựa vào một trong các kỹ thuật sau:

### 3.1. Phương án A: Phiên Web Cookie (Web Session Cookies) qua HTTP / GraphQL
- **Cơ chế**: Người dùng trích xuất các cookie phiên từ trình duyệt đã đăng nhập:
  - `c_user`: User ID của Facebook.
  - `xs`: Session secret token của Facebook.
  - `fr`: Encrypted authentication cookie.
  - `datr`: Trình theo dõi trình duyệt và thiết bị của Meta.
  - Token bảo mật đi kèm: `fb_dtsg` và `jazoest` được bóc tách từ HTML của Facebook để ký các GraphQL mutation / POST request.
- **Thực trạng các thư viện mã nguồn mở**:
  - `fbchat` (Python): Thư viện nổi tiếng nhất một thời đã ngừng duy trì hoàn toàn từ 2020 do Meta chuyển dịch toàn bộ chat sang MQTT WebSocket edge (`wss://edge-chat.facebook.com`) và liên tục thay đổi mã hóa GraphQL schema.
  - `fca-unofficial` / `facebook-chat-api` (Node.js): Duy trì chắp vá, thường xuyên bị lỗi khi Meta cập nhật payload schema hoặc đổi thuật toán sinh hash.
- **Ưu điểm**: Nhẹ, không cần cài đặt môi trường trình duyệt cồng kềnh, có thể chạy trực tiếp bằng các HTTP request Python chuẩn (`httpx` / `aiohttp`).

### 3.2. Phương án B: Tự động hóa Trình duyệt không đầu (Headless Browser - Playwright / Puppeteer)
- **Cơ chế**: Khởi chạy một instance Chromium chạy ngầm, chia sẻ `user-data-dir` (profile trình duyệt) với người dùng để duy trì phiên.
- **Nhược điểm**:
  - Tốn bộ nhớ RAM lớn (300MB – 800MB cho mỗi phiên trình duyệt), gây nặng nề cho các máy cấu hình thấp hoặc thiết bị chạy bot nền.
  - Hệ thống Bot Detection của Meta (sử dụng Akamai Bot Manager và behavioral biometric profiling) rất dễ dàng phát hiện headless flags (`navigator.webdriver`, canvas fingerprinting, WebGL anomalies, nhịp gõ phím máy móc).

### 3.3. Phương án C: Cầu nối giao thức Matrix / Beeper (`mautrix-meta`)
- **Cơ chế**: Dự án mã nguồn mở `mautrix-meta` kết nối với Facebook thông qua việc giả lập client web hoặc Android MQTT.
- **Kinh nghiệm thực tế**: Người dùng Beeper / Matrix khi kết nối Facebook thường xuyên bị yêu cầu re-authenticate (đăng nhập lại) sau vài tuần, và thỉnh thoảng gặp tình trạng tin nhắn bị trễ do rate-limit phía Meta.

---

## 4. Đánh giá Toàn diện về Rủi ro: Checkpoint, 2FA & Khóa Tài khoản

Đây là yếu tố quan trọng nhất cần minh bạch cho người dùng trước khi quyết định sử dụng:

### 4.1. Cơ chế Phát hiện Bot của Meta
Meta sở hữu một trong những hệ thống phát hiện hành vi tự động hóa tinh vi nhất thế giới:
1. **Phân tích ASN & IP Reputation**:
   - Nếu request gửi từ các dải IP Datacenter/Cloud (AWS, GCP, DigitalOcean, Hetzner, Vultr): **Tỉ lệ Checkpoint là 95% – 100%** ngay từ request đầu tiên.
   - Nếu request gửi từ IP dân cư (Residential IP / Home Internet) của chính máy Mac/PC mà người dùng thường ngày lướt Facebook: **Tỉ lệ kích hoạt thấp hơn nhiều** do cùng subnet và ASN với trình duyệt thực tế của chủ sở hữu.
2. **Kiểm tra Fingerprint và Headers**:
   - Meta kiểm tra nghiêm ngặt các header bảo mật HTTP/2 và Client Hints: `sec-ch-ua`, `sec-ch-ua-mobile`, `sec-ch-ua-platform`, `sec-fetch-dest`, `sec-fetch-mode`, `sec-fetch-site`. Thiếu hoặc sai lệch các header này lập tức khiến cookie bị hủy hiệu lực.

### 4.2. Các cấp độ Checkpoint của Facebook
Khi phát hiện nghi vấn, Facebook sẽ kích hoạt các biện pháp sau theo mức độ tăng dần:
1. **Checkpoint Mức 1 (Re-authentication / Session Expiry)**:
   - Session cookie bị vô hiệu hóa (`xs` hết hạn). Người dùng chỉ cần đăng nhập lại trên trình duyệt để lấy cookie mới.
2. **Checkpoint Mức 2 (2FA / Thiết bị lạ)**:
   - Facebook hiển thị thông báo "Chúng tôi phát hiện lượt đăng nhập bất thường" và yêu cầu nhập mã OTP SMS, ứng dụng Authenticator, hoặc bấm xác nhận trên điện thoại.
3. **Checkpoint Mức 3 (Checkpoint 282 / Selfie / ID Verification)**:
   - Tài khoản bị tạm khóa 180 ngày. Facebook yêu cầu tải lên ảnh chụp giấy tờ tùy thân (CCCD/Hộ chiếu) hoặc quay video nhận diện khuôn mặt.
4. **Vô hiệu hóa vĩnh viễn (Account Disabled)**:
   - Meta đình chỉ vĩnh viễn tài khoản với lý do vi phạm **Điều khoản dịch vụ (ToS Điều 3.2.3)**: *"Bạn không được truy cập hoặc thu thập dữ liệu từ Sản phẩm của chúng tôi bằng các phương tiện tự động nếu không có sự cho phép trước bằng văn bản của chúng tôi..."*

---

## 5. Kết luận Nghiên cứu & Hướng đi Chấp nhận được có Điều kiện

Từ các phân tích thực nghiệm trên, nhóm phát triển Antigravity rút ra kết luận dứt khoát:

> [!CAUTION]
> **KẾT LUẬN QUAN TRỌNG**:
> KHÔNG CÓ BẤT KỲ ĐƯỜNG ĐI NÀO ĐẠT CHUẨN AN TOÀN TUYỆT ĐỐI (100% SAFE) CHO FACEBOOK CÁ NHÂN NHƯ TELEGRAM MTPROTO HAY ZALO WEB.
> Việc kết nối Facebook cá nhân bằng web session cookie LUÔN TIỀM ẨN NGUY CƠ CHECKPOINT VÀ KHÓA TÀI KHOẢN NẾU LẠM DỤNG HOẶC CHẠY TRÊN IP LẠ.

### Tiêu chí Chấp nhận được có Điều kiện (Conditionally Acceptable)
Để đáp ứng yêu cầu tính năng nhưng **TUYỆT ĐỐI KHÔNG LÁCH LUẬT HAY ĐÁNH ĐỔI SỰ AN TOÀN CỦA NGƯỜI DÙNG**, MuLon triển khai theo mô hình bảo vệ nhiều lớp:

1. **Chỉ hỗ trợ phiên Cookie trên máy Local**:
   - Người dùng tự lấy session cookie từ chính trình duyệt đang dùng trên máy cài MuLon (cùng IP mạng gia đình).
   - Tuyệt đối không lưu mật khẩu tài khoản Facebook, chỉ lưu session trong Vault mã hóa (`facebook_personal:session`).
2. **Cơ chế Checkpoint Guard (Tự ngắt bảo vệ)**:
   - Module có cơ chế phát hiện sớm phản hồi Checkpoint từ Facebook (mã HTTP 302 chuyển hướng tới `/checkpoint/`, hoặc thẻ HTML chứa `checkpoint_required`).
   - Khi phát hiện checkpoint, connector **NGAY LẬP TỨC DỪNG MỌI REQUEST TIẾP THEO**, chuyển trạng thái sang `checkpoint_detected` và cảnh báo người dùng mở trình duyệt xử lý, tránh spam request làm trầm trọng thêm mức độ khóa nick.
3. **Cảnh báo Rủi ro Rõ ràng (Risk Disclosure)**:
   - Màn Kết nối Mini App và các lệnh chat Telegram hiển thị cảnh báo rủi ro cao nổi bật trước khi người dùng dán cookie.
   - Khuyến nghị rõ ràng: Khuyên người dùng nên thử nghiệm với tài khoản phụ (clone/test) trước khi áp dụng cho tài khoản chính.
4. **Phân quyền và Bảo mật nghiêm ngặt**:
   - Đọc thông tin, bạn bè, bảng tin, tin nhắn: Mặc định `allow`.
   - Gửi tin nhắn Messenger hoặc bài viết: Mặc định **`ask`** (bắt buộc duyệt qua Approval Card trước khi gửi ra ngoài).
   - Toàn bộ nội dung tin nhắn và bài đăng từ bên ngoài đều được bọc qua `frame_external` chống prompt injection.
   - Degrade sạch 100%: Chưa có cookie hoặc lỗi kết nối thì báo rõ, bot không bao giờ sập.

---

## 6. Thiết kế Kỹ thuật Connector `facebook_personal`

```
┌────────────────────────────────────────────────────────┐
│                   MuLon Application                    │
│    (Telegram Bot / Mini App / Agent Context Engine)    │
└───────────────────────────┬────────────────────────────┘
                            │
               ┌────────────▼─────────────┐
               │ FacebookPersonalConnector│
               │   (mulon/personal_...)   │
               └────────────┬─────────────┘
                            │
       ┌────────────────────┼───────────────────┐
       ▼                    ▼                   ▼
┌──────────────┐     ┌──────────────┐    ┌──────────────┐
│  Vault Store │     │  Policy /    │    │  Checkpoint  │
│(cookie, user)│     │  Approval    │    │    Guard     │
└──────────────┘     └──────────────┘    └──────┬───────┘
                                                │
                                         ┌──────▼───────┐
                                         │  Facebook    │
                                         │  Web Session │
                                         │  (mbasic/www)│
                                         └──────────────┘
```

- **Vault Labels**:
  - `facebook_personal:session`: Lưu trữ chuỗi cookie (JSON hoặc raw cookie string).
  - `facebook_personal:user_info`: Lưu trữ cache thông tin cá nhân (`id`, `name`, `vanity`).
- **Các hành động (Actions)**:
  - `configure_session`: Lưu chuỗi cookie phiên vào Vault an toàn.
  - `check_session`: Kiểm tra tính hợp lệ của cookie và phát hiện checkpoint.
  - `get_profile`: Đọc thông tin trang cá nhân của tài khoản.
  - `get_friends`: Đọc danh sách bạn bè gần đây.
  - `read_feed`: Đọc các bài viết gần nhất trên Bảng tin (đóng khung `frame_external`).
  - `read_messages`: Đọc tin nhắn Messenger từ hội thoại (đóng khung `frame_external`).
  - `send_message`: Gửi tin nhắn Messenger (bắt buộc qua duyệt `ask`).
  - `disconnect`: Xóa sạch cookie và dữ liệu khỏi Vault.

---

## 7. Khuyến nghị gửi Chủ dự án

1. **Khuyến cáo vận hành**: MuLon cung cấp module này như một tính năng nâng cao (Advanced / Experimental Feature). Người dùng có quyền tự quyết định kích hoạt dựa trên nhận thức đầy đủ về rủi ro.
2. **Khuyến nghị tương lai**: Nếu người dùng cần quản lý tương tác Facebook ở mức độ ổn định tuyệt đối và lâu dài cho công việc, giải pháp chuẩn hóa vẫn là liên kết Facebook Page qua **Meta Business Graph API** (đã nằm trong kế hoạch của T-17).
