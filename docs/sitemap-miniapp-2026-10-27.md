# BẢN ĐỒ MINI APP MULON — khảo sát chỉ đọc 2026-10-27 (app v1.7.3)

> [!IMPORTANT]
> **TÀI LIỆU ĐÃ ĐƯỢC THAY THẾ (SUPERSEDED):** Khảo sát này ghi nhận hiện trạng lịch sử lúc ứng dụng ở phiên bản cũ v1.7.3.
> Toàn bộ các bất thường cấu trúc (thiếu nút quay lại, sheet lồng 3 cấp, thiếu tìm kiếm/phân trang, banner lỗi rò rỉ...) đã được giải quyết triệt để qua các đợt nâng cấp T-12, T-13, T-14, T-23, T-27.
> **Xem cây cấu trúc và sitemap chính thức hiện tại tại:** [`docs/sitemap-miniapp-v17.md`](sitemap-miniapp-v17.md).

Nguồn: browser task fddae190 (01:42–02:14 +07), mở bằng WebView URL chủ sở hữu, không đổi gì.
Quy ước: [CHẾT] = chạm thân hàng không có tác dụng.

## Cây bản đồ

```
Mulon (mọi tab: header "Mulon" + "Sẵn sàng"; tab: Việc | Phê duyệt | Lịch | Hồ sơ | Cài đặt)
├─ Việc
│  └─ "Việc gần nhất": 20 hàng (tiêu đề + x/y bước + ✓ Đã xong / ✕ Đã lỗi + giờ)
│      └─ thân → "Chi tiết việc" (L2): Dòng thời gian / Tóm tắt / banner lỗi + "Thử lại"
│         (nội dung LỖI TẢI trong phiên này — xem Bất thường d)
├─ Phê duyệt
│  ├─ Trạng thái chờ: "Không có yêu cầu nào đang chờ duyệt..."
│  └─ "Lịch sử phê duyệt": 2 hàng "Gửi thẻ phê duyệt thử" (the_duyet, ask) — thân → accordion tại chỗ
│     (1 Hết hạn 24/10 18:56; 1 Đã duyệt 24/10 14:23). KHÔNG có nút gửi thẻ thử trong app hiện tại.
├─ Lịch
│  ├─ "Hàng ngày": Heartbeat "30 phút một lần" › → sheet Heartbeat (L2)
│  │   ├─ nhãn "Đã lên lịch", nút ✕, "Lịch sử chạy" 5→20 lượt ("Xem thêm"), chạm lượt → mở rộng tại chỗ
│  │   ├─ "Xem quyền" → sheet chồng "Quyền của Heartbeat" (L3): 6 mục quyền, "Đã hiểu"/✕
│  │   └─ nút "Xóa" (không thử)
│  └─ "Lịch hẹn & Nhắc việc cá nhân": 7 hàng (cron threads/sheets cũ) — thân [CHẾT] cả 7, chỉ có công tắc
├─ Hồ sơ
│  ├─ Thẻ "Hồ sơ của agent" (9 file, cập nhật 26/10 17:36) → màn "Hồ sơ" (L2): MỘT văn bản gộp (===== AGENTS.md ===== ... gồm cả MEMORY)
│  ├─ Thẻ "Bộ nhớ dài hạn" (875 fact) → màn "Bộ nhớ" (L2): MỘT văn bản dài, không tìm kiếm, không hàng fact
│  ├─ "Kỹ năng (91)": ô tìm kiếm HOẠT ĐỘNG (thử "tdd": 91→2 hàng, lọc tại chỗ, tiêu đề không đổi số)
│  │   └─ thân/chevron → chi tiết kỹ năng (L2): toàn văn SKILL.md
│  └─ "Thư viện tài liệu (Artifacts)": nút "Xem thùng rác" → đổi chế độ tại chỗ (không màn riêng)
│      └─ 100 hàng tài liệu (tên + ngày giờ + Chia sẻ/Ghim/Sửa tên/Xóa) — thân [CHẾT] cả 100, không xem trước, không tìm kiếm
└─ Cài đặt
   ├─ "Công cụ kết nối" › (L2)
   │   ├─ Tab "Đã cài": 3 connector (system / mcp-marketplace / google-workspace) — thân [CHẾT] cả 3; chỉ trạng thái + công tắc
   │   ├─ Tab "Chợ": "Chưa tải được danh mục." + "Làm mới" (bấm 2 lần đều lỗi initData — xem d)
   │   └─ "Thêm thủ công" › → "Nhập thủ công" (L3): form dán JSON MCP + "Phân tích"
   ├─ "Kho lưu trữ an toàn" › (L2): 17 bí mật (nhãn + vault:ref + ngày giờ; Sửa → khung sửa tại chỗ; Xoá) — thân [CHẾT] cả 17
   │   + mục "Thêm bí mật mới" (nhãn + giá trị + "Lưu vào kho"). Ghi chú đúng chuẩn: chỉ hiện nhãn+ref.
   ├─ "Quyền" › (L2): "Đổi là áp dụng ngay." + công tắc "Lưu bền vào file policy" (TẮT)
   │   ├─ "Nhóm việc": 13 hàng — tất cả "Cho phép"
   │   ├─ "Connector & server MCP": 3 hàng — tất cả "Cho phép"
   │   └─ "Từng tool": 90 hàng phẳng theo alphabet — tất cả "Cho phép" (google-workspace 43, marketplace 7, lõi 14, còn lại 26)
   │   (chạm hàng → menu Cho phép/Hỏi/Chặn tại chỗ)
   ├─ "Feed chủ động" › (L2): trạng thái (kế tiếp 08:00; 0/8 bài; 0/60.000 token; yên lặng 23:00–07:00),
   │   "Chạy ngay một lượt", nhịp đăng (cron "0 8,12,17,20 * * *" + nút preset), giờ yên lặng, giới hạn ngày,
   │   nguồn đã ghim, domain luôn tránh
   ├─ "Thiết bị & hệ thống" › (L2): máy chạy Mulon (phiên bản 1.7.3, proxy 8317...) + phiên này (tài khoản Telegram, ID)
   └─ Mục "Giao diện": "Màu chủ đề" — 6 màu (Tím Mulon đang chọn, Xanh dương, Hồng, Đào, Xanh lá, Chì)
```

