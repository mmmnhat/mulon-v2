# THIẾT KẾ LẠI BẢN ĐỒ MINI APP MULON — cây IA mới (2026-10-27)

Căn cứ: bản đồ hiện trạng `docs/sitemap-miniapp-2026-10-27.md` (5 tab, 10 màn con, 127 hàng chết,
không màn con nào có nút quay lại, thiếu chi tiết connector / xem trước tài liệu / chi tiết fact).
Nguyên tắc xuyên suốt (user chốt): mọi thứ có nhà; danh sách dài phải nhóm + gập mặc định + tìm kiếm +
phân trang; chi tiết nằm ở màn con; quyền + cấu hình của connector nằm TRONG màn chi tiết của connector đó.

## A. LUẬT ĐIỀU HƯỚNG (áp cho mọi màn, nghiệm thu bằng chạm thật)
1. Hàng nào trông như hàng thì PHẢI mở được bằng cả thân hàng lẫn chevron. Không có hàng chết:
   thông tin chỉ-để-đọc thì trình bày dạng khối chữ, không đóng giả hàng.
2. Mọi màn con có nút quay lại "‹" ở góc trái trên + tiêu đề màn. Tiêu đề màn = đúng nhãn hàng đã chạm
   (hết cảnh "Bộ nhớ dài hạn" → "Bộ nhớ", "Thêm thủ công" → "Nhập thủ công").
3. Sâu tối đa 3 cấp. Sheet/modal luôn có ✕ hoặc vuốt xuống để đóng.
4. Trạng thái thể hiện bằng CHỮ + phân cấp trung tính; KHÔNG xanh lá/vàng/đỏ cho trạng thái.
   Một màu nhấn duy nhất (tím Mulon) cho hành động chính của màn.
5. Lỗi tải nằm trong màn của nó, có nút "Thử lại" tại chỗ; banner lỗi KHÔNG dính sang tab khác.
6. Danh sách >15 mục bắt buộc có: ô tìm kiếm (lọc tại chỗ + tiêu đề cập nhật số kết quả),
   nhóm/gập, và "Xem thêm" phân trang. Không màn nào là một cột cuộn vô tận.

## B. CÂY IA MỚI (giữ khung 5 tab quen thuộc)

