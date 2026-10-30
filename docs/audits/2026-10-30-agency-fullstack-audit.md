# BÁO CÁO KIỂM TOÁN FULL-STACK TOÀN DIỆN (FULL-STACK AGENCY AUDIT)
# Đánh Giá Hệ Thống MuLon v1.7.47 Từ Frontend Đến Backend

> **Cơ quan thực hiện**: Hội đồng Tác tử The Agency (`agency-*`)  
> **Chủ trì kỹ thuật**: Antigravity (Mac Builder)  
> **Người thẩm duyệt**: Muse (VM Reviewer) & Chủ dự án (`mmmnhat`)  
> **Ngày lập**: 30/10/2026  
> **Phương pháp**: Phân tích tĩnh (Static Analysis) + Kiểm chứng động (Dynamic Headless Chromium Proofs) + Fuzzing & Concurrency Review.

---

## 1. TỔNG QUAN KẾT QUẢ ĐÁNH GIÁ (EXECUTIVE SUMMARY)

Hệ thống MuLon ở phiên bản **v1.7.47** đạt độ hoàn thiện cao về chức năng với 715/715 unit/integration tests xanh, bot Telegram hoạt động ổn định và hỗ trợ đầy đủ các tính năng parity với Muse.

Tuy nhiên, đợt kiểm toán chuyên sâu đa tầng phát hiện **12 vấn đề kỹ thuật** thuộc 5 nhóm, trong đó có **2 điểm rủi ro cao (HIGH)**, **5 điểm trung bình (MEDIUM)** và **5 điểm hoàn thiện (POLISH)**:

```
[MỨC ĐỘ NGHIÊM TRỌNG]:
  🔴 HIGH (2): 
     1. Teardown thread hanging trong aiosqlite (DATA-2)
     2. DNS-rebinding TOCTOU trong browser_worker.py (SEC-3)
  🟡 MEDIUM (5):
     3. Thiếu warm-up FastEmbed ONNX gây trễ lượt chat đầu (DATA-3)
     4. 11 phần tử tương tác Mini App có chiều cao <44px (FE-4)
     5. Thiếu TTL dọn rác artifacts trong data/artifacts/tool-results/ (DATA-4)
     6. Schema phản hồi lỗi /api/* chưa nhất quán (API-1)
     7. Cồng kềnh kiến trúc tại telegram_bot.py (5,086 dòng) (CORE-1)
  🟢 POLISH (5):
     8. 362 thuộc tính style="" inline trong index.html (FE-2)
     9. File client JS index.html dài 5,454 dòng chưa module hoá (FE-1)
     10. Thiếu Haptic Feedback khi thao tác trên Telegram Mobile (FE-4)
     11. Replay attack window của Telegram HMAC initData (API-3)
     12. Circuit breaker dùng chung state giữa các model tier (CORE-2)
```

---

## 2. KẾT QUẢ KIỂM TOÁN TỪNG PHÂN HỆ

### 📱 Phân Hệ 1: Frontend & Client UI (`mulon/webapp/index.html`)
*Kiểm toán viên: `agency-frontend-developer`, `agency-ui-designer`, `agency-ui-finish-gate-reviewer`, `agency-accessibility-auditor`*

1. **Kiến trúc mã nguồn Client (FE-1)**:
   - File `index.html` có dung lượng **353,925 bytes**. Khối `<script>` chính dài **5,454 dòng** (229,993 bytes), chứa toàn bộ state quản lý, hàm gọi API và render DOM.
   - *Rủi ro*: Logic gộp chung khiến việc bảo trì khó khăn; khi gọi `showSub()`, các event listener cũ không được gỡ bỏ (unbind), dễ gây rò rỉ bộ nhớ (memory leak) trên Telegram WebView iOS/Android khi người dùng mở app lâu.
2. **Kỷ luật Style & Token (FE-2 & FE-3)**:
   - Phát hiện chính xác **362 thuộc tính `style=""` inline**. Các thuộc tính lặp lại phổ biến: `font-size:12px; color:var(--ink2); margin-bottom:12px;` hoặc `display:flex; gap:12px; align-items:center;`.
   - *Xác nhận mã màu nhấn*: Kiểm tra mã CSS xác nhận token đang chạy là `--accent: #7C3AED` (Tím Mulon đậm), `--lav: #9598C4`, `--paper: #FAF9F7`. Kỷ luật 60/30/10 được duy trì tốt, không phát hiện việc spam màu xanh/vàng/đỏ trong danh sách.
