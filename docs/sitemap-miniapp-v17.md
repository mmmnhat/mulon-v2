# BẢN ĐỒ MINI APP MULON — Kiến trúc chính thức v1.7.3x (Design System 100% Chuyên Nghiệp)

> **Tham chiếu tài liệu khảo sát cũ:** Tài liệu này thay thế hoàn toàn bản khảo sát hiện trạng cũ tại [`docs/sitemap-miniapp-2026-10-27.md`](sitemap-miniapp-2026-10-27.md) (bản cũ đã được đánh dấu superseded).
>
> Cập nhật 2026-10-28 theo các đợt hoàn thiện T-12 (Design System), T-13 (Brand & Mascot), T-14 (CLIProxyAPI), T-23 (Phân tách Hồ sơ & Ký ức), T-27 (UI Perfection).
> Chuẩn giao diện: Tỉ lệ 60/30/10 với màu tím Mulon `#7C3AED`, chiều cao hàng tương tác tối thiểu 44px, phân cấp 4 trạng thái chuẩn (Loading Skeleton, Empty State, Error State có nút thử lại tại chỗ, Ready State). 100% màn con tích hợp BackButton chuẩn (đồng bộ nút quay lại native của Telegram WebApp SDK).

---

## 1. Cây cấu trúc Mini App (5 Tab chính)

