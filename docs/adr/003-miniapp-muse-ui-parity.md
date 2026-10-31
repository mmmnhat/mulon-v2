# ADR-003: Cải Tổ Giao Diện Mini App Đồng Bộ Nhận Diện & Trải Nghiệm Meta Muse App ([T-40])

> **Trạng thái**: Đề xuất (Proposed) — Chờ thẩm định & phản hồi từ Muse reviewer qua kênh `AGENT_TASKS.md`  
> **Chủ trì (The Agency)**: `agency-ui-designer` & `agency-frontend-developer`  
> **Phối hợp thẩm định**: `agency-ui-finish-gate-reviewer`, `agency-reality-checker`, `agency-test-automation-engineer`  
> **Ngày lập**: 31/10/2026  
> **Tác động**: `mulon/webapp/index.html` (CSS tokens, Header Hero, Task Cards, Responsive media queries), `tests/test_v17_miniapp_modular_js.py`, `scripts/capture_touch_renders.py`, `docs/audits/renders/`  

---

## 1. Ngữ cảnh & Đánh giá sai lệch (Context & Gap Analysis)

Sau khi đối chiếu ảnh chụp màn hình thực tế của ứng dụng **Meta Muse** (ảnh do chủ dự án cung cấp tại `media_1792156759818_6a34c0a8.png`) với giao diện Mini App hiện hành (`01_dashboard_light.png` / `02_dashboard_dark.png`), phát hiện các sai lệch thị giác và trải nghiệm cốt lõi:

| Thành phần | Meta Muse App (Bản gốc) | Mini App MuLon hiện tại | Sai lệch & Hướng xử lý |
|---|---|---|---|
| **Cảm giác tổng thể** | **Personal AI Agent Studio**: Ấm cúng, hiện đại, đậm chất cộng sự cá nhân. | Bảng quản trị **Todo List / Task Manager** kỹ thuật khô khan. | Tái cấu trúc không gian thị giác: đưa Mascot & Danh tính cộng sự lên vị trí trung tâm, giảm bớt tính "bảng quản trị". |
| **Bảng màu & Nền** | Nền xám nhạt (`#F8F9FA`), thẻ card trắng tinh khiết (`#FFFFFF`), viền siêu mỏng (`#EBECEF`), bóng đổ mềm. | Nền giấy ngả vàng (`--paper: #FAF9F7`), màu nhấn tím đậm (`--accent: #7C3AED`) rải rác. | Cập nhật hệ thống **Muse Clean Palette** (Trắng tinh khiết - Xám hiện đại - Viền thanh mảnh), giữ accent thương hiệu tinh tế. |
| **Header Danh tính (Identity Hero)** | Avatar Mascot tròn ấm áp, tên to rõ ràng, badge chấm xanh `● Đã kết nối`, 4 icon tròn chuyển nhanh trực quan. | Avatar nhỏ ở góc trái, trạng thái chữ mờ ("Sẵn sàng") kèm text lỗi nếu có. | Thiết kế lại **Header Hero chuẩn Muse** ở đầu app: Mascot nổi bật, tên bot, nhãn trạng thái kết nối sống, 4 icon switcher tròn (Việc, Quyền, Lịch, Vault). |
| **Dòng thời gian tác vụ (Today Stream)** | Tác vụ hiển thị dạng dòng thời gian "Hôm nay", checkmark tròn, tiêu đề in đậm, subtext giải thích, nhãn thời gian và **badge nguồn nền tảng** (`[FA facebook.com]`, `[TH threads.net]`, `[GS Google Sheets]`). | Thẻ task log kỹ thuật ("Hoàn tất 7/9 bước (2 bước lỗi)"), thiếu nhận diện nguồn nền tảng. | Thiết kế lại **Activity Stream Card**: Thêm badge nguồn tương tác (Facebook, Threads, Zalo, Google Sheet, Web) và phân nhóm thời gian (Hôm nay, Hôm qua). |
| **Bố cục Responsive** | Hỗ trợ co giãn linh hoạt 3 cột trên màn hình rộng. | Cố định 1 cột đơn lập cả trên di động lẫn máy tính. | Thêm CSS Media Queries `@media (min-width: 768px)`: Bung giao diện **Split-View 2 cột** khi mở trên Telegram Desktop. |

---

## 2. Kiến Trúc Thiết Kế Đề Xuất (Architecture & UI System)