```
Mulon
├─ 1. Việc
│   ├─ Ô tìm kiếm + chip lọc: Tất cả | Đang chạy | Đã xong | Đã lỗi
│   ├─ Danh sách việc (phân trang "Xem thêm", không khoá cứng 20)
│   └─ Hàng → Chi tiết việc (L2)
│       ├─ Tóm tắt (render markdown sạch, không lộ ký tự thô)
│       ├─ Dòng thời gian: từng BƯỚC là một hàng → chạm mở sheet Chi tiết bước (L3):
│       │   công cụ, mô tả đầu vào (đã che bí mật), kết quả, thời lượng, trạng thái bằng chữ
│       └─ Việc lỗi: nút "Thử lại" + "Thử lại từ bước lỗi" khi có bước lỗi
├─ 2. Phê duyệt
│   ├─ Mục "Đang chờ" (trên cùng): thẻ chờ duyệt kèm 2 nút Duyệt / Từ chối ngay tại thẻ
│   │   (đồng bộ 2 chiều với thẻ trong chat — T-10.1)
│   └─ Mục "Lịch sử": gập theo tháng, hàng → mở rộng tại chỗ (giữ accordion hiện tại, đã tốt)
│       (xoá 2 bản ghi "Gửi thẻ phê duyệt thử" — dữ liệu thử không nằm trong bản thật)
├─ 3. Lịch
│   ├─ Nhóm "Hệ thống": Heartbeat → Màn Lịch trình (L2, thay sheet):
│   │   lịch bằng chữ người ("30 phút một lần") + cron phụ, lịch sử chạy (phân trang,
│   │   hàng → mở rộng chi tiết lượt), quyền của lịch trình này nằm TẠI ĐÂY, tạm dừng/xoá có xác nhận
│   └─ Nhóm "Cá nhân": từng lịch hẹn → Màn Lịch trình (L2) cùng khuôn (hết hàng chết;
│       công tắc bật/tắt ở cả hàng lẫn trong màn chi tiết)
├─ 4. Hồ sơ — tách 4 mục rõ ràng (hết văn bản gộp)
│   ├─ "Hồ sơ agent": danh sách file hồ sơ → chạm mở màn đọc file (L2, render sạch)
│   ├─ "Bộ nhớ": danh sách FACT (nhóm theo chủ đề, gập mặc định) + ô tìm kiếm fact
│   │   └─ Hàng fact → Chi tiết fact (L2): nội dung, nguồn, ngày tạo/cập nhật, xoá fact có xác nhận
│   ├─ "Kỹ năng": nhóm theo nguồn/chủ đề, gập mặc định, ô tìm kiếm (tiêu đề cập nhật "x / 91"),
│   │   hàng gọn 1 dòng mô tả → Chi tiết kỹ năng (L2) như hiện tại (màn này đang ổn)
│   └─ "Thư viện tài liệu": ô tìm kiếm + nhóm theo loại file
│       ├─ Hàng → Xem trước tài liệu (L2): ảnh xem ảnh; văn bản xem trích đoạn; kèm metadata
│       │   (tên, loại, kích thước, ngày) và các hành động Chia sẻ / Ghim / Sửa tên / Xoá (xoá có xác nhận)
│       └─ "Thùng rác" là MÀN riêng (L2): danh sách đã xoá + Khôi phục / Xoá hẳn (có xác nhận)
└─ 5. Cài đặt
    ├─ "Công cụ kết nối" (L2): 2 tab Đã cài | Chợ
    │   ├─ Đã cài: hàng connector → CHI TIẾT CONNECTOR (L3) — khuôn mẫu cho mọi connector:
    │   │   trạng thái kết nối, tài khoản đang nối, danh sách tool của connector này,
    │   │   QUYỀN TỪNG HÀNH ĐỘNG của connector này (Cho phép/Hỏi/Chặn, sửa tại đây),
    │   │   cấu hình riêng, nút ngắt kết nối (có xác nhận)
    │   ├─ Chợ: ô tìm kiếm + danh mục → danh sách server (phân trang) → Chi tiết server (L3):
    │   │   mô tả, tool, nút Cài (cài ngay theo luật user chốt 24/10)
    │   └─ "Thêm thủ công" → đổi nhãn "Thêm bằng JSON" → form như hiện tại (đang ổn)
    ├─ "Kho lưu trữ an toàn" (L2): ô tìm kiếm khi >15 bí mật
    │   └─ Hàng → Chi tiết bí mật (L3): nhãn, mã tham chiếu, ngày tạo/sửa; thay giá trị; xoá (có xác nhận).
    │       Giá trị KHÔNG bao giờ hiện (giữ chuẩn hiện tại — đang đúng)
    ├─ "Quyền" (L2) — CHỈ còn: mặc định toàn cục theo "Nhóm việc" (13 nhóm) + ghi chú nơi sửa
    │   quyền riêng (trong chi tiết connector / chi tiết lịch trình). BỎ danh sách "Từng tool"
    │   phẳng 90 hàng và bỏ mục connector trùng ở đây. Mặc định an toàn theo T-23.6:
    │   đọc = Cho phép; ghi/gửi = Hỏi; xoá/phá huỷ = Hỏi + xác nhận.
    ├─ "Feed chủ động" (L2): giữ nội dung hiện tại, chia mục gập (Trạng thái / Nhịp đăng /
    │   Giờ yên lặng / Giới hạn / Nguồn ghim / Domain tránh); sửa nhãn field cron thành
    │   "Nhịp (cron)" + preset là chính; bỏ emoji trạng thái.
    ├─ "Thiết bị & hệ thống" (L2): giữ nguyên (màn gọn nhất hiện tại — khuôn mẫu trình bày)
    └─ "Giao diện" (L2 hoặc mục cuối Cài đặt): màu chủ đề — 6 màu hiện tại chờ user chốt giữ/bỏ
        (đã ghi ở T-23.5); nếu giữ, chỉ áp cho điểm nhấn, không đổi màu trạng thái.
```

## C. ÁNH XẠ TỪ HIỆN TRẠNG → MỚI (để builder không lạc)
- 127 hàng chết → 0: 7 hàng lịch hẹn mở Màn Lịch trình; 100 tài liệu mở Xem trước; 3 connector mở
  Chi tiết connector; 17 bí mật mở Chi tiết bí mật.
- 10 màn con không nút back → mọi màn con có "‹" + tiêu đề khớp nhãn.
- Bộ nhớ xuất hiện 2 nơi → chỉ còn danh sách fact ở Hồ sơ > Bộ nhớ; màn Hồ sơ agent chỉ chứa file hồ sơ.
- Quyền connector nằm rải ở màn Quyền → chuyển hết vào Chi tiết connector; màn Quyền rút còn mặc định nhóm việc.
- Sheet Heartbeat + sheet Quyền của Heartbeat (L3 chôn sâu) → gộp thành Màn Lịch trình L2, quyền nằm trong đó.
- "Xem thùng rác" đổi-tại-chỗ → màn Thùng rác riêng.
- Lỗi initData ở Chi tiết việc + Chợ: xử lý ở T-24.5 (điều kiện để cây mới chạy được).
- Việc liên quan đã có: T-23.1 (điều hướng), T-23.3 (tách Hồ sơ), T-23.5 (màu/nhãn/chợ), T-23.6
  (quyền mặc định), T-10.2 (tab Hành động), T-12 (design system tổng). Tài liệu này là bản đồ đích
  cho T-12/T-23, không tạo việc trùng.
