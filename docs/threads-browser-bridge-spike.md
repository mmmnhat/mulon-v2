# Spike browser bridge gửi DM Threads thật (T-22.3, LUỒNG PHỤ 1)

## Vì sao cần bridge này

API Threads chính thức không mở endpoint DM. Connector `threads_messages`
trước đây trả `sent: True` giả khi không có session runner — tin chưa hề
gửi đi. Bridge này là đường gửi thật duy nhất đã xác định: dùng trình
duyệt Chromium với profile đã đăng nhập Threads web của người cài, mở
hộp thư thật, vào hội thoại có sẵn, gửi, rồi xác minh.

## Cách chạy thật trên máy Mac (cần chủ dự án làm 1 lần)

1. Cài Playwright: `pip install playwright && playwright install chromium`
   (trong venv của bot).
2. Tạo profile Chromium đã đăng nhập Threads web: mở Chromium với
   profile riêng (chính là thư mục sẽ đặt vào `BROWSER_PROFILE_DIR`),
   đăng nhập Threads web 1 lần bằng tài khoản của chủ, rồi đóng trình
   duyệt. Bot KHÔNG tự đăng nhập và KHÔNG lưu password — bước này do
   người cài làm bằng tay.
3. Đặt env trong `.env` của bản cài:
   `BROWSER_PROFILE_DIR=<thư mục profile ở bước 2>`
   (`THREADS_WEB_BASE_URL` mặc định là `https://www.threads.net`, chỉ
   đổi khi Meta đổi domain).
4. Khởi động lại bot, nhắn bot gửi 1 DM thử vào 1 hội thoại Threads
   ĐÃ CÓ (không gửi người lạ — guard sẽ chặn trước khi bridge chạy).
   Lần gửi nào cũng qua thẻ duyệt (policy `ask` cho
   `threads_messages:send_message`): chủ bấm duyệt thì tin mới đi.
5. Đối chiếu: tin phải xuất hiện trong hộp thư Threads thật (mở app
   Threads / web Threads kiểm tra). Bridge chỉ báo thành công khi
   chính nó thấy nội dung vừa gửi xuất hiện trong hội thoại; không
   thấy thì báo lỗi, không báo thành công giả.

## Nếu lần chạy thật đầu tiên gãy ở đâu

- Bị chuyển về trang đăng nhập: profile chưa đăng nhập, hoặc phiên
  web đã hết hạn — đăng nhập lại bằng tay ở bước 2, không dán cookie
  vào Vault cho đường này.
- Không thấy hộp thư / ô soạn / nút gửi: giao diện Threads web đã
  đổi so với spike. Sửa `config/threads_web_selectors.json`
  (`inbox_path`, `conversation_link_selector`, `composer_selectors`,
  `send_button_selectors`) rồi thử lại — không cần sửa code.
- Không thấy hội thoại khớp: bridge chỉ gửi hội thoại có sẵn trong
  hộp thư web; thread_id/participant phải khớp với 1 link hội thoại
  thật trong hộp thư đó. Tin nhắn tới người chưa có hội thoại vẫn bị
  từ chối theo giới hạn cứng, không phải lỗi bridge.

## Giới hạn còn lại của spike này (ghi rõ)

- Chỉ phủ `send_message` (tin văn bản). `send_reaction` chưa có
  đường bridge, vẫn đi nhánh cũ; đọc inbox/tin nhắn vẫn từ cache
  Vault như trước — spike này không giả vờ đã phủ hết.
- Chưa có lần gửi thật nào thành công: lần chạy thật đầu tiên trên
  tài khoản chủ mới là nghiệm thu bắt buộc của T-22.3.
- Full suite chưa chạy được từ máy làm spike (không có checkout đầy
  đủ): 9/9 test bridge mới + 5 test Threads cũ qua ở bộ test cô lập;
  cần chạy lại full suite trên máy Mac / phía reviewer trước VERIFIED.