```
Mulon Mini App (Header: Tên bot [đồng bộ theo cấu hình brand] + Chấm trạng thái + Sprite avatar v0)
│
├── 1. Tab Việc (`#tab-viec`)
│   ├── Thanh tổng quan số liệu (`#tasks-overview-bar`): Đang chạy / Đã xong / Đã lỗi / Tổng
│   ├── Thanh tìm kiếm việc (`#tasks-search-input`) + Nút xoá tìm kiếm nhanh
│   ├── Dải chip lọc trạng thái (`#tasks-filter-chips`: Tất cả, Đang chạy, Đã xong, Đã lỗi)
│   ├── Danh sách tác vụ (`#task-list`): Skeleton khi tải, Empty state khi rỗng, Error state tại chỗ
│   ├── Phân trang tác vụ: Nút "Xem thêm" (`#tasks-load-more`)
│   └── └─ Chạm vào việc → Màn Chi tiết việc (`#screen-task`, L2):
│          ├── Tóm tắt tác vụ + Trạng thái
│          ├── Dòng thời gian các bước thực thi (Timeline)
│          ├── Cụm nút Thử lại cho việc lỗi (`#btn-retry-task`, `#btn-retry-step`)
│          └── └─ Chạm từng bước → Bottom Sheet Chi tiết bước (`#sheet-step-detail`, L3):
│                 Hiển thị công cụ, đầu vào (đã che bí mật), kết quả thực tế, thời lượng, trạng thái bằng chữ
│
├── 2. Tab Phê duyệt (`#tab-pheduyet`)
│   ├── Thẻ Banner yêu cầu đang chờ duyệt nổi bật ở đầu tab (`#pending-wrap`):
│   │   Hiển thị công cụ, nhóm việc, tóm tắt và 3 nút hành động (Duyệt / Từ chối / Duyệt & Nhớ cho phiên)
│   ├── Lịch sử phê duyệt (`#history-list`):
│   │   ├── Nhóm ngày trực quan: "Hôm nay", "Hôm qua", "DD/MM/YYYY" kèm số lượng quyết định
│   │   ├── Mốc giờ hiển thị ngay trên hàng thu gọn (`lúc HH:MM`)
│   │   └── Chạm hàng → Mở rộng accordion xem chi tiết quyền, công cụ, thời gian và kết quả
│   └── Bộ lọc & Trạng thái: Dọn dẹp sạch thẻ thử nghiệm, chuẩn hóa nhãn tiếng Việt ("Chế độ quyền", "Hỏi trước khi chạy")
│
├── 3. Tab Lịch trình (`#tab-lich`)
│   ├── Nhóm Hàng ngày:
│   │   └── Heartbeat chủ động (`data-sched-open="heartbeat"`):
│   │       Hợp nhất trực tiếp vào Màn Chi tiết Lịch trình (`#screen-schedule-detail`, L2),
│   │       không còn cấu trúc sheet lồng 3 cấp; hỗ trợ bật/tắt công tắc trực tiếp
│   ├── Nhóm Lịch hẹn & Việc cá nhân:
│   │   └── Chạm vào từng lịch hẹn → Màn Chi tiết Lịch trình (`#screen-schedule-detail`, L2):
│   │       ├── Trạng thái lịch trình, biểu thức cron (kèm diễn giải tiếng Việt), múi giờ, payload
│   │       └── Phân trang lịch sử chạy (5 lượt/trang + nút "Xem thêm" báo số lượt còn lại)
│   └── Nút thêm lịch hẹn cá nhân
│
├── 4. Tab Hồ sơ & Ký ức (`#tab-hoso`)
│   ├── Thẻ Hồ sơ của agent (`#card-dossier`) → Màn Hồ sơ agent (`#screen-sub-dossier`, L2):
│   │   Duyệt danh sách 9 tệp cấu hình dossier độc lập (SOUL, IDENTITY, USER, MEMORY...)
│   │   └─ Chạm từng tệp → Màn Chi tiết tệp hồ sơ (`#screen-profile`, L3)
│   ├── Thẻ Bộ nhớ dài hạn (`#card-memory`) → Màn Bộ nhớ dài hạn (`#screen-sub-memory`, L2):
│   │   Danh sách facts kèm ô tìm kiếm bộ nhớ, lọc theo trạng thái/nguồn gốc
│   │   └─ Chạm từng fact → Màn Chi tiết ký ức (`#screen-fact-detail`, L3)
│   ├── Thẻ Kỹ năng (`#card-skills`) → Màn Kỹ năng (`#screen-sub-skills`, L2):
│   │   Tìm kiếm kỹ năng, lọc theo danh mục, che giấu đường dẫn tuyệt đối máy cá nhân
│   │   └─ Chạm từng kỹ năng → Màn Chi tiết kỹ năng (`#screen-skill`, L3): Đọc nội dung SKILL.md
│   └── Thẻ Thư viện tài liệu (`#card-library`) → Màn Thư viện (`#screen-sub-library`, L2):
│       ├── Danh sách tài liệu artifacts đã sinh (chia sẻ, ghim, sửa tên, xoá)
│       ├── Nút mở Thùng rác tài liệu (`#screen-library-trash`, L3)
│       └── Chạm tài liệu → Màn Xem trước tài liệu (`#screen-library-preview`, L3)
│
└── 5. Tab Cài đặt (`#tab-caidat`)
    ├── Card Cài đặt hệ sinh thái:
    │   ├── Công cụ kết nối (`#screen-connectors`, L2):
    │   │   ├── Tab "Đã cài": Quản lý danh sách connectors (Google, FB, Threads, Zalo, MCP)
    │   │   │   └─ Chạm connector → Màn Chi tiết connector & Quyền (`#screen-connector-policy`, L3)
    │   │   ├── Tab "Chợ MCP" (`#screen-mktcat`, L2): Danh mục curated, tìm kiếm, đánh giá bảo mật
    │   │   └── Tab "Thêm thủ công" (`#screen-import`, L2): Dán JSON khai báo MCP server
    │   ├── Kho lưu trữ an toàn (`#screen-vault`, L2):
    │   │   Thanh tìm kiếm `#vault-search` tự hiện khi >= 5 mục; thêm, sửa, xoá bí mật an toàn
    │   │   └─ Chạm bí mật → Màn Chi tiết bí mật (`#screen-vault-detail`, L3)
    │   ├── Quyền (`#screen-policy`, L2):
    │   │   Phân quyền 3 nấc (Cho phép / Hỏi / Chặn) cho nhóm việc và từng công cụ
    │   │   └─ Nút xem Tất cả công cụ (`#screen-all-tools-policy`, L3)
    │   ├── Feed chủ động (`#screen-feed`, L2):
    │   │   Điều khiển nhịp đăng cron, nút preset, giờ yên lặng, nguồn tin ghim/tránh
    │   │   và nút "Chạy ngay một lượt"
    │   └── Thiết bị & Hệ thống (`#screen-system`, L2):
    │       Thông tin máy chủ, OS, phiên làm việc, nút "Thêm ra màn hình chính" (`addToHomeScreen`)
    │       và liên kết mở Cổng model CLIProxyAPI (`#screen-cliproxy`, L3)
    │
    ├── Card Cá nhân hoá:
    │   └── Thương hiệu & Mascot (`#screen-brand`, L2):
    │       ├── Đổi tên bot hiển thị và lưu bền KV
    │       ├── Lưu ý ranh giới Telegram: @BotFather cho username/tên/avatar vs Tên hiển thị app/chat
    │       ├── Lưới chọn Mascot đại diện (Mulon Cổ Điển, Spark, Cosmo, Zen)
    │       └── Chuẩn hoá thương hiệu tỉ lệ 60/30/10 với màu tím Mulon `#7C3AED`
    │
    └── Card Giao diện:
        ├── Chọn màu chủ đề (Tím Mulon mặc định + 5 tuỳ chọn)
        └── Ghi chú thiết kế về chuẩn màu nhận diện thương hiệu
```

---

## 2. Tiêu chuẩn điều hướng và Trải nghiệm người dùng
1. **Nút quay lại thống nhất**: Mọi màn con (L2, L3) đều có phần tử `.backrow` ở đầu trang và tự động đăng ký với nút `BackButton` native của Telegram WebApp SDK (`tg.BackButton.show()` / `hide()`).
2. **Khử rò rỉ lỗi giữa các tab**: Mọi thao tác chuyển tab chính (`showMain`) hoặc chuyển màn con (`showSub`) tự động làm sạch `global-error`, chống dính banner đỏ sang tab khác.
3. **Phản hồi xúc giác (Haptic Feedback)**: Mọi thao tác chuyển tab, chọn chip, bấm nút và mở sheet đều kích hoạt haptic nhẹ (`tg.HapticFeedback.selectionChanged()` / `impactOccurred()`).
4. **Xác thực phiên bền vững**: Header `X-Telegram-Init-Data` hỗ trợ thời hạn phiên lên tới 24 giờ (`INIT_DATA_MAX_AGE_S`), lấy động qua `getInitData()` chống đóng băng phiên khi mở app lâu.
