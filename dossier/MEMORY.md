# MEMORY — Ký ức dài hạn đã chắt lọc

<!-- Hệ thống (consolidation worker) duy trì file này từ hội thoại.
     User xem/sửa được bất cứ lúc nào. Trần cứng 40.000 ký tự: vượt
     trần thì phải tự gộp trước khi ghi tiếp (thiết kế mục 4.1). -->

## Sự kiện & quyết định bền vững
- [2026-10-24] User yêu cầu gọi là "ní", không gọi bằng tên. Cách xưng hô mặc định: agent xưng "tui", gọi user là "ní".

## Cam kết đang mở
- [2026-10-26] Vận hành tự động hóa Threads cho tài khoản `@mmmnhat.1810`:
  + Quét lịch đăng bài từ Google Sheets (4 bài/ngày vào các khung giờ 08:30, 11:45, 17:30, 20:30 từ Thứ 2 đến Thứ 6) và tự động đăng lên Threads.
  + Lắng nghe Webhooks Meta: khi có tương tác (reply / comment), tự động thả react và phản hồi (reply) lại.

## Bài học đã rút (từ những lần bị sửa)
- [2026-10-24] Xưng hô và hồ sơ: tuyệt đối gọi user là "ní", không gọi tên. Khi user điều chỉnh cách xưng hô, thông tin cá nhân hoặc nhắc lưu/cập nhật, agent phải chủ động cập nhật ngay vào dossier (USER.md / IDENTITY.md), không được hứa miệng rồi bỏ đó và tuyệt đối không hỏi ngược lại user về cấu trúc kỹ thuật nội bộ (dossier hay memory).
- [2026-10-26] Tuyệt đối KHÔNG BAO GIỜ nói gửi acc cho khách test, KHÔNG CHO khách test acc Muse dưới bất kỳ hình thức nào. Bán thật, không có chính sách test acc free.
- [2026-10-26] Reply cmt Threads: Phải hiểu đúng ý người cmt, đọc kỹ ngữ cảnh để phản hồi tự nhiên như người thật.
  + Với cmt thảo luận/kỹ thuật/chia sẻ/khen ngợi: Cùng đàm đạo, trả lời đúng chuyên môn, lịch sự, xưng hô "mình - bạn" hoặc "em - bạn", TUYỆT ĐỐI KHÔNG bán hàng hay lôi kéo sang Telegram.
  + Chỉ khi khách chủ động hỏi mua/hỏi giá/xin link mua: Mới báo giá rõ ràng (1B: lẻ 6k, sỉ từ 3k; 31B: lẻ 55k, sỉ từ 37k) và hướng dẫn nhắn Telegram @mmmnhat để giao dịch, TUYỆT ĐỐI KHÔNG hứa hẹn cho test acc.
