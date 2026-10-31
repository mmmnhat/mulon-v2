# ADR-003: Cải Tổ Giao Diện Mini App Đồng Bộ Nhận Diện & Trải Nghiệm Meta Muse App ([T-40])

> **Trạng thái**: Đã nghiệm thu Lát cắt 1 & 2 (VERIFIED) — Đã hoàn thành toàn bộ 3 Lát cắt (DONE, Chờ nghiệm thu tổng thể T-40)  
> **Chủ trì (The Agency)**: `agency-ui-designer` & `agency-frontend-developer`  
> **Phối hợp thẩm định**: `agency-ui-finish-gate-reviewer`, `agency-reality-checker`, `agency-test-automation-engineer`  
> **Ngày lập**: 31/10/2026 (Cập nhật sau verdict thẩm định của Muse)  
> **Tác động**: `mulon/webapp/index.html` (CSS tokens, Header Hero, Task Cards, Responsive media queries), `tests/test_v17_miniapp_modular_js.py`, `scripts/capture_touch_renders.py`, `docs/audits/renders/`  

---

## 1. Ngữ cảnh & Đánh giá sai lệch (Context & Gap Analysis)

Sau khi đối chiếu ảnh chụp màn hình thực tế của ứng dụng **Meta Muse** (ảnh do chủ dự án cung cấp, đã lưu trữ độc lập trong kho tài liệu tại [`docs/reference/meta_muse_app_reference.png`](docs/reference/meta_muse_app_reference.png)) với giao diện Mini App hiện hành (`01_dashboard_light.png` / `02_dashboard_dark.png`), xác định các sai lệch thị giác và trải nghiệm cốt lõi:

| Thành phần | Meta Muse App (Bản gốc) | Mini App MuLon hiện tại | Sai lệch & Hướng xử lý |
|---|---|---|---|
| **Cảm giác tổng thể** | **Personal AI Agent Studio**: Ấm cúng, hiện đại, đậm chất cộng sự cá nhân. | Bảng quản trị **Todo List / Task Manager** kỹ thuật khô khan. | Tái cấu trúc không gian thị giác: đưa Mascot & Danh tính cộng sự lên vị trí trung tâm, giảm bớt tính "bảng quản trị". |
| **Bảng màu & Nền** | Nền xám nhạt (`#F8F9FA`), thẻ card trắng tinh khiết (`#FFFFFF`), viền siêu mỏng (`#EBECEF`), bóng đổ mềm. | Nền giấy ngả vàng (`--paper: #FAF9F7`), màu nhấn tím đậm (`--accent: #7C3AED`) rải rác. | Cập nhật hệ thống **Muse Clean Palette** (Trắng tinh khiết - Xám hiện đại - Viền thanh mảnh), bảo toàn màu nhấn thương hiệu Tím Mulon (`#7C3AED`). |
| **Header Danh tính (Identity Hero)** | Avatar Mascot tròn ấm áp, tên to rõ ràng, badge trạng thái `● Đã kết nối`, 4 icon tròn chuyển nhanh trực quan. | Avatar nhỏ ở góc trái, text "Đã kết nối" chìm ở góc, thiếu khối Hero danh tính nổi bật. | Nâng cao prominence của **Header Hero**: Đưa Mascot ra vị trí trung tâm nổi bật, tên bot to rõ, khối pill trạng thái "Đã kết nối" chỉn chu, 4 icon switcher tròn (Việc, Quyền, Lịch, Kho). |
| **Dòng thời gian tác vụ (Today Stream)** | Tác vụ hiển thị dạng dòng thời gian "Hôm nay", checkmark tròn, tiêu đề in đậm, subtext giải thích, nhãn thời gian và **badge nguồn nền tảng** (`[FA facebook.com]`, `[TH threads.net]`, `[GS Google Sheets]`). | Thẻ task log kỹ thuật ("Hoàn tất 7/9 bước (2 bước lỗi)"), thiếu nhận diện nguồn nền tảng. | Thiết kế lại **Activity Stream Card**: Thêm badge nguồn tương tác (Facebook, Threads, Zalo, Google Sheet, Web) và phân nhóm thời gian (Hôm nay, Hôm qua). |
| **Bố cục Responsive** | Hỗ trợ co giãn linh hoạt 2 cột trên màn hình rộng. | Giới hạn khung 600px căn giữa (`@media (min-width: 769px)`). | Thay thế/mở rộng giới hạn 600px bằng **Split-View 2 cột** (`@media (min-width: 768px)`): Cột trái danh mục & Activity Feed, cột phải chi tiết tác vụ & Settings khi mở trên Telegram Desktop. |

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