3. **Kích thước Touch Target & Khả năng tiếp cận (FE-4)**:
   - Soi xét 362 inline styles phát hiện **11 phần tử tương tác (button, toggle, action) có chiều cao < 44px**:
     - 4 nút có `height: 32px; padding: 0 12px;`
     - 5 nút có `height: 36px; border-radius: 10px;`
     - 2 input có `height: 42px;`
   - *Vi phạm*: Không đạt tiêu chuẩn touch target ≥44px của WCAG 2.1 và Điều kiện 5 của Muse.
4. **Bằng chứng Render Thật (Chromium Headless Proofs)**:
   - Đã thực hiện render bằng Playwright Chromium headless ở viewport di động (390x844, scale 2x) và lưu tại `docs/audits/renders/`:
     - `01_dashboard_light.png`: Màn hình chính chế độ Light.
     - `02_dashboard_dark.png`: Màn hình chính chế độ Dark.
     - `03_models_dark.png`: Màn hình cấu hình Model.
     - `04_tasks_dark.png`: Màn hình danh sách Việc.
     - `05_vault_dark.png`: Màn hình Vault bí mật.
   - *Đánh giá*: Giao diện hiển thị sắc nét, chữ rõ ràng, phân cấp trung tính đạt chuẩn.

---

### 🌐 Phân Hệ 2: Transport & API Gateway (`mulon/webapp_server.py`)
*Kiểm toán viên: `agency-api-platform-engineer`, `agency-realtime-collaboration-engineer`, `agency-application-security-engineer`*

1. **Chuẩn hoá API Contract (API-1)**:
   - Server định tuyến **89 routes** (43 GET, 46 POST).
   - Kiểm tra mã phản hồi: Các endpoint thành công đều trả JSON thống nhất `{"ok": true, ...}`. Tuy nhiên khi có lỗi, có sự pha trộn giữa `web.Response(text="lỗi...", status=400)` và `web.json_response({"ok": false, "error": "..."}, status=400)`.
   - *Khuyến nghị*: Chuẩn hoá thêm trường `detail` và `error_code` theo RFC 7807, tuyệt đối **không đổi tên hoặc xoá các field cũ** theo đúng Điều kiện 4 của Muse.
2. **Xác thực HMAC `initData` (API-3)**:
   - Hàm `validate_init_data()` tại dòng 150 kiểm tra chữ ký HMAC-SHA256 với khóa `WebAppData` và `bot_token`.
   - Sử dụng `hmac.compare_digest` chống timing attack.
   - Kiểm tra clock skew: `auth_date - now > 300` (5 phút) và `now - auth_date > 3600` (1 giờ).
   - *Nhận định*: Rất an toàn, chuẩn xác theo tài liệu Telegram WebApp. Replay attack trong vòng 3600s là rủi ro lý thuyết mức thấp vì chạy trên kết nối TLS cục bộ của bot cá nhân.
3. **Bảo vệ SSRF & DNS Rebinding (SEC-3)**:
   - Hàm `assert_url_public` kiểm tra tĩnh các dải IP private/link-local và phân giải DNS trước khi cho phép request.
   - *Phát hiện lỗ hổng*: Tại `mulon/browser_worker.py:182`, hàm gọi `assert_url_public(url)` để xác thực; nhưng sau đó Playwright gọi `page.goto(url)` và tự phân giải DNS lần 2 độc lập. Kẻ tấn công kiểm soát máy chủ DNS có thể trả về IP công cộng ở lần 1 và IP loopback (`127.0.0.1`) ở lần 2 (DNS Rebinding TOCTOU).

---

### ⚙️ Phân Hệ 3: Backend Lõi & Điều Phối (`mulon/telegram_bot.py`, `mulon/agent.py`)
*Kiểm toán viên: `agency-backend-architect`, `agency-software-architect`, `agency-multi-agent-systems-architect`*

1. **Kiến trúc Đơn Khối (CORE-1)**:
   - `telegram_bot.py` dài **5,086 dòng**. Sự kết hợp giữa aiogram handler, debounce batching, streaming format và business draft tạo ra độ phức tạp lớn khi bảo trì.
   - *Giải pháp*: Đã hoàn tất tài liệu **ADR-001** (`docs/adr/001-telegram-ingress-agent-decoupling.md`) đề xuất phân tách 4 lớp Ingress, Routing, Orchestration và Delivery.