### 2.1 Bố cục Header Hero & Quick Switcher
```
┌─────────────────────────────────────────────────────────────┐
│                    HEADER HERO CHUẨN MUSE                   │
│                                                             │
│                    [   Avatar Mascot   ]                    │
│                      Mulon (Muse Companion)                 │
│                          ● Đã kết nối                       │
│                                                             │
│      [ 📋 Việc ]     [ 🛡️ Quyền ]     [ ⏰ Lịch ]     [ 🔑 Kho ]    │
│     (Tasks Feed)     (Policy/Appr)   (Schedules)     (Vault)│
└─────────────────────────────────────────────────────────────┘
```

### 2.2 Bố cục Thẻ Tác Vụ Chuẩn Muse (Activity Stream Cards)
```
┌─────────────────────────────────────────────────────────────┐
│  Hôm nay                                                    │
│                                                             │
│  ✔  Quyết định đăng comment chào hàng                20:06  │
│     Posted Claude API comment on Facebook                   │
│     [FA facebook.com]                                       │
│                                                             │
│  ✔  Thiết lập quét bài mỗi giờ                       20:01  │
│     Set up hourly post scan every minute                    │
│     [TH threads.net]                                        │
│                                                             │
│  ✔  Dựng lịch bán hàng đa sản phẩm                   19:36  │
│     Created evening comment and Threads post widgets        │
│     [GS Google Sheets]                                      │
└─────────────────────────────────────────────────────────────┘
```

### 2.3 Hệ thống Design Tokens Mới (Muse Clean Palette)
- **Màu nền**: `--muse-bg: #F8F9FA;` (Light), `--muse-bg-dark: #121214;` (Dark)
- **Màu bề mặt card**: `--muse-surface: #FFFFFF;` (Light), `--muse-surface-dark: #1E1E22;` (Dark)
- **Màu đường kẻ viền**: `--muse-border: #EBECEF;` (Light), `--muse-border-dark: #2A2A30;` (Dark)
- **Màu văn bản chính**: `--muse-text-primary: #1C1E21;` (Light), `--muse-text-primary-dark: #F5F5F7;` (Dark)
- **Màu văn bản phụ**: `--muse-text-secondary: #65676B;` (Light), `--muse-text-secondary-dark: #A0A0A8;` (Dark)
- **Màu trạng thái kết nối**: `--muse-status-online: #10B981;`
- **Màu thương hiệu nhấn**: `--muse-accent: #7C3AED;` (hoặc toggle xanh Muse `#0064E0`)

---

## 3. Kế Hoạch Triển Khai Theo Lát Cắt (Slices)

Để đảm bảo tuân thủ nghiêm ngặt **Quy tắc số 0 (Zero Hardcode)**, **Single-File Serving** và **Kỷ luật kiểm thử 100% xanh**:

- **Lát cắt 1 — Design Tokens & Header Hero chuẩn Muse**:
  - Tái cấu trúc Header: Avatar Mascot to tròn trung tâm, tên bot, badge trạng thái `● Đã kết nối` (bắt theo `S.system` / heartbeat live), thanh 4 icon tròn chuyển nhanh.
  - Cập nhật Design Tokens chuẩn Muse Clean Palette.
  - Kiểm thử render Chromium 390×844 không lỗi DOM, touch target ≥ 44px.
- **Lát cắt 2 — Thẻ Tác vụ Stream & Badge Nền tảng (Platform Badges)**:
  - Nâng cấp card công việc: Tích hợp badge icon nguồn (Facebook, Threads, Zalo, Google Sheet, Web) suy từ metadata hoặc tên công cụ của task.
  - Phân nhóm thời gian (Hôm nay / Cũ hơn).
  - Giữ nguyên 100% backward compatibility với các API `/api/state`, `/api/tasks`.
- **Lát cắt 3 — Responsive Split-View cho Telegram Desktop (≥ 768px)**:
  - Bổ sung breakpoint `@media (min-width: 768px)`: Khi mở trong cửa sổ Telegram Desktop, chuyển layout 1 cột thành 2 cột song song (Trái: Danh mục & Activity Feed, Phải: Chi tiết công việc & Cài đặt).
  - Cập nhật suite test `tests/test_v17_miniapp_modular_js.py`, chụp lại bộ render thật `01_dashboard_light.png`, `02_dashboard_dark.png`, `04_tasks_dark.png`.

---

## 4. Ràng buộc bảo toàn (Invariants)
1. **Zero Backend Breaking**: Không sửa đổi hoặc phá vỡ các hợp đồng API REST hiện hữu trong `mulon/webapp_server.py`.
2. **Single-File Serving**: Không sinh thêm file `.js` độc lập hay build tool Node ngoài; toàn bộ thay đổi nằm trong `mulon/webapp/index.html`.
3. **Accessibility**: Toàn bộ nút bấm, hàng tương tác tiếp tục đạt tiêu chuẩn touch target $\ge 44\text{px}$ và độ tương phản WCAG AA.