#### Bản đồ điều hướng 4 nút Hero (Navigation Mapping — Fulfilling Điều kiện 5):
- `[ 📋 Việc ]`: Kích hoạt `Mulon.State.setTab('viec')` / `showMain('viec')`.
- `[ 🛡️ Quyền ]`: Kích hoạt `Mulon.State.setTab('pheduyet')` / `showMain('pheduyet')`.
- `[ ⏰ Lịch ]`: Kích hoạt `Mulon.State.setTab('lich')` / `showMain('lich')`.
- `[ 🔑 Kho ]`: Kích hoạt `Mulon.State.setSubScreen('screen-vault')` / `showSub('screen-vault')`.
- **Thanh Bottom Segbar (5 tab)**: Giữ nguyên làm thanh điều hướng toàn cục vĩnh viễn ở đáy app (`viec`, `pheduyet`, `lich`, `hoso`, `caidat`). 4 icon trên Hero đóng vai trò lối tắt ngữ cảnh nhanh (Quick Companion Shortcuts), hoàn toàn đồng bộ với State Bus.

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
│     Set up hourly post scan every hour                      │
│     [TH threads.net]                                        │
│                                                             │
│  ✔  Dựng lịch bán hàng đa sản phẩm                   19:36  │
│     Created evening comment and Threads post widgets        │
│     [GS Google Sheets]                                      │
└─────────────────────────────────────────────────────────────┘
```

### 2.3 Hệ thống Design Tokens Mới (Muse Clean Palette — Tuân thủ Tuyệt đối Lock Thiết kế §6)
Tuân thủ nghiêm ngặt quy định tại `AGENTS.md` §6 và `docs/ops/antigravity-coordinator-prompt.md` §32 (Một màu nhấn duy nhất là Tím Mulon `#7C3AED`, trạng thái bằng chữ + phân cấp trung tính, KHÔNG dùng màu xanh lá/vàng/đỏ):
- **Màu nền ứng dụng**: `--muse-bg: #F8F9FA;` (Light), `--muse-bg-dark: #121214;` (Dark)
- **Màu bề mặt thẻ (Cards)**: `--muse-surface: #FFFFFF;` (Light), `--muse-surface-dark: #1E1E22;` (Dark)
- **Màu đường viền mỏng**: `--muse-border: #EBECEF;` (Light), `--muse-border-dark: #2A2A30;` (Dark)
- **Màu chữ chính**: `--muse-text-primary: #1C1E21;` (Light), `--muse-text-primary-dark: #F5F5F7;` (Dark)
- **Màu chữ phụ**: `--muse-text-secondary: #65676B;` (Light), `--muse-text-secondary-dark: #A0A0A8;` (Dark)
- **Màu chỉ báo trạng thái (Status Indicator)**: Giữ nguyên token trung tính `var(--ink3)` hoặc Tím Mulon `var(--accent)`, trạng thái thể hiện rõ bằng chữ "Đã kết nối" (không dùng dot xanh lá).
- **Màu thương hiệu nhấn duy nhất**: `--accent: #7C3AED;`

---

## 3. Kế Hoạch Triển Khai Theo 3 Lát Cắt (Slices)

Để đảm bảo tuân thủ nghiêm ngặt **Quy tắc số 0 (Zero Hardcode)**, **Single-File Serving** và **Kỷ luật kiểm thử 100% xanh**:

- **Lát cắt 1 — Design Tokens Muse Clean Palette & Header Hero chuẩn Muse**:
  - Tái cấu trúc Header: Avatar Mascot tròn trung tâm, tên bot, nhãn trạng thái `● Đã kết nối` (bắt theo `S.system` / heartbeat live với dot trung tính), thanh 4 icon tròn chuyển nhanh trực quan.
  - Cập nhật Design Tokens chuẩn Muse Clean Palette.
  - Kiểm thử render Chromium 390×844 không lỗi DOM, touch target $\ge 44\text{px}$.
- **Lát cắt 2 — Thẻ Tác vụ Stream & Badge Nền tảng (Platform Badges)**:
  - Bổ sung trường tuỳ chọn `platform: Optional[str]` vào mô hình task hoặc khai báo bảng mapping trong config theo luật Rule 0 (fallback: không rõ nguồn → không gắn badge).
  - Nâng cấp card công việc: Tích hợp badge icon nguồn (Facebook, Threads, Zalo, Google Sheet, Web).
  - Phân nhóm thời gian (Hôm nay / Cũ hơn).
  - Giữ nguyên 100% backward compatibility với các API `/api/state`, `/api/tasks`.
- **Lát cắt 3 — Responsive Split-View cho Telegram Desktop (≥ 768px)**:
  - Thay thế/mở rộng giới hạn 600px hiện tại: Bổ sung breakpoint `@media (min-width: 768px)` chuyển layout thành Split-View 2 cột song song (Trái: Danh mục & Activity Feed, Phải: Chi tiết công việc & Cài đặt) khi mở trên Telegram Desktop.
  - Cập nhật suite test `tests/test_v17_miniapp_modular_js.py`, refresh bộ 3 ảnh render thật `01_dashboard_light.png`, `02_dashboard_dark.png`, `04_tasks_dark.png`.

---

## 4. Ràng buộc bảo toàn (Invariants)
1. **Zero Backend Breaking**: Không sửa đổi hoặc phá vỡ các hợp đồng API REST hiện hữu trong `mulon/webapp_server.py`.
2. **Single-File Serving**: Không sinh thêm file `.js` độc lập hay build tool Node ngoài; toàn bộ thay đổi nằm trong `mulon/webapp/index.html`.
3. **Accessibility**: Toàn bộ nút bấm, hàng tương tác tiếp tục đạt tiêu chuẩn touch target $\ge 44\text{px}$ và độ tương phản WCAG AA.