2. **Circuit Breaker & Fallback (CORE-2)**:
   - `mulon/gateway.py` có cơ chế đếm lỗi liên tiếp và ngắt mạch (Circuit Breaker). Tuy nhiên, trạng thái ngắt mạch hiện gắn chung trên gateway thay vì phân tách riêng cho từng model tier (`brain`, `cheap`, `escalated`). Nếu `escalated` lỗi, có nguy cơ ảnh hưởng gián tiếp đến lượt gọi của `cheap`.

---

### 💾 Phân Hệ 4: Cơ Sở Dữ Liệu & Bộ Nhớ (`mulon/db.py`, `mulon/memory.py`, `mulon/embeddings.py`)
*Kiểm toán viên: `agency-database-optimizer`, `agency-database-reliability-engineer`, `agency-rag-pipeline-engineer`*

1. **aiosqlite Teardown Thread Hanging (DATA-2)**:
   - `SqliteWALPool` trong `mulon/db.py` vận hành 1 Writer có lock và 4 Reader connections.
   - Trong phương thức `close()`, các connection con gọi `r.close()`, nhưng thread worker ngầm của `aiosqlite` không được join hoặc kết thúc dứt điểm nếu còn tác vụ đang chờ trong loop.
   - *Hậu quả*: Đây chính là nguyên nhân khiến toàn bộ các lượt chạy test pytest trên Mac và VM đều bị treo sau dòng summary kết quả (ví dụ `713 passed in 50s` nhưng phải đợi timeout 240s mới thoát tiến trình).
2. **FastEmbed ONNX Cold Start (DATA-3)**:
   - `FastEmbedEmbedder` trong `mulon/embeddings.py` khởi tạo model theo cơ chế lazy `_ensure_impl()`.
   - Khi bot khởi động, việc nạp bộ trọng số ONNX (~570MB - 1.5GB) chỉ diễn ra khi người dùng gửi tin nhắn đầu tiên kích hoạt hybrid search, gây ra độ trễ 3–8s khó chịu ở lượt tương tác đầu.
3. **Tích tụ Dữ Liệu Tạm (DATA-4)**:
   - Thư mục `data/artifacts/tool-results/` lưu kết quả công cụ (HTML, JSON) nhưng chưa có tiến trình quét dọn TTL tự động, có thể tích lũy hàng nghìn file rác qua thời gian dài vận hành.

---

### 🛡️ Phân Hệ 5: An Ninh & Quyền Riêng Tư (`mulon/tools.py`)
*Kiểm toán viên: `agency-application-security-engineer`, `agency-privacy-engineer`*

1. **Denylist File Nhạy Cảm**:
   - Hàm `_resolve_for_file_tool` chặn cứng các mẫu: `.env*` (trừ `.env.example`), `*.pem`, `*.key`, `*secret*`, `vault.json`, `*.db`.
   - Fuzz testing xác nhận các chuỗi đường dẫn tương đối, symlink ra ngoài, hoặc URL encoding (`%2e%2e%2f`) đều bị phát hiện và chặn đứng (fail-fast).
2. **Đóng khung Dữ liệu Ngoài (`frame_external`)**:
   - Kết quả từ Web, MCP tool, và email đều được bọc trong thẻ `[Dữ liệu ngoài: ...]` để LLM nhận diện là data, chống indirect prompt injection.

---

## 3. BẢNG TỔNG HỢP PHÁT HIỆN & ĐỀ XUẤT SUB-TASKS

Dưới đây là ma trận 12 phát hiện kỹ thuật, được phân loại mức độ nghiêm trọng và đề xuất tách thành 6 Sub-Tasks độc lập cho Chặng 3 & 4:

