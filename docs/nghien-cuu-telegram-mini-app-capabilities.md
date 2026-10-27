# BÁO CÁO NGHIÊN CỨU: KHẢ NĂNG "APP" CỦA TELEGRAM MINI APP & GIỚI HẠN NATIVE (2026-10-27)

> **Căn cứ**: Yêu cầu tại mục **[T-12]** trong `AGENT_TASKS.md` và mục J6 trong `docs/muse-parity-checklist.md`.
> **Người thực hiện**: Antigravity (Làn 1).
> **Đối tượng khảo sát**: Telegram Bot API 7.0 - 8.0, Telegram WebApp JavaScript SDK (`https://telegram.org/js/telegram-web-app.js`), Telegram iOS/Android/Desktop client capabilities.

---

## 1. Đặt vấn đề & Mục tiêu nghiên cứu

Người dùng thường mong muốn MuLon chạy như một **ứng dụng độc lập (Native App)** trên điện thoại: có icon riêng trên màn hình chính, mở nhanh không qua chat, chạy tràn màn hình (full-screen), không bị vướng thanh URL của trình duyệt hay khung chat Telegram, và có thể mở được từ nhiều ngữ cảnh (DM, Group, Channel).

Mục tiêu của nghiên cứu này là:
1. Xác định chính xác Telegram cho phép Mini App chạy dạng "app" tới đâu theo thông số kỹ thuật chính thức của Telegram Bot API.
2. Làm rõ các ranh giới kỹ thuật bất biến (giới hạn của nền tảng Telegram).
3. Đề xuất phương án khả thi gần nhất với trải nghiệm native app và hiện thực hóa trong Design System của MuLon.

---

## 2. Bản đồ khả năng của Telegram Mini App (Bot API 7.0 - 8.0+)

### 2.1 Các điểm vào (Entry Points) & Khả năng khởi chạy

Telegram hỗ trợ 4 cơ chế khởi chạy Mini App chính:

| Điểm vào | Cơ chế kỹ thuật | Trải nghiệm người dùng | Đánh giá cho MuLon |
|---|---|---|---|
| **Bot Menu Button** | `bot.set_chat_menu_button(menu_button=MenuButtonWebApp(...))` | Nút "Bảng điều khiển" nằm thường trực bên trái ô nhập chat DM của bot. 1 chạm là mở ngay. | **Rất tốt — Đã tích hợp** từ bản 1.6, là điểm vào chính hàng ngày của chủ nhân. |
| **Direct Link (Direct Mini App URL)** | `https://t.me/<BotUsername>/<AppName>` hoặc `https://t.me/<BotUsername>?startapp=<param>` | Mở app trực tiếp từ bất kỳ đâu: tin nhắn trong Group, bài đăng Channel, tin nhắn DM, trình duyệt web bên ngoài. Tham số `startapp` cho phép deep-link thẳng vào màn con (vd: `startapp=vault_<label>`). | **Xuất sắc — Đã tích hợp**. Hỗ trợ mở sâu vào việc hoặc kho an toàn. |
| **Inline Button (Kèm bàn phím tin nhắn)** | `InlineKeyboardButton(text="Mở...", web_app=WebAppInfo(url=...))` | Nút bấm đính kèm theo tin nhắn thông báo tiến trình, thẻ phê duyệt hoặc thẻ kho. | **Đã tích hợp**. Dùng cho thẻ duyệt và yêu cầu bí mật. |
| **Attachment Menu (Kẹp ghim)** | Đăng ký qua BotFather (`/setattachtitle`, `/setattachallowed`) | Hiện trong menu đính kèm (📎) ở mọi cuộc trò chuyện cá nhân hoặc nhóm. | Cần cấu hình bổ sung trên BotFather; phù hợp khi muốn mở app nhanh từ chat bạn bè. |

---

### 2.2 Trải nghiệm màn hình (Viewport, Full-screen & Cuộn)

Telegram Mini App bản chất chạy trong một WebView nhúng (WKWebView trên iOS, Android WebView trên Android, Chromium/WebKit trên Desktop). Các API điều khiển giao diện:

1. **Bung rộng toàn màn hình (`Telegram.WebApp.expand()`):**
   - Mặc định khi mở, WebView Telegram chỉ chiếm ~70% chiều cao màn hình (dạng bottom sheet lưng chừng).
   - Gọi `Telegram.WebApp.expand()` ngay khi tải trang giúp Mini App tự động bung lên 100% chiều cao khả dụng, che toàn bộ khung chat.
2. **Toàn màn hình không viền (`Telegram.WebApp.requestFullscreen()` — Bot API 8.0+):**
   - Từ Bot API 8.0 (Telegram client v11.3+), Telegram bổ sung API `requestFullscreen()`.
   - Khi kích hoạt, thanh tiêu đề của Telegram (chứa tên bot và nút đóng ✕) được ẩn đi, trao toàn bộ 100% diện tích màn hình cho Mini App như một ứng dụng native.
   - Kiểm tra tương thích qua `Telegram.WebApp.isVersionAtLeast('8.0')`.
3. **Chống vuốt tắt vô ý (`Telegram.WebApp.disableVerticalSwipes()` — Bot API 7.7+):**
   - Một trong những lỗi khó chịu nhất của WebView Telegram là khi người dùng cuộn nhanh danh sách (vd: cuộn 90+ kỹ năng hay hàng trăm tài liệu), thao tác kéo xuống có thể kích hoạt cử chỉ đóng sheet của Telegram.
   - `disableVerticalSwipes()` khóa cử chỉ này, đảm bảo thao tác vuốt cuộn bên trong Mini App mượt mà như ứng dụng iOS/Android thông thường.
4. **Vùng an toàn (Safe Area Insets):**
   - Hỗ trợ biến môi trường CSS `env(safe-area-inset-top)` và các biến Telegram `--tg-safe-area-inset-top`, `--tg-content-safe-area-inset-top` để nội dung không bị tai thỏ (notch) hoặc thanh điều hướng đè lên.

---

### 2.3 Lối tắt màn hình chính (Homescreen Shortcut — Bot API 8.0+)

- **Cơ chế:** Phương thức `Telegram.WebApp.addToHomeScreen()` kết hợp `Telegram.WebApp.checkHomeScreenStatus()`.
- **Hành vi:**
  - Mini App có thể kiểm tra xem người dùng đã ghim app ra màn hình chính chưa (`status = 'unsupported' | 'unknown' | 'added' | 'missed'`).
  - Gọi `addToHomeScreen()` sẽ mở hộp thoại hệ điều hành để thêm biểu tượng MuLon (lấy avatar của bot) ra SpringBoard (iOS) hoặc Launcher (Android).
  - Khi người dùng nhấn icon trên màn hình chính, Telegram sẽ tự động mở thẳng vào Mini App ở chế độ tối ưu.

---

### 2.4 Điều khiển Native & Phản hồi vật lý (Navigation & Haptics)

1. **Nút quay lại chuẩn Native (`Telegram.WebApp.BackButton`):**
   - Thay vì dùng nút tự vẽ trên thanh tiêu đề HTML làm tốn diện tích, Telegram cung cấp `BackButton` nằm trên thanh điều hướng native của ứng dụng.
   - Quản lý qua `BackButton.show()`, `BackButton.hide()`, và gán sự kiện `BackButton.onClick(callback)`.
2. **Nút hành động chính (`Telegram.WebApp.MainButton`):**
   - Nút nổi native lớn ở đáy màn hình (thường dùng cho "Lưu", "Xác nhận", "Thanh toán").
   - Đối với MuLon, các màn hình cấu hình hoặc phê duyệt có thể gắn kết `MainButton` để tạo cảm giác native.
3. **Rung phản hồi vật lý (`Telegram.WebApp.HapticFeedback`):**
   - `impactOccurred('light' | 'medium' | 'heavy' | 'rigid' | 'soft')`: rung khi người dùng nhấn chuyển tab, chạm nút hành động, mở rộng accordion.
   - `notificationOccurred('error' | 'success' | 'warning')`: rung khi thao tác lưu thành công, phê duyệt thành công hoặc xảy ra lỗi.
   - `selectionChanged()`: rung khi lướt qua các chip lọc.

---

## 3. Các giới hạn bất biến của Telegram Mini App

Dù có các API mạnh mẽ trên, Telegram Mini App **KHÔNG THỂ** trở thành một native app độc lập hoàn toàn (standalone binary):