## Tổng số
- 5 tab; 10 màn con phân biệt (9 L2 + 1 L3); 2 sheet (Heartbeat L2, Quyền của Heartbeat L3); sâu tối đa: cấp 3.
- Hàng chết (thân): **127** = 7 lịch hẹn + 100 tài liệu + 3 connector + 17 bí mật.
- Mọi màn con (10/10) KHÔNG có nút quay lại — thoát duy nhất bằng chạm lại tab cha. Chỉ sheet có ✕/"Đã hiểu".

## Bất thường cấu trúc
a) Không lối ra: cả 10 màn con không nút back/✕ (sheet thì có — chuẩn không nhất quán).
b) Nhiều điểm vào / trùng lặp: chi tiết việc từ 20 hàng; chi tiết kỹ năng từ 91 hàng; sheet Heartbeat mở được cả thân lẫn chevron;
   nội dung Bộ nhớ xuất hiện 2 lần (màn riêng + trong văn bản gộp Hồ sơ); tên connector ở 2 màn khác nghĩa
   ("Đã cài" = trạng thái/công tắc; "Quyền" = mức cho phép) dễ nhầm.
c) Mồ côi/chôn sâu/nhãn lệch: "Nhập thủ công" L3, nhãn "Thêm thủ công" không gợi form JSON MCP; "Xem thùng rác" không phải màn riêng;
   "Quyền của Heartbeat" L3 chỉ tới được từ trong sheet; Feed chỉ có 1 điểm vào từ Cài đặt; Cài đặt không có hàng Bộ nhớ;
   nhãn lệch đích: "Bộ nhớ dài hạn"→"Bộ nhớ", "Hồ sơ của agent"→"Hồ sơ", hàng kỹ năng → tiêu đề màn chung "Kỹ năng".
d) Lỗi tải initData (KHÁC "không tồn tại"): màn "Chi tiết việc" — cả Dòng thời gian + Tóm tắt báo
   "Không tải được dữ liệu: initData không hợp lệ hoặc không phải chủ nhân", "Thử lại" vẫn lỗi; tab "Chợ" — "Làm mới" 2 lần cùng lỗi.
   Banner lỗi còn dính ở đầu các tab khác sau đó (danh sách vẫn hiện bình thường).
   → Chi tiết từng bước việc + danh mục chợ MCP: CHƯA XÁC NHẬN ĐƯỢC trong phiên này.
e) Nhánh thiếu (đã chạm thử, kết luận trên cấu trúc nút/hàng):
   - Chi tiết connector: KHÔNG tồn tại (không trạng thái chi tiết/tài khoản/tool/quyền/cấu hình riêng).
   - Xem trước tài liệu: KHÔNG tồn tại.
   - Chi tiết/tìm kiếm fact Bộ nhớ: KHÔNG tồn tại (một khối văn bản).
   - Tìm kiếm/phân trang danh sách dài: CHỈ có ở Kỹ năng. Việc 20, Tài liệu 100, Quyền 106, Kho 17, Lịch 8 — không có.