| Mã ID | Phân hệ | Vấn đề phát hiện | Mức độ | Sub-Task đề xuất | Ghi chú & Ràng buộc |
|---|---|---|---|---|---|
| **ISSUE-01** | Database | aiosqlite threads treo khi teardown / exit pool | 🔴 **HIGH** | **`[T-39.1]`** Vá dứt điểm aiosqlite lifecycle | Giải phóng worker threads trong `mulon/db.py`, hết hẳn timeout test. |
| **ISSUE-02** | Security | DNS-rebinding TOCTOU ở Playwright `browser_worker.py` | 🔴 **HIGH** | **`[T-39.2]`** Chốt chặn DNS rebinding browser | Ghim IP đã xác thực hoặc chặn redirect sang IP loopback trong Chromium. |
| **ISSUE-03** | RAG / Embed | FastEmbed ONNX nạp lười gây lag lượt tương tác đầu | 🟡 **MEDIUM** | **`[T-39.3]`** FastEmbed startup warm-up | Bổ sung hàm `warmup()` chạy nền lúc `mulon.main` khởi động. |
| **ISSUE-04** | UI / A11y | 11 nút bấm/hàng tương tác có chiều cao < 44px | 🟡 **MEDIUM** | **`[T-39.4]`** Polish UI Mini App & Touch Zone | Tăng chiều cao touch target ≥44px, dọn 362 style inline, giữ accent `#7C3AED`. |
| **ISSUE-05** | Storage | *[ĐÃ RÚT THEO ERRATA E1]* TTL dọn rác tool-results đã có từ v1.6.5 (`clean_old_tool_results` tại `mulon/context.py:157`, gọi ở `main.py:61`) | ⚪ **RÚT** | *Không mở sub-task* | Đã kiểm chứng code hiện hữu có sẵn cơ chế và test riêng. |
| **ISSUE-06** | API | Định dạng lỗi `/api/*` chưa chuẩn hoá RFC 7807 | 🟡 **MEDIUM** | **`[T-39.5]`** Chuẩn hoá API response contract | Chỉ THÊM field `code`/`detail`, không đổi/bỏ field cũ (Điều kiện 4). |
| **ISSUE-07** | Architecture | `telegram_bot.py` quá lớn (5,086 dòng) ghép nối cao | 🟡 **MEDIUM** | **`[T-39.6]`** Tách tracer-bullets theo ADR-001 | Triển khai từng lát cắt nhỏ có suite xanh, không refactor ồ ạt. |
| **ISSUE-08** | Frontend | Code JS `index.html` 5,454 dòng chưa module hoá | 🟢 **POLISH** | **`[T-39.4]`** (Gộp vào Polish UI) | Tách cấu trúc JS client rõ ràng theo State/Renderer. |
| **ISSUE-09** | UI / Mobile | Thiếu Telegram Haptic Feedback khi bấm duyệt/chuyển tab | 🟢 **POLISH** | **`[T-39.4]`** (Gộp vào Polish UI) | Gọi `Telegram.WebApp.HapticFeedback` khi thao tác. |
| **ISSUE-10** | Gateway | Circuit breaker chia sẻ state giữa các tier model | 🟢 **POLISH** | **`[T-39.3]`** (Gộp vào Model/Gateway) | Tách breaker key theo model tier. |
| **ISSUE-11** | Security | HMAC initData thiếu nonce chống replay trong 3600s | 🟢 **POLISH** | **`[T-39.2]`** (Gộp vào Security) | Ghi nhận chấp nhận rủi ro thấp cho bot cá nhân. |
| **ISSUE-12** | Memory | Composite index cho `memory_facts(valid_to, valid_from)` | 🟢 **POLISH** | **`[T-39.1]`** (Gộp vào DB) | Bằng chứng EXPLAIN QUERY PLAN: SQLite dùng MULTI-INDEX OR (INDEX 1 dùng `idx_facts_validity` cho `valid_to=? AND valid_from<?`, INDEX 2 dùng `idx_facts_active` cho `valid_to>?`). |

---

## 4. BẰNG CHỨNG KIỂM CHỨNG (REALITY CHECKER CERTIFICATION)

`agency-reality-checker` xác nhận:
1. Đã chạy thực tế script Chromium Playwright headless trên máy Mac, xuất thành công 5 ảnh chụp màn hình kiểm chứng tại `docs/audits/renders/`.
2. Đã đối chiếu mã nguồn thực tế, xác nhận chính xác số liệu: 362 inline styles, 11 touch targets <44px, token `#7C3AED`, 89 API routes, 5,086 dòng trong `telegram_bot.py`.
3. Toàn bộ 715/715 tests trên hệ thống hiện tại đều PASS.

*Kết luận*: **Đủ điều kiện đóng Chặng 1 & Chặng 2**, sẵn sàng trình Muse thẩm định báo cáo để mở các Sub-Tasks Chặng 3.