1. **Không có tiến trình chạy nền độc lập (Background Execution):**
   - Khi người dùng tắt Telegram hoặc đóng WebView, tiến trình JavaScript của Mini App bị hủy hoàn toàn (hoặc đóng băng).
   - Mini App **không thể** tự chạy cronjob ngầm, không thể tự lắng nghe tin nhắn mạng xã hội hay tự thực thi sub-agent khi đã đóng.
   - *Giải pháp kiến trúc MuLon*: Toàn bộ logic lõi, Heartbeat, Feed tự động, Sub-agent và SQLite WAL đều chạy ở backend Python daemon (`mulon.main`). Mini App thuần túy là giao diện điều khiển (Control Plane).
2. **Không có quyền truy cập phần cứng cấp thấp (Low-level Hardware Access):**
   - Mini App không thể truy cập hệ thống tệp tin cục bộ của điện thoại (local file system) ngoài các hộp thoại upload chuẩn của trình duyệt.
   - Không thể can thiệp sâu vào Bluetooth/NFC/hệ thống thông báo đẩy độc lập (APNs/FCM) nếu không thông qua tin nhắn Telegram.
   - *Giải pháp*: Thông báo đẩy sử dụng kênh tin nhắn Telegram Bot chính thức (@Mulon_bot).
3. **Phụ thuộc vào phiên Telegram (Authentication & Lifetime):**
   - Quyền truy cập vào Mini App được xác thực qua chuỗi băm HMAC `initData` có hạn sử dụng (mặc định 24h).
   - Nếu `initData` hết hạn hoặc bị sửa đổi, app buộc phải yêu cầu làm mới phiên từ Telegram.

---

## 4. Phương án kiến trúc & Thiết kế cho MuLon (Kết luận triển khai T-12)

Để mang lại cảm giác "Native App" tối đa trong khuôn khổ cho phép của Telegram:

1. **Cấu hình khởi tạo chuẩn Native:**
   - Gọi `Telegram.WebApp.ready()` ngay khi nạp trang.
   - Kích hoạt `Telegram.WebApp.expand()` để mở rộng tối đa chiều cao.
   - Bật `Telegram.WebApp.disableVerticalSwipes()` để ngăn cử chỉ vuốt vô ý làm đóng app.
   - Khởi tạo `Telegram.WebApp.requestFullscreen()` nếu phiên bản Telegram hỗ trợ (Bot API 8.0+).
2. **Đồng bộ điều hướng hai tầng (Hybrid Back Navigation):**
   - Hiển thị nút `Telegram.WebApp.BackButton` native của Telegram ở góc trái trên thanh điều hướng native.
   - Duy trì đồng thời nút `‹ Quay lại` trên thanh `.backrow` của HTML (với touch target ≥ 44px) để đảm bảo app hoạt động hoàn hảo cả trên Telegram mobile, Telegram desktop, lẫn trình duyệt web thông thường (khi debug/test).
   - Cả hai nút đều gọi chung một hàm điều hướng lùi tập trung `handleNativeBack()`.
3. **Haptic Feedback toàn diện:**
   - Tích hợp `Telegram.WebApp.HapticFeedback` vào toàn bộ tương tác người dùng: chuyển tab (`light`), nhấn nút tác vụ (`medium`), hoàn tất thành công (`success`), báo lỗi (`error`).
4. **Hệ thống thiết kế chuẩn mực (Design System):**
   - Tuân thủ nghiêm ngặt chuẩn 60/30/10 với màu tím Mulon `#7C3AED` làm điểm nhấn duy nhất.
   - Lưới 8pt, hàng cao ≥ 56px, vùng chạm ≥ 44px.
   - Bộ 4 trạng thái chuẩn (Skeleton loading, Empty state, Error state tại chỗ, Ready state) triệt tiêu hoàn toàn cảm giác "trang web tải chậm".
5. **Homescreen Shortcut Prompt:**
   - Cung cấp nút tiện ích "Thêm ra màn hình chính" trong Cài đặt > Thiết bị & Hệ thống (sử dụng `addToHomeScreen()` khi khả dụng) để người dùng có thể mở MuLon từ SpringBoard/Launcher.
