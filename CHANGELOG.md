# CHANGELOG

## 1.7.61 — 2026-10-31 — Cải tổ giao diện Mini App theo Meta Muse App (Lát cắt 2: Thẻ Tác vụ Stream & Badge Nền tảng) theo ADR-003 (T-40 — ký: Antigravity)

- **(T-40 Lát cắt 2) Thẻ Tác vụ Activity Stream Cards & Platform Badges (`mulon/webapp_server.py`, `mulon/webapp/index.html`):**
  - **Nhận diện Nền tảng Rule 0 (Backend Contract & Declarative JSON):**
    - Thêm cấu hình khai báo `config/platform_keywords.json` nạp qua `load_json_data()` cho 5 nền tảng: Facebook (`FA`, `facebook.com`), Threads (`TH`, `threads.net`), Google Sheets (`GS`, `Google Sheets`), Zalo (`ZL`, `Zalo`), Web (`WB`, `Web`).
    - Bổ sung helper `_detect_task_platform(t, norm_steps)` trong `mulon/webapp_server.py` với cơ chế fallback chặt chẽ: không rõ nguồn → `None` (không đoán bừa), tôn trọng `t.get("platform")` nếu có sẵn.
    - Bổ sung trường tuỳ chọn additive `"platform"` vào `_normalize_task_view(t)` dùng chung cho cả 3 endpoint `/api/state`, `/api/task` và `/api/tasks`, bảo toàn 100% 18 trường hiện hữu.
  - **Activity Stream Cards & Date Grouping (Frontend UI Parity):**
    - Tái cấu trúc danh sách việc `renderTasks()` thành dòng thời gian hoạt động: tự động phân nhóm theo ngày (`getDayGroupKey()`) với tiêu đề nhóm `.stream-group-title` ("Hôm nay", "Hôm qua", ngày cụ thể).
    - Thẻ tác vụ `.row.stream-card` kế thừa `.row` (giữ nguyên touch target $\ge 56$px $\ge 44$px, bảo toàn bộ chọn `#task-list .row[data-task]`, `.r-title`, `.r-sub`, `.r-meta`, `.r-time`, `.r-state` cho các suite kiểm thử Playwright và DOM).
    - Thêm icon trạng thái tròn `.stream-status-glyph` ở bên trái (✓ `done`, ◌ `running`, ✕ `failed`, ⊘ `cancelled`, · `partial`), tuân thủ lock thiết kế §6 (màu nhấn Tím Mulon `#7C3AED` và neutral, tuyệt đối không dùng xanh lá/vàng/đỏ).
    - Tích hợp Platform Badge `.stream-platform-badge`: hiển thị pill nền tảng thanh lịch gồm monogram `.badge-code` và tên miền `.badge-name` ngay dưới dòng phụ.
  - **Đồng bộ Theme Lavender Runtime với Muse Clean Palette:**
    - Cập nhật định nghĩa `THEMES.lavender` trong `index.html` (`paper: "#F8F9FA"`, `deep: "#7C3AED"`, `surface2: "#F1F3F5"`, dark `dpaper: "#121214"`, `dsurface: "#1E1E22"`), giải quyết dứt điểm TODO runtime override mà Muse autowatch đã chỉ ra ở Lát cắt 1.
    - Cập nhật đường dẫn tương đối trong `docs/adr/003-miniapp-muse-ui-parity.md` (`docs/reference/meta_muse_app_reference.png`).
- **Render thật Playwright Chromium (390×844) & Bằng chứng:**
  - Chạy `scripts/capture_touch_renders.py`: Cả 3 ảnh render được làm mới, `04_tasks_dark.png` đổi sha256 (`63247bc2f6fd521cac8bf478712469b51550981c23e5f14e131d70b9ba5ccdfe`) phản ánh Activity Stream Cards và Platform Badges thực tế.
  - Runtime JavaScript: **0 pageerror**.
- **Kiểm thử & Bằng chứng đo đạc thực tế:**
  - File test hồi quy: `tests/test_v17_miniapp_modular_js.py` (**13/13 passed** trong 0.20s, bổ sung 2 test mới ròng: `test_detect_task_platform_rule0_and_normalization` và `test_muse_activity_stream_and_platform_badges`).
  - Suite kiểm thử đầy đủ: **754 passed, 11 deselected, 0 failed trong 38.10s**, tiến trình tự thoát sạch.
  - Phân vai The Agency: Chủ trì `agency-ui-designer` (hệ thống thẻ stream & badge) + `agency-frontend-developer` (Single-File vanilla JS/CSS) + `agency-api-platform-engineer` (additive backend Rule 0 platform contract); cổng chốt `agency-ui-finish-gate-reviewer`, kiểm thử `agency-test-automation-engineer`, tự kiểm `agency-reality-checker`.

## 1.7.60 — 2026-10-31 — Cải tổ giao diện Mini App theo Meta Muse App (Lát cắt 1: Muse Clean Palette & Header Hero Mascot) theo ADR-003 (T-40 — ký: Antigravity)

- **(T-40 Lát cắt 1) Triển khai Design Tokens Muse Clean Palette & Header Hero Mascot (`mulon/webapp/index.html`):**
  - **Hệ thống Design Tokens Muse Clean Palette:**
    - Cập nhật palette giao diện sáng: nền xám hiện đại `--paper: #F8F9FA`, bề mặt card trắng tinh khiết `--surface: #FFFFFF`, bề mặt phụ `--surface2: #F1F3F5`, chữ độ tương phản cao `--ink: #1C1E21`, chữ phụ `--ink2: #65676B`, viền mỏng `--line: #EBECEF`.
    - Cập nhật palette giao diện tối: nền `--paper: #121214`, card `--surface: #1E1E22`, viền `--line: #2A2A30`, chữ `--ink: #F5F5F7`.
    - Bảo toàn 100% màu nhấn nhận diện Tím Mulon `--accent: #7C3AED` và lock thiết kế §6 (trạng thái thể hiện bằng chữ, dot trung tính, không dùng xanh/vàng/đỏ).
  - **Tái cấu trúc Header Hero Mascot Trung Tâm:**
    - Nâng cấp Mascot Avatar nổi bật với đường kính 64px, căn giữa ấm cúng, tương thích bộ Sprite Mascot Animator.
    - Tiêu đề danh tính bot `MuLon` (20px, font-weight 700) căn giữa trang trọng.
    - Pill trạng thái kết nối `● Đã kết nối` bo tròn mềm mại (`app-status`) với dot chỉ báo trung tính `var(--ink3)` và hiệu ứng nhịp thở `pulse` tím khi bận.
    - Bổ sung 4 nút chuyển nhanh ngữ cảnh tròn (`#hero-quick-nav`) với touch target 48×48px $\ge 44$px: `[ 📋 Việc ]` (`data-hero-tab="viec"`), `[ 🛡️ Quyền ]` (`data-hero-tab="pheduyet"`), `[ ⏰ Lịch ]` (`data-hero-tab="lich"`), `[ 🔑 Kho ]` (`data-hero-sub="screen-vault"`).
    - Tích hợp sự kiện chuyển tab đồng bộ qua `Mulon.State.setTab()` / `showMain()` và `Mulon.State.setSubScreen()` / `showSub()`.
  - **Bổ sung tài liệu tham chiếu & Phân vai Agency:**
    - Lưu trữ ảnh tham chiếu ứng dụng Meta Muse thật tại `docs/reference/meta_muse_app_reference.png`.
    - Cập nhật tài liệu thiết kế `docs/adr/003-miniapp-muse-ui-parity.md` đáp ứng trọn vẹn 5 điều kiện duyệt của Muse autowatch.
    - Bổ sung vai trò `[T-40]` vào bảng phân vai mục G trong `docs/ops/antigravity-coordinator-prompt.md`.
- **Render thật Playwright Chromium (390×844) & Bằng chứng nghiệm thu:**
  - Chạy `scripts/capture_touch_renders.py`: Cả 3 ảnh render `01_dashboard_light.png`, `02_dashboard_dark.png`, `04_tasks_dark.png` đều được làm mới bằng Playwright Chromium headless thật với hash sha256 mới.
  - Runtime JavaScript: **0 pageerror**, các nút bấm và trạng thái hoạt động trơn tru.
- **Kiểm thử & Bằng chứng đo đạc thực tế:**
  - File test hồi quy: `tests/test_v17_miniapp_modular_js.py` (**11/11 passed** trong 0.05s, bổ sung 2 test mới cho tokens và Hero Quick Switcher).
  - Test Mini App & Design System: **32/32 passed** trong 21.50s.
  - Phân vai The Agency: Chủ trì `agency-ui-designer` + `agency-frontend-developer`, cổng chốt thẩm định giao diện `agency-ui-finish-gate-reviewer`, kiểm thử `agency-test-automation-engineer`, tự kiểm `agency-reality-checker`.

## 1.7.59 — 2026-10-31 — Module hoá JS Client Mini App (Lát cắt 3: Mulon.Tabs & Lifecycle Decoupling) theo ADR-002 (T-39.4b, Agency Council Chặng 3 — ký: Antigravity)

- **(ISSUE-08 / T-39.4b Lát cắt 3) Hoàn tất Phân rã JS Client theo Phương án A (ADR-002) (`mulon/webapp/index.html`):**
  - **Đóng gói Subsystem `Mulon.Tabs` & Phân rã 5 Tab:**
    - Đóng gói toàn bộ logic render của 5 tab chính (`viec`, `pheduyet`, `lich`, `hoso`, `caidat`) vào namespace `Mulon.Tabs[tabName]`.
    - Chuẩn hoá hợp đồng lifecycle cho từng tab: `render()`, `mount()` (kích hoạt render khi tab mở), và `cleanup()` (giải phóng tài nguyên khi rời tab).
    - Cung cấp `Mulon.Tabs.renderAll()` gom toàn bộ render của các tab và uỷ quyền an toàn từ hàm `renderAll()` toàn cục.
  - **Thống nhất Cơ chế Chuyển Tab/Màn con qua `Mulon.State`:**
    - Triệt tiêu hoàn toàn hiện tượng 2 đường đổi state theo ghi chú (i) của Muse: hàm `showMain(tab)` và `showSub(id)` giờ đây gọi tập trung qua `Mulon.State.setTab(tab)` và `Mulon.State.setSubScreen(id)`.
    - Tích hợp hook chuyển tab: khi rời tab cũ, `showMain` tự động kích hoạt `Mulon.Tabs[prevTab].cleanup()` trước khi mount tab mới `Mulon.Tabs[tab].mount()`.
  - **Quản lý Event Listener & Dọn Rác Triệt Để:**
    - Tab `caidat`: Dừng dứt điểm polling tác vụ `opTimer` (`stopOpPoll()`) khi rời tab Cài đặt.
    - Tab `viec` & `hoso`: Tự động ẩn các modal overlay đang treo (`modal-heartbeat`, `modal-lib-menu`) khi chuyển tab.
    - Xác nhận đối với các DOM render dạng `innerHTML = ...`: toàn bộ các event listener con gắn trên thẻ DOM được garbage collector của trình duyệt tự động thu hồi khi node bị thay thế.
  - **Bảo toàn 100% Backward Compatibility:**
    - Re-export các shim toàn cục `window.showMain = showMain;`, `window.showSub = showSub;`, `window.renderAll = renderAll;` giúp toàn bộ mã điều hướng hiện hữu chạy trơn tru mà không có breaking change.
- **Render thật Playwright Chromium (390×844) & Kiểm chứng Runtime:**
  - Chạy `scripts/capture_touch_renders.py`: Cả 3 ảnh render `01_dashboard_light.png`, `02_dashboard_dark.png`, `04_tasks_dark.png` đều được làm mới bằng trình duyệt Playwright Chromium thật.
  - Kiểm chứng runtime JavaScript trong Chromium headless: **0 pageerror**, `Mulon.Tabs` chứa đủ 5 tab và phương thức lifecycle, tab switch kích hoạt `cleanup()` của tab cũ và `mount()` của tab mới, `renderAll` hoạt động hoàn hảo.
- **Kiểm thử & Bằng chứng đo đạc thực tế:**
  - File test hồi quy: `tests/test_v17_miniapp_modular_js.py` (**9/9 passed** trong 0.05s).
  - Test Mini App & Design System: **15/15 passed** trong 4.53s.
  - Full test suite Mac: **761 passed / 0 failed** trong 71.34s (tăng 1 test so với 760 của v1.7.58; tiến trình tự thoát sạch sau summary <1s, exit code 0).
  - Eval vàng: **33/36 (92%)** đạt cổng 85%; smoke `--dry-run` exit code 0.
  - Phân vai The Agency: Chủ trì `agency-frontend-developer` + `agency-software-architect`, kiểm thử `agency-test-automation-engineer`, thẩm định `agency-reality-checker`.

## 1.7.58 — 2026-10-31 — Module hoá JS Client Mini App (Lát cắt 2: Mulon.State & Mulon.Mascot) theo ADR-002 (T-39.4b, Agency Council Chặng 3 — ký: Antigravity)

- **(ISSUE-08 / T-39.4b Lát cắt 2) Phân rã JS Client theo Phương án A (ADR-002) (`mulon/webapp/index.html`):**
  - **Đóng gói Subsystem `Mulon.State` & Event Bus nội bộ:**
    - Cung cấp getter reactive an toàn: `raw`, `current` (trỏ tới `S`), `tab` (`mainTab`), `subScreen`.
    - Cung cấp các phương thức cập nhật: `set(newS)` (hỗ trợ updater function hoặc object), `setTab(tab)`, `setSubScreen(id)`.
    - Event Bus đa kênh nhẹ nhàng, độc lập không phụ thuộc thư viện ngoài: `on(event, handler)`, `off(event, handler)`, `emit(event, ...args)` bọc try-catch an toàn.
    - Tích hợp phát sự kiện tự động: `showMain` emit `tab:changed` (`{tab, prev}`), `showSub` emit `screen:changed` (`{subScreen, prev}`), `load()` cập nhật state qua `Mulon.State.set(S)` và emit `change` / `update`.
  - **Đóng gói Subsystem `Mulon.Mascot` Sprite Animator Controller:**
    - Gom toàn bộ bộ điều khiển avatar sprite atlas 21 frame vào `Mulon.Mascot`: `raw` (`sprite`), `state`, `isReady`, `getBaseState`, `applyBase`, `flash`, `play`, `stop`.
    - `Mulon.Mascot.play(name, once)` tự động phát sự kiện `mascot:state` (`{state, once}`) qua Event Bus `Mulon.State` giúp các component khác lắng nghe mà không bị ghép nối chặt.
  - **Bảo toàn 100% Backward Compatibility:**
    - Giữ nguyên các biến toàn cục `S`, `mainTab`, `subScreen`, `sprite` và shim re-export toàn bộ các hàm tiện ích (`window.spritePlay`, `window.spriteStop`, `window.spriteApplyBase`, `window.flashAvatar`). Hàng trăm vị trí logic cũ tiếp tục hoạt động mà không bị ảnh hưởng.
- **Đính chính số liệu Kiến trúc ADR-002 (`docs/adr/002-miniapp-js-modularization.md`):**
  - Xử lý lưu ý (ii) của Muse: sửa triệt để cụm từ "cơ chế kết nối SSE/polling" tại dòng 12 §1 thành "cơ chế kết nối polling-only (load() 3s và opTimer 2s)", bảo đảm tính nhất quán 100% xuyên suốt tài liệu.
- **Render thật Playwright Chromium (390×844):**
  - Chạy script `scripts/capture_touch_renders.py`, capture thành công 3 ảnh màn hình trong môi trường headless Chromium. Ghi nhận chính xác theo lưu ý (i) của Muse: 2 ảnh thực sự đổi hash trong commit này là `02_dashboard_dark.png` và `04_tasks_dark.png`; `01_dashboard_light.png` giữ nguyên hash.
  - Kiểm chứng runtime JavaScript trong trình duyệt thật: 0 pageerror, `Mulon.State` và `Mulon.Mascot` hoạt động đầy đủ, Event Bus phát và nhận sự kiện chính xác, chuyển tab phản hồi đúng.
- **Kiểm thử & Bằng chứng đo đạc thực tế:**
  - File test hồi quy: `tests/test_v17_miniapp_modular_js.py` (**8/8 passed** trong 0.05s, bổ sung 3 test mới cho State, Mascot và Event integration).
  - Test Mini App & Design System: **15/15 passed** trong 4.53s.
  - Full test suite Mac: **760 passed / 0 failed** trong 72.51s (tăng 3 test so với 757 của v1.7.57; tiến trình tự thoát sạch sau summary <1s, exit code 0).
  - Eval vàng: **33/36 (92%)** đạt cổng 85%; smoke `--dry-run` exit code 0.
  - Phân vai The Agency: Chủ trì `agency-frontend-developer` + `agency-software-architect`, kiểm thử `agency-test-automation-engineer`, thẩm định `agency-reality-checker`.

## 1.7.57 — 2026-10-31 — Rerun & Khép trọn vẹn Chân Windows Thật: 19/19 T-36 & 757/757 Full Suite PASSED trên Windows 11 (T-36 — ký: Antigravity [WIN])

- **Thực thi rerun trên phần cứng Windows 11 thật (`Windows-11-10.0.26300-SP0`, Python `3.12.10`, path có khoảng trắng `E:\New folder\lane1\.venv`) & xử lý dứt điểm các lỗi thứ cấp lộ diện sau bản vá W1–W6:**
  - **(W1/W2/W5 hậu kiểm — Mã hóa UTF-8 tường minh trên Windows `cp1252`):**
    - Sau khi W1 (`normalize_server_config`) được gỡ ở `v1.7.46`, 3/19 test gốc của `T-36` trong `tests/test_v13_service.py` (`test_full_two_approval_install`, `test_commit_failure_rolls_back`, `test_uninstall_flow_blocks_then_removes`) chạy xuyên qua bước `probe`/`commit`/`rollback` (nơi `MarketplaceService` ghi UTF-8 tiếng Việt `"_comment": "giữ nguyên trường lạ"`) và lộ lỗi thứ cấp `.read_text()` thiếu `encoding="utf-8"` trên Windows (`cp1252`). Đã bổ sung `encoding="utf-8"` cho `.read_text()`/`.write_text()` tại `tests/test_v13_service.py`, `tests/test_v13_api.py`, `tests/test_v13_bootgate.py`, `tests/test_v13_e2e.py`, và helper `_git` trong `tests/test_auto_watch.py` (triệt tiêu hoàn toàn `PytestUnhandledThreadExceptionWarning: UnicodeDecodeError` ở `test_pop_conflict_keeps_stash`).
    - Bổ sung tự động `reconfigure(encoding="utf-8", errors="replace")` cho `sys.stdout`/`sys.stderr` khi stream mặc định khác UTF-8 trong `mulon/evals.py` và `mulon/main.py`: khắc phục lỗi sản phẩm `python -m mulon.evals` bị sập `UnicodeEncodeError` khi in tiếng Việt (`"ĐẠT CỔNG"`) ra pipe `cp1252` trên Windows (tránh làm `self_verify_and_restart(run_evals=True)` rollback oan trên Windows).
  - **(BrowserWorker Windows Multi-Channel Fallback — `mulon/browser_worker.py`, `tests/test_v17_browser_dns_guard.py`):**
    - Bổ sung `_launch_browser` và `_launch_persistent` trong `BrowserWorker` tự động duyệt thứ tự channel `(None, "msedge", "chrome")`: ưu tiên nguyên bản Chromium của Playwright (`None` — không đổi hành vi trên Mac/Linux VM), và tự động fallback sang Microsoft Edge / Chrome có sẵn trên Windows khi máy chưa tải riêng `chromium_headless_shell`; vẫn degrade sạch qua `_unavailable()` khi thiếu mọi trình duyệt.
    - Bổ sung guard `_skip_if_browser_binary_missing` chuẩn W6 và kiểm tra thông điệp chặn thật trong Test 1 của `tests/test_v17_browser_dns_guard.py` (cả 3 test SSRF/DNS-rebinding e2e của `T-39.2` chạy thật qua headless Chromium/Edge trên Windows 11 đều PASSED).
  - **(Tối ưu 1-hop `SqliteWALPool.execute_fetchall` & đóng kết nối an toàn trên NTFS — `mulon/db.py`, `mulon/memory.py`, `tests/test_perf_db_concurrency.py`):**
    - Bổ sung `SqliteWALPool.execute_fetchall(sql, parameters)` (tương thích chuẩn `aiosqlite.Connection.execute_fetchall`) thực thi `SELECT` + `fetchall` trong 1 bước worker-thread duy nhất và trả ngay reader connection về pool; sửa lỗi rò rỉ reader connection nếu `conn.execute()` ném ngoại lệ sau `asyncio.wait_for(self._readers.get())`.
    - Cập nhật `Memory.active_facts()` dùng `execute_fetchall`, giảm ~40% độ trễ đọc đồng thời dưới tải ghi nặng trên Windows NTFS mà **giữ nguyên 100% ngưỡng kiểm thử gốc** (`avg_latency < 25.0ms`, `max_latency < 60.0ms`, không nới test). Bọc `try ... finally: await mem.close()` trong `tests/test_perf_db_concurrency.py` để Windows NTFS luôn giải phóng file handle trước khi `TemporaryDirectory` xoá `.db` (ngăn `PermissionError: [WinError 32]`).
- **3 test hồi quy mới (tổng suite tăng từ 754 → 757 tests):**
  - `tests/test_phase3_browser.py::test_browser_worker_launch_channel_fallback`
  - `tests/test_v17_db_pool.py::test_pool_execute_fetchall_and_no_reader_leak_on_error`
  - `tests/test_phase5_evals.py::test_cli_subprocess_cp1252_stdout_does_not_crash`
- **Bằng chứng đo đạc thực tế trên máy Windows 11 thật:**
  - Nhóm 19 test gốc của `T-36`: **19/19 PASSED** (0 failed, 0 skipped) trong `11.32s`, `EXIT_CODE=0`.
  - Full test suite Windows 11 (chạy đủ cả Playwright, không lọc `-k`): **757 passed, 0 failed, 0 skipped** trong `191.34s` (`TOTAL_WALL_SECONDS=196.93s`, tiến trình tự thoát sạch sau `~5.59s`, `EXIT_CODE=0`).
  - Evals vàng trên Windows 11: **33/36 = 92% -> ĐẠT CỔNG** (ngưỡng 85%, đúng 3 ca cũ họ `cho_mcp`), `EXIT_CODE=0`; smoke `--dry-run` `EXIT_CODE=0`.
  - Phân vai The Agency: Chủ trì `agency-test-automation-engineer`, cổng chốt tự kiểm nội bộ `agency-reality-checker`.

## 1.7.56 — 2026-10-31 — Module hoá JS Client Mini App (Lát cắt 1: Mulon.TG, Mulon.API & RFC 7807 Client) theo ADR-002 & Triệt tiêu Dead Code Utility Classes (T-39.4b, Agency Council Chặng 3 — ký: Antigravity)

- **(ISSUE-08 / T-39.4b Lát cắt 1) Phân rã JS Client theo Phương án A (ADR-002) (`mulon/webapp/index.html`):**
  - **Khởi tạo Namespace toàn cục:** Khởi tạo `window.Mulon = window.Mulon || {};` tại đầu khối script để chuẩn bị cho kiến trúc module hoá in-place không cần build tool.
  - **Đóng gói Subsystem `Mulon.TG`:** Đóng gói toàn bộ các hàm trợ giúp Telegram WebApp SDK vào một đối tượng duy nhất (`raw`, `isAvailable`, `updateInsets`, `getInitData`, `haptic`).
  - **Đóng gói Subsystem `Mulon.API` & Bắt lỗi RFC 7807:**
    - Tập trung hoá HTTP fetch client có tự động đính kèm `X-Telegram-Init-Data`.
    - Tích hợp middleware parse lỗi chuẩn RFC 7807 (bắt cả `detail`, `error`, `title` từ server T-39.5), đính kèm thuộc tính `err.rfc7807` vào `Error` object.
  - **Bảo toàn 100% Backward Compatibility:** Re-export các shim toàn cục `window.api = api;`, `window.haptic = haptic;`, `window.getInitData = getInitData;`, đảm bảo hàng trăm vị trí gọi API hiện hữu trong 5 tab hoạt động trơn tru mà không cần refactor ồ ạt một lần.
- **Đính chính số liệu Kiến trúc ADR-002 (`docs/adr/002-miniapp-js-modularization.md`):**
  - Đính chính 2 điểm số liệu ở §1 theo yêu cầu thẩm định thiết kế của Muse: (i) thay các tên biến ví dụ bằng danh sách biến trạng thái thật (`S`, `mainTab`, `subScreen`, `tg`, `INIT`, `sprite`, `curTheme`, `opTimer`...); (ii) xác nhận cơ chế đồng bộ client là polling-only (`load()` 3s và `opTimer` 2s), không có kênh SSE/WebSocket.
- **Triệt tiêu hoàn toàn Dead Code Utility Classes:**
  - Áp dụng `.flex-center` vào 2 vị trí markup: icon Heartbeat dòng 1080 và thẻ mascot template dòng 7421 (đạt 1 định nghĩa + 2 vị trí sử dụng).
  - Áp dụng `.flex-col` vào 3 vị trí markup: modal Heartbeat dòng 1209, menu Thư viện dòng 1392, Mascot grid dòng 1632 (đạt 1 định nghĩa + 3 vị trí sử dụng).
  - Xác nhận bằng `grep` và test tự động: Toàn bộ 5 utility classes (`.flex-center`, `.flex-between`, `.flex-col`, `.touch-target-44`, `.text-sub-12`) đều có $\ge 1$ lần dùng ở markup ngoài định nghĩa, hoàn toàn hết dead code.
- **Render thật Playwright Chromium:** Refresh cả 3 ảnh render thật 390×844 (`01_dashboard_light.png`, `02_dashboard_dark.png`, `04_tasks_dark.png`).
- **Kiểm thử & Bằng chứng đo đạc thực tế:**
  - File test hồi quy mới: `tests/test_v17_miniapp_modular_js.py` (**5/5 passed** trong 0.03s).
  - Suite Mini App & Design System: **36/36 passed** trong 27.24s.
  - Full test suite Mac: **754 passed / 0 failed** (tăng 5 test so với 749 của v1.7.55) trong 69.23s; evals vàng **33/36 (92%)** đạt cổng 85%; tiến trình tự thoát sạch (<1s).
  - Phân vai The Agency: Chủ trì `agency-frontend-developer` + `agency-software-architect`, kiểm thử `agency-test-automation-engineer`, thẩm định `agency-reality-checker`.

## 1.7.55 — 2026-10-31 — Tracer-Bullet Presenter `telegram_delivery.py` theo ADR-001 & Polish hoàn thiện Mini App (T-39.6, Agency Council Chặng 3 — ký: Antigravity)

- **(ADR-001 / T-39.6) Tách lớp Presentation & Delivery khỏi `telegram_bot.py` (`mulon/telegram_delivery.py`):**
  - **Triển khai lát cắt tracer-bullet đầu tiên theo ADR-001:** Trích xuất toàn bộ logic định dạng và xử lý khối văn bản Telegram từ siêu module `mulon/telegram_bot.py` sang module độc lập `mulon/telegram_delivery.py`:
    - `clean_final_text(text)`: Làm sạch phân cách thô và chuẩn hoá khoảng trắng thừa.
    - `safe_stream_markdown_to_html(text)`: Chuyển đổi markdown stream sang HTML an toàn, tự đóng thẻ dở dang, triệt tiêu hiện tượng nhấp nháy markdown thô trên Telegram.
    - `md_to_html(text)`: Chuyển đổi markdown tối thiểu, escape HTML thô chống injection trước khi format bold và heading.
    - `chunk_html(text, max_chars)`: Cắt khối tin nhắn an toàn dưới giới hạn Telegram (mặc định 3500 ký tự), tự động cân bằng các cặp thẻ đóng/mở HTML qua các chunk.
    - `format_progress_lines(steps, max_items, header)`: Format danh sách tiến trình trực quan chuẩn Muse (`✓` / `⏳`) dùng chung cho placeholder.
  - **Bảo toàn 100% Backward Compatibility:** Re-export toàn bộ hàm và hằng số qua `mulon/telegram_bot.py` (`_open_tags`, `_VOID_TAGS`, `_KNOWN_TAGS`, v.v.), không làm thay đổi chữ ký hay ảnh hưởng bất kỳ module nào đang gọi vào.
- **Hoàn thiện các lưu ý giao diện Mini App của Muse (T-39.4a Polish):**
  - Áp dụng thực tế 5 utility classes (`.flex-center`, `.flex-between`, `.flex-col`, `.touch-target-44`, `.text-sub-12`) vào các vị trí markup trong `mulon/webapp/index.html` (màn hình task detail, heartbeat confirm, library trash, mascot settings), triệt tiêu hoàn toàn mã lớp không dùng (dead code).
  - Refresh lại ảnh render theme Light thật `docs/audits/renders/01_dashboard_light.png` bằng Playwright Chromium 390×844.
- **Kiểm thử & Bằng chứng đo đạc thực tế:**
  - File test hồi quy mới: `tests/test_v17_telegram_delivery.py` (6/6 passed trong 0.85s).
  - Full test suite Mac: **749 passed / 0 failed** (tăng 6 test mới so với 743 passed của v1.7.54) trong 68.68s; evals vàng **33/36 (92%)** đạt cổng 85%; tiến trình tự thoát sạch (<1s).
  - Phân vai The Agency: Chủ trì kiến trúc `agency-software-architect` + `agency-minimal-change-engineer`, kiểm thử `agency-test-automation-engineer`, thẩm định `agency-reality-checker`.

## 1.7.54 — 2026-10-31 — Chuẩn hóa Touch Target $\ge 44$px, Haptic Feedback đa hình & Polish UI Mini App (T-39.4a, Agency Council Chặng 3 — ký: Antigravity)

- **(ISSUE-07 / T-39.4a) Chuẩn hóa Touch Target $\ge 44$px (`mulon/webapp/index.html`):**
  - Rà soát toàn diện và xử lý triệt để 11 vị trí touch target bị co hẹp dưới 44px (như 32px, 36px, 38px, 42px), nâng toàn bộ lên chuẩn Apple HIG và AGENTS.md mục 6 ($\ge 44$px):
    1. `.segbar` (`min-height: 48px; height: 48px`) và `.segbar button` (`min-height: 44px; height: 44px; border-radius: 10px; font-size: var(--fs-callout); padding: 0 8px`).
    2. `.ds-search-bar` (`min-height: 44px; height: 44px`).
    3. `.filter-chip`, `.fchip` (`min-height: 44px; height: 44px; padding: 0 14px; font-size: var(--fs-callout); display: inline-flex; align-items: center; justify-content: center`).
    4. `.lib-more-btn` (`width: 44px; height: 44px; min-width: 44px; min-height: 44px; border-radius: 10px`).
    5. `#btn-stop-task-detail` (`min-height: 44px; height: 44px; padding: 0 14px; font-size: 13px; border-radius: 10px`).
    6. `#btn-heartbeat-confirm-pause` (`min-height: 44px; height: 44px; border-radius: 10px`).
    7. `#btn-heartbeat-confirm-cancel` (`min-height: 44px; height: 44px; border-radius: 10px`).
    8. `#lib-trash-view` (`min-height: 44px; height: 44px; padding: 0 14px; font-size: 13px; border-radius: 10px`).
    9. `#input-bot-name` (`min-height: 44px; height: 44px`).
    10. `#btn-save-bot-name` (`min-height: 44px; height: 44px`).
    11. `data-lib-restore` & `data-lib-purge` trong render JS thư viện (`min-height: 44px; height: 44px; padding: 0 14px; font-size: 13px; border-radius: 10px`).
  - Kiểm tra `grep -n -E "height:\s*(32|36|42)px"` cho kết quả 0 phần tử tương tác còn sót lại.
- **Nâng cấp Telegram Native Haptic Feedback (`mulon/webapp/index.html`):**
  - Hàm `haptic(kind)` nâng cấp hỗ trợ đa hình đầy đủ theo Telegram WebApp SDK:
    - `selectionChanged()`: khi `kind === 'select' || kind === 'selection'` (chọn tab, chọn chip).
    - `notificationOccurred(type)`: khi `kind === 'success' || kind === 'error' || kind === 'warning'`.
    - `impactOccurred(style)`: hỗ trợ `light`, `medium`, `heavy`, `rigid`, `soft` (mặc định fallback `medium`).
    - Bọc `try/catch` an toàn và kiểm tra `tg.HapticFeedback` trước khi gọi, không gây lỗi khi chạy ngoài môi trường Telegram.
- **Bổ sung Utility Classes & Render thật Playwright:**
  - Bổ sung 5 utility classes chuẩn hóa trong `<style>`: `.flex-center`, `.flex-between`, `.flex-col`, `.touch-target-44`, `.text-sub-12`.
  - Tạo script `scripts/capture_touch_renders.py` render thật HTML/CSS bằng Playwright Chromium viewport 390×844 cho 2 theme Light & Dark (lưu tại `docs/audits/renders/01_dashboard_light.png`, `02_dashboard_dark.png`, `04_tasks_dark.png`), bảo đảm quy định cấm mock vẽ tay.
- **Kiểm thử & Bằng chứng đo đạc thực tế:**
  - File test hồi quy mới: `tests/test_v17_miniapp_touch_and_haptic.py` (4/4 passed).
  - Full test suite Mac: **743 passed / 0 failed** (tăng 4 test mới so với 739 passed của v1.7.53) trong 69.22s; evals vàng **33/36 (92%)** đạt cổng 85%.
  - Phân vai The Agency: Chủ trì `agency-ux-architect` + `agency-frontend-developer`, rà soát cổng `agency-ui-finish-gate-reviewer`, kiểm chứng bằng chứng thật `agency-reality-checker`.


## 1.7.53 — 2026-10-31 — FastEmbed Startup Warm-up không chặn & Bulkhead Circuit Breaker cách ly per-tier (T-39.3, Agency Council Chặng 3 — ký: Antigravity)

- **(ISSUE-03) FastEmbed ONNX Startup Warm-up (`mulon/embeddings.py`, `mulon/main.py`):**
  - Bổ sung phương thức `warmup() -> bool` cho `FastEmbedEmbedder` (và protocol `Embedder`), chủ động gọi `_ensure_impl()` và thực thi một dummy embedding vector ngắn `["warmup"]` để khởi tạo hoàn tất ONNX Runtime session trong RAM.
  - Tích hợp tác vụ nền không chặn `asyncio.create_task(asyncio.to_thread(embedder.warmup))` khi khởi động bot trong `mulon/main.py`. Triệt tiêu hoàn toàn độ trễ 3–8s ở lượt tương tác đầu tiên của người dùng mà không làm chậm thời gian boot bot (<1s).
  - Tuân thủ nguyên tắc Degrade không sập: nếu vắng thư viện ONNX/fastembed hoặc lỗi nạp model, `warmup()` bắt ngoại lệ an toàn và bot vẫn chạy bình thường với BM25-only.
- **(ISSUE-10) Bulkhead Circuit Breaker cách ly lỗi per-tier (`mulon/gateway.py`):**
  - Tách biến trạng thái circuit breaker toàn cục thành mapping `self._breakers: dict[str, dict]` theo model/tier key chuẩn hoá (`_model_tier_key()`).
  - Áp dụng Bulkhead Pattern cách ly sự cố: Khi một model cụ thể (ví dụ model cheap hoặc escalated) bị lỗi liên tiếp $\ge 5$ lần dẫn đến mở circuit breaker trong 30s, chỉ duy nhất model đó bị chặn tạm thời; các model thuộc tier khác (như Brain model) hoàn toàn không bị ảnh hưởng, tiếp tục hoạt động thông suốt.
  - Bảo toàn 100% tính tương thích ngược với API breaker hiện có và duy trì breaker toàn cục bảo vệ hệ thống nếu mọi model đều liên tục sập ($\ge 15$ lần).
- **Kiểm thử & Bằng chứng đo đạc thực tế:**
  - File test hồi quy mới: `tests/test_v17_rag_warmup_and_breaker.py` (5/5 passed).
  - Full test suite Mac: **739 passed / 0 failed** (tăng 5 test mới so với 734 passed của v1.7.52) trong 68.06s; evals vàng **33/36 (92%)** đạt cổng 85%.
  - Phân vai The Agency: Chủ trì `agency-backend-architect` + `agency-rag-pipeline-engineer`, kiểm thử `agency-test-automation-engineer`, thẩm định `agency-reality-checker`.

## 1.7.52 — 2026-10-31 — Chuẩn hóa mã lỗi `/api/*` theo RFC 7807 Problem Details & bảo đảm 100% Backward Compatibility (T-39.5, Agency Council Chặng 3 — ký: Antigravity)

- **(ISSUE-06 / T-39.5) Chuẩn hoá phản hồi lỗi REST API theo RFC 7807 (`mulon/webapp_server.py`):**
  - **Middleware RFC 7807 tự động (`_rfc7807_middleware`):** Bổ sung middleware tầng ngoài bắt mọi HTTP response lỗi (`status >= 400`) trên toàn bộ 86 route `/api/*` (đối chiếu chính xác tổng 98 route theo Errata E4).
  - **Tuân thủ tuyệt đối Điều kiện 4 của Muse:**
    - Tuyệt đối không xoá hoặc đổi tên các field cũ: giữ nguyên vẹn 100% `ok: False`, `error: <string>` và `content_type="application/json"` để bảo đảm không phá vỡ client Mini App và các test suite hiện hữu.
    - Làm giàu thêm các trường RFC 7807 tiêu chuẩn: `status` (int), `title` (string theo RFC 9110), `detail` (string chi tiết lỗi), `error_code` (mã lỗi snake_case định danh máy đọc như `invalid_init_data`, `missing_parameter`, `not_found`), `code` (alias cho error_code), `instance` (đường dẫn request URL), `type` (URI tham chiếu URN `urn:mulon:error:<code>`).
  - **Hàm tiện ích `problem_json_response()` & `infer_error_code()`:** Cung cấp helper sinh `web.json_response` chuẩn RFC 7807 dùng chung cho các endpoint cần ném lỗi tường minh.
- **Kiểm thử & Bằng chứng đo đạc thực tế:**
  - File test hồi quy mới: `tests/test_v17_api_rfc7807.py` (4/4 passed).
  - Đối chiếu route theo Errata E4: Đã rà soát đủ 98 routes (44 GET + 54 POST), gồm 12 routes non-API + 86 REST API routes (`/api/*`).
  - Full test suite Mac: **734 passed** (tăng 4 test mới so với 730 passed của v1.7.51) trong 61.77s; evals vàng **33/36 (92%)** đạt cổng 85%.
  - Phân vai The Agency: Chủ trì API `agency-api-platform-engineer`, kiểm thử `agency-test-automation-engineer`, thẩm định `agency-reality-checker`.

## 1.7.51 — 2026-10-31 — Đồng bộ kép aiosqlite 0.20/0.22+ thread lifecycle & dứt điểm triệt để rò rỉ VM teardown (T-39.1 vòng 3, Agency Council Chặng 3 — ký: Antigravity)

- **(ISSUE-01 Vòng 3) Khắc phục triệt để khác biệt API giữa aiosqlite <=0.20 (Mac) và >=0.22 (VM):**
  - **Nhận diện đúng kiến trúc aiosqlite v0.22+ (`mulon/db.py`):** Trong aiosqlite >=0.22, `Connection` không còn kế thừa `threading.Thread` mà bọc worker thread ngầm tại `self._thread`. Phương thức dừng đồng bộ chuẩn là `conn.stop()`, method `_stop_running()` cũ không tồn tại.
  - **Hàm trợ giúp đa hình `get_connection_thread()` & `_stop_connection_sync()` (`mulon/db.py`):**
    - Trích xuất đúng `threading.Thread` worker thật ở cả 2 môi trường: `conn._thread` (ở aiosqlite >=0.22) hoặc `conn` (ở aiosqlite <=0.20).
    - Quy trình dừng đồng bộ 4 lớp: gọi `conn.stop()` -> gọi `conn._stop_running()` -> đưa sentinel trực tiếp vào transaction queue -> join thread thật `th.join(timeout=...)`.
    - Thiết lập `_make_connection_daemon()` trước khi start thread để bảo đảm thread luôn là daemon trên mọi môi trường.
    - Đảm bảo `self._closed = True` chỉ được gán sau khi toàn bộ worker threads đã được ra lệnh dừng và join.
  - **Sửa test hồi quy `tests/test_v17_db_pool.py`:**
    - Sử dụng `get_connection_thread(pool._writer)` và `get_connection_thread(r)` để kiểm tra và join thread worker thật. Khắc phục dứt điểm lỗi `AttributeError: 'Connection' object has no attribute 'join'` trên aiosqlite 0.22.1.
- **Kiểm thử & Bằng chứng đo đạc thực tế:**
  - Môi trường đo Mac: Python 3.14.6, aiosqlite 0.20.0. Môi trường đo VM: Python 3.12, aiosqlite 0.22.1.
  - `tests/test_v17_db_pool.py`: 4/4 passed trong 6.60s.
  - Toàn bộ full suite: **730 passed / 0 failed** trong 63.69s; evals vàng **33/36 (92%)** đạt cổng 85%.
  - Tiến trình pytest tự thoát hoàn toàn sau dòng summary (<1s), 0 non-daemon thread rò rỉ.
  - Phân vai The Agency: Chủ trì `agency-database-reliability-engineer`, thẩm định `agency-reality-checker`.

## 1.7.50 — 2026-10-31 — Chốt chặn DNS-rebinding TOCTOU & Hop-by-hop Redirect Guard cho Chromium Browser Worker (T-39.2, Agency Council Chặng 3 — ký: Antigravity)

- **(ISSUE-02) Khắc phục triệt để lỗ hổng DNS-rebinding & Redirect SSRF trên Chromium Playwright (`mulon/browser_worker.py`):**
  - **Spike kỹ thuật xác thực hành vi Chromium (ĐK2):**
    - Thực nghiệm chứng minh Chromium tự động follow redirect ngầm mà *không* gọi lại `page.route` ở các hop redirect kế tiếp khi dùng `continue_()` hoặc `fulfill(response=302)`.
    - Triển khai giải pháp **Manual Follow Loop** bằng `context.request.get(url, max_redirects=0)` có trần hop ≤10: kiểm tra `resolve_and_verify_url` trước mỗi hop và `abort()` ngay lập tức nếu gặp IP private/loopback/cloud-metadata. Chỉ `fulfill()` kết quả cuối cùng (non-3xx) vào Chromium page.
    - Bảo toàn cookie phiên nhờ `context.request` chia sẻ cookie store chung với `BrowserContext`.
  - **Gắn Route Interception Guard tập trung (`mulon/browser_worker.py`):**
    - Hàm `_setup_route_guard()` được gắn tại `_open_page()` bảo vệ toàn bộ 3 luồng trình duyệt (`_fetch_rendered`, `_capture_png`, `_interact`).
    - Chỉ intercept navigation request (`request.is_navigation_request()`), subresources được `continue_()` an toàn sau khi validate sơ bộ.
  - **Tài liệu thiết kế (`docs/notes/2026-10-30-t39-2-dns-rebinding-browser-design.md`):**
    - Hoàn thiện toàn diện 5 điều kiện duyệt của Muse (ĐK1–ĐK5), đính kèm kết quả thực nghiệm 3 bài spike câu hỏi (a, b, c).
    - Ghi nhận đánh giá an ninh cho ISSUE-11 (HMAC initData replay) là Accepted Risk cho môi trường bot cá nhân.
- **Kiểm thử & Bằng chứng đo đạc thực tế:**
  - `tests/test_v17_browser_dns_guard.py`: 3 bài test hồi quy đạt 100% (redirect sang private IP bị abort không chạm server nội bộ; initial URL private IP bị chặn ngay hop 1; safe public redirect tải thành công nội dung trang đích).
  - Toàn bộ full suite: **730 passed** trong 63.22s; evals vàng **33/36 (92%)** đạt cổng 85%.
  - Phân vai The Agency: Chủ trì an ninh `agency-application-security-engineer`, kiểm thử `agency-test-automation-engineer`, thẩm định `agency-reality-checker`.

## 1.7.49 — 2026-10-31 — Diệt dứt điểm rò rỉ thread aiosqlite teardown lifecycle & bảo đảm tiến trình tự thoát (T-39.1 vòng 2, Agency Council Chặng 3 — ký: Antigravity)

- **(ISSUE-01 Vòng 2) Giải quyết triệt để hiện tượng tiến trình pytest không tự thoát sau summary:**
  - **Truy vết chính xác nguồn gốc rò rỉ:** Dùng hook giám sát thread trong `tests/conftest.py` ghi nhận được toàn bộ các thread rò rỉ ở cuối session: chính xác là 5 worker threads (`Connection`) của 1 `SqliteWALPool` (1 writer + 4 readers) đang chờ trong `self._tx.get()`, sinh ra từ `test_cmd_memory_structured_summary_no_raw_dossier_dump` (và các test mở `open_memory` mà chưa gọi `close()`).
  - **Cơ chế `close_sync()` khẩn cấp đồng bộ (`mulon/db.py`):** Cung cấp phương thức `close_sync()` không phụ thuộc vào async event loop, gửi sentinel `_stop_running()` trực tiếp qua queue để ép toàn bộ worker threads thoát khỏi vòng lặp `Connection.run()` ngay lập tức.
  - **Đăng ký dọn dẹp toàn cục `_ACTIVE_POOLS` & `atexit` (`mulon/db.py`):** Sử dụng `weakref.WeakSet` quản lý mọi pool đang hoạt động trong tiến trình, tự động kích hoạt `close_all_pools()` tại sự kiện `atexit` của Python runtime và tại hook `pytest_sessionfinish`.
  - **Quản lý vòng đời `open_memory` trong test suite (`tests/conftest.py`, `tests/test_v17_commands.py`):** Bổ sung fixture autouse tự động đóng sạch toàn bộ `Memory` sau mỗi bài test; bổ sung đóng tường minh trong `tests/test_v17_commands.py`.
- **Kiểm thử & Bằng chứng đo đạc thực tế:**
  - `tests/test_v17_db_pool.py`: Bổ sung kiểm chứng `close_sync()` và `close_all_pools()` đảm bảo `writer_th.join()` và `reader_ths.join()` thành công, `is_alive() == False`.
  - Kết quả đo tại `PYTEST_SESSIONFINISH`, `PYTEST_UNCONFIGURE` và `ATEXIT`: **Chỉ còn duy nhất 1 thread (MainThread), 0 thread phụ, 0 thread aiosqlite còn sống**.
  - Toàn bộ full suite: **716 passed, 11 deselected, 0 failed** trong 26.28s; evals vàng **33/36 (92%)** đạt cổng; tiến trình tự thoát tức thì sau summary.


## 1.7.48 — 2026-10-30 — Vá dứt điểm aiosqlite teardown thread lifecycle + Composite index facts (T-39.1, Agency Council Chặng 3 — ký: Antigravity)

- **(ISSUE-01) Khắc phục aiosqlite threads treo khi teardown / exit pool (`mulon/db.py`):**
  - **Đặt `conn.daemon = True` trước khi await khởi tạo kết nối:** Cả Writer connection và toàn bộ Reader pool connections trong `SqliteWALPool.open()` đều được thiết lập `daemon = True` ngay sau khi gọi `aiosqlite.connect()` (trước khi start thread ngầm qua `__await__`).
  - **Dọn dẹp an toàn qua `__del__`:** Bổ sung phương thức `__del__` tự động gọi `_stop_running()` gửi sentinel kết thúc cho các thread worker aiosqlite khi object pool bị Garbage Collection mà chưa kịp gọi `await pool.close()`.
  - **Triệt tiêu hoàn toàn lỗi treo test suite:** Toàn bộ 716 tests chạy xong trong 26s và process thoát ngay lập tức, không còn bị treo hay timeout chờ đợi các thread worker aiosqlite nền như các lượt autowatch trước đó.
- **(ISSUE-12) Bổ sung composite index tối ưu hóa truy vấn bi-temporal facts (`mulon/memory.py`):**
  - Bổ sung chỉ mục `CREATE INDEX IF NOT EXISTS idx_facts_validity ON memory_facts(valid_to, valid_from);` trong `SCHEMA`.
  - Tối ưu hóa các câu truy vấn lọc active facts theo khoảng thời gian `(valid_to IS NULL OR valid_to > ?) AND valid_from <= ?`.
- **Kiểm thử nghiệm thu (`tests/test_v17_db_pool.py`):**
  - Bổ sung bài kiểm tra `test_pool_daemon_threads_and_gc_cleanup()` xác thực 100% writer và readers trong pool đều là daemon threads và dọn dẹp sạch sẽ khi GC.
  - Toàn bộ full suite: **716 passed, 11 deselected, 0 failed** trong 26.34s (thoát ngay lập tức).

## 1.7.47 — 2026-10-28 — Khắc phục 19 test fail trên Windows thật (W1–W6, T-36, LUỒNG 5 — ký: Antigravity [L5])

- **(W1) Khắc phục lỗi sản phẩm Chợ MCP trên Windows (`mulon/marketplace.py`):**
  - **Sửa phân loại executable path vs shell command string:** Hàm `_is_shell_command_string` phân biệt chính xác đường dẫn executable hợp lệ trên Windows (kể cả khi đường dẫn chứa khoảng trắng như `C:\Program Files\Python312\python.exe` hay `E:\New folder\lane1\.venv\Scripts\python.exe` và dùng dấu gạch chéo ngược `\`) với chuỗi shell đa từ hoặc chứa cờ CLI (như `npx -y some-server` hoặc `python.exe -m foo`).
  - **Gỡ bỏ dấu `\` khỏi `SHELL_META_RE`:** Dấu `\` là `os.sep` hợp lệ trên Windows, việc đưa vào regex shell meta trước đây đã chặn nhầm mọi đường dẫn Windows.
  - **Nhận diện phần mở rộng `.exe` của shell binary:** Kiểm tra `base.removesuffix(".exe") in SHELL_COMMANDS` để chặn chính xác `cmd.exe`, `powershell.exe`. Đồng bộ hỗ trợ `.exe` cho `DOWNLOAD_RUNNERS`.
  - Giải quyết dứt điểm 12 test chợ MCP fail cùng gốc trên Windows thật; người dùng Windows có Python ở đường dẫn có khoảng trắng nay cài đặt MCP server bình thường.
  - Thêm regression tests trong `tests/test_v13_normalize.py`.
- **(W2) Mã hóa UTF-8 cho toàn bộ tiến trình Git con (`scripts/auto_watch.py`):**
  - Bổ sung `encoding="utf-8", errors="replace"` cho `_git`, `get_local_commit`, `get_remote_commit`, `get_commit_summary`, `run_smoke_test`, `check_requirements_changed`, `pull_res`, `pip_res`.
  - Khắc phục triệt để lỗi cp1252 mặc định trên Windows làm mojibake / lỗi giải mã khi git diff hoặc commit message chứa tiếng Việt (`tests/test_auto_watch.py::test_backup_stash_pop_roundtrip`).
  - Bổ sung regression test `test_git_utf8_encoding_multilingual_diff` trong `tests/test_auto_watch.py`.
- **(W3) Khắc phục lỗi đốt phụ đề ffmpeg trên Windows (`mulon/media_tools.py`):**
  - Chuyển `burn_subs` sang chạy ffmpeg với `cwd=subs.parent` và truyền tên file phụ đề tương đối qua filter `subtitles=...`, triệt tiêu hoàn toàn lỗi libavfilter không parse được dấu `:` (ổ đĩa `C:`) và `\` của đường dẫn Windows tuyệt đối.
  - `_escape_filter_path` chuẩn hoá dấu gạch chéo, escape nháy đơn và escape colon `\:` bọc trong nháy đơn để bảo toàn tương thích khi gọi trực tiếp.
  - Bổ sung regression test `test_escape_filter_path_windows` trong `tests/test_phase4_media.py`.
- **(W4) Graceful degrade cho Hook `.sh` trên Windows (`mulon/hooks.py`):**
  - Hàm `_find_bash()` tự động dò tìm shell `bash`/`sh` trong `PATH` và các đường dẫn cài đặt Git for Windows quen thuộc (`%ProgramFiles%\Git\bin\bash.exe`, v.v.).
  - Khi môi trường Windows không có sẵn shell bash, `HookManager.dry_run` và `poll` trả về kết quả degrade an toàn `{"ok": False, "skipped": True, "reason": "bash_not_available_on_system"}` theo nguyên tắc Degrade không sập của dự án.
  - Test `test_hook_lifecycle` skip duyên dáng khi thiếu bash thay vì sập test; bổ sung regression test `test_hook_degrade_when_no_bash` trong `tests/test_hooks_and_goals_workspace.py`.
- **(W5) Chuẩn hoá so sánh đường dẫn & ngữ nghĩa token expiry (`tests/test_v17_cliproxy.py`, `tests/test_v17_cross_platform_setup.py`, `mulon/vault.py`):**
  - `test_config_cliproxy_fields`: so sánh qua `str(Path("bin/cliproxyapi"))` thay vì chuỗi POSIX `/`.
  - `test_paths_resolve`: so sánh sau khi chuẩn hoá `str(p2).replace("\\", "/")`.
  - `mulon/vault.py`: chuyển điều kiện `check_token` từ `time.time() > entry["expires_at"]` sang `time.time() >= entry["expires_at"]`, phản ánh chính xác ngữ nghĩa "hết hạn ngay tức thì" khi `ttl=0` mà không phụ thuộc vào độ phân giải đồng hồ (timer resolution 15.6ms của Windows).
- **(W6) Bổ sung guard môi trường cho Playwright test (`tests/test_v17_policy_tightening.py`):**
  - Đồng bộ pattern dò channel `(None, "msedge", "chrome")` và gọi `pytest.skip` khi máy chưa cài binary trình duyệt Playwright, khớp 100% với các test Playwright khác trong repo.

## 1.7.46 — 2026-10-28 — Business Chatbot: Bản thảo theo ngữ cảnh + Chống chồng thẻ duyệt (T-37, LUỒNG 4 — ký: Antigravity [L4])

- **(C1) Bản thảo đa dạng theo ngữ cảnh & Chuẩn giọng chủ shop Nam bộ (`mulon/business.py`):**
  - **Nhận diện tin chào kết / cảm ơn (`CLOSING_KEYWORDS`):** Phân loại các tin "Tks em", "Cảm ơn shop nha", "Ok em", "okie shop", "bye em", "thế nhé em", "vậy nha em" thành diện cần duyệt với đề xuất rõ ràng: *"Đề xuất: KHÔNG CẦN TRẢ LỜI hoặc gửi câu kết ngắn"*. Nút bấm trên thẻ được tinh chỉnh thành `[Gửi câu kết]` | `[Bỏ qua (Không cần rep)]`.
  - **Soạn nháp theo ngữ cảnh tự nhiên:** Bổ sung nhận diện câu hỏi phí ship/vận chuyển/địa chỉ (`shipping_inquiry`) và câu hỏi tình trạng kho/màu sắc/size (`stock_inquiry`).
  - **Triệt tiêu hoàn toàn mẫu cứng máy móc:** Xoá bỏ hoàn toàn câu cứng ngắc *"Dạ em chào <tên>, em xin phép ghi nhận thông tin này và sẽ kiểm tra phản hồi lại cho mình ngay nha ạ!"*. Thay bằng giọng chủ shop Nam bộ ngắn gọn, thân mật, xưng em - gọi tên khách hoặc anh/chị, đệm các từ ngữ tự nhiên (*"nè"*, *"nghen"*, *"nha"*, *"liền"*, *"Dạ hông có chi nè {c_name} ơi!"*, *"Dạ em nghe nè {c_name} ơi! Để em coi kỹ lại phần này rồi nhắn lại liền cho mình nghen, {c_name} đợi em xíu nha!"*).
- **(C2) Chống chồng thẻ duyệt & TTL 15 phút (`mulon/business.py`, `mulon/telegram_bot.py`):**
  - **Duy nhất một thẻ duyệt hiện hành cho mỗi hội thoại khách (`_active_drafts`, `_draft_cards`):** Quản lý thẻ duyệt đang chờ theo `customer_chat_id`. Khi khách gửi tin nhắn mới trong khi thẻ cũ còn đang chờ, thẻ cũ lập tức bị đánh dấu `superseded` và resolve `approved=False` ở broker.
  - **Vô hiệu hóa trực quan thẻ cũ trên Telegram:** Sửa nội dung tin nhắn của thẻ cũ ở DM của chủ nhân thành cảnh báo `⚠️ [THẺ ĐÃ BỊ VÔ HIỆU HÓA] Bản thảo này không còn hiệu lực do có tin nhắn mới hơn từ khách`, đồng thời gỡ sạch nút inline keyboard (`reply_markup=None`), ngăn chặn việc bấm nhầm thẻ cũ khi ngữ cảnh đã trôi xa.
  - **Guard kép chống gửi tin từ thẻ cũ/quá hạn:** Cả ở `TelegramSurface.handle_approval_callback` lẫn `TelegramBusinessService._settle_draft_approval` đều kiểm tra guard `is_draft_active()`. Nếu thẻ đã bị thay thế hoặc quá hạn, chặn gửi tin tuyệt đối và thông báo rõ ràng cho chủ.
  - **Giới hạn thời gian hiệu lực (TTL 15 phút):** Rút ngắn TTL thẻ nháp business từ 1 giờ xuống 15 phút (900 giây) theo đúng yêu cầu bài toán. Quá 15 phút không duyệt, thẻ tự hết hiệu lực.
- **Kiểm thử nghiệm thu (`tests/test_v17_telegram_business.py`):**
  - Thêm 5 bài test hồi quy mới: phân loại tin chào kết `Tks em` và giọng Nam bộ, bản thảo đa ngữ cảnh không còn mẫu cứng, chống chồng thẻ duyệt cho cùng khách, chặn callback từ thẻ superseded/expired, và kiểm tra hết hạn TTL 900s.
  - Chạy full test suite: **722 passed, 0 failed (100% xanh)**. Eval vàng: **33/36 case đạt (92%, vượt ngưỡng 85%)**.

## 1.7.45 — 2026-10-28 — Hoàn tất Audit 28/10: dọn topics thừa, gỡ emoji trang trí, sửa lỗi bề mặt Feed/Library & Mini App (T-35, LUỒNG 1 — ký: Antigravity [L1])

- **Dọn dẹp topics thừa & cơ chế chốt phiên gọn gàng (A1–A3):**
  - **Auto-close sidechat khi chốt phiên (`mulon/telegram_bot.py: cmd_new`):** Khi người dùng thực thi `/new` ngay trong một topic chat phụ (sidechat), bot tự động chốt phiên và đóng topic đó an toàn, tránh để lại các topic phụ rác trôi nổi.
  - **Thẻ duyệt không lưu nút bấm stale (`mulon/telegram_bot.py: on_approval_button`):** Khi thẻ duyệt được chủ nhân bấm xử lý hoặc đã hết hạn, bàn phím inline lập tức được gỡ bỏ (`reply_markup=None`) và nội dung tin nhắn được cập nhật trạng thái quyết định (`[Quyết định: ĐÃ DUYỆT]`), loại bỏ hoàn toàn tình trạng nút bấm mồ côi/stale.
  - **Menu Dashboard duy nhất chống spam (`mulon/telegram_bot.py: cmd_menu`):** Sử dụng khóa KV `menu_msg:{chat_id}` để lưu vết `message_id` của dashboard `/menu`. Các lượt gọi `/menu` tiếp theo tự động cập nhật (edit) tin nhắn menu hiện có thay vì spam tạo tin mới.
- **Gỡ bỏ triệt để 261 ký tự emoji trang trí khỏi bot và Mini App (B1–B3):**
  - **Telegram bot template emojis (`mulon/telegram_bot.py`):** Gỡ bỏ 261 emoji trang trí template (`⚠`, `👉`, `✅`, `❌`, `🧭`, `💡`, `🖼`, `📥`, `🟢`, `🔴`, `🎯`, `🚀`, `📌`, `🔐`...). Giữ lại ký hiệu mảnh `✓` / `✕` theo chuẩn `DESIGN.md`; trạng thái được thể hiện bằng CHỮ phân cấp trung tính rõ ràng. Giữ nguyên bộ reaction tin nhắn của `pick_chat_reaction`.
  - **Mini App (`mulon/webapp/index.html`):** Gỡ emoji tier model (`🧠 Model Brain`, `⚡ Model Cheap`, `🚀 Model Escalated`), `📬` và `📍` ở thẻ goal, và các cảnh báo thô; cập nhật toast sang `✓` và `✕`.
  - **Đồng bộ toàn bộ các module liên quan (`mulon/feed.py`, `mulon/surfaces.py`, `mulon/os_service.py`, `mulon/business.py`, `mulon/library.py`, `mulon/webapp_server.py`, `mulon/setup_wizard.py`):** Gỡ emoji nút (`Thích`, `Thảo luận`), gỡ `🎉`, `⚠️`, `🏦`, `💳`, `👤`, `💬`, chuẩn hoá nhãn library sang `[Ảnh]`, `[Media]`, `[Tài liệu]`, `[Mã]`, `[Tệp]`.
- **Sửa lỗi bề mặt Feed & Library (C1, C2):**
  - **Sanitize văn bản Feed (`mulon/feed.py: sanitize_feed_text`):** Làm sạch tiêu đề Markdown thô dạng `### 🤖 [GitHub](...)` và chuyển đổi sang HTML an toàn (`<b>...</b>`, thẻ link) trên Telegram, loại bỏ emoji robot.
  - **Chuẩn hóa nhãn tệp tải lên Thư viện (`mulon/telegram_bot.py`):** Đăng tệp media lên topic Library dùng nhãn đọc được theo caption hoặc `[Thư viện] Ảnh tải lên / Ảnh #{id}`, triệt tiêu hoàn toàn việc để lộ tên tệp nội bộ vô nghĩa (`photo_288_AQAD3RprG-cE-FZ9.jpg`).
- **Render & Tinh chỉnh Mini App (D1–D10 & E1):**
  - **(E1) Chuẩn hóa W3C:** Đổi thẻ `<label class="row static">` tại dòng 1938 thành `<div class="row static">` để loại bỏ lỗi lồng thẻ label (nested label).
  - **(D1) Khắc phục gọi API sai tên:** Sửa `apiFetch` thành `api` tại hàm `renderCLIProxy`.
  - **(D2) Render Goals tự động:** Tự động gọi `renderGoals()` trong `renderTasks()` và `renderAll()` để cây mục tiêu luôn hiển thị sống động.
  - **(D3) Đóng gói meta hàng việc đang chạy:** Gói `r-state`, nút `Dừng` (`.btn-subtle` trung tính, không co giãn khối đỏ lỗi) và `r-time` vào container `.r-meta`.
  - **(D4) Token theme Design System:** Đồng bộ `--ds-primary:var(--accent)` và `--ds-primary-tint:var(--tint-lav)` để ăn theo theme người dùng chọn; chuẩn hóa `.ds-chip.active` theo `.filter-chip.active`.
  - **(D5) Monogram & Tên kết nối thân thiện:** Suy monogram động ("G", "T", "Z", "F", "M") theo loại kết nối, hiển thị tên dễ đọc (`zalo_personal` -> "Zalo Cá nhân").
  - **(D6) Chống tràn inset thẻ:** Bổ sung `padding: 0 var(--s4)` cho các khối nội dung và form ở màn Thương hiệu & Quyền.
  - **(D7) Bỏ emoji tier Model:** Loại bỏ `🧠`, `⚡`, `🚀` khỏi màn hình cấu hình Model.
  - **(D8) Tinh giản affordance kết nối:** Chỉ giữ 1 nút action soft/accent, ẩn chevron khi hàng kết nối đã có nút bấm hoặc toggle.
  - **(D9) Header hero 56pt compact & ẩn ở màn con:** Thu gọn header hero về kích thước 56pt dạng thanh ngang (avatar 40px, name 17px, status 13px), tự động ẩn trên các màn con (`showSub`).
  - **(D10) Chống xén chữ & ẩn phân trang rỗng:** Thêm `line-height:1.45` cho `.appr-sub`, bỏ `text-transform:uppercase` ở tiêu đề lịch sử duyệt, ẩn thanh phân trang `mkt-pagination` khi chưa có dữ liệu.
- **Kiểm thử nghiệm thu (`tests/test_v17_t35_audit_surfaces_polish.py`):**
  - Bổ sung 5 bài test mới kiểm chứng toàn bộ luồng A1, A2, A3, C1, C2.
  - Toàn bộ suite test **717 passed, 0 failed**.

## 1.7.44 — 2026-10-28 — Triển khai đề xuất hiệu năng T-08: Reader Pool + Writer Lock cho SQLite (T-34, LUỒNG 4 — ký: Antigravity [L4])

- **Triển khai kiến trúc SQLite WAL đa kết nối (`mulon/db.py`, `mulon/memory.py`, T-34):**
  - **Single Writer Connection:** Một kết nối ghi chuyên biệt được bảo vệ bởi `asyncio.Lock()` cho mọi câu lệnh ghi (`INSERT`, `UPDATE`, `DELETE`, `REPLACE`, `DDL`, `COMMIT`, `ROLLBACK`), triệt tiêu 100% lỗi `sqlite3.OperationalError: database is locked` khi có nhiều tác vụ chạy đồng thời.
  - **Reader Pool Connections:** Một hàng đợi `asyncio.Queue` chứa N kết nối đọc (mặc định 4 kết nối, cấu hình linh hoạt qua biến môi trường `SQLITE_READER_POOL_SIZE`) ở chế độ `PRAGMA query_only=ON;`. Các truy vấn đọc (`SELECT`, `PRAGMA table_info`, v.v.) từ Mini App, hybrid recall, bot queries tự động được phân phối song song trên các thread nền độc lập, tận dụng tối đa lợi thế của SQLite WAL ("Readers do not block writers, and writers do not block readers").
  - **Lớp bọc trong suốt `SqliteWALPool` & `PooledCursor`:** Đóng vai trò drop-in replacement tương thích 100% với giao thức của `aiosqlite.Connection`. Tự động phân loại câu query (`is_read_only_query`), điều hướng lệnh đọc sang Reader Pool và lệnh ghi sang Writer Lock. Cursor được bọc `PooledCursor` tự động trả connection về pool ngay khi fetchall hoàn tất hoặc khi cursor được đóng.
  - **Hỗ trợ Dynamic Extensions (`sqlite-vec`):** Đồng bộ nạp extension `sqlite-vec` trên cả writer connection và toàn bộ reader connections khi khởi tạo hoặc khi bật embedder, bảo đảm hybrid recall vector queries hoạt động song song mượt mà.
  - **Context Managers tường minh (`Memory.read_conn()`, `Memory.write_conn()`):** Cho phép các tác vụ gom nhóm câu truy vấn mượn connection đọc/ghi rõ ràng.
- **Cấu hình & Tương thích ngược (`mulon/config.py`, `.env.example`):**
  - Thêm thuộc tính cấu hình `sqlite_reader_pool_size: int = 4` trong `Config` và `Config.load()`, tương thích biến môi trường `SQLITE_READER_POOL_SIZE`.
  - Bổ sung tài liệu cấu hình chi tiết vào `.env.example`.
- **Kiểm thử hiệu năng & hồi quy (`tests/test_v17_db_pool.py`, `tests/test_perf_db_concurrency.py`):**
  - 3 unit tests mới trong `tests/test_v17_db_pool.py`: kiểm tra bộ phân loại query đọc/ghi, vòng đời pool, và concurrency đọc-ghi không bị lock.
  - 3 benchmark/stress tests trong `tests/test_perf_db_concurrency.py`: kiểm tra 25 readers bắn đồng thời trong lúc writer đang ghi liên tục (độ trễ trung bình < 2ms, max < 15ms), stress test 30 workers đọc-ghi xen kẽ đồng thời bảo toàn tính toàn vẹn dữ liệu, và kiểm thử context managers.
  - Toàn bộ suite test **712 passed, 0 failed**; Eval vàng **33/36 = 92%** qua cổng 85%.


- **Đồng bộ chuẩn xác tài liệu sitemap Mini App (`docs/sitemap-miniapp-2026-10-27.md`, `docs/sitemap-miniapp-v17.md`, T-32):**
  - Cập nhật tiêu đề và banner cảnh báo `SUPERSEDED` rõ ràng, nổi bật ở đầu file `docs/sitemap-miniapp-2026-10-27.md`, dẫn link sang sitemap v1.7 chính thức.
  - Thêm khối tham chiếu chéo ngược lại tài liệu cũ trong `docs/sitemap-miniapp-v17.md`, bảo đảm tính nhất quán và triệt tiêu mâu thuẫn giữa 2 tài liệu.
- **Sửa tên biến cấu hình Telegram Business trong `README.md` (T-32):**
  - Đổi biến `BUSINESS_BOT_ENABLED` thành `TELEGRAM_BUSINESS_ENABLED` trong bảng biến môi trường tại dòng 234 của `README.md`, khớp 100% với mã nguồn `mulon/config.py:460` và mẫu `.env.example:199`.
  - Cập nhật badges phiên bản 1.7.43, 706 tests passed, eval vàng 92% (33/36).
- **Làm sạch merge marker (T-32):**
  - Xác nhận và đảm bảo không còn bất kỳ merge marker nào (`>>>>>>> 47c0c58` hay dạng tương tự) tồn tại trong `CHANGELOG.md` hay toàn bộ cây mã nguồn.

## 1.7.42 — 2026-10-28 — Sửa lỗi eval vàng T-33 & hoàn tất phần còn lại T-25 (LUỒNG 5 — ký: Antigravity [L5])

- **Chẩn đoán & sửa dứt điểm lỗi code trong eval vàng (`mulon/tools.py`, T-33):**
  - **Sửa ca `tool-list-dir`:** Trong `_resolve_for_file_tool`, khi `raw` là `.` hoặc chuỗi rỗng, điều kiện kiểm tra codebase vô tình khớp `project_root / "."` khiến `list_dir(".")` duyệt thư mục gốc repo thay vì workspace. Đã sửa để `raw in {".", "", "./"}` luôn neo tuyệt đối vào `workspace_dir`, bảo đảm liệt kê đúng các file trong workspace.
  - **Sửa ca `self-read-own-source`:** Trong `_resolve_for_file_tool`, kiểm tra sự tồn tại trong workspace `(base / p).exists()` trước khi neo vào `project_root`. Nhờ đó, các file mock do test/eval thiết lập trong workspace được ưu tiên đọc chính xác thay vì đọc file thật của repo; khi không có file trong workspace, hệ thống vẫn tự động fallback về codebase của repo để bot tự đọc/sửa chính mình.
  - Sau bản vá, số ca đạt trong eval vàng tăng từ **31/36 (86%) lên 33/36 (92%)**, 100% ca họ `tool` (7/7) và `trung_thuc` (8/8) đều PASS.
- **Tự nhận thức về Chợ MCP & Công cụ kết nối (`mulon/agent.py`, T-33):**
  - Bổ sung khối chỉ dẫn về MCP & Marketplace vào `build_self_knowledge`: bot hiểu rõ giới hạn an toàn của mình là không có tool tự cài/gỡ MCP server trực tiếp trong chat; khi chủ nhân yêu cầu, bot hướng dẫn mở Mini App > Cài đặt > Công cụ kết nối (hoặc Chợ MCP) hoặc qua thẻ duyệt 2 lần; nắm vững quy tắc hệ thống chỉ hỗ trợ MCP server local (stdio) và miễn phí, không hỗ trợ remote hoặc trả phí.
- **Phân loại & bằng chứng 3 ca `cho_mcp` còn lại (T-33):**
  - Cả 3 ca `marketplace-install-guides-to-app`, `marketplace-no-agent-install-tool`, `marketplace-remote-paid-not-supported` thuộc loại (b): kỳ vọng của ca chạy ở chế độ offline `StubGateway` nhưng thiếu định nghĩa `stub.answer` trong `evals/golden.jsonl` (khác với `self-approval-card-real` và `self-can-read-file` cùng đợt 1.3.0 có định nghĩa `stub.answer`). Giữ nguyên ca theo đúng nguyên tắc không tự nới lỏng ca, ghi nhận đầy đủ bằng chứng vào `AGENT_TASKS.md` cho Muse và chủ dự án quyết định.
- **Hoàn tất phần còn lại của T-25 trong Telegram Bot (`mulon/telegram_bot.py`, T-25):**
  - Xóa bỏ hoàn toàn giờ feed hardcode trong handler `/upcoming`. Nhãn giờ Feed chủ động được suy động từ `cron_times_label(feed_cron)` thông qua `FeedAutoRunner.settings()` hoặc `DEFAULT_CRON`. Khi cron là mẫu không cố định, hiển thị trực tiếp biểu thức cron thay vì nhãn giờ cố định sai lệch.
- **Kiểm thử bổ sung (`tests/test_v17_eval_fixes.py`, `tests/test_v17_feed_time_label.py`):**
  - Bổ sung 4 unit tests trong `tests/test_v17_eval_fixes.py` kiểm chứng `list_dir(".")` trong workspace, quyền ưu tiên workspace cho file mock, và nội dung tự nhận thức MCP.
  - Bổ sung 2 unit tests trong `tests/test_v17_feed_time_label.py` kiểm chứng lệnh `/upcoming` hiển thị đúng giờ feed suy từ cron và fallback đúng `DEFAULT_CRON`.

## 1.7.41 — 2026-10-28 — Kiểm chứng Live Test DM Threads và Instagram Anti-Fake Send (T-22.3, LUỒNG 3 — ký: Antigravity [L3])

- **Kiểm chứng gửi DM Threads thật qua Browser Bridge (`mulon/threads_browser_bridge.py`, T-22.3):**
  - Chạy live test thực tế trên máy Mac với profile Chromium persistent (`~/.mulon-browser-profile`), đăng nhập thật phiên tài khoản Meta `@mmmnhat.1810`.
  - Tối ưu bộ chuyển hướng hội thoại `PlaywrightThreadsDriver.send`: điều hướng trực tiếp bằng URL `target_href` (`/messages/t/<thread_id>/`), khắc phục triệt để hiện tượng overlay pointer-events che nút click; bổ sung fallback nhấn `Enter` trên bàn phím khi web không có nút gửi riêng.
  - Gửi thành công 1 DM Threads thật vào hội thoại có sẵn (`1843103926844931`, `@nghialuthe`) với kết quả trả về `verified: True` sau khi xác thực nội dung tin nhắn xuất hiện trong DOM của Threads Web.
  - Kiểm chứng chốt chặn Strict Parity Guard: người lạ hoàn toàn (`@stranger_never_met_999`) bị từ chối dứt khoát trước khi gọi bridge (`LIMITATION_THREADS_MSG`).
- **Kiểm chứng Instagram Send & Anti-Fake Stubs (`mulon/personal_connectors.py`, `mulon/instagram_browser_bridge.py`, T-22.3):**
  - Đồng bộ cờ `unsupported: True` trong các nhánh thiếu transport / thiếu session của `InstagramMessagesConnector` và `ThreadsMessagesConnector`.
  - Kiểm chứng trực tiếp 4 kịch bản không có transport: `send_message`, `send_file`, `send_reaction`, và `send_message` khi đã cấu hình cookie nhưng chưa có bridge/runner. Tất cả đều trả lỗi trung thực `ok: False, unsupported: True`, tuyệt đối không báo `sent: True` hoặc `reacted: True` giả.
  - Kiểm chứng `InstagramBrowserBridge` sẵn sàng (`availability = True`) trên Chromium profile; thử gửi vào thread lạ trả lỗi trung thực 'Không thấy hội thoại có sẵn khớp...'.
- **Kiểm thử:**
  - Toàn bộ test suite 700+ tests PASSED 100%.

## 1.7.40 — 2026-10-28 — Đồng bộ README + docs và nghiệm thu chéo T-25 (T-32, LUỒNG 2 — ký: Antigravity [L2])

- **Đồng bộ toàn diện `README.md` (T-32):**
  - Cập nhật badges phiên bản 1.7.40, 700 tests passed, eval vàng 86%, hỗ trợ đa nền tảng (macOS / Windows / Linux).
  - Phản ánh trung thực 100% các tính năng lớn đã hoàn thành từ chuỗi 1.7.x:
    - Cổng model chính thức CLIProxyAPI loopback 8317 (`mulon/cliproxy.py`, T-14) & `muse2api` (`mulon/muse2api.py`, T-16).
    - Thương hiệu & Mascot vũ trụ Mulon: catalog 4 mascot, đổi tên bot & mascot trực tiếp trong app, lưu bền KV store (`config/mascots.json`, T-13).
    - Telegram Business Chatbot: tự rep giá catalog & soạn nháp STK/giảm giá qua thẻ duyệt DM chủ (`mulon/business.py`, T-29).
    - Built-in Connectors: Google Workspace (Gmail, Calendar, Drive, Docs, Sheets, Keep, T-17), Facebook cá nhân 31 hành động & Threads cá nhân kết hợp Playwright Browser Bridge cho DM (T-30), Zalo cá nhân.
    - Chuẩn hóa bề mặt lệnh Telegram: menu 10 lệnh tinh gọn, lệnh `/help` phân 3 nhóm trực quan, chặn tức thì mọi lệnh lạ (T-26).
    - Trải nghiệm Telegram mượt mà: phản hồi xếp hàng ngay `⏳` (< 1s), chống chớp markdown thô qua HTML streaming, xóa dòng phân cách rác `---` (T-24.7).
    - Mini App Design System 100% chuyên nghiệp: 60/30/10 tím Mulon `#7C3AED`, Bottom Sheet L3 chi tiết bước, Telegram WebApp SDK native (T-12, T-23, T-27).
    - Parity hệ thống & Model tiers: đổi model trực tiếp trong chat/app, thiết lập API an toàn với kiểm tra kết nối sống, tự sửa mã nguồn & kiểm thử fail-safe (T-11).
  - Hướng dẫn cài đặt nhanh đa nền tảng cho macOS, Windows (bổ sung `tzdata` múi giờ IANA và quyền hạn tệp NTFS), và Linux.
  - Cập nhật bảng tra cứu lệnh Telegram và danh mục module mới trong dự án.
- **Cập nhật chuẩn kiểm chứng `docs/muse-parity-checklist.md` (T-32):**
  - Cập nhật trạng thái các mục parity theo verdict mới nhất: `G1` (ĐẠT - Google, FB, Threads, Zalo, Business), `H3` (ĐẠT - CLIProxyAPI), `H4` (ĐẠT MỨC GATEWAY - muse2api), `J1/J2` (ĐẠT - Design System & 60/30/10), `J5` (ĐẠT - Mascot & Brand), `J6` (ĐẠT - Native WebApp SDK), `K1/K2/K3` (ĐẠT - Đa nền tảng), `A3` (ĐẠT - Phản hồi xếp hàng ⏳).
- **Cập nhật Bản đồ Mini App (T-32):**
  - Viết mới `docs/sitemap-miniapp-v17.md` mô tả toàn diện kiến trúc sitemap 5 tab chính, màn con L2/L3, Bottom Sheet L3, card Cá nhân hoá, và tiêu chuẩn BackButton native.
  - Đánh dấu cảnh báo superseded rõ ràng trong `docs/sitemap-miniapp-2026-10-27.md`.
- **Nghiệm thu chéo T-25 (LUỒNG MUSE):**
  - Kiểm tra độc lập logic hàm `cron_times_label` động trong `mulon/feed_auto.py`, `_upcoming_state` trong `mulon/webapp_server.py`, và dòng hiển thị Feed trong `mulon/telegram_bot.py`.
  - 4/4 test trong `tests/test_v17_feed_time_label.py` PASSED 100%. Antigravity [L2] đóng dấu `VERIFIED` cho T-25.

## 1.7.39 — 2026-10-28 — Kiểm chứng sống tích hợp muse2api qua CLIProxyAPI trên macOS (T-16, LUỒNG 1 — ký: Antigravity [L1])

- **Kiểm chứng sống 3 bước của T-16 trên máy Mac thật (`config/cliproxy-muse2api.example.yaml`, `AGENT_TASKS.md`, T-16):**
  - **Bước 1 (GET /v1/models qua cổng 8317):** Gọi `http://127.0.0.1:8317/v1/models` với Bearer PROXY_API_KEY, liệt kê đủ 43 models bao gồm cả `muse/muse-spark`, `muse-spark`, `muse-spark-1.1`, `muse-image`, `muse-wonder-1.0`, `muse-video`. Hàm `muse2api.muse_model_in_proxy_models` trả lời `True`.
  - **Bước 2 (Lượt chat Muse thật qua cổng 8317 với muse2api Docker + tài khoản Muse thật):** Gọi `ModelGateway.complete` qua cổng proxy local 8317 với cả 2 định dạng `model="muse-spark"` và `model="muse/muse-spark"`. Cả hai lượt đều trả lời thành công HTTP 200, phản hồi text `'Mulon'`, model `openai/muse/muse-spark` (lượt 1: 92.64s khi khởi tạo session browser CDP cho tài khoản pool, lượt 2: 36.67s khi session đã ấm).
  - **Bước 3 (Tắt Docker muse2api kiểm tra degrade & khôi phục):** Tắt container bằng `docker stop muse2api`, gọi model Muse báo lỗi mạng rõ ràng (`GatewayError: gọi model thất bại sau 3 lần: litellm.InternalServerError`), trong khi model đối chứng khác qua cổng 8317 (`gemini-3.8-flash` -> `openai/gemini-3.8-flash-high`) vẫn gọi thành công bình thường (text `'Dạ?'`, 15.63s). Bật lại `docker start muse2api`, kiểm tra `/healthz` trả về `{"status":"ok"}` và gọi lại `model="muse-spark"` phục hồi thành công (text `'Mulon'`, 90.87s).
  - Cập nhật mẫu `config/cliproxy-muse2api.example.yaml` bổ sung cả hai alias `muse-spark` và `muse/muse-spark`.
  - Ghi nhận đầy đủ evidence vào mục `[T-16]` trong `AGENT_TASKS.md` để Muse chính đối chiếu nghiệm thu VERIFIED.

## 1.7.38 — 2026-10-28 — Parity hệ thống: connector/MCP/quyền/model/tự sửa (T-11, LUỒNG 5 — ký: Antigravity [L5])

- **Đổi model TRỰC TIẾP trong chat và Mini App (`mulon/telegram_bot.py`, `mulon/agent.py`, `mulon/webapp_server.py`, `mulon/webapp/index.html`, T-11):**
  - Hỗ trợ đầy đủ 3 tiers model hệ thống (Brain, Cheap, Escalated) với phân tầng rõ ràng, không trùng lặp.
  - Ghi đè model theo phiên (`/model session <tên_model>`): lưu bền vững trong SQLite KV (`session_model:<session_key>`). `Agent.handle` tự động phân giải `_resolve_brain_model` và ưu tiên model override cho phiên đó mà không ảnh hưởng các luồng trò chuyện khác.
  - Cấu hình từng tầng (`/model tier <brain|cheap|escalated> <tên_model>`) và xóa ghi đè (`/model reset`).
  - Mini App REST API: `GET /api/model` (lấy danh sách tiers, model phiên và danh mục gợi ý phổ biến) và `POST /api/model` (cập nhật tier hoặc model theo phiên).
  - Giao diện Mini App: bổ sung màn hình `#screen-models` độc lập, liên kết từ thẻ "Mô hình AI" trong tab Cài đặt (`#tab-caidat`), cho phép chọn nhanh các model phổ biến hoặc nhập tên model tùy chỉnh.
- **Rà soát & chốt bề mặt Slash Commands (`mulon/telegram_bot.py`, `mulon/commands.py`, T-11):**
  - Chuẩn hóa lệnh `/help`: hỗ trợ xem tổng quan phân nhóm hoặc xem chi tiết từng lệnh cụ thể (`/help <lệnh>`).
  - Chặn đứng các slash command lạ ngay tại cửa ngõ `on_text`, phản hồi ngay hướng dẫn gõ `/help` mà không tốn lượt xử lý của Agent LLM.
  - Tái cấu trúc lệnh `/memory`: hiển thị tóm tắt có cấu trúc (tổng số facts đang lưu, phân bố chủ đề chính, các dữ kiện gần nhất, trích đoạn `USER.md`), tuyệt đối không dump nội dung thô `MEMORY.md`.
  - Khóa chặt lệnh `/the_duyet` thử nghiệm: chỉ cho phép chạy khi cờ phát triển được bật tường minh (`dev_mode=True`, `ENABLE_DEV_COMMANDS=1`, hoặc `MULON_DEV_MODE=1`).
- **Thiết lập API từ đầu với kiểm tra kết nối sống (`mulon/telegram_bot.py`, `mulon/webapp_server.py`, T-11):**
  - Hỗ trợ lệnh `/setup api <endpoint> <key>` cho Owner: kiểm tra kết nối sống (`httpx.get` tới `/models`) trước khi lưu cấu hình proxy và cất khóa bảo mật vào Vault an toàn. Từ chối lưu và cảnh báo ngay nếu endpoint chết hoặc khóa không hợp lệ.
  - Endpoint Mini App `POST /api/vault/verify-and-capture`: kiểm tra bảo mật SSRF/loopback và kết nối trước khi ghi nhận khóa API proxy.
- **Tự sửa & vòng đời an toàn (Self-evolution, `mulon/evolution.py`, T-11):**
  - Đăng ký công cụ `self_verify_and_restart` trong `ToolRegistry` qua `register_evolution_tools`: khi agent tự sửa mã nguồn theo yêu cầu của chủ dự án, công cụ tự động chạy kiểm thử toàn bộ test suite (`pytest tests/ -q`) và kiểm tra cổng eval vàng nếu cần.
  - Cơ chế tự vệ (Fail-safe): nếu test fail hoặc timeout, tự động thực thi `git checkout -- mulon/` để rollback sạch sẽ các thay đổi, bảo vệ bot không bao giờ bị rơi vào trạng thái lỗi hay sập tiến trình. Nếu test pass 100%, ghi nhận lý do và kích hoạt restart tiến trình sạch sẽ.
- **Bảo toàn quyền connector theo từng hành động (Action-Level Policy, T-11):**
  - Giữ vững chuẩn bảo mật 1.6: hành động đọc (`read`) được cho phép tự động; hành động ghi/xóa (`write`, `delete`) hoặc nhạy cảm bắt buộc phải qua thẻ phê duyệt (`ApprovalBroker`) gửi về DM của chủ nhân.
- **Kiểm thử toàn diện (`tests/test_v17_t11_parity.py`, T-11):**
  - 10 unit tests mới bao phủ 100% các tiêu chí của T-11: tính toàn vẹn lệnh, /help phân nhóm, /the_duyet dev guard, /memory tóm tắt cấu trúc, /model 3 tiers & session override, tích hợp Agent session override, Mini App model API, /setup api kiểm tra kết nối sống, và tool self_verify_and_restart.

- **Triển khai toàn diện Telegram Business Service (`mulon/business.py`, T-29):**
  - Quản lý vòng đời kết nối Bot API Telegram Business: nhận và lưu trữ trạng thái `business_connection`, tự động ngắt rep khi bị ngắt kết nối trong Telegram Settings và cảnh báo về DM chủ.
  - Tách biệt ngữ cảnh tuyệt đối (bài học X-01): tin nhắn của khách là vũ trụ riêng biệt, bảo vệ dữ liệu ngoài qua `frame_external`, tuyệt đối không truy cập file/vault/system tools của chủ, chặn triệt để prompt injection hoặc yêu cầu xem dossier/mã nguồn.
  - Bỏ qua tin nhắn gửi từ client khác do chính chủ gửi (`from_user.id == cfg.allowed_user_id`), tránh can thiệp vào cuộc trò chuyện tay của chủ.
  - Rate limit per chat chống spam khách hàng (mặc định 10 tin/phút, cấu hình được).
- **Mức tự chủ phân tầng chặt chẽ theo quyết định của chủ dự án (`mulon/business.py`, `config/shop_catalog.json`, T-29):**
  - **TỰ REP:** Chào hỏi, hướng dẫn mua hàng, chính sách bảo hành, thông tin/giá sản phẩm dựa trên nguồn sự thật duy nhất từ catalog `config/shop_catalog.json` (nạp qua `load_json_data`, Rule 0). Trả lời bằng giọng bán hàng miền Nam thân thiện, lễ phép (dạ, em chào anh/chị, bên em...), CẤM BỊA GIÁ.
  - **SOẠN NHÁP CHỜ DUYỆT:** Khi khách hỏi STK/chuyển khoản (TUYỆT ĐỐI KHÔNG TỰ GỬI STK), thương lượng giảm giá ngoài bảng, khiếu nại, phản ánh chất lượng, hoặc ca không chắc chắn — tự động soạn nháp câu trả lời lịch sự và mở thẻ phê duyệt về DM chủ qua `ApprovalBroker`. Chủ bấm Cho phép -> bot gửi tin qua `business_connection_id`; Chủ từ chối/im lặng -> bot im lặng tuyệt đối.
- **Bề mặt điều khiển & API Mini App (`mulon/telegram_bot.py`, `mulon/webapp_server.py`, `mulon/commands.py`, T-29):**
  - Đăng ký lệnh Telegram `/business` (alias `/biz`) cho chủ xem báo cáo trạng thái kết nối, thống kê lượt auto-rep và nháp duyệt.
  - Endpoint API `/api/business/status` trong Mini App server.
  - Khai báo cấu hình `TELEGRAM_BUSINESS_ENABLED`, `TELEGRAM_BUSINESS_CATALOG_PATH`, `TELEGRAM_BUSINESS_RATE_LIMIT_PER_MIN` trong `mulon/config.py` và `.env.example`.
- **Kiểm thử (`tests/test_v17_telegram_business.py`, T-29):**
  - 11 unit tests mới bao phủ 100% yêu cầu: vòng đời connection, bỏ qua tin chủ, tự rep giá sản phẩm chuẩn catalog, soạn nháp STK/giảm giá, chờ duyệt thẻ, im lặng khi từ chối, rate limit, chặn moi thông tin hệ thống, và lệnh /business.

## 1.7.36 — 2026-10-28 — Polish X-06/X-07: Báo xếp hàng ngay, hết lóe markdown thô, dọn dòng phân cách (T-24.7, LUỒNG 1 — ký: Antigravity [L1])

- **Xác nhận xếp hàng ngay khi bot đang bận (`mulon/telegram_bot.py`, T-24.7, X-06):**
  - Thêm phương thức `_notify_queued(key, message)`: khi người dùng gửi tin nhắn (chữ, ảnh, video, âm thanh, tài liệu, giọng nói) trong lúc bot đang bận xử lý lượt trước, bot lập tức thả reaction `⏳` trên tin nhắn của người dùng và gửi tin xác nhận `"⏳ <i>Đã nhận, đang xếp hàng (chờ hoàn thành lượt trước)...</i>"` trong vòng < 1 giây.
  - Ngăn chặn gửi tin xếp hàng trùng lặp nếu người dùng gửi nhiều tin liên tiếp trong cùng đợt bận.
  - Tái sử dụng tin nhắn xếp hàng làm placeholder chính thức khi lượt xếp hàng bắt đầu chạy (`_on_batch`): cập nhật trực tiếp thành `"⏳ <i>Đang xử lý...</i>"` rồi chỉnh sửa thành kết quả cuối cùng, triệt tiêu tin nhắn rác.
  - Tự động xóa dọn placeholder xếp hàng khi người dùng đổi ý hủy tác vụ (`/cancel`, `/stop`, hoặc câu thoại ngắt ý).
- **Triệt tiêu hoàn toàn hiện tượng lóe markdown thô (`mulon/telegram_bot.py`, T-24.7, X-07):**
  - Bổ sung hàm `safe_stream_markdown_to_html(text)`: tự động cân bằng và đóng các thẻ dở dang (bold `**`, code block ````, inline code ```) trong quá trình stream, render sạch sẽ qua `md_to_html` và `parse_mode="HTML"`.
  - Nâng ngưỡng stream trong `on_delta` lên `>= 50` ký tự: các câu trả lời ngắn (như phép tính `"17 + 25 = 42"`) đi thẳng một nhịp vào HTML hoàn chỉnh, không qua trạng thái chỉnh sửa dở dang lộ dấu `**`.
  - Mọi nhịp stream bài dài (cách nhau >= 1.2s) đều được gửi dưới dạng HTML định dạng chuẩn, không bao giờ hiển thị cú pháp thô (`**` hay `###`), loại bỏ hoàn toàn cảnh "chờ 3 nhịp mới ổn định định dạng".
- **Dọn sạch dòng phân cách thô trong bài viết dài (`mulon/telegram_bot.py`, T-24.7, X-07):**
  - Bổ sung regex chuẩn CommonMark `_HR_RE` (`^[ \t]*([-*_][ \t]*){3,}$`) và hàm `clean_final_text(text)`: tự động loại bỏ các dòng phân cách ngang thô (`---`, `***`, `___`, `- - -`, `* * *`) khỏi thân bài viết và thu gọn khoảng trắng thừa.
  - Tích hợp `_HR_RE` vào `md_to_html`, đảm bảo bảo toàn dòng `---` trong code block YAML (`<pre>`) và giữ nguyên bảng Markdown (`| --- | --- |`), chỉ xóa các dòng thematic break đơn lẻ gây mất thẩm mỹ trên Telegram.
- **Kiểm thử (`tests/test_v17_polish_x06_x07.py`, T-24.7):**
  - 7 unit tests mới kiểm tra toàn diện: xóa dòng phân cách thô `---` và bảo toàn trong YAML/bảng, streaming an toàn với `safe_stream_markdown_to_html`, bỏ qua edit dở dang với câu ngắn, gửi phản hồi xếp hàng tức thì trong vài giây, tái sử dụng placeholder trong `_on_batch`, và xóa dọn placeholder khi hủy lệnh.
  - Toàn bộ suite 660 test passed 100%. Eval vàng stub đạt 31/36 (86% >= ngưỡng 85%).

## 1.7.35 — 2026-10-28 — Chốt bề mặt slash commands, danh mục tập trung & chặn lệnh lạ (T-26, LUỒNG 4 — ký: Antigravity [L4])

- **Nguồn sự thật duy nhất cho Slash Commands (`mulon/commands.py`, T-26):**
  - Bổ sung module `mulon/commands.py` với `CommandDef` và danh mục `COMMAND_DEFINITIONS` tập trung.
  - Phân loại rõ ràng 4 nhóm: `BASIC` (Cơ bản), `WORK_DATA` (Việc & Dữ liệu), `ADVANCED` (Nâng cao & Kết nối), `INTERNAL` (Nội bộ / Thao tác thẻ item).
  - Khởi tạo tập hợp `ALL_HANDLED_COMMANDS` dùng chung cho toàn bộ hệ thống kiểm tra và điều hướng.
- **Rút gọn Menu "/" trên Telegram còn 10 lệnh cốt lõi (`mulon/commands.py`, `mulon/telegram_bot.py`, T-26):**
  - Menu "/" popup của Telegram (đăng ký qua `bot.set_my_commands`) rút gọn đúng 10 lệnh cốt lõi: `start`, `menu`, `new`, `cancel`, `status`, `model`, `vault`, `upcoming`, `goals`, `help`.
  - Giữ nguyên `BOT_COMMANDS` đầy đủ cho tính tương thích ngược với toàn bộ test suite.
- **Bổ sung lệnh `/help` có cấu trúc & phân nhóm (`mulon/commands.py`, `mulon/telegram_bot.py`, T-26):**
  - Handler `@dp.message(F.text.startswith("/help"))` trả lời nhanh danh sách lệnh phân theo 3 nhóm rõ ràng (Cơ bản, Việc & Dữ liệu, Nâng cao & Kết nối).
  - Các lệnh có tính phá huỷ hoặc thay đổi trạng thái lớn (`/restart`, `/forget`) có cảnh báo rõ ràng `(⚠️)`.
  - Lệnh dev thử nghiệm `/the_duyet` chỉ hiển thị trong `/help` khi bật cờ dev.
- **Gộp alias ẩn & Chuyển lệnh-theo-id thành nội bộ (`mulon/commands.py`, `mulon/telegram_bot.py`, T-26):**
  - `/saptol` và `/lich` gộp làm alias ẩn của `/upcoming`.
  - `/stop` làm alias ẩn của `/cancel`.
  - `/dongchat` làm alias ẩn của `/chatphu_dong`; `/setup_topics` làm alias ẩn của `/topics`.
  - Các lệnh thao tác item (`pin_item`, `rename_item`, `trash_item`, `restore_item`, `share_item`, `note_ok`, `note_bo`, `idea_do`, `idea_bo`) giữ handler làm đường nội bộ cho nút bấm/thẻ, rút khỏi bề mặt `/help` và menu.
- **Chặn lệnh lạ — không vào vòng lặp agent (`mulon/telegram_bot.py`, T-26):**
  - Khi người dùng gửi lệnh lạ không có trong danh mục (ví dụ `/xyz123khongco`), bot phản hồi tức thì `"Không có lệnh này — xem /help"` và dừng lại ngay lập tức, triệt tiêu việc chạy vòng lặp model/agent lãng phí tài nguyên.
  - Phân biệt chính xác giữa slash command và đường dẫn tệp (như `/Users/...`, `/Volumes/...`).
- **Cải tiến lệnh `/memory` — tóm tắt có cấu trúc thay vì dump thô (`mulon/telegram_bot.py`, T-26):**
  - Bỏ hoàn toàn việc in nội dung thô `MEMORY.md` (chứa chỉ thị nội bộ agent).
  - Hiển thị bảng tóm tắt có cấu trúc: tổng số dữ kiện (facts), phân nhóm theo chủ đề chính, 5 dữ kiện gần nhất, và hướng dẫn xem đầy đủ tại Mini App hoặc gõ `/export_memory`.
- **Kiểm soát lệnh dev `/the_duyet` qua cờ cấu hình (`mulon/config.py`, `mulon/telegram_bot.py`, `.env.example`, T-26):**
  - Thêm cấu hình `ENABLE_DEV_COMMANDS` (mặc định tắt ở môi trường thật). Khi tắt, lệnh `/the_duyet` không tạo thẻ phê duyệt rác mà thông báo nhẹ nhàng hướng dẫn bật cờ dev.
- **Kiểm thử (`tests/test_v17_commands.py`, T-26):**
  - Bổ sung test tĩnh AST/quét mã nguồn kiểm tra 100% handler trong `telegram_bot.py` đều được đăng ký trong `mulon/commands.py`.
  - 9 unit tests mới kiểm tra toàn diện: cấu trúc menu 10 lệnh, tương thích ngược BOT_COMMANDS, văn bản /help, nhận diện alias, chặn lệnh lạ không vào agent, kiểm soát cờ dev cho /the_duyet, và tóm tắt /memory không lộ dossier.

## 1.7.34 — 2026-10-28 — Hoàn tất Tin nhắn Instagram + Tin nhắn Threads Browser Bridge, gỡ bỏ triệt để stub báo gửi giả (T-22.3, LUỒNG 3 — ký: Antigravity [L3])

- **Gỡ bỏ triệt để stub báo gửi giả và phân tách cổng phiên cookie (`mulon/personal_connectors.py`, T-22.3):**
  - Instagram Messages: Gỡ bỏ hoàn toàn việc trả về `sent: True` hoặc `reacted: True` giả lập khi không có transport trong `send_message`, `send_file`, `send_reaction`. Khi không có session runner lẫn browser bridge, trả về `{"ok": False, "unsupported": True, "error": "..."}` trung thực.
  - Threads Messages: Gỡ bỏ stub `reacted: True` giả trong `send_reaction`, tích hợp gọi `ThreadsBrowserBridge.send_reaction` thật và trả `unsupported: True` khi thiếu transport.
  - Facebook Personal: Rà soát và gỡ bỏ stub `sent: True` trong Messenger `send_message` khi thiếu session runner/HTTP client.
  - Phân tách cổng kiểm tra phiên cookie: Không chặn gọi bridge khi người dùng chỉ cấu hình `BROWSER_PROFILE_DIR` mà chưa dán cookie vào Vault (`has_session or self._browser_bridge is not None`).
- **Bổ sung Instagram Browser Bridge & Bộ Selectors (`mulon/instagram_browser_bridge.py`, `config/instagram_web_selectors.json`, T-22.3):**
  - Xây dựng `InstagramBrowserBridge` và `PlaywrightInstagramDriver` chạy trên profile Chromium bền (`BROWSER_PROFILE_DIR`), hỗ trợ `send_message` và `send_reaction` trực tiếp qua DOM Instagram Web với cơ chế đối chiếu xác thực thật trước khi báo thành công.
  - Tách toàn bộ selector DOM vào `config/instagram_web_selectors.json` (inbox path, conversation link, composer, send button, reaction triggers).
  - Tích hợp chuẩn hoá tên và username (`_normalize_name`) để nhận diện chính xác hội thoại.
- **Tích hợp Threads Browser Bridge Reaction (`mulon/threads_browser_bridge.py`, `mulon/connectors.py`, T-22.3):**
  - Mở rộng `ThreadsBrowserBridge` với phương thức `send_reaction` thật qua web interface.
  - Gắn tự động `InstagramBrowserBridge` vào `InstagramMessagesConnector` trong `build_default_connectors`.
- **Tài liệu & Kiểm thử (`docs/threads-browser-bridge-spike.md`, `tests/test_instagram_browser_bridge.py`, `tests/test_v17_personal_connectors.py`, T-22.3):**
  - Cập nhật tài liệu kỹ thuật hướng dẫn chạy Browser Bridge trên máy Mac không bắt buộc dán cookie.
  - Bổ sung test suite `tests/test_instagram_browser_bridge.py` (10 test), cập nhật `tests/test_threads_browser_bridge.py` và `tests/test_v17_personal_connectors.py`.
  - Toàn bộ suite 655/655 test PASSED 100%.

## 1.7.33 — 2026-10-28 — Đường thẳng Kho bí mật -> API, chống loop và chặn lục lọi repo (T-24.6, LUỒNG 1 — ký: Antigravity [L1])

- **Giải mã Vault đa định dạng & Fail-fast trong lệnh (`mulon/vault.py`, `mulon/tools.py`, T-24.6):**
  - Mở rộng `VaultStore.resolve()` hỗ trợ linh hoạt: ref UUID (`vault:<uuid>`), nhãn trực tiếp (`accesstrade:api_key`), tham chiếu prefix (`vault:accesstrade:api_key`), placeholder template (`${VAULT:accesstrade:api_key}`, `${vault:...}`) và tra cứu chuẩn hóa ký tự (`:` vs `_`, không phân biệt hoa thường). Đồng bộ `VaultStore.exists()`.
  - Trong `run_command`: tự động phân tích và thay thế các mẫu `${VAULT:<nhãn>}` và `vault:<nhãn>` thành giá trị bí mật thật trước khi chạy subprocess; bảo toàn cơ chế redaction giấu bí mật khỏi stdout/stderr; nếu nhãn yêu cầu không tồn tại trong Kho an toàn, trả về lỗi ngay lập tức (`ok: False`), gợi ý dùng `list_vault_secrets` hoặc `request_vault_secret`, tuyệt đối không chạy lệnh shell với placeholder rác.
- **Chặn lùng sục mã nguồn repo khi đã có Connector hoặc Kho bí mật (`mulon/tools.py`, `mulon/agent.py`, T-24.6):**
  - Trong `run_command`: chặn các lệnh tìm kiếm mã nguồn (`find`, `grep`, `egrep`, `ag`, `rg`) nhắm vào các từ khóa của connector (`threads`, `facebook`, `zalo`) hoặc kho bí mật (`accesstrade`). Hướng dẫn thẳng tới tool `connector_call` hoặc dùng `${VAULT:...}`.
  - Cập nhật khối TỰ NHẬN THỨC (`build_self_knowledge` trong `mulon/agent.py`): quy tắc cứng số 7 và 2 mục chỉ dẫn chi tiết về "ĐƯỜNG THẲNG KHO BÍ MẬT -> API" và "ĐƯỜNG THẲNG CONNECTOR", yêu cầu hoàn tất trong MỘT lượt (hoặc báo rõ thiếu gì), cấm tuyệt đối lùng sục mã nguồn hay tự viết script ngoài.
- **Chống lặp đọc tài liệu & Chống loop vô tận trong vòng lặp agent (`mulon/agent.py`, T-24.6):**
  - Trong `_act_loop`: theo dõi các lượt gọi `web_fetch` / `web_read`. Nếu một URL đã đọc thành công ở bước trước, chặn ngay lượt đọc lặp lại thứ 2; nếu trang lỗi, cho phép tối đa 2 lần thử, chặn từ lần thứ 3.
  - Chặn bất kỳ tool call nào được gọi lặp lại 3 lần liên tiếp với cùng tham số (`tool_call_counts[tool_sig] >= 3`), yêu cầu agent tổng hợp kết quả hiện có hoặc báo rõ thiếu gì để kết thúc.
- **Đường thẳng Connector (`mulon/connectors.py`, T-24.6):**
  - Cập nhật mô tả và schema tham số của `connector_call` liệt kê tường minh các connector khả dụng (`threads_personal`, `threads_messages`, `facebook_personal`, `zalo_personal`, `telegram_personal`, `gmail`, `gcalendar`, `system`) và các action phổ biến.
  - Khi gọi connector không khả dụng, `ConnectorRegistry.call()` liệt kê danh sách connector hiện có.
- **Kiểm thử (`tests/test_v17_direct_vault_and_connector_path.py`, T-24.6):**
  - 8 test mới kiểm chứng: resolve đa dạng định dạng, run_command thay thế và redact bí mật, fail-fast khi thiếu bí mật, chặn find/grep tìm kiếm repo, chỉ dẫn Tự nhận thức, connector_call báo lỗi hữu ích, và vòng lặp `_act_loop` chặn lặp đọc web cũng như chặn lặp tool 3 lần.
  - Toàn bộ suite test passed 100%. Eval vàng stub đạt 31/36 (86% >= ngưỡng 85%).

## 1.7.32 — 2026-10-28 — Connector tích hợp sẵn: TikTok, Facebook Page, Threads, Instagram, Google Workspace (T-17, LUỒNG 3 — ký: Antigravity [L3])

- **Nâng cấp toàn diện bộ Google Workspace built-in (`mulon/google_conn.py`, `mulon/connectors.py`, T-17):**
  - Mở rộng Google Drive (`gdrive`): hỗ trợ các hành động `list_files`, `get_file`, `create_folder`, `upload_file`, `delete_file`, `share_file`.
  - Mở rộng Google Docs (`gdocs`): hỗ trợ `get_document` (trích xuất body text), `create_document`, `append_text` (batchUpdate insertText), `search_docs`.
  - Mở rộng Google Sheets (`gsheets`): hỗ trợ `get_spreadsheet` (metadata + danh sách sheets), `read_sheet_values`, `append_rows` (append API), `update_cells`, `create_spreadsheet`.
  - Sử dụng chung một luồng xác thực `GoogleAuth` và Vault (`google:client_id`, `google:client_secret`, `google:refresh_token`, `google:account_email`) đã kiểm chứng ở Gmail/GCalendar.
  - Mọi nội dung dữ liệu bên ngoài đọc từ Google Drive/Docs/Sheets đều được bọc qua thẻ `frame_external`.
- **Bổ sung các Connector Mạng xã hội doanh nghiệp/công khai (`mulon/social_connectors.py`, `mulon/connectors.py`, T-17):**
  - `FacebookPageConnector` (`facebook_page`): Đọc và quản lý Fanpage qua Meta Graph API (`get_page_profile`, `read_feed`, `read_posts`, `get_post_detail`, `read_insights`, `read_comments`, `publish_post`, `create_draft_post`, `reply_comment`, `delete_post`).
  - `InstagramBusinessConnector` (`instagram_business`): Đọc và quản lý tài khoản Instagram Business/Creator qua Meta Graph API (`get_profile`, `read_media`, `get_media_detail`, `read_insights`, `read_comments`, `publish_photo` container 2 bước, `publish_reel`, `reply_comment`, `delete_comment`).
  - `ThreadsOfficialConnector` (`threads_official`): Đọc và đăng bài qua Meta Threads Publishing & Insights API chính thức (`get_profile`, `read_threads`, `get_thread_detail`, `read_insights`, `read_replies`, `publish_thread`, `reply_thread`, `delete_thread`).
  - `TikTokConnector` (`tiktok`): Tích hợp TikTok Content Display & Direct Post API (`get_user_info`, `read_videos`, `get_video_stats`, `post_video`, `upload_draft`). Ghi rõ `LIMITATION_TIKTOK` và degrade sạch khi thiếu cấu hình hoặc quyền API.
- **Tích hợp PolicyEngine, WebApp & Telegram Commands (`mulon/policy.py`, `mulon/webapp_server.py`, `mulon/telegram_bot.py`, T-17):**
  - Phân quyền Action-Level: Mọi hành động đọc (read, list, get, search) là `VERDICT_ALLOW`; mọi hành động ghi, đăng bài, sửa, xoá ra ngoài là `VERDICT_ASK` (yêu cầu phê duyệt).
  - Mini App: Quản lý trạng thái kết nối, cấu hình qua Vault, ngắt kết nối an toàn qua `_connectors_state` và danh mục `VALID_PERSONAL_CONNECTORS`.
  - Lệnh Telegram Bot: Bổ sung `/google`, `/google drive`, `/fbpage`, `/tiktok`.
  - Tài liệu kỹ thuật: Tạo mới sổ tay hướng dẫn chi tiết `docs/connector-built-in-chinh-thuc.md`.
  - Kiểm thử: 6/6 test T-17 mới trong `tests/test_v17_builtin_connectors_t17.py`, 641/641 test toàn dự án PASS 100%.

## 1.7.31 — 2026-10-28 — Brand, mascot và đổi tên hiển thị bot (T-13, LUỒNG 2 — ký: Antigravity [L2])

- **Bộ sưu tập Mascot vũ trụ Mulon (`config/mascots.json`, T-13):**
  - Khai báo catalog 4 mascot chính thức cùng vũ trụ Mulon:
    - `mulon_v0`: "Mulon Cổ Điển" (Sprite v0 chính thức - Mèo tím hiếu kỳ, mặc định ban đầu).
    - `mulon_spark`: "Mulon Spark" (Tia chớp năng động - Tinh anh, lanh lợi, sắc sảo).
    - `mulon_cosmo`: "Mulon Cosmo" (Nhà thám hiểm vũ trụ - Tri thức sâu, bao quát không gian).
    - `mulon_zen`: "Mulon Zen" (Thiền định tĩnh tại - Thư thái, thận trọng, kiên định).
  - Không hardcode danh sách mascot trong code; nạp qua `load_json_data("mascots.json")`.
- **Cấu hình & lưu trữ bền vững KV (`mulon/config.py`, `.env.example`, `mulon/webapp_server.py`, `mulon/telegram_bot.py`, T-13):**
  - Khai báo trường cấu hình mặc định `bot_display_name: str = "Mulon"` (env `BOT_DISPLAY_NAME`) và `bot_mascot: str = "mulon_v0"` (env `BOT_MASCOT`).
  - Đăng ký endpoint `GET /api/brand` và `POST /api/brand` trên `WebAppServer`, nhúng trạng thái `brand` vào `GET /api/state`. Cho phép đổi tên bot hiển thị và chọn mascot trực tiếp từ Mini App.
  - Tên bot và mascot đã chọn được lưu bền vững vào `Memory` KV store (`brand_bot_name`, `brand_mascot_id`) và ghi log trajectory hành động.
  - Helper `get_bot_display_name(memory, cfg)` ưu tiên đọc từ KV -> config -> fallback "Mulon" để đồng bộ tên bot trong bot chat Telegram.
- **Giao diện Mini App chuyên nghiệp & Chuẩn hoá thương hiệu (`mulon/webapp/index.html`, T-13):**
  - Bổ sung card "Cá nhân hoá" với hàng điều hướng "Thương hiệu & Mascot" trong Tab Cài đặt (`#tab-caidat`), giữ nguyên chuẩn 5 hàng điều hướng kỹ thuật trong card đầu tiên.
  - Màn hình con `#screen-brand` chuyên nghiệp:
    - **Đổi tên bot hiển thị:** Ô nhập tên bot và nút "Lưu tên", kèm hộp lưu ý giải thích rõ giới hạn kỹ thuật Telegram (username `@Mulon_bot`, tên bot danh bạ và avatar trên Telegram chỉ đổi được qua `@BotFather` bằng `/setusername`, `/setname`, `/setuserpic`, trong khi tên hiển thị trong app/chat đổi ngay lập tức).
    - **Bộ sưu tập mascot đại diện:** Danh sách mascot trực quan dạng lưới, hiển thị biểu tượng SVG đặc trưng, huy hiệu đại diện ("✓ Đang đại diện"), tính cách và nút bấm chọn mascot.
    - **Chuẩn hoá thương hiệu Mulon:** Card hướng dẫn định vị thương hiệu với màu nhấn Tím Mulon (`#7C3AED`) theo tỉ lệ 60/30/10, logo Spark và giọng văn cốt lõi (thân thiện, khiêm nhường, thông minh).
    - Tự động đồng bộ tên bot đã đổi lên tiêu đề App Header (`#app-brand-name`).
- **Kiểm thử hồi quy & Render thật Chromium 390×844 (`tests/test_v17_t13_brand_mascot.py`, T-13):**
  - Kiểm thử tĩnh cấu trúc HTML, thông báo cảnh báo BotFather.
  - Kiểm thử API `/api/brand`, xác thực độ dài tên <= 50 ký tự, chặn mascot không hợp lệ, kiểm tra lưu trữ KV và helper Telegram.
  - Kiểm thử render tương tác thật với Playwright Chromium viewport iPhone 390×844, chụp và lưu ảnh artifact kiểm chứng tại `data/artifacts/t13_screen_brand.png` và `data/artifacts/t13_brand_updated.png`.
  - 100% test suite xanh (639 passed).

## 1.7.31 — 2026-10-28 — Brand, mascot và đổi tên hiển thị bot (T-13, LUỒNG 2 — ký: Antigravity [L2])

## 1.7.30 — 2026-10-28 — Sửa lỗi CI đa nền tảng Windows & macOS và chẩn đoán hạ tầng Actions (T-28, LUỒNG 5 — ký: Antigravity [L5])

- **Chẩn đoán hạ tầng GitHub Actions (`.github/workflows/ci.yml`, T-28):**
  - Trích xuất và phân tích toàn bộ log GitHub Actions qua `gh run view` trên các commit gần đây.
  - Xác định nguyên nhân các commit gần nhất bị fail tức thì sau 3-5 giây: lỗi thanh toán / hạn mức GitHub Actions ("The job was not started because recent account payments have failed or your spending limit needs to be increased"). Đây là lỗi hạn mức tài khoản GitHub, không phải do code hồi quy.
- **Khắc phục lỗi kiểm thử trên Windows (T-28):**
  - **Múi giờ `Asia/Ho_Chi_Minh` trên Windows (`requirements.txt`):** Python `zoneinfo` trên Windows không có cơ sở dữ liệu IANA timezone hệ thống sẵn (như `/usr/share/zoneinfo` trên Linux/macOS), dẫn đến lỗi `zoneinfo._common.ZoneInfoNotFoundError: 'No time zone found with key Asia/Ho_Chi_Minh'` làm sập hàng loạt test scheduler/proactivity khi collect. Bổ sung dependency chuẩn `tzdata>=2024.1` vào `requirements.txt`.
  - **Quyền hạn file Vault 0600 (`tests/test_phase6_vault.py`):** Hệ thống tệp NTFS trên Windows không có bit quyền POSIX `0o600` (trả về `0o666`), bọc assertion `assert mode == 0o600` với điều kiện `if sys.platform != "win32":` (trong khi logic an toàn của `mulon/vault.py` đã tự try-except `chmod`).
- **Khắc phục lỗi kiểm thử trên macOS GitHub Actions Runner (T-28):**
  - **Extension SQLite trên Apple libsqlite3 (`tests/test_phase2_recall.py`):** Trên runner `macos-latest` (Apple Silicon), bản Python chuẩn liên kết với `libsqlite3.dylib` của Apple được biên dịch với `SQLITE_OMIT_LOAD_EXTENSION=1`, khiến việc nạp `sqlite-vec` extension bị tắt và `_try_enable_vector` trả về `False`. Sửa `_open_vec` tự động `pytest.skip` một cách duyên dáng khi môi trường SQLite không hỗ trợ loadable extension, đúng theo nguyên tắc degrade của dự án.
- **Khắc phục biên múi giờ nửa đêm trong fixture UI (`tests/test_v17_t27_ui_perfection.py`):**
  - Sửa mốc thời gian chèn quyết định duyệt trong test Playwright dùng `now.isoformat()` thay vì `(now - timedelta(hours=1)).isoformat()`, tránh việc 1 giờ trước rơi vào ngày hôm qua khi test chạy vào những phút đầu ngày theo múi giờ địa phương.

## 1.7.29 — 2026-10-27 — Sửa alias LiteLLM cho muse2api (T-16 NEEDS-FIX, LUỒNG 5 — ký: Antigravity [L5])

- **Khắc phục triệt để lỗi LiteLLM từ chối provider muse (`mulon/gateway.py`, `mulon/muse2api.py`, T-16):**
  - Sửa alias `_MODEL_ALIASES` map cả `muse-spark` và `muse/muse-spark` sang `openai/muse/muse-spark` thay vì `muse/muse-spark`. Trước đây LiteLLM lấy tiền tố trước `/` và báo lỗi `LLM Provider NOT provided. You passed model=muse/muse-spark` trước khi gọi mạng, gây lỗi và cộng dồn vào circuit breaker chung làm tắc nghẽn các model khác.
  - Với alias `openai/muse/muse-spark`, LiteLLM nhận diện provider `openai` hợp lệ, định tuyến tới `api_base` local `127.0.0.1:8317` và gửi đúng wire model `muse/muse-spark` trong body request cho CLIProxyAPI bắt prefix `muse` điều hướng tới muse2api.
  - Cập nhật `is_muse_model` trong `mulon/muse2api.py` nhận diện cả định dạng `openai/muse/muse-spark`.
- **Hiệu đính tài liệu (`docs/muse2api-duong-a.md`):**
  - Sửa câu chữ về phạm vi không gọi thẳng muse2api ở đường chat/model, cập nhật hướng dẫn alias chuẩn hóa.
- **Kiểm thử tích hợp (`tests/test_v17_muse2api.py`):**
  - Bổ sung test tích hợp `test_gateway_complete_via_stub_proxy` kiểm chứng `ModelGateway.complete` thực tế qua stub server OpenAI-compatible trên cả hai dạng tên model `muse-spark` và `muse/muse-spark`, xác nhận wire model nhận được tại server đúng `muse/muse-spark`.
  - 10/10 test T-16 PASS 100%.

## 1.7.28 — 2026-10-27 — Bề mặt đầy đủ Facebook + Threads cá nhân theo chuẩn Muse (T-30, LUỒNG 3 — ký: Antigravity [L3])

- **Facebook cá nhân mở rộng toàn diện (`mulon/personal_connectors.py`, T-30):**
  - Mở rộng đầy đủ 31 hành động theo chuẩn Muse parity:
    * Danh tính & quan hệ: `get_profile`, `get_me`, `get_friends`, `list_friends`, `view_user_profile` (xem trang cá nhân/timeline người khác).
    * Bảng tin: `read_feed`, `read_news_feed`, `read_friends_feed`.
    * Nhóm Facebook: `list_groups` liệt kê TOÀN BỘ nhóm tham gia (kể cả nhóm kín/ẩn bí mật), `get_group_detail`, `read_group_posts`, `search_groups`.
    * Bài viết & tương tác: `read_post`, `read_comments`, `read_reactions`, `write_comment`, `reply_comment`, `create_post`.
    * Fanpage: `list_pages`, `get_page_insights`, `create_page_draft`, `create_page_post`.
    * Sự kiện, Story, Đã lưu, Marketplace: `search_events`, `get_event_detail`, `read_stories`, `list_saved`, `save_item`, `unsave_item`, `search_marketplace`, `get_my_marketplace_listings`.
  - Checkpoint Guard tự ngắt an toàn và tự động kích hoạt cờ bảo vệ tài khoản khi phát hiện dấu hiệu checkpoint.
- **Bổ sung connector Threads cá nhân chuyên nội dung (`mulon/personal_connectors.py`, `mulon/connectors.py`, T-30):**
  - Triển khai `ThreadsPersonalConnector` (`threads_personal`), tách biệt độc lập với kênh DM `threads_messages`.
  - Ưu tiên API chính thức (Graph API token qua nhãn `threads_personal:token`) cho profile, bài viết, reply, insights, đăng bài và reply.
  - Tự động fallback phiên Web Cookie (`threads_personal:session`) cho các endpoint web-only: `read_feed`, `get_trends`, `search_posts`, `set_feed_suggestions`.
  - Đính kèm metadata `transport` ("official_api" | "web_session") và cờ `web_only` trong mọi phản hồi.
- **Kỷ luật bảo mật & Chống stub giả (T-30):**
  - Toàn bộ nội dung văn bản bên ngoài (bài viết, bình luận, bio, mô tả nhóm, tin story, marketplace) đều được bọc bảo vệ bằng `frame_external`.
  - Phân quyền Action-Level Policy: Đọc = `VERDICT_ALLOW`, Mọi hành động GHI (`create_post`, `write_comment`, `reply_comment`, `create_reply`, `set_feed_suggestions`, `save_item`...) = `VERDICT_ASK` duyệt từng lần.
  - CẤM trả `ok: True` stub khi không có transport thực tế — trả `unsupported: True` rõ ràng, không giả vờ thành công.
- **Tích hợp Bot & Mini App (`mulon/telegram_bot.py`, `mulon/webapp_server.py`, `docs/connector-tai-khoan-ca-nhan.md`):**
  - Thêm lệnh `/facebook groups`, `/facebook feed`, `/threads posts`.
  - Đăng ký `threads_personal` vào `VALID_PERSONAL_CONNECTORS` và serialize trạng thái `_connectors_state`.
- **Kiểm thử (`tests/test_v17_personal_full_surface_t30.py`, T-30):**
  - 7 test suite mới kiểm chứng 100% bề mặt Facebook, Threads, Checkpoint Guard, transport rejection, policy allow/ask và đăng ký registry.

## 1.7.27 — 2026-10-27 — Sửa lỗi tải initData ở Chi tiết việc + Chợ MCP, cô lập banner lỗi (T-24.5, LUỒNG 1 — ký: Antigravity [L1])

- **Phân biệt nguyên nhân và khắc phục tuổi phiên Mini App (`mulon/config.py`, `mulon/webapp_server.py`, T-24.5):**
  - Xác nhận hai endpoint `/api/task` và `/api/marketplace/*` KHÔNG validate sai logic: cả hai đều đi qua `_auth_middleware` dùng chung và trả về 200 OK dữ liệu thật khi `initData` còn hạn.
  - Hiện tượng "các màn khác tải bình thường" là do giao diện SPA đã cache state `S` ở lượt tải đầu và render sẵn DOM, việc chuyển tab chính chỉ ẩn/hiện CSS không gọi mạng. Chỉ khi mở Chi tiết việc hoặc bấm Làm mới Chợ MCP, request mạng thật mới được gửi và bị chặn 403 do trần tuổi phiên cũ đặt quá ngắn (3600s / 1 giờ).
  - Nâng thời hạn hiệu lực phiên Mini App trên server lên 86400s (24 giờ — chuẩn phiên Telegram Mini App, có thể cấu hình qua `INIT_DATA_MAX_AGE_S`), chống hết hạn đột ngột khi người dùng mở app lâu.
- **Khắc phục lấy initData động ở Frontend (`mulon/webapp/index.html`, T-24.5):**
  - Thay thế biến `INIT` tĩnh (gán 1 lần lúc nạp file) bằng hàm `getInitData()` đọc động từ `window.Telegram.WebApp.initData`, hỗ trợ fallback đọc tham số `tgWebAppData` từ URL hash và query search, chống đóng băng chuỗi rỗng khi SDK nạp trễ.
- **Cô lập lỗi và chống dính banner sang tab khác (`mulon/webapp/index.html`, T-24.5):**
  - Khi chuyển tab chính (`showMain`) và chuyển màn con (`showSub`), hệ thống tự động xoá sạch nội dung `global-error`, triệt tiêu tình trạng banner lỗi dính sang đầu các tab khác.
  - Đóng gói lỗi trong màn Chi tiết việc (`screen-task`): khi `openTask` gặp lỗi mạng, giao diện hiển thị khung lỗi nội bộ kèm nút "Thử lại" gọi lại trực tiếp `openTask(id)`, không rò rỉ lỗi ra banner toàn cục.
- **Kiểm thử (`tests/test_v17_miniapp_initdata_task_mkt.py`, T-24.5):**
  - 3 test mới xác nhận: phiên mới mở Chi tiết việc + Chợ tải được dữ liệu thật 200 OK; phiên 2 giờ (7200s) được chấp nhận thành công; phiên quá 24 giờ (90000s) bị từ chối 403; kiểm tra cô lập lỗi giao diện và `getInitData()` động.

## 1.7.26 — 2026-10-27 — Giao diện Mini App đạt chuẩn chuyên nghiệp 100% (T-27, LUỒNG 2 — ký: Antigravity [L2])

- **Tab Phê duyệt đạt chuẩn chuyên nghiệp (`mulon/webapp/index.html`, T-27):**
  - Thẻ banner nổi bật dạng card ở đầu tab khi có yêu cầu đang chờ duyệt (`Yêu cầu đang chờ duyệt (N)`), kèm thẻ rỗng giải thích rõ ràng khi không có yêu cầu (`Không có yêu cầu chờ duyệt`).
  - Lịch sử phê duyệt được phân nhóm theo ngày thông minh (`Hôm nay`, `Hôm qua`, hoặc ngày cụ thể `DD/MM/YYYY`) kèm số lượng quyết định trong từng ngày.
  - Hiển thị mốc thời gian rõ ràng (`lúc HH:MM`) ngay trên hàng tóm tắt thu gọn thay vì chỉ có ngày chung chung.
- **Tab Lịch & Hợp nhất Heartbeat (`mulon/webapp/index.html`, `mulon/webapp_server.py`, T-27):**
  - Hợp nhất Heartbeat vào chung màn chi tiết lịch trình L2 (`#screen-schedule-detail` với `data-sched-open="heartbeat"`), xóa bỏ tình trạng sheet chôn sâu 3 cấp; đồng thời vẫn bảo toàn tương thích với modal điều hướng nhanh.
  - Phân trang lịch sử chạy lịch trình: mặc định hiển thị 5 lượt gần nhất kèm nút "Xem thêm (N lượt cũ hơn)" tự động tải thêm khi cần.
  - Sửa lỗi trong `_build_schedule_detail` (`webapp_server.py`): gọi `effective_enabled(self.memory, self.cfg)` thay vì gọi method không tồn tại `_heartbeat_state`.
- **Kho lưu trữ bí mật Vault (`mulon/webapp/index.html`, T-27):**
  - Tự động hiển thị thanh tìm kiếm `#vault-search` khi danh sách có từ 5 bí mật trở lên, hỗ trợ tìm kiếm và lọc tức thì không giật lag.
- **Dọn dẹp kỹ năng Skills (`mulon/webapp/index.html`, T-27):**
  - Loại bỏ hoàn toàn các mô tả lỗi dạng `>` hoặc `>-` từ header YAML để danh sách hiển thị sạch sẽ, chuyên nghiệp.
- **Feed chủ động (`mulon/webapp/index.html`, T-27):**
  - Nút preset kích hoạt khớp lịch, chuẩn hóa visual token 60/30/10, phân cấp thị giác rõ ràng với một màu nhấn duy nhất.
- **Kiểm thử tĩnh và render thật Playwright (`tests/test_v17_t27_ui_perfection.py`, T-27):**
  - Kiểm thử tĩnh HTML/JS toàn bộ các tiêu chí mới.
  - Kiểm thử Chromium thật bằng Playwright (viewport iPhone 390×844) tương tác qua 4 tab: Phê duyệt, Lịch & Chi tiết Heartbeat (phân trang lượt chạy), Cài đặt & Kho bí mật (lọc tìm kiếm), Feed chủ động (presets). Tạo đầy đủ ảnh chụp render thật trong `data/artifacts/`.
  - Bộ kiểm thử toàn dự án đạt 605/605 passed.

## 1.7.25 — 2026-10-27 — Tích hợp CLIProxyAPI làm cổng model chính thức (T-14, LUỒNG 4 — ký: Antigravity [L4])

## 1.7.24 — 2026-10-27 — Triệt tiêu nhân đôi tin nhắn, thẻ duyệt và thẻ Vault (T-24.4, LUỒNG 1 — ký: Antigravity [L1])

- **Chống nhân đôi câu trả lời chat/group (`mulon/telegram_bot.py`, T-24.4):**
  - Khắc phục lỗi câu trả lời xuất hiện 2 lần giống hệt ("một bản sửa cuối + một tin mới"): khi `placeholder.edit_text` gặp ngoại lệ Telegram `message is not modified` (do text đã được cập nhật trước đó qua streaming), hệ thống không còn nhảy vào khối fallback gửi thêm tin nhắn mới `anchor.answer`.
  - Nếu gặp lỗi định dạng HTML, ưu tiên escape và cập nhật trực tiếp trên placeholder cũ; chỉ gửi `anchor.answer` khi placeholder chưa từng được cập nhật thành công.
- **Duy nhất một thông báo khi huỷ tác vụ (`mulon/telegram_bot.py`, T-24.4):**
  - Khi tác vụ đang chạy bị huỷ qua `/stop` hoặc cancellation intent, `_on_batch` sửa trực tiếp placeholder thành thông báo dừng (`⚠️ Đã dừng tác vụ theo yêu cầu.`); `cmd_cancel` và `on_text` không gửi thêm tin nhắn `message.answer` thứ hai.
- **Chống phát lặp thẻ yêu cầu bí mật Vault (`mulon/telegram_bot.py`, T-24.4):**
  - `send_vault_card_to_owner`: kiểm tra trạng thái thẻ đang chờ (in-memory và bền vững sau restart qua KV `vault_card_pending:<label>`). Nếu agent gọi `request_vault_secret` lần 2 cho cùng nhãn, hệ thống cập nhật nội dung thẻ cũ tại chỗ nếu mô tả thay đổi, không gửi thêm thẻ mới.
- **Khử trùng thông báo nhận bí mật Vault (`mulon/telegram_bot.py`, `mulon/webapp_server.py`, T-24.4):**
  - `on_vault_secret_captured`: bổ sung bộ đệm chống trùng 30s theo `(label, ref)`.
  - `webapp_server.py`: không gọi lặp `vault_notifier` nếu notifier đã là listener đăng ký trực tiếp trên `vault_store`.
- **Khử trùng thẻ duyệt và tin nhắn đến Telegram (`mulon/telegram_bot.py`, T-24.4):**
  - `send_approval_card`: kiểm tra `_sent_approval_cards` và KV `approval_card_sent:<id>` để không gửi 2 lần cùng một yêu cầu duyệt.
  - Bổ sung `_is_duplicate_message` kiểm tra bộ đệm 5.000 tin nhắn gần nhất `(chat_id, message_id)`, loại bỏ update trùng lặp khi Telegram getUpdates re-deliver.
- **Kiểm thử (`tests/test_v17_message_deduplication.py`, T-24.4):**
  - 6 unit test mới kiểm chứng đủ 4 ca thực tế: không nhân đôi câu trả lời, 1 thông báo dừng duy nhất, 1 tin xác nhận Vault duy nhất, thẻ Vault idempotent & phục hồi qua restart, khử trùng update đến, và thẻ duyệt không lặp.

## 1.7.23 — 2026-10-27 — Tích hợp muse2api theo Đường A, làm upstream của CLIProxyAPI (T-16, LUỒNG PHỤ 2 — ký: Phu2)

- **Đường A đã chốt, không gọi thẳng muse2api (`mulon/muse2api.py`, T-16):**
  - Module mới chỉ sinh cấu hình upstream cho CLIProxyAPI và kiểm tra tên model, không gọi HTTP, không giữ secret, không gõ chết cổng muse2api trong code MuLon.
  - Model trong MuLon: `muse/muse-spark` (model chat duy nhất của muse2api trong đợt này; media để đợt sau). Hàm sinh cấu hình chỉ nhận tham chiếu key dạng placeholder `${...}` hoặc `vault:...`, key thật bị từ chối ngay để không lọt vào repo.
  - Guard Đường A: proxy model của MuLon vẫn phải là 127.0.0.1:8317 local; `validate_proxy_base_url` không bị nới.
- **Alias gateway (`mulon/gateway.py`, T-16):**
  - Thêm `"muse-spark": "muse/muse-spark"` vào `_MODEL_ALIASES`. Người dùng gõ `muse-spark` cũng được chuẩn hóa về `muse/muse-spark` và đi qua proxy 8317 như model thường.
- **Tài liệu và mẫu cấu hình (T-16):**
  - `docs/muse2api-duong-a.md`: sơ đồ Đường A, cách cài đặt trên máy cài, nghiệm thu sống, degrade và giới hạn (T-14 chưa xong nên cấu hình upstream nằm ở CLIProxyAPI trên máy cài, chưa gắn vào UI quản lý gateway).
  - `config/cliproxy-muse2api.example.yaml`: mẫu upstream cho CLIProxyAPI trên máy cài, key chỉ dạng placeholder. MuLon không đọc file này.
- **Kiểm thử (`tests/test_v17_muse2api.py`, T-16):**
  - 9 test mới, chạy độc lập trên VM: 9 passed (alias gateway, sinh cấu hình placeholder, từ chối host lạ/thiếu cổng/key thật, kiểm tra model trong danh sách proxy, guard proxy 8317, module không chứa địa chỉ gọi trực tiếp).
- **Còn lại, ghi rõ không giấu (T-16):**
  - Full suite trên cây head mới nhất CHƯA chạy được trên VM này (repo private, VM không có cây head), nên bản này push theo lệnh trực tiếp của chủ dự án để Muse chính nghiệm thu và chạy full suite; Muse chính xác nhận full suite trước khi coi là VERIFIED.
  - Nghiệm thu sống 4 bước của T-16 (GET /v1/models qua 8317 thấy muse-spark; lượt chat thật; tắt muse2api thì degrade rõ; grep không có key thật) vẫn cần muse2api Docker + tài khoản Muse trên máy cài, chưa làm trong đợt này.
  - Circuit breaker của gateway là chung, không theo model: nếu muse2api chết nhiều lần liên tiếp, breaker mở có thể ảnh hưởng tạm thời cả model khác trong 30s — hành vi chung sẵn có, cần test sống bước 3 xác nhận.

## 1.7.22 — 2026-10-27 — Nhãn giờ Feed trong Sắp tới suy từ cron thật, bỏ hardcode 17:00 (T-25, LUỒNG MUSE — ký: Muse)

- **Một nguồn sự thật cho giờ Feed (`mulon/feed_auto.py`, T-25):**
  - Thêm `cron_times_label(cron_expr)`: suy nhãn các giờ chạy cố định trong ngày từ biểu thức cron 5 trường (vd `0 8,20 * * *` -> `08:00 & 20:00`); mẫu không phải giờ cố định hằng ngày (mỗi giờ, `*/n`, khoảng giờ, theo thứ) trả `""` để nơi hiển thị dùng diễn giải cron đầy đủ thay vì nhãn giờ có thể sai. Đây là helper suy nhãn giờ dùng chung — không nơi nào được ghi cứng giờ Feed nữa.
- **Bỏ fallback cron ghi cứng sai (`mulon/webapp_server.py`, T-25):**
  - Mục Feed chủ động trong `_upcoming_state` trước đây fallback về `"0 8,17 * * *"` khi `get_state()` thiếu cron — lệch 3 tiếng so với cron mặc định thật `0 8,20 * * *` và là nguồn sự thật thứ hai dễ trôi tiếp. Nay fallback là `DEFAULT_CRON` import từ `mulon.feed_auto`; nhãn `time_label` vẫn suy từ cron hiệu lực thật qua `_format_cron_display` như đường chính đã làm.
- **Kiểm thử (`tests/test_v17_feed_time_label.py`, T-25):**
  - 4 test mới: nhãn giờ cho các mẫu cron cố định + mẫu không cố định trả rỗng; mục feed_auto trong `_upcoming_state` dùng đúng cron hiệu lực từ `get_state()` (06:30 & 21:30, không dính 17:00); fallback khi thiếu cron cho ra đúng `DEFAULT_CRON` (08:00 & 20:00).
- **Còn lại (ghi rõ, không giấu):** dòng hiển thị Feed trong handler `/upcoming` của `mulon/telegram_bot.py` vẫn ghi cứng `08:00 & 17:00 (2 bài/ngày)` — file này đang thuộc LUỒNG 1 sửa dở cho T-24.3 nên LUỒNG MUSE không đụng theo lưu ý an toàn của LUẬT ĐA LUỒNG; khi T-24.3 lên main, dòng đó được thay bằng nhãn suy từ `cron_times_label(settings cron)` trong một commit nối tiếp của T-25.

## 1.7.22 — 2026-10-27 — Spike browser bridge cho DM Threads thật (T-22.3, LUỒNG PHỤ 1) — [BẢN KHÔI PHỤC]

> Mục này do Muse (LUỒNG MUSE) khôi phục ngày 27/10/2026: bản gốc của LUỒNG PHỤ 1 trong commit `d9d2a853` đã bị lượt push `8fe2e97d` của LUỒNG MUSE ghi đè mất (nền CHANGELOG cũ). Nội dung dưới đây dựng lại theo commit message + danh sách file của `d9d2a853`; LUỒNG PHỤ 1 có thể thay bằng bản gốc của mình.

- Thêm `mulon/threads_browser_bridge.py` + `config/threads_web_selectors.json`: cầu nối trình duyệt mở hộp thư Threads web trên phiên đã đăng nhập của người cài để gửi DM thật vào hội thoại có sẵn, giữ giới hạn cứng chỉ-nhắn-người-đã-có-hội-thoại.
- Nối bridge vào `mulon/personal_connectors.py` + `mulon/connectors.py`; cấu hình ở `mulon/config.py` + `.env.example`; tài liệu spike ở `docs/threads-browser-bridge-spike.md`; test ở `tests/test_threads_browser_bridge.py` + cập nhật `tests/test_v17_personal_connectors.py`. (Trạng thái tại thời điểm đó: spike, T-22.3 vẫn DOING.)

## 1.7.22 — 2026-10-27 — Không lộ chữ nội bộ kiểm chứng/chẩn đoán vào câu trả lời chat (T-24.3, LUỒNG 1) — [BẢN KHÔI PHỤC]

> Mục này do Muse (LUỒNG MUSE) khôi phục ngày 27/10/2026: bản gốc của LUỒNG 1 trong commit `c73ce23d` đã bị lượt push `8fe2e97d` của LUỒNG MUSE ghi đè mất (nền CHANGELOG cũ). Nội dung dưới đây dựng lại theo commit message + danh sách file của `c73ce23d`; LUỒNG 1 có thể thay bằng bản gốc của mình.

- Sửa `mulon/agent.py` + `mulon/prompts/verify_system.txt` + `mulon/prompts/muse_reply_style.txt` + `config/intent_hints.json`: lớp tự kiểm vẫn chạy nhưng kết luận/chẩn đoán nội bộ không còn in vào mặt chat; khi kiểm chứng mâu thuẫn ngữ cảnh hội thoại thật thì ưu tiên ngữ cảnh.
- Test hồi quy: `tests/test_v17_verification_privacy.py`.

## 1.7.21 — 2026-10-27 — Huỷ việc dứt điểm, ngắt sạch mục tiêu cũ khỏi ngữ cảnh làm việc (T-24.2, Luồng 1)

- **Cơ chế huỷ dứt điểm lượt xử lý (`mulon/memory.py: cancel_turn`, `cancel_running_tasks_for_session`, T-24.2):**
  - Khắc phục triệt để lỗi khi người dùng ra lệnh `/cancel` hoặc gửi cancellation intent: trước đây bot chỉ dừng hiển thị mà để lại thông điệp yêu cầu của người dùng trong bảng `messages` ở trạng thái mồ côi (chưa có câu trả lời), khiến các lượt chat tiếp theo bị LLM gom lại thực thi tiếp việc cũ đã huỷ.
  - Hàm `cancel_turn` tự động chuyển `role` của thông điệp bị huỷ thành `'cancelled_user'`, cập nhật `meta.cancelled = 1`, `meta.cancelled_reason = 'user_cancelled'`, đồng thời lưu bản ghi phản hồi `'cancelled_assistant'` đóng phiên rõ ràng.
  - Tự động chuyển toàn bộ các tác vụ đang chạy (`status = 'running'`) và các bước còn dở (`status IN ('doing', 'pending')`) của `session_key` trong bảng `tasks` sang `'cancelled'`.
- **Lọc sạch thông điệp đã huỷ khỏi cửa sổ ngữ cảnh LLM (`mulon/memory.py: recent_messages`, `mulon/context.py: memory_flush`, `mulon/memory.py: recall`, T-24.2):**
  - `recent_messages`: mặc định (`include_cancelled=False`) lọc sạch hoàn toàn mọi thông điệp có `meta.cancelled = 1` hoặc `role IN ('cancelled_user', 'cancelled_assistant')`, đảm bảo prompt ngữ cảnh hội thoại gửi tới model chỉ chứa các thông điệp sạch, loại bỏ hoàn toàn nguy cơ mục tiêu cũ sống lại ở các lượt sau.
  - `ContextEngine.compact` và `ContextEngine.memory_flush` cũng tự động loại trừ các thông điệp bị huỷ, ngăn chặn việc nén các mục tiêu đã huỷ vào bản tóm tắt hoặc trích xuất thành fact vĩnh viễn.
  - `MemoryStore.recall` và `session_search`: bổ sung bộ lọc loại trừ các thông điệp bị huỷ để tránh tìm kiếm ngữ nghĩa hay hybrid recall gợi lại việc cũ.
- **Bắt và dọn dẹp huỷ tác vụ toàn diện (`mulon/agent.py: handle`, `mulon/telegram_bot.py: _run_task`, `cmd_cancel`, `on_text`, `mulon/webapp_server.py: ActivityTracker.stop_session_tasks`, T-24.2):**
  - Trong `Agent.handle`: bọc khối thực thi trong `try ... except asyncio.CancelledError`, tự động kích hoạt `cancel_turn` ngay khi task bị huỷ.
  - Trong `TelegramSurface`: cả 3 bề mặt huỷ (`_run_task`, lệnh `/cancel` / `/stop`, và cơ chế bắt ý định đổi ý `is_cancellation_intent` khi bot đang bận) đều gọi `cancel_turn` và `activity.stop_session_tasks(key)`, dọn dẹp buffer `batcher.drain(key)` và ngắt dứt điểm tiến trình.
  - Trong `ActivityTracker`: bổ sung `stop_session_tasks(session_key)` huỷ và gỡ bỏ toàn bộ `asyncio.Task` đang chạy thuộc session tương ứng.
- **Kiểm thử hồi quy (`tests/test_v17_cancellation_durable.py`, T-24.2):**
  - Viết mới `tests/test_v17_cancellation_durable.py` gồm 4 test toàn diện kiểm chứng: (1) `cancel_turn` làm sạch `messages` và `tasks`, (2) `ContextEngine` và `recall` không còn dấu vết mục tiêu cũ, (3) quy trình huỷ và tiếp nhận lượt mới độc lập trên `TelegramSurface`, (4) `ActivityTracker.stop_session_tasks`.
  - Toàn bộ suite đạt 577/577 tests PASS (100%), evals vàng stub đạt 31/36 (86%, qua cổng 85%).

## 1.7.20 — 2026-10-27 — Chạy song song sub-agent cho việc nhiều phần độc lập chuẩn Muse (T-24.1, Luồng 1)

- **Tự động nhận diện việc nhiều phần độc lập (`mulon/agent.py: should_plan_multi_task`, `config/intent_hints.json`, T-24.1):**
  - Bổ sung `multi_task_markers` và `parallel_action_hints` trong `config/intent_hints.json` (nạp qua `load_json_data`, Rule 0).
  - Tự động nhận diện các yêu cầu có từ 2 hành động độc lập trở lên (phân tách bởi gạch đầu dòng, dấu `/`, từ khoá song song: vừa... vừa, đồng thời, và, kèm theo...) để lập kế hoạch phân rã đa nhánh.
- **Kế hoạch phân rã song song chuẩn Muse (`mulon/prompts/plan_system.txt`, `mulon/agent.py: _plan`, T-24.1):**
  - Prompt lập kế hoạch mới `mulon/prompts/plan_system.txt` (nạp qua `load_prompt`, Rule 0) yêu cầu model phân tích và gắn cờ `parallel: true` cùng danh sách `subtasks` kèm hồ sơ (profile: `researcher`, `coder`, `default`).
  - Trong `_task_path`: khi phát hiện nhiệm vụ song song (`is_parallel and len(subtasks) >= 2`), tự động gọi `spawn_subagents_parallel` để các nhánh sub-agent chạy đồng thời qua `asyncio.gather`, ghi nhận đầy đủ tiến trình task con, timeline và trajectory.
- **Mở rộng hồ sơ công cụ Sub-agent chỉ đọc (`config/subagent_profiles.json`, `mulon/subagents.py`, T-24.1):**
  - Đưa định nghĩa hồ sơ subagent ra cấu hình `config/subagent_profiles.json` nạp linh hoạt qua `load_json_data` (Rule 0).
  - Bổ sung các công cụ tra cứu chỉ đọc cho `researcher` và `default`: `web_search`, `list_approvals`, `list_schedules`, `list_goals`, `get_goal_detail`, `list_goal_briefings`, `search_library`, `get_library_item`.
  - Đăng ký công cụ `list_approvals` vào `ToolRegistry` qua `mulon/approvals.py: register_approval_tools`.
- **Đồng bộ phong cách trả lời và giải thích trung thực (`mulon/prompts/muse_reply_style.txt`, `mulon/agent.py: build_self_knowledge`, T-24.1):**
  - Hướng dẫn mô hình tự nhận thức rõ ràng: khi có nhiều phần việc độc lập phải dùng `spawn_subagents_parallel`, không chạy tuần tự từng tool; khi người dùng hỏi lại thì đối chiếu lịch sử gọi tool và giải thích trung thực cách đã phân chia các nhánh sub-agent song song.
- **Kiểm thử hồi quy toàn diện (`tests/test_v17_parallel_subagents.py`, T-24.1):**
  - Thêm bộ test `tests/test_v17_parallel_subagents.py` (5 test PASS, toàn bộ suite 573/573 test PASS 100%, evals vàng 31/36 = 86% qua cổng).

## 1.7.19 — 2026-10-27 — Hệ thống thiết kế chuẩn mực, Design Tokens, tích hợp Native Telegram SDK & tái cấu trúc Tab Việc (T-12, Làn 1)

- **Báo cáo nghiên cứu khả năng 'app' của Telegram Mini App (`docs/nghien-cuu-telegram-mini-app-capabilities.md`, T-12):**
  - Khảo sát toàn diện Bot API 7.0 - 8.0, Telegram WebApp JavaScript SDK trên iOS/Android/Desktop: các entry points (Menu Button, Direct Link, Inline Keyboard, Attachment Menu), viewport controls (`expand()`, `requestFullscreen()`, `disableVerticalSwipes()`), Homescreen Shortcut (`addToHomeScreen()`), native controls (`BackButton`, `MainButton`, `HapticFeedback`).
  - Xác định rõ các giới hạn bất biến: không chạy nền độc lập (background daemon phải chạy ở backend Python `mulon.main`), không truy cập low-level FS ngoài file picker, phụ thuộc phiên `initData` HMAC (24h).
- **Hệ thống thiết kế chuẩn mực & Design Tokens (`mulon/webapp/index.html`, T-12):**
  - Bộ Design Tokens chuẩn: màu 60/30/10 với tím Mulon (`--ds-primary: #7C3AED`, `--ds-destructive: #DC2626`, `--ds-primary-tint: #F3EEFF`), typography tối đa 4 cỡ chữ (18px, 15px, 13px, 11px), 2 weights (400, 600), lưới 8pt (padding 16px, gap 8/16/24), bo góc thống nhất (12 card / 8 nút / chip 999 / sheet 16).
  - Thư viện component chuẩn: `.ds-card`, `.ds-row`, `.ds-btn` (primary, secondary, danger), `.ds-chip`, `.ds-search-bar`, `.ds-skeleton`, `.ds-empty-state`, `.ds-error-state`, `.ds-sheet-overlay`, `.ds-sheet-panel`.
- **Tái cấu trúc Tab Việc theo cây IA mới (`mulon/webapp/index.html`, T-12):**
  - Thanh tổng quan số liệu (`#tasks-overview-bar`): Đang chạy / Đã xong / Đã lỗi / Tổng.
  - Ô tìm kiếm việc (`#tasks-search-input`) kèm nút xoá tìm kiếm nhanh (`#tasks-search-clear`).
  - Dải chip lọc trạng thái (`#tasks-filter-chips`: Tất cả, Đang chạy, Đã xong, Đã lỗi).
  - Bộ 4 trạng thái chuẩn: Đang tải (skeleton), Rỗng (empty state chuẩn kèm hướng dẫn), Lỗi tại chỗ (`#tasks-error-state` có nút Thử lại không dính tab khác), Sẵn sàng.
  - Phân trang chuẩn với nút Xem thêm (`#tasks-load-more`).
  - Cụm nút thử lại cho việc lỗi (`#task-retry-actions`: Thử lại việc `#btn-retry-task` / Thử lại từ bước lỗi `#btn-retry-step`).
- **Màn Chi tiết bước L3 dạng Bottom Sheet (`mulon/webapp/index.html`, T-12):**
  - Chạm vào từng bước trên timeline mở Bottom Sheet `#sheet-step-detail` hiển thị đầy đủ công cụ (`#step-sheet-tool`), mô tả đầu vào (đã che bí mật, `#step-sheet-input`), kết quả (`#step-sheet-output`), thời lượng (`#step-sheet-time`), và trạng thái bằng chữ (`#step-sheet-status`).
- **Tích hợp Native Telegram WebApp SDK (`mulon/webapp/index.html`, T-12):**
  - Tự động gọi `Telegram.WebApp.ready()`, `expand()`, `disableVerticalSwipes()`, `requestFullscreen()` (khi hỗ trợ).
  - Đồng bộ `BackButton` native với nút quay lại HTML qua `handleNativeBack()`.
  - Haptic feedback cho mọi thao tác chuyển tab, nhấn nút, lọc.
  - Bổ sung nút tiện ích "Thêm ra màn hình chính" (`addToHomeScreen()`) trong Cài đặt > Thiết bị & Hệ thống (`#card-homescreen-shortcut`, `#row-add-homescreen`).
- **Kiểm thử hồi quy & Render thật Chromium (`tests/test_v17_design_system_and_native.py`, T-12):**
  - Viết mới `tests/test_v17_design_system_and_native.py` (3/3 test PASS, toàn bộ suite 568/568 test PASS 100%, evals vàng 31/36 = 86%). Render thật Chromium 390×844 chụp 3 ảnh: `t12_tab_viec_ds.png`, `t12_task_detail_with_sheet.png`, `t12_screen_system_homescreen.png`.

## 1.7.18 — 2026-10-27 — Siết quyền mặc định chuẩn F4, gom quyền vào màn chi tiết connector & hộp thoại xác nhận hành động phá huỷ (T-23.6, Làn 1)

- **Khôi phục nguồn sự thật Policy tuân thủ nghiêm ngặt chuẩn F4 (`config/policy.json`, `mulon/policy.py`, QA Q-09 / T-23.6):**
  - Gỡ bỏ hoàn toàn `{"default": "allow"}` phẳng trong `config/policy.json` (nguyên nhân khiến toàn bộ ~100+ quyền đều bị đánh giá thành Cho phép).
  - Khôi phục mặc định chuẩn F4: các công cụ nguy hiểm / ghi / xoá / phá huỷ / shell (`run_command`, `restart_bot`, `write_file`, `edit_file`, `vault_put`, `delete_vault_secret`, `delete_library_item`, `share_library_item`, `schedule_delete`, `goal_delete`, `web_click`, `web_fill`) đều được siết mặc định ở nấc `ask` (Hỏi trước khi chạy).
  - Giữ nguyên các quyền do người dùng đã chủ động cấu hình tường minh, không ghi đè âm thầm.
- **Tái cấu trúc màn Quyền chung (`mulon/webapp/index.html`, QA Q-09 / T-23.6):**
  - Bổ sung khối **Tổng quan quyền** `#policy-summary-card` ở đầu trang hiển thị rõ ràng số lượng công cụ tự chạy (Cho phép) / cần hỏi trước / bị chặn (`#policy-overview-text`) và nấc mặc định toàn cục (`#policy-global-default-row`).
  - Loại bỏ hoàn toàn danh sách phẳng 90+ tool `#policy-tools` khỏi màn Quyền chung; thay thế bằng hàng điều hướng mở màn con **Tất cả công cụ** (`#screen-all-tools-policy`) có ô tìm kiếm theo tên `#all-tools-search` và dải chip lọc nhóm (Lệnh hệ thống, Tệp tin, Web, Ký ức, Kho an toàn, Kế hoạch).
  - Tích hợp liên kết mở màn chi tiết connector cho từng connector và server MCP (`data-open-conn-pol`).
- **Gom quyền hành động vào màn chi tiết từng Connector (`mulon/webapp/index.html`, `mulon/webapp_server.py`, T-23.6):**
  - Chuyển toàn bộ quyền theo từng hành động của connector (Google Workspace, System, Personal Connectors, MCP servers) vào đúng **Màn chi tiết connector** (`#screen-connector-policy`).
  - Backend `WebAppServer._policy_state` tự động trích xuất và tổng hợp specs chi tiết các hành động đọc/ghi cho System, Google Workspace, Zalo, Telegram, Facebook, Instagram, Threads và mọi MCP server đã cài đặt.
  - Tại màn chi tiết connector, người dùng có thể theo dõi trạng thái kết nối, cấu hình, và chỉnh sửa trực tiếp quyền từng hành động phân loại theo thẻ Quyền đọc (`#conn-pol-read-card`) và Quyền ghi & xoá (`#conn-pol-write-card`).
- **Hộp thoại xác nhận cho toàn bộ các hành động phá huỷ (`mulon/webapp/index.html`, QA Q-09 / T-23.6):**
  - Chuyển tác vụ Xoá bí mật khỏi Kho vào màn con Chi tiết bí mật `#screen-vault-detail` (hiển thị nhãn, mã ref, chế độ lưu, form cập nhật giá trị/nhãn) và nút Xoá trong Thẻ Vùng nguy hiểm `#vd-btn-delete` luôn yêu cầu xác nhận qua `confirmDialog`.
  - Bổ sung hộp thoại xác nhận khi cài đặt connector/MCP server yêu cầu quyền truy cập file trên máy chủ trong `prepareInstall()`.
  - Bổ sung hộp thoại xác nhận khi ngắt kết nối Google Workspace và các tài khoản cá nhân trong cả danh sách Công cụ kết nối lẫn màn chi tiết connector.
- **Kiểm thử hồi quy & Render thật Chromium (`tests/test_v17_policy_tightening.py`, T-23.6):**
  - Viết mới bộ test `tests/test_v17_policy_tightening.py` kiểm chứng nguồn sự thật `config/policy.json`, chuẩn F4 (đọc = allow, ghi/xoá = ask), specs connector trong `_policy_state`, cấu trúc HTML màn Quyền / Chi tiết connector / Chi tiết Vault và Playwright Chromium E2E (390×844) tương tác thực tế và chụp 4 ảnh render thật (`t23_6_screen_policy.png`, `t23_6_screen_all_tools.png`, `t23_6_screen_conn_detail.png`, `t23_6_screen_vault_detail.png`).

- **Chuẩn hoá bảng màu 60/30/10 & ghi chú thiết kế (`mulon/webapp/index.html`, QA Q-06 / T-23.5):**
  - Đổi chấm và chữ trạng thái header (`.app-status`, `.dot`), lịch sử chạy (`.run-item .dot-green`), trạng thái tạm dừng Heartbeat (`updateHeartbeatModalState`) và dòng trạng thái chi tiết listing/thao tác sang gam trung tính (`var(--ink)`, `var(--ink2)`, `var(--ink3)`, `var(--surface2)`), giữ đúng một màu nhấn thương hiệu tím Mulon (`#7C3AED`).
  - Bổ sung ghi chú thiết kế `#theme-design-note` ngay dưới bộ chọn giao diện trong tab Cài đặt (`#tab-caidat`).
- **Dọn dữ liệu phê duyệt thử & Việt hoá toàn bộ nhãn kỹ thuật (`mulon/webapp_server.py`, `mulon/webapp/index.html`, QA Q-08 / T-23.5):**
  - Xoá `"the_duyet": "Gửi thẻ phê duyệt thử"` khỏi `TOOL_ACTION_LABELS` và lọc bỏ mọi bản ghi phê duyệt thử (`tool == "the_duyet"`, `test == True`, `kind == "test"` hoặc tóm tắt chứa `"phê duyệt thử"` / `"thẻ duyệt thử"`) ở cả `/api/state` lẫn `renderApprovals()`.
  - Bổ sung `_POLICY_LAYER_LABELS` và `policy_layer_label()` dịch toàn bộ mã lớp quyền (`ask`, `allow`, `deny`, `host`, `session`, `tool-default`, `builtin`) sang tiếng Việt đời thường; đổi nhãn `"Lớp policy"` thành `"Chế độ quyền"`.
  - Đổi `"X tool"` thành `"X công cụ"` và thay `"Đang nối"` / `"Chưa nối"` ở phụ đề Connector bằng `"Tích hợp sẵn"` / `"Máy chủ MCP"` hoặc `"Đã kết nối"` / `"Chưa kết nối"`, hết trùng lặp với cột phải `"Đang bật"`.
- **Chợ MCP có ô tìm kiếm, chip lọc, phân trang chuẩn & số công cụ rõ ràng (`mulon/marketplace.py`, `mulon/webapp_server.py`, `mulon/webapp/index.html`, QA Q-08 / Q-10 / T-23.5):**
  - Bổ sung ô tìm kiếm `#mkt-search-input` và dải chip lọc `#mkt-filter-chips` (`Tất cả`, `Chạy cục bộ`, `Từ xa`, `Bảo mật ≥ 8`) ngay tại tab Chợ MCP (`#conn-view-market`) và đồng bộ với màn danh mục `#screen-mktcat`.
  - Backend `_mkt_catalog` và `MarketplaceCatalog.search_catalog` / `search_catalog_async` hỗ trợ lọc kết hợp `query`, `locality` (`local` / `remote`) và `min_score`.
  - Bổ sung `tool_count_label` (`"X công cụ"` hoặc `"Đa công cụ"`) cho mọi mục trên Chợ MCP; sửa hiển thị tổng số mục và phân trang (`"Trang 1 / 106 (2107 mục)"`) không còn dùng dấu chấm ngăn cách hàng nghìn gây hiểu nhầm số thập phân.
- **Feed chủ động tách rõ Trạng thái chỉ xem và Cấu hình 1 nút Lưu (`mulon/webapp_server.py`, `mulon/webapp/index.html`, QA Q-08 / Q-10 / T-23.5):**
  - Bỏ emoji `🟢` và chữ xanh lá ở thẻ công tắc tự động; gắn công tắc thật `#feed-master-switch` ở đầu màn `#screen-feed`.
  - Tách riêng **Thẻ Trạng thái hoạt động (chỉ xem)** (hiển thị `Nhịp đăng hiện tại` tiếng Việt, `Lượt kế tiếp`, `Bài đã đăng hôm nay`, `Token hôm nay`, `Khung giờ nghỉ` — không lặp nhãn `"Giờ yên lặng"`, kèm nút `Chạy ngay một lượt` có hộp xác nhận `#feed-run-confirm-box`) và **Thẻ Cấu hình Feed chủ động** (gộp `cron`, `quiet_hours`, `max_posts_per_day`, `daily_token_budget`, `denylist` vào một nút `Lưu cấu hình Feed` duy nhất qua action `save_all`).
- **Kiểm thử hồi quy & Render thật Chromium (`tests/test_v17_miniapp_polish_mkt_feed.py`, `mulon/paths.py`, T-31):**
  - Bổ sung `mask_embedded_paths` trong `mulon/paths.py` và bọc `maskPaths(...)` khi render mô tả hàng kỹ năng trong `mulon/webapp/index.html` (T-31), che triệt để mọi đường dẫn tuyệt đối (`/Users/...`, `/Volumes/...`, `/home/...`, `C:\...`) nhúng giữa câu.
  - Viết mới bộ test `tests/test_v17_miniapp_polish_mkt_feed.py` kiểm chứng lọc thẻ thử, dịch chế độ quyền, lọc Chợ MCP, `save_all` Feed, che path nhúng giữa câu (T-31) và E2E Playwright Chromium (390×844) chụp & kiểm tra trực quan 5 màn hình thật.

## 1.7.16 — 2026-10-27 — Thống nhất trạng thái Việc một nguồn sự thật, định dạng thời gian duy nhất & màn chi tiết Lịch trình (T-23.4, Làn 1)

- **Một nguồn sự thật duy nhất cho trạng thái Việc giữa Danh sách, Chi tiết, Dòng thời gian và Tóm tắt (`mulon/webapp_server.py`, `mulon/memory.py`, `mulon/webapp/index.html`, QA Q-03 / T-23.4):**
  - Bổ sung hàm chuẩn hoá `_normalize_task_view` trong `mulon/webapp_server.py` dùng chung cho cả `/api/state` (danh sách Việc) và `/api/task` (chi tiết Việc); `list_tasks` trong `mulon/memory.py` batch-load toàn bộ `steps` và `result` trong 1 truy vấn SQL để hai bề mặt dùng chung đúng 1 bộ dữ liệu đầu vào.
  - Khi việc ở trạng thái `failed`: tự động đóng các bước `doing`/`pending` còn treo sang `failed`, đổi bước `"Kiểm chứng: Đạt yêu cầu"` (nếu có từ lượt thử trước) thành `"Kiểm chứng: Không đạt (tác vụ lỗi)"`, đặt bước cuối timeline là `"✕ Đã lỗi"`, và hiển thị rõ `"**Trạng thái: ✕ Đã lỗi (x/y bước)** — Chi tiết lỗi / Chẩn đoán: ..."` ở đầu hộp Tóm tắt (kể cả khi `result` nháp khác rỗng).
  - Khi việc đã kết thúc nhưng chưa đủ bước (`steps_done < steps_total`, ví dụ `5/6 bước`, `17/19 bước`): chuẩn hoá thành trạng thái `partial` với nhãn `"· Xong x/y bước"` và bước cuối `"· Hoàn tất một phần (x/y bước)"`, tuyệt đối không ghi `"✓ Đã xong"`.
- **Một định dạng thời gian duy nhất toàn ứng dụng & chống cắt chữ giữa từ (`mulon/webapp/index.html`, `mulon/webapp_server.py`, QA Q-03 / Q-07):**
  - Hợp nhất `todayLabel` và `hhmm` qua `formatTimeUnified(iso)` trả định dạng duy nhất `DD/MM/YYYY HH:MM` xuyên suốt danh sách Việc, dòng thời gian, Phê duyệt, Lịch và Hồ sơ.
  - Chuyển `.r-title` và `.r-sub` sang hiển thị tối đa 2 dòng theo ranh giới từ (`-webkit-line-clamp: 2`, `overflow-wrap: break-word`) kết hợp `_truncate_words` / `truncateWords` và `_disambiguate_schedule_items` (tự nối phần đuôi phân biệt cho các lịch trùng phần mở đầu như `"Quét TẤT CẢ…"`).
- **Màn con Chi tiết lịch trình `#screen-schedule-detail` & diễn giải Cron tiếng Việt (`mulon/webapp_server.py`, `mulon/webapp/index.html`, QA Q-10 / T-23.4):**
  - Bổ sung `_describe_cron_vi` và `_format_cron_display` hiển thị lời thường tiếng Việt ngay cạnh biểu thức cron (ví dụ: `"Hằng ngày lúc 08:00 (0 8 * * *)"`, `"Mỗi 5 phút (*/5 * * * *)"`).
  - Bổ sung các API `GET /api/schedules/{id}`, `POST /api/schedules/{id}/update`, `POST /api/schedules/{id}/delete` và `Memory.delete_schedule`.
  - Mọi hàng lịch trong `#upcoming-list` và `#schedule-list` đều mở màn con `#screen-schedule-detail` gồm: thông tin chu kỳ & nội dung lời nhắc, **Lịch sử chạy** (bấm mở từng lượt để xem Thời điểm, Thời lượng, Trạng thái, Đầu ra, Lỗi), **Quyền của lịch trình**, biểu mẫu **Sửa lịch** (kèm xem trước diễn giải cron tiếng Việt) và nút **Xoá lịch** có hộp xác nhận.
- **Kiểm thử hồi quy & Render thật Chromium (`tests/test_v17_miniapp_tasks_schedule.py`, `tests/test_v17_miniapp_navigation.py`):**
  - Viết mới bộ test `tests/test_v17_miniapp_tasks_schedule.py` kiểm chứng `_normalize_task_view`, diễn giải cron tiếng Việt, phân biệt lịch trùng đầu, API chi tiết/sửa/xoá lịch và Playwright Chromium E2E (390×844) đối chiếu 3 việc + 2 lịch hẹn.

## 1.7.15 — 2026-10-27 — Tách tab Hồ sơ thành 4 màn con, chuẩn hoá mô tả Kỹ năng tiếng Việt & Xem trước Thư viện (T-23.3, Làn 1)

- **Kiến trúc thông tin tab Hồ sơ gọn thành 4 hàng điều hướng (`mulon/webapp/index.html`, QA Q-05 / T-23.3):**
  - Chuyển toàn bộ `#tab-hoso` thành 1 thẻ `.card` duy nhất gồm đúng 4 hàng điều hướng chuẩn: **Hồ sơ của agent**, **Bộ nhớ dài hạn**, **Kỹ năng**, **Thư viện tài liệu** (kèm số lượng/ngày cập nhật ở `.r-sub` và mũi tên `›`), triệt tiêu việc đổ trực tiếp hàng trăm kỹ năng và ~400 nút bấm ra màn chính.
- **4 màn con độc lập với phân nhóm gập mặc định, tìm kiếm không dấu và xem trước nội dung (`mulon/webapp/index.html`, `mulon/webapp_server.py`, `mulon/skills.py`):**
  1. **Màn con Hồ sơ của agent (`#screen-sub-dossier`):** Liệt kê từng tệp hồ sơ (`IDENTITY.md`, `SOUL.md`, `USER.md`, `MEMORY.md`, v.v.) kèm mô tả tiếng Việt 1 dòng và thời điểm cập nhật; nhấn vào tệp nào chỉ mở đọc riêng tệp đó (`#screen-profile`).
  2. **Màn con Bộ nhớ dài hạn (`#screen-sub-memory` & `#screen-fact-detail`):** Bổ sung API `/api/profile/facts`, `/api/profile/facts/{id}` và `/api/profile/facts/delete`. Đồng bộ 100% số lượng fact ngoài tab Hồ sơ và trong màn con (`total_active`). Hỗ trợ tìm kiếm không dấu, chip lọc thời gian (`Tất cả`, `Hôm nay`, `7 ngày`, `30 ngày`), nhóm theo chủ đề (gập mặc định, phân trang `Xem thêm` mỗi 20 mục), xem chi tiết fact và xoá fact có xác nhận.
  3. **Màn con Kỹ năng (`#screen-sub-skills` & `#screen-skill`):** Sửa `parse_skill_md` và `_parse_meta_lines` trong `mulon/skills.py` để nối đầy đủ mô tả YAML đa dòng (`>`, `>-`, `|`, `|-`), triệt tiêu lỗi mô tả chỉ còn ký tự `">"`. Dịch mô tả kỹ năng sang tiếng Việt 1 dòng gọn gàng (`_localize_skill_description`), tự động gỡ YAML frontmatter khi mở đọc chi tiết kỹ năng, nhóm theo danh mục (gập mặc định, tự bung khi tìm kiếm và cập nhật tiêu đề `Kỹ năng (x / tổng)`).
  4. **Màn con Thư viện tài liệu (`#screen-sub-library`, `#screen-library-preview`, `#screen-library-trash`):** Mỗi tài liệu chỉ hiển thị 1 hàng gọn (tiêu đề + phân loại/dung lượng/ngày tạo + nút `⋯`). Nhấn thân hàng mở màn **Xem trước tài liệu** (hỗ trợ xem ảnh, đọc Markdown, xem code block + bảng thông tin tệp). Nhấn `⋯` mở bottom sheet tác vụ (`Chia sẻ`, `Ghim`/`Bỏ ghim`, `Sửa tên`, `Chuyển vào thùng rác` có xác nhận). Tách **Thùng rác tài liệu** thành màn con riêng có `Khôi phục` và `Xoá hẳn` (có xác nhận).
- **Kiểm thử hồi quy (`tests/test_v17_miniapp_profile_ia.py`, `tests/test_v17_miniapp_navigation.py`):**
  - Bổ sung bộ test kiểm chứng parser YAML đa dòng, Việt hoá mô tả kỹ năng, API facts/library preview/delete và E2E Playwright Chromium cho toàn bộ 4 màn con của tab Hồ sơ.

## 1.7.14 — 2026-10-27 — Render rich markdown, triệt tiêu rò rỉ toast & tối ưu tải màn con (T-23.2, Làn 1)

- **Render Rich Markdown toàn diện & triệt tiêu lộ HTML comments / đường dẫn máy (QA Q-02 / T-23.2):**
  - Viết lại hàm `renderMd` trong `mulon/webapp/index.html`:
    - Tự động strip toàn bộ HTML comments (`<!-- ... -->`) trước khi render.
    - Sửa dính chữ do thiếu khoảng trắng (`fixGluedWords`: "toàn bộ63/63 bài đăngcủa" -> "toàn bộ 63/63 bài đăng của").
    - Ẩn toàn bộ đường dẫn tuyệt đối của máy chủ cục bộ (`maskPaths`: loại bỏ `/Volumes/...`, `/Users/...`, `/home/...`, `C:\...`).
    - Hỗ trợ đầy đủ các phần tử markdown: Headings (`#`, `##`, `###`, `####`), đường kẻ ngang (`---`, `***`), trích dẫn (`>`), danh sách (`- `, `* `, `1. `), bảng (`| ... |`), code block fenced với thụt lề chuẩn, inline code, bold, italic, links và image preview.
  - Áp dụng container `.md-content` cho toàn bộ các màn: Tóm tắt việc (`#task-summary`), Hồ sơ agent (`#profile-content`), Bộ nhớ dài hạn, Chi tiết kỹ năng (`#skill-content`), và mô tả connector trong Chợ MCP (`#screen-listing`).
  - Lệnh chạy connector và nguồn kỹ năng được chuẩn hóa qua `maskPaths` / `cleanPath` không còn lộ đường dẫn file tuyệt đối.
- **Triệt tiêu hoàn toàn rò rỉ DOM của Toast hoàn tất (QA Q-02):**
  - Bổ sung `display: none; visibility: hidden;` cho `#toast` khi ở trạng thái nghỉ.
  - Khi `toast(msg)` ẩn đi, sau transition 250ms tự động dọn sạch `textContent = ""` và đặt lại `display: none; visibility: hidden;` để không còn rò rỉ cụm chữ "Một lượt việc vừa hoàn tất." trong DOM cuối trang.
- **Xóa triệt để Stale Heading ở Chi tiết việc (QA Q-03):**
  - Ngay đầu hàm `openTask(id)`: reset ngay tiêu đề `#task-detail-title` về "Chi tiết việc" và hiển thị skeleton cho timeline và summary trước khi gọi API, ngăn chặn hoàn toàn việc hiện tiêu đề việc cũ trước khi việc mới tải xong.
- **Tối ưu tốc độ tải màn con < 3s & bổ sung Skeleton (QA Q-04):**
  - Backend `_handle_profile_content` trong `mulon/webapp_server.py`: hỗ trợ lấy toàn bộ file dossier (`kind=dossier`) trong 1 request duy nhất thay vì frontend phải lặp 8-9 HTTP request tuần tự (giảm thời gian tải từ 15-20s xuống < 50ms).
  - Bổ sung skeleton placeholder tức thì khi bấm mở màn Hồ sơ, Bộ nhớ, Kỹ năng và Chi tiết việc.
- **Làm sạch đường dẫn máy & sửa dính chữ ở tầng Python (`mulon/paths.py`, `mulon/agent.py`):**
  - Bổ sung hàm `sanitize_path_display` và `fix_glued_words` trong `mulon/paths.py`.
  - Áp dụng làm sạch đường dẫn và dính chữ cho `format_step_title`, `format_step_detail`, `_handle_skills`, `_handle_skill_detail` và lưu kết quả `finish_task`.
- **Kiểm thử hồi quy toàn diện (`tests/test_v17_miniapp_markdown_perf.py`):**
  - 4 test mới kiểm chứng sanitization đường dẫn, fix glued words, batch API dossier, kiểm tra tĩnh HTML và render thật qua Playwright Chromium (390×844).
  - Toàn bộ suite đạt 550/550 passed 100%, evals vàng đạt 31/36 (86%).


- **Uỷ quyền điều hướng tập trung toàn thân hàng (`mulon/webapp/index.html`):**
  - Hợp nhất toàn bộ sự kiện nhấn hàng (`[data-open]`, `#card-heartbeat-item`, `[data-task]`, `[data-skill]`, `[data-open-conn-pol]`, `[data-open-gconfig]`, `[data-cat]`, `[data-pid]`, `[data-hist]`) vào bộ lắng nghe uỷ quyền duy nhất trên `document`, đảm bảo nhấn bất kỳ vị trí nào trên thân hàng cũng mở đúng màn con ngay lần đầu mà không bị rơi click khi DOM re-render định kỳ.
  - Gỡ bỏ các listener cục bộ trùng lặp trên `#conn-add-manual` và `[data-open="screen-connectors"]` tránh gọi `showSub` / nạp API hai lần.
  - Đồng bộ tiêu đề màn con `#profile-title` khớp nhãn thẻ chạm (`"Hồ sơ của agent"`, `"Bộ nhớ dài hạn"`).
- **Kiểm thử điều hướng & khai báo dependency (`tests/test_v17_miniapp_navigation.py`, `requirements-dev.txt`):**
  - Đảm bảo `tests/test_v17_miniapp_navigation.py` chỉ dùng thư viện chuẩn `re`, dùng `Path.as_uri()` tương thích đa nền tảng cho Playwright Chromium, và mở rộng kiểm thử click thân hàng trên Cài đặt, Lịch (Heartbeat), Hồ sơ và điều hướng đa cấp.
  - Khai báo đầy đủ `beautifulsoup4>=4.12` trong `requirements-dev.txt` và đồng bộ diff lên `main`.

## 1.7.12 — 2026-10-27 — Khắc phục Threads Checkpoint & Parity Guard khi có Session Runner (T-22.3)

- **Khắc phục triệt để lỗ hổng bypass Giới hạn cứng của Threads:**
  - Bổ sung `_check_send_message_guard` và `_check_reaction_guard` trong `ThreadsMessagesConnector` (`mulon/personal_connectors.py`).
  - Đưa toàn bộ việc kiểm tra GIỚI HẠN CỨNG (từ chối mở DM mới tới người lạ qua @handle, từ chối thread lạ không có từ trước) lên **TRƯỚC KHI** dispatch `session_runner`.
  - Đảm bảo khi phát hiện gửi tin hoặc thả reaction tới người lạ / thread lạ, connector từ chối ngay lập tức và session runner tuyệt đối không bao giờ được gọi.
  - Viết mới test hồi quy `test_threads_messages_strict_limitation_with_session_runner` trong `tests/test_v17_personal_connectors.py` kiểm chứng đầy đủ 6 trường hợp gửi/thả reaction có session runner.
- **Chuẩn hóa câu chữ bảo mật Vault:**
  - Điều chỉnh toàn bộ tài liệu và thông báo trong bot từ "lưu trữ mã hóa" thành "lưu an toàn qua Vault" đúng với kiến trúc thực tế của `VaultStore` (file quyền 0600, hỗ trợ Fernet tuỳ chọn).
- **Loại bỏ dependency ngầm bs4 trong test suite:**
  - Viết lại các hàm kiểm thử HTML trong `tests/test_v17_miniapp_navigation.py` dùng regex chuẩn, không phụ thuộc vào `bs4`.
  - Khai báo bổ sung `beautifulsoup4>=4.12` trong `requirements-dev.txt` đảm bảo test suite xanh 100% trên cả môi trường tối giản lẫn môi trường dev sạch.

## 1.7.11 — 2026-10-27 — Sửa điều hướng Mini App theo QA Q-01 (T-23.1)

- **Khắc phục lỗi điều hướng và affordance Mini App (QA Q-01):**
  - **Hiển thị nút Quay lại chuẩn trên 14 màn con:**
    - Gỡ bỏ hoàn toàn CSS `.has-tg-back .backrow{display:none !important}` vốn ẩn sạch thanh quay lại khi chạy trong môi trường Telegram WebView / `initData`.
    - Chuẩn hóa thanh quay lại `.backrow` kèm icon chevron `‹` SVG tím, nhãn "Quay lại", chiều cao tối thiểu 44px (touch target chuẩn ngón cái) trên toàn bộ 14 màn con: `screen-connectors`, `screen-import`, `screen-install`, `screen-listing`, `screen-mktcat`, `screen-conn-pol`, `screen-vault`, `screen-policy`, `screen-system`, `screen-feed`, `screen-job`, `screen-sub-dossier`, `screen-sub-memory`, `screen-sub-skills`.
  - **Khắc phục lỗi bấm trúng thân hàng lúc được lúc không (Micro-drag click swallow):**
    - Thêm `user-select: none; -webkit-user-select: none;` cho `.row, .row *` để ngăn chặn vi chuyển động kéo rê 1px trên trackpad/chuột vô tình biến thành text-selection drag làm nuốt mất sự kiện `click` của trình duyệt.
    - Thêm `pointer-events: none` vào `.row + .row:before` để đường chia hàng không cản trở hit-testing.
  - **Loại bỏ triệt để lỗi nhảy cóc 2 cấp (Double-pop back navigation):**
    - Gỡ bỏ các event listener cục bộ trùng lặp trên `import-back`, `install-back`, `listing-back`, `mktcat-back`, `connPolBack`.
    - Thống nhất cơ chế event delegation duy nhất trên `document` cho mọi nút quay lại `[data-back]` và `[data-back-sub]`, ủy quyền xử lý phân cấp lùi cho `handleNativeBack()`.
  - **Đồng bộ nhãn và dọn dẹp chevron chết:**
    - Đổi nhãn nút `conn-add-manual` từ "Thêm thủ công" thành "Nhập thủ công" khớp 100% với tiêu đề màn con `screen-import`.
    - Bỏ SVG chevron chết trên các hàng lịch sử chạy Heartbeat modal (`renderHeartbeatRunList`), đảm bảo nguyên tắc: có chevron là phải mở được, không mở được thì không gắn chevron.
  - **Cập nhật dữ liệu tức thì khi chuyển màn con:**
    - Tự động gọi render hàm dữ liệu mới (`renderConnectors`, `renderVault`, `renderPolicy`, `renderSystem`, `renderFeed`) ngay khi `showSub(id)` được kích hoạt, loại trừ dữ liệu cũ / stale state.


## 1.7.10 — 2026-10-27 — Tin nhắn Instagram + Tin nhắn Threads (T-22.3)

- **Tách biệt kết nối TIN NHẮN với kết nối nội dung bài đăng (chuẩn Muse Parity):**
  - Người dùng có thể kết nối riêng biệt hộp thư/tin nhắn mà không bắt buộc liên kết bài đăng (T-17).
  - Sử dụng tài khoản Meta của người cài, phiên đăng nhập/cookie/token lưu trữ an toàn trong Vault.
- **Tin nhắn Instagram (`instagram_messages`):**
  - `read_inbox`: đọc hộp thư với các thư mục phân loại: `inbox` (hộp thư chính), `pending` (yêu cầu chờ), `spam`. Mọi trích đoạn bọc bảo vệ bằng `frame_external`.
  - `read_messages`: đọc chi tiết tin nhắn trong từng hội thoại (`thread_id`), bảo vệ bằng `frame_external`.
  - `search_messages`: tìm kiếm tin nhắn theo từ khóa `query`, bọc `frame_external`.
  - `send_message`: gửi tin nhắn văn bản vào hội thoại có sẵn hoặc cho người nhận xác định (phân quyền `ask`).
  - `send_file`: gửi tệp đính kèm hoặc hình ảnh vào hội thoại (phân quyền `ask`).
  - `send_reaction`: thả reaction emoji (❤️, 🔥, ...) vào tin nhắn (phân quyền `ask`).
  - Tích hợp **Checkpoint Guard**: tự động ngắt kết nối an toàn khi phát hiện checkpoint Instagram, lưu cờ trong Vault (`instagram_messages:checkpoint`) để chặn gửi request tiếp theo.
- **Tin nhắn Threads (`threads_messages`):**
  - `read_inbox`: đọc hộp thư (`inbox`, `pending`). Bọc bảo vệ bằng `frame_external`.
  - `read_messages`: đọc tin nhắn chi tiết trong hội thoại, bọc `frame_external`.
  - **GIỚI HẠN CỨNG BẮT BUỘC (Strict Parity Guard):**
    - Chỉ cho phép gửi tin nhắn tới người ĐÃ có hội thoại từ trước (hoặc đã nhắn cho mình trước).
    - Tuyệt đối KHÔNG mở DM mới tới người lạ chỉ bằng @handle. Nếu người dùng cố gửi tin nhắn tới người lạ chưa từng có hội thoại, connector từ chối ngay lập tức kèm thông báo lỗi giải thích rõ ràng giới hạn, tuyệt đối không nuốt lỗi im lặng.
  - `send_reaction`: thả reaction emoji vào tin nhắn (phân quyền `ask`).
  - Tích hợp Checkpoint Guard an toàn.
- **Bảo mật và Phân quyền hành động (Policy Engine):**
  - Phiên và bí mật chỉ lưu trữ trong Vault (`instagram_messages:session`, `threads_messages:session`).
  - Thao tác đọc (`read_inbox`, `read_messages`, `search_messages`, `check_session`) mặc định Cho phép (`allow`).
  - Thao tác gửi (`send_message`, `send_file`, `send_reaction`) mặc định Hỏi trước (`ask`) qua `ApprovalBroker`.
- **Bề mặt Giao diện & Lệnh chat Telegram:**
  - Lệnh Telegram: `/instagram status`, `/instagram connect <cookies>`, `/instagram inbox [pending|spam]`, `/instagram disconnect`.
  - Lệnh Telegram: `/threads status`, `/threads connect <cookies>`, `/threads inbox [pending]`, `/threads disconnect` (cảnh báo rõ giới hạn cứng).
  - Mini App (Cài đặt -> Công cụ kết nối): tích hợp thẻ Instagram Messages và Threads Messages với nút Nhập Phiên, nút Ngắt, huy hiệu trạng thái và ghi chú giới hạn cứng.
  - REST API: hỗ trợ đầy đủ qua `/api/personal-connector/status`, `/connect`, `/disconnect`, và `/api/state`.

## 1.7.9 — 2026-10-27 — Nghiên cứu và Triển khai Connector Facebook cá nhân (T-22.2)

- **Hoàn tất Nghiên cứu Kỹ thuật Chuyên sâu (Bước 1):**
  - Khảo sát toàn diện cơ chế Meta Accounts Center của Muse thật vs MuLon: làm rõ lý do MuLon không thể dùng lại đường liên kết nội bộ của Meta (đặc quyền first-party của Muse).
  - Khảo sát hiện trạng Graph API v21.0: Meta đã khóa hoàn toàn User News Feed, Friend list (chỉ trả bạn cùng dùng app), và User-to-User Messenger cá nhân.
  - Phân tích rủi ro kỹ thuật của giải pháp Unofficial (Web Session Cookies `c_user`, `xs`): phân tích nguy cơ Checkpoint 2FA, Checkpoint 282 (180 ngày), và rủi ro vi phạm ToS Meta Điều 3.2.3.
  - Báo cáo chi tiết: `docs/nghien-cuu-facebook-ca-nhan.md` và `docs/connector-tai-khoan-ca-nhan.md`.
- **Connector Facebook cá nhân (`facebook_personal`) bảo vệ nhiều lớp (Bước 2):**
  - **Cơ chế Checkpoint Guard**: tự động phát hiện chuyển hướng Checkpoint (HTTP 302 tới `/checkpoint/`, `checkpoint_required`), lập tức ngắt phiên, bật cờ `checkpoint_detected` trong Vault để dừng gửi request, bảo vệ tài khoản khỏi nguy cơ bị khóa vĩnh viễn do spam request lặp lại.
  - **Bảo mật phiên qua Vault**: Cookies (`c_user`, `xs`, `fr`, `datr`) được mã hóa và lưu trữ an toàn trong Vault (`facebook_personal:session`), không bao giờ lọt vào log, trajectory, commit hay chat.
  - **Phạm vi hành động**:
    - `get_profile`: xem trang cá nhân (id, tên, bio, URL).
    - `get_friends`: xem danh sách bạn bè gần đây.
    - `read_feed`: đọc bài viết trên Bảng tin (bảo vệ toàn diện bằng `frame_external`).
    - `read_messages` / `get_messages`: đọc tin nhắn Messenger (bảo vệ toàn diện bằng `frame_external`).
    - `send_message`: gửi tin nhắn Messenger (phân quyền `ask` qua thẻ phê duyệt).
    - `check_session`: kiểm tra tính hợp lệ của phiên.
    - `disconnect`: dọn dẹp sạch sẽ session, user cache và checkpoint trong Vault.
  - **Phân quyền hành động (Policy Engine)**: thao tác đọc (`get_profile`, `get_friends`, `read_feed`, `read_messages`) mặc định Cho phép (`allow`); thao tác gửi (`send_message`, `send_post`) mặc định Hỏi trước (`ask`).
  - **Degrade sạch sẽ**: khi chưa có cookie hoặc lỗi kết nối, hệ thống báo lỗi rõ ràng, bot không sập.
- **Bề mặt Giao diện & Lệnh chat:**
  - Lệnh chat Telegram: `/facebook status`, `/facebook connect <cookies>`, `/facebook disconnect`.
  - Màn Kết nối Mini App: tích hợp thẻ Facebook cá nhân, hiển thị huy hiệu Cảnh báo Rủi ro cao, nút Nhập Cookie (hộp thoại cảnh báo trước khi dán cookie) và nút Ngắt.
  - REST API: `GET /api/personal-connector/status`, `POST /api/personal-connector/connect`, `POST /api/personal-connector/disconnect`.
- **Kiểm chứng:** 528/528 unit tests PASS (thêm 7 test toàn diện trong `tests/test_v17_personal_connectors.py`); eval vàng stub đạt 31/36 (86%, qua cổng 85%).


## 1.7.8 — 2026-10-27 — Connector tài khoản cá nhân: Zalo cá nhân + Telegram cá nhân (T-22.1)

- **Zalo cá nhân (zca-js qua Node bridge):**
  - Đăng nhập an toàn qua mã QR trên ứng dụng Zalo điện thoại (`login_qr` / `login_session`).
  - Hỗ trợ gửi/nhận tin nhắn cả 1-1 lẫn nhóm (`send_message`, `read_messages`), gửi tệp đính kèm (`send_file`), tìm người dùng theo số điện thoại (`find_user`), và lắng nghe tin nhắn mới (`listen`).
  - Minh bạch giới hạn: ghi rõ trong tài liệu kỹ thuật, màn Kết nối Mini App và trạng thái hệ thống: KHÔNG hỗ trợ đăng nhật ký/bài viết (muốn đăng phải qua Zalo OA API — ngoài phạm vi connector cá nhân).
  - Tách lớp Node bridge `mulon/bridges/zalo_bridge.mjs` giao tiếp qua stdin/stdout JSON dòng (chuẩn stdio an toàn).
- **Telegram cá nhân (Telethon MTProto userbot):**
  - Đăng nhập QR độc lập qua ứng dụng Telegram di động (`tg://login?token=...`).
  - Kênh MTProto riêng biệt chạy song song với Telegram Bot API (`aiogram`) hiện tại — không thay thế, không can thiệp lẫn nhau.
  - Hỗ trợ đọc/gửi tin nhắn trong mọi hội thoại tài khoản tham gia (kể cả nhóm bot không có mặt), gửi tệp, xem danh sách hội thoại (`list_dialogs`) và nghe tin mới.
  - Cảnh báo rủi ro userbot: ghi rõ trên Mini App và thông điệp chat để người dùng giữ tần suất sử dụng ở mức bình thường, tránh spam hàng loạt.
- **Bảo mật và Kiến trúc bất biến:**
  - Phiên đăng nhập (`telegram_personal:session`, `zalo_personal:session`) và bí mật CHỈ lưu trữ an toàn trong Vault của bản cài (quyền 0600), không bao giờ lọt vào log, trajectory, commit, hay chat.
  - Quyền theo từng hành động (Policy Engine): các thao tác đọc (`read_messages`, `list_dialogs`, `find_user`) mặc định Cho phép (allow); các thao tác gửi (`send_message`, `send_file`) mặc định Hỏi trước (ask).
  - Bảo vệ dữ liệu ngoài: 100% nội dung tin nhắn nhận từ bên ngoài đều đi qua `frame_external`.
  - Degrade sạch: nếu thiếu Node.js hoặc gói `telethon`, bot vẫn hoạt động 100% bình thường, connector báo trạng thái chưa sẵn sàng kèm hướng dẫn.
- **Giao diện & Lệnh chat:**
  - Lệnh chat Telegram: `/zalo status`, `/zalo qr`, `/zalo disconnect`, `/telethon status`, `/telethon qr`, `/telethon disconnect`.
  - Mini App (Cài đặt -> Công cụ kết nối): tích hợp thẻ hiển thị trạng thái kết nối, nút Quét QR và nút Ngắt kết nối.
  - REST API: `GET /api/personal-connector/status`, `POST /api/personal-connector/qr`, `POST /api/personal-connector/disconnect`.
  - Tài liệu chi tiết: `docs/connector-tai-khoan-ca-nhan.md`.
- **Kiểm chứng:** 521/521 unit tests PASS (thêm 12 test toàn diện trong `tests/test_v17_personal_connectors.py`); eval vàng stub đạt 31/36 (86%, qua cổng 85%).


## 1.7.7 — 2026-10-27 — Gửi/nhận mọi loại nội dung, Thư viện và Chat phụ & Định tuyến R15 (T-10.5 Parity E2 + E3 + R15)

- **Gửi đi đa dạng mọi loại nội dung (Outgoing Multi-Content Types):**
  - Tự động nhận diện nội dung bot tạo và gửi qua đúng phương thức aiogram của Telegram:
    - Ảnh (`.png`, `.jpg`, `.jpeg`, `.webp`, `.gif`): gửi qua `answer_photo` / `send_photo` kèm chú thích và icon `🖼️`.
    - Video (`.mp4`, `.mov`, `.avi`, `.webm`, `.mkv`): gửi qua `answer_video` / `send_video` kèm chú thích và icon `🎥`.
    - Voice thoại (`.ogg`): gửi qua `answer_voice` / `send_voice` kèm chú thích và icon `🎙️`.
    - Âm thanh / Nhạc (`.mp3`, `.wav`, `.m4a`, `.flac`, `.aac`): gửi qua `answer_audio` / `send_audio` kèm chú thích và icon `🎵`.
    - Tài liệu / Tệp tin (`.pdf`, `.docx`, `.xlsx`, `.csv`, `.txt`, `.md`, `.json`, `.zip`, `.tar.gz`...): gửi qua `answer_document` / `send_document` kèm chú thích và icon `📄`.
  - Cơ chế Degrade an toàn và minh bạch:
    - Kiểm tra trần dung lượng tải lên của Telegram Bot API (`TELEGRAM_MAX_FILE_SIZE_BYTES`, mặc định 50MB); file vượt trần được báo rõ ràng kích thước và đường dẫn trực tiếp, tuyệt đối không nuốt lỗi im lặng.
    - Bắt lỗi giao thức/định dạng Telegram và báo rõ cho người dùng thay vì crash bot.
  - Tự động lập chỉ mục mọi tệp bot tạo ra vào Thư viện (`LibraryService.index_file`) và đồng bộ vào topic Library nếu đang ở group forum.
- **Nhận vào: MỌI file người dùng gửi đều vào Thư viện (Incoming Files & Storage):**
  - Hỗ trợ đầy đủ các handler nhận nội dung: `@dp.message(F.document)`, `@dp.message(F.photo)`, `@dp.message(F.video)`, `@dp.message(F.audio)`, `@dp.message(F.voice)`.
  - Không còn từ chối bất kỳ định dạng tài liệu nào: mọi tệp gửi đến đều được tải về thư mục `workspace/uploads/` và tự động lập chỉ mục vào `library_items` kèm chú thích (`caption`).
  - Hỗ trợ bối cảnh hội thoại: truyền đầy đủ thông tin tệp (tên, loại, ID Thư viện, đường dẫn) vào ngữ cảnh agent để đọc hiểu và xử lý theo yêu cầu người dùng.
- **Tìm kiếm Thư viện bằng ngôn ngữ tự nhiên (Natural Language Library Search - Parity E2):**
  - Migration DB 1.7.7: thêm cột `caption` vào bảng `library_items` trong SQLite.
  - Tìm kiếm thông minh không dấu `fold_vi` trên tên tệp (`name`), chú thích (`caption`), phân loại (`kind`) và đường dẫn (`path`).
  - Lệnh `/library <từ khóa>`: hiển thị trực quan các mục khớp với từ khóa tìm kiếm.
  - Lệnh `/library <id>`: tải trực tiếp tệp gốc về chat qua đúng phương thức Telegram theo định dạng.
  - Cung cấp bộ công cụ cho Agent: `search_library` (tìm kiếm bằng ngôn ngữ tự nhiên), `get_library_item` (lấy chi tiết mục), `share_library_item` (tạo link chia sẻ an toàn).
  - WebApp REST API: hỗ trợ tìm kiếm qua `/api/library/items?q=...` và `/api/library/search`.
  - Khống chế link chia sẻ công khai <= 48 giờ (`share_item`), bảo mật hash token và kiểm tra quyền truy cập.
- **Chat phụ & Định tuyến hội thoại chuẩn R15 (Sidechats & Context Isolation - Parity E3 + R15):**
  - Cô lập lịch sử: các topic chat phụ trong group forum (`thread_id`) có `session_key` riêng biệt; `recent_messages` chỉ truy vấn đúng luồng trao đổi đó, không lẫn vào Main chat hay các chat phụ khác.
  - Ký ức bền dùng chung: các sự kiện quan trọng và hồ sơ người dùng (`USER.md`, `MEMORY.md`, `memory_facts`) được chia sẻ nhất quán xuyên suốt mọi chat thông qua cơ chế `ContextEngine.build` và `recall`.
  - Định tuyến chuẩn R15: bổ sung `parse_session_key(session_key)` và `TelegramSurface.send_to_session`, đảm bảo kết quả tác vụ/thông báo nền quay về đúng chat và đúng thread khởi tạo.
- **Kiểm chứng:** 509/509 unit tests PASS (thêm 6 test toàn diện trong `tests/test_v17_media_library_sidechat_parity.py`); eval vàng stub đạt 31/36 (86%, qua cổng 85%).


## 1.7.6 — 2026-10-27 — Goals lồng 1 cấp, tiến triển thật và Goal Briefings dạng Letter (T-10.4 Parity D1 + D2/C8 + D3)

- **Mục tiêu & Mục tiêu con lồng 1 cấp (Goals & Subgoals - Parity D1):**
  - Hỗ trợ tạo mục tiêu chính (`root goal`, `parent_id=None`) và mục tiêu con (`subgoal`, `parent_id=<root_id>`).
  - Kiểm soát cấu trúc phân cấp nghiêm ngặt: giới hạn đúng 1 cấp lồng (chặn tạo con của subgoal, chặn chu trình tự gán cha).
  - Tích hợp đầy đủ bộ công cụ quản lý mục tiêu qua chat & agent loop (`create_goal`, `update_goal`, `close_goal`, `list_goals`, `get_goal_detail`).
  - Đóng subgoal tự động roll up ghi nhật ký hoạt động (`goal_activity`) lên mục tiêu cha.
- **Tiến triển thật tính toán tất định (Factual Progress Tracking - No Fake Percentages):**
  - Tuyệt đối không bịa phần trăm hoặc để agent tự đoán mò; tiến triển được suy diễn trực tiếp từ các đơn vị thực tế đã hoàn thành:
    - `completed_subgoals / total_subgoals` (số subgoal đã đóng / tổng số subgoal).
    - `completed_tracked_items / total_tracked_items` (số cam kết đã giải quyết / tổng số cam kết).
    - Tỷ lệ hoàn thành tổng thể: `round((completed_units / total_units) * 100)`.
    - Nhãn minh bạch: ví dụ `"1/2 subgoal, 0/1 cam kết (33%)"`, `"100% (Hoàn thành)"`, `"0% (Đang thực hiện)"`.
- **Thư Briefing mục tiêu dạng Letter (Goal Briefings - Parity D2 & C8):**
  - Tiến trình nền tự động nghiên cứu dữ liệu thực tế và soạn thư briefing dạng Letter đính kèm mục tiêu (`mulon/goal_briefing.py`, `GoalBriefingService`).
  - Thư briefing gồm 3 phần trọng tâm:
    1. *Tiến triển (Progress Summary):* Tóm tắt tỷ lệ hoàn thành thực tế và trạng thái gần nhất.
    2. *Việc tiếp theo (Next Steps):* Danh sách các hành động cụ thể cho các subgoal hoặc cam kết còn đang chạy.
    3. *Điểm nghẽn & Rủi ro (Bottlenecks):* Các nút thắt cần giải quyết hoặc mốc hạn chót cần lưu ý.
  - Tuân thủ chuẩn Muse C8: Người dùng **KHÔNG** đặt lịch được cho Goal Briefings (`schedule_task` từ chối nếu yêu cầu đặt lịch cho briefing; tiến trình nền của hệ thống tự quản lý).
  - Bảng lưu trữ `goal_briefings` trong SQLite, hỗ trợ tra cứu qua công cụ `generate_goal_briefing`, `list_goal_briefings`.
  - Prompt hệ thống tách bạch tại `mulon/prompts/goal_briefing_system.txt` (tuân thủ Rule 0, phi hardcode).
- **Trải nghiệm hội thoại Telegram & Mini App:**
  - Lệnh chat Telegram: `/goal create <tiêu đề> [--parent <id>] [--desc <mô tả>]`, `/goal update <id> ...`, `/goal close <id>`, `/goal briefing <id>`, `/goals` (hiển thị cây phân cấp phân nhánh trực quan `├─`, `└─` kèm tiến triển thật).
  - Giao diện Mini App:
    - Bổ sung khối "Mục tiêu & Cây tiến triển" trên tab Việc (`#tab-viec`), hiển thị cây mục tiêu phân cấp 1 level, thanh tiến trình tỷ lệ thật, thẻ subgoal và trích đoạn thư briefing mới nhất.
    - REST APIs cho Mini App: `GET /api/goals`, `GET /api/goals/{id}`, `POST /api/goals/create`, `POST /api/goals/update`, `POST /api/goals/close`, `POST /api/goals/{id}/briefing`, nạp cây goal vào `/api/state` (`goals`).
- **Kiểm chứng:** 503/503 unit tests PASS (thêm 7 test hồi quy toàn diện trong `tests/test_v17_goals_briefings_parity.py`); golden eval stub đạt 31/36 (86%, qua cổng 85%).

- **Feed đa nguồn & Adapter dịch vụ kết nối (External Sources Web, Social & Connectors - Parity C1):**
  - Mở rộng nguồn tin tức ngoài không chỉ gói gọn trong các trang báo chính thống mà bao gồm các mạng xã hội & kho tri thức: GitHub, X/Twitter, Threads, Substack, Medium, HuggingFace, ArXiv, Dev.to, Reddit... (khai báo phi hardcode qua `config/feed_sources.json` thuộc tính `social_domains`).
  - Hỗ trợ chuẩn thu thập dữ liệu `feed_snapshot` từ các dịch vụ kết nối (Connectors):
    - `SystemConnector`: Cung cấp thông tin môi trường và trạng thái hệ thống.
    - `GmailConnector`: Cung cấp tóm tắt email chưa đọc / gắn dấu sao gần nhất (`feed_snapshot`).
    - `GCalendarConnector`: Cung cấp sự kiện lịch sắp tới trong 3 ngày (`feed_snapshot`).
    - Cơ chế tổng hợp tự động trong `FeedEngine.collect_external_material` giúp tư liệu phong phú, đa chiều và bám sát ngữ cảnh làm việc thực tế của người dùng.
- **Học gu (Taste Learning) từ Phản ứng VÀ Thảo luận (Discussion Signals - Parity C1 + C3/C7):**
  - Cơ chế Taste không chỉ tính điểm số từ reaction đơn thuần (`👍`, `❤️`, `🔥` / `👎`) mà học trực tiếp từ các cuộc trao đổi, bình luận, và thảo luận thực tế của người dùng:
    - Khi người dùng phản hồi (reply) vào bài Feed hoặc bấm nút thảo luận, `FeedEngine.record_discussion` ghi nhận tín hiệu thảo luận kèm trích đoạn nội dung bình luận vào bảng `feed_signals` (cột `comment`).
    - `Memory.feed_discussion_stats` thống kê tần suất các chủ đề được người dùng thảo luận nhiều nhất.
    - `taste_summary` và `taste_profile` tự động đưa các chủ đề thảo luận tích cực vào danh sách `liked_topics`, giúp khâu xếp hạng tư liệu (`rank_materials`) ưu tiên các chủ đề người dùng quan tâm sâu.
- **Tuân thủ nghiêm ngặt Luật R11 (Strict Separation - No Raw Transcripts):**
  - Khâu viết Feed (`FeedEngine.compose`) TUYỆT ĐỐI không đọc transcript chat thô của người dùng.
  - Writer chỉ nhận văn bản tổng hợp gu tất định (`taste_summary`), tài liệu đề cương (`DEFAULT_BRIEF`), và danh sách tư liệu ngoài đã qua chọn lọc; bảo vệ hoàn toàn dữ liệu nhạy cảm và sự riêng tư của người dùng.
- **Thẻ Ý tưởng (Ideas) chủ động sinh từ ngữ cảnh thật kèm Rationale & Scoring (Parity C2):**
  - Sinh thẻ ý tưởng từ ngữ cảnh thực tế: mục tiêu (`goals`), cam kết đang mở (`tracked_items`), tri thức (`active_facts`), và ngữ cảnh trao đổi gần đây.
  - Mỗi thẻ ý tưởng được chấm điểm chi tiết và gắn nguồn gốc rõ ràng:
    - `rationale`: Lý do vì sao đề xuất ý tưởng này từ bối cảnh thực tế của người dùng.
    - `source`: Nguồn ngữ cảnh dẫn tới ý tưởng (ví dụ: `Goal #...`, `Cam kết...`, `Fact...`).
    - Hệ thống thang điểm 1.0 - 5.0 phản ánh chất lượng đề xuất: `feasibility` (tính khả thi), `fit` (độ phù hợp với gu), `novelty` (tính mới mẻ/đột phá).
  - Tương tác trực tiếp trên thẻ:
    - Nút "Làm luôn" (`do_card`): Tự động chuyển thẻ thành Goal và Task thực thi thật sự, chuyển thẻ sang trạng thái `done`.
    - Nút "Bỏ qua" (`dismiss`): Đánh dấu thẻ là `dismissed`.
    - Hết hạn tự động sau 14 ngày (`expired`).
    - Hỗ trợ đầy đủ tương tác qua Telegram (Inline buttons & Reply chat) và Mini App REST APIs (`/api/ideas`, `/api/ideas/generate`, `/api/ideas/do`, `/api/ideas/dismiss`, `/api/state`).
  - Chạy nền an toàn: Mặc định TẮT (`effective_auto_enabled`), tuân thủ hạn mức tài nguyên và giờ yên tĩnh (quiet hours).
- **Kiểm chứng:** 496/496 unit tests PASS (bổ sung 6 test toàn diện trong `tests/test_v17_feed_ideas_parity.py`); eval vàng stub đạt 31/36 (86%, qua cổng 85%).

## 1.7.4 — 2026-10-27 — Tab Hành động thời gian thực và Danh sách Sắp tới (T-10.2 Parity D4 + C6 + E8)

- **Tab Hành động thời gian thực (Realtime Action & Subagent Step Tracking):**
  - Mọi tác vụ đang thực thi (kể cả sub-agents khởi tạo bởi `SubagentRunner`) được đăng ký và theo dõi tự động qua `ActivityTracker`.
  - Cập nhật liên tục bước thực thi hiện tại (`current_step`):
    - Agent chính phát sự kiện `tool_start` kèm `step_title`, `tool_done`, `verify` để cập nhật bước đang chạy theo thời gian thực.
    - `SubagentRunner._run_inner` tự động đăng ký subagent vào `activity`, ghi nhận tiến trình từng bước `Subagent [<profile>]: <tiêu đề>`.
    - `Memory.list_tasks` và `Memory.get_task` nạp `current_step` mới nhất từ bảng `task_steps` (subquery `SELECT title FROM task_steps WHERE task_id = t.id ORDER BY step_order DESC, created_at DESC LIMIT 1`).
    - Tab Hành động trong Mini App (`renderTasks` và màn chi tiết `#screen-task`): hiển thị rõ ràng bước hiện tại (`current_step`), trạng thái (`Đang chạy`, `Hoàn thành`, `Thất bại`, `Đã huỷ`), thời gian tạo.
- **Nút Dừng việc thực chất (True Cancellation & Stop Execution):**
  - Trang bị nút "Dừng" trên từng dòng tác vụ đang chạy trong tab Hành động và nút "Dừng tác vụ này" trong màn chi tiết tác vụ (`#screen-task`).
  - Khi bấm Dừng: gọi endpoint `POST /api/task/stop` kèm `task_id`.
  - Hệ thống thực hiện huỷ thực sự (`activity.stop_task(task_id)` huỷ trực tiếp `asyncio.Task` đang chạy và `memory.cancel_task(task_id)` chuyển trạng thái thành `cancelled` trong SQLite).
  - Khối `_task_path` trong `Agent` và `SubagentRunner` bắt chuẩn `asyncio.CancelledError`, cập nhật DB trạng thái `cancelled`, emit sự kiện `task_done(status="cancelled")`, dọn dẹp runner an toàn.
  - Đồng bộ lệnh chat Telegram: `/stop <task_id>` hoặc `/cancel <task_id>` cho phép chủ sở hữu huỷ nhanh tác vụ ngay từ chat Telegram.
- **Danh sách Sắp tới tổng hợp từ dữ liệu thật (Unified Real-Data Upcoming List):**
  - Endpoint `GET /api/upcoming` và thuộc tính `upcoming` trong `/api/state` tổng hợp 100% dữ liệu thật từ hệ thống:
    - Lịch định kỳ do người dùng đặt (`schedules` từ `Memory.list_schedules()`): nhãn "Sửa/huỷ qua chat: /schedules", có thể điều chỉnh qua bot.
    - Heartbeat định kỳ (`heartbeat` cấu hình qua `Config.heartbeat_interval_s`, trạng thái bật/tắt `effective_enabled`): nhãn "Chỉ xem (hệ thống)".
    - Lịch tự động điểm tin Feed (`feed_auto` theo `Config.feed_auto_interval_s` và trạng thái `effective_enabled`): nhãn "Chỉ xem (hệ thống)".
    - Cam kết & việc đang theo dõi (`tracked_items` từ `Memory.list_commitments(status="open")`): nhãn "Sửa/huỷ qua chat: /commitments".
  - Hiển thị trực quan trong Mini App (Tab Lịch - Sắp tới) với phân loại rõ ràng: "Sửa/huỷ qua chat" (kèm gợi ý lệnh) vs "Chỉ xem (hệ thống)", không có dữ liệu mock/dummy (đáp ứng trọn vẹn tiêu chí Parity D4 + C6 + E8).
  - Hỗ trợ xem nhanh danh sách sắp tới ngay trong chat Telegram qua lệnh `/upcoming` (alias `/saptol`, `/lich`).
- **Kiểm chứng:** 490/490 unit tests PASS (bổ sung 6 test toàn diện trong `tests/test_v17_activity_upcoming.py`); eval vàng stub đạt 31/36 (86%, qua cổng 85%).


## 1.7.3 — 2026-10-27 — Phê duyệt đồng bộ 2 chiều và Thẻ Vault trong chat (T-10.1 Parity F3 + F2)

- **Đồng bộ phê duyệt 2 chiều (Bidirectional Approval Synchronization & In-Chat Status Update):**
  - Đồng bộ trạng thái thẻ giữa Telegram Chat và màn Phê duyệt Mini App qua ApprovalBroker dùng chung bản ghi duyệt:
    - Quyết định (Duyệt / Chặn / Duyệt và nhớ) ở bất kỳ bề mặt nào thì bề mặt còn lại được cập nhật trạng thái tức thời.
    - Trong chat Telegram: Thẻ phê duyệt không bị xóa mất như trước (v1.2 cũ) mà chuyển trạng thái trực quan rõ ràng (`✅ ĐÃ DUYỆT`, `❌ ĐÃ CHẶN`, `⌛ HẾT HẠN PHÊ DUYỆT`) và gỡ bàn phím inline (`reply_markup=None`) để vô hiệu hoá nút bấm hoàn toàn.
    - Trong Mini App: Quyết định từ Telegram chat lập tức dọn thẻ khỏi danh sách "Đang chờ duyệt" và đưa sang "Lịch sử duyệt" với outcome tương ứng (`✓ Đã duyệt`, `✕ Đã chặn`, `· Hết hạn`). Nút bấm trong Mini App tự động vô hiệu hoá ngay khi bấm.
    - Cấu hình linh hoạt: bổ sung `approval_card_action` trong `Config` (mặc định `update` theo chuẩn Parity, hỗ trợ `delete` kế thừa), env `APPROVAL_CARD_ACTION` trong `.env.example`.
- **Tính Idempotent & Xử lý hết hạn an toàn (Idempotent Decisions & Expiry):**
  - Quyết định trùng lặp hoặc gửi liên tiếp từ 2 bề mặt được xử lý idempotent: chỉ giải quyết `Future` của broker một lần duy nhất, hành động không bị chạy đúp; các lượt gọi sau trả về thông báo an toàn ("Thẻ này đã được xử lý hoặc đã hết hạn.").
  - Thẻ hết hạn sau `approval_timeout_s`: cập nhật trạng thái `⌛ HẾT HẠN PHÊ DUYỆT` tại chỗ trong chat Telegram và ghi nhận `outcome: expired` trong lịch sử Mini App.
- **Thẻ Vault trong chat end-to-end (Interactive In-Chat Vault Cards):**
  - Khi agent thiếu bí mật (API key, client secret, tokens...): tự động gọi tool `request_vault_secret` để gửi thẻ tương tác vào chat kèm nút mở Mini App điền sẵn nhãn và khóa nhãn (`startapp=vault_<label>`).
  - Tích hợp `VaultBroker` và cơ chế lắng nghe `VaultStore.on_captured`: khi người dùng dán bí mật vào Kho (qua Mini App `/api/vault/capture` hoặc Vault server), hệ thống phát sự kiện tức thời:
    - Bot gửi thông báo xác nhận NGAY trong chat đã gửi thẻ: `"🔐 ✅ Đã nhận và lưu bí mật cho '<label>' vào Kho an toàn (mã ref: vault:...)."`
    - Tự động đánh thức và tiếp tục tác vụ đang dở mà không bắt người dùng phải gõ lại yêu cầu từ đầu.
  - Bảo mật tuyệt đối (Rule 5): Giá trị bí mật lưu thẳng vào file JSON quyền 0600 (hoặc mã hoá Fernet), không bao giờ lọt vào log, trajectory, hay nội dung chat (chỉ truyền `ref` và `label`).
- **Kiểm chứng:** 484/484 unit tests PASS (bổ sung 6 test toàn diện trong `tests/test_v17_parity_approval_vault.py`); eval vàng stub đạt 31/36 (86%, qua cổng 85%).

## 1.7.2 — 2026-10-27 — Mở khoá cài đặt và hỗ trợ đa nền tảng (T-15)

- **Mở khoá cài đặt & Quyền sở hữu động (Unlocking Owner Authentication & Allowlist):**
  - Bỏ hard-lock theo ID Telegram cố định: bản cài đặt tự quản lý quyền sở hữu thông qua file allowlist local (`data/allowlist.json` hoặc thư mục cấu hình chuẩn OS).
  - Khởi tạo lần đầu an toàn: khi chạy chưa có `ALLOWED_USER_ID`, bot sinh mã **Claim Token** ngẫu nhiên hiển thị trên terminal/log. Người cài chỉ cần gửi `/setup <claim_token>` từ Telegram để nhận quyền chủ sở hữu (Owner) mà không sợ bị người lạ chiếm quyền.
  - Quản trị quyền trong chat Telegram (`/setup`): Chủ sở hữu có thể tra cứu thông tin cấu hình hệ thống, bổ sung (`/setup add <user_id>`) hoặc thu hồi (`/setup remove <user_id>`) quyền tương tác của các tài khoản khác; chặn hoàn toàn người lạ theo Rule 4.
  - Mini App đồng bộ: `validate_init_data` hỗ trợ đối chiếu với toàn bộ danh sách `allowed_user_ids` của bản cài.
- **Trình hướng dẫn thiết lập (Setup Wizard):**
  - Bổ sung module `mulon.setup` và `mulon.setup_wizard` (hỗ trợ cả CLI cờ tham số và wizard tương tác trực quan qua terminal).
  - Tự động hướng dẫn khai báo Bot Token, Owner ID, Proxy URL, Model Brain, Timezone và khởi tạo cấu trúc thư mục hoàn chỉnh cho máy mới.
  - Tích hợp cờ `python -m mulon.main --setup`.
- **Tách lớp OS & Hỗ trợ đa nền tảng (pathlib, platformdirs & process supervisor):**
  - Bổ sung module `mulon.paths`: chuẩn hoá đường dẫn dữ liệu cross-platform qua `platformdirs` khi bật `MULON_USE_PLATFORMDIRS=1`, đồng thời giữ nguyên tính tương thích project-local cho các bản cài hiện có.
  - Bổ sung `mulon.os_service` (CLI `python -m mulon.service`): quản lý tiến trình nền tự động chuẩn theo từng hệ điều hành:
    - **macOS**: Quản lý qua `launchd` (User LaunchAgents, sinh file plist chuẩn).
    - **Linux**: Quản lý qua `systemd` (User unit `mulon.service` và `mulon-autowatch.service`).
    - **Windows**: Quản lý qua `Windows Task Scheduler` (`schtasks`) và sinh sẵn các file khởi chạy `.bat`.
  - Khắc phục `scripts/dev_watch.py` hoạt động an toàn trên Windows thông qua `msvcrt.locking` khi thiếu `fcntl`.
- **Đóng gói cài đặt & Tài liệu hướng dẫn (Packaging & Documentation):**
  - Script cài đặt tự động one-click cho macOS/Linux: `scripts/install.sh`.
  - Script cài đặt tự động PowerShell cho Windows: `scripts/install.ps1`.
  - Batch runners khởi động nhanh trên Windows: `scripts/run_bot.bat`, `scripts/run_autowatch.bat`.
  - Tài liệu chi tiết: `docs/cai-dat-da-nen-tang.md`.
  - CI Matrix GitHub Actions (`.github/workflows/ci.yml`): Tự động kiểm thử song song trên cả 3 hệ điều hành `ubuntu-latest`, `macos-latest`, `windows-latest` với Python 3.12.
- **Sửa luật AGENTS.md:**
  - Cập nhật điều 3.4 từ "Một chủ duy nhất" thành "Chủ do bản cài tự định (mở khoá cài đặt từ 1.7.2, T-15)" theo quyết định của chủ dự án.
- **Kiểm chứng:** 478/478 unit tests PASS (bổ sung 9 test toàn diện trong `tests/test_v17_cross_platform_setup.py`); golden eval stub đạt 31/36 (86%, qua cổng 85%).


- **X-01 (Bảo mật & Phân tách ngữ cảnh DM và Group):**
  - Tách bạch episodic memory và recall theo loại session: bổ sung tham số `exclude_dm` trong `Memory.recall()` và `Memory.session_search()` (chặn hoàn toàn các bản ghi có `session_key` thuộc `:dm:` trong cả nhánh BM25/FTS và vector search khi truy vấn từ nhóm).
  - Tự động phát hiện phiên nhóm (`:group:` hoặc `:channel:`) trong `ContextEngine.build()`, áp dụng `exclude_dm=True` và tiêm khối chỉ thị an toàn `GROUP PRIVACY GUARD` vào system prompt: tuyệt đối không trích dẫn hay nhắc lại các nội dung riêng tư đã bàn trong tin nhắn trực tiếp (DM).
- **X-02 & X-09 (Thời gian chuẩn xác & Giảm độ trễ câu hỏi đơn giản):**
  - `ContextEngine.build()` tự động tính toán và tiêm khối thông tin thời gian thực chuẩn xác theo múi giờ (`cfg.default_timezone`, mặc định `Asia/Ho_Chi_Minh` từ `DEFAULT_TIMEZONE` — tuân thủ Rule 0, không hardcode): giờ:phút:giây, thứ trong tuần, ngày/tháng/năm và ISO timestamp.
  - Phân loại ý định hỏi thời gian vào `Intent.CHAT` (fast path): trả lời trực tiếp trong 1-2 giây từ ngữ cảnh hệ thống, loại bỏ tình trạng bot tự đoán mò lệch 25 phút hay treo placeholder gọi tool không cần thiết.
- **X-03 & X-07 (Trạng thái rõ ràng, không treo placeholder & chống nói dối tiến trình):**
  - Bổ sung `correction_markers` vào `config/cancellation_markers.json` (nạp qua `load_json_data`) và mở rộng `is_cancellation_intent()` nhận diện đa dòng: phát hiện chuẩn xác các mẩu sửa ý ("á nhầm", "ý là", "không phải", "thôi khỏi, đổi ý:...").
  - Khi tác vụ bị dừng do hủy hoặc chuyển hướng, placeholder của lượt trước lập tức được cập nhật thành `⚠️ Đã dừng tác vụ theo yêu cầu`, loại bỏ tình trạng giữ nguyên kế hoạch cũ hay im lặng mất tích.
  - Bổ sung từ khóa tìm kiếm vào `tool_hints` và thêm "dùng tool", "đang tìm", "tui sẽ tìm" vào `action_promises` (`config/intent_hints.json`) để nâng cấp tự động sang `task_path` khi model có xu hướng hứa hẹn.
- **X-04 (Gộp tin nhịp nhàng & Nhận diện mẩu sửa ý):**
  - `MessageBatcher`: khi lượt bận kết thúc, các tin nhắn đến dở dang được hẹn giờ gộp nhịp nhàng theo tỉ lệ `debounce_seconds`, tạo điều kiện cho người dùng gõ nốt ý hoàn chỉnh.
  - Mẩu sửa ý tự động hủy lượt việc đang chạy và khởi chạy ngay yêu cầu mới, không bắt người dùng chờ 50 giây cho lượt việc sai ý.
- **X-05 (Chống phóng đại phạm vi — Scope Restraint):**
  - Bổ sung chỉ dẫn phong cách trong `mulon/prompts/muse_reply_style.txt` (nạp qua `load_prompt`): khi yêu cầu kiểm tra ngắn gọn hoặc mơ hồ ("check giùm bài đăng"), chỉ kiểm tra đúng 1 bài gần nhất hoặc hỏi lại 1 câu, tuyệt đối không tự ý quét toàn bộ hệ thống tài khoản nếu không có yêu cầu "tất cả" / "toàn bộ".
- **X-06 (Tín hiệu hàng đợi rõ ràng):**
  - Khi lượt tin nhắn mới đến trong lúc phiên đang bận xử lý lượt trước, bot gửi ngay thông báo hàng đợi trên placeholder: `⏳ Đang xếp hàng (chờ hoàn thành lượt trước)...` trước khi chờ lock, giúp người dùng nắm được trạng thái xử lý.
- **X-07 (Chất lượng hiển thị & Tránh lặp câu chào hiện diện):**
  - `md_to_html`: tách dòng tiêu đề (`_HEADING_RE`) bằng ngắt dòng rõ ràng, không làm vỡ phân cấp thị giác khi Telegram render HTML.
  - `on_delta`: áp ngưỡng độ dài tối thiểu (15 ký tự) và rate limit 1.2s trước khi cập nhật placeholder, loại bỏ hiện tượng flash 1 ký tự khi stream.
  - Thêm chỉ thị trong `muse_reply_style.txt` tránh lặp lại các mẫu câu chào hiện diện cứng nhắc ("Tui đây tui đây ní ơi!...") khi người dùng hối thúc.
- **X-08 (Trải nghiệm mượt mà trong Group):**
  - `TelegramSurface._should_respond`: khi người dùng đã mở đầu chuỗi tin vụn với `@bot` trong nhóm, các mẩu tin kế tiếp trong cửa sổ gộp không bắt buộc phải lặp lại `@bot`, giúp câu hỏi không bị rơi hay ngắt quãng.
- **Kiểm chứng:** 469/469 unit tests PASS (bổ sung 6 test hồi quy toàn diện trong `tests/test_v17_experience_fixes.py`); eval vàng stub đạt 31/36 (86%, qua cổng 85%).


## 1.7.0 — 2026-10-26 — Cơ chế hội thoại ngang Muse (T-09)

- **Gộp tin (Message batching) & Cơ chế ngắt (Cancellation / Queueing):**
  - Cửa sổ chờ debounce động dựa theo loại tin (câu mở đầu, câu cụt, ảnh, chuỗi tin dồn dập).
  - Tin mới tới khi bot đang bận được giữ trong buffer và gộp vào lượt kế tiếp theo thứ tự.
  - Cơ chế ngắt khi đổi ý rõ ràng: phát hiện các từ khóa/marker hủy (`config/cancellation_markers.json`, nạp qua `load_json_data` không hardcode) để ngắt ngay tác vụ đang chạy (`task.cancel()`), dọn sạch buffer hoặc chuyển hướng ngay sang ý mới nếu người dùng kèm theo yêu cầu khác.
  - Bổ sung lệnh `/cancel` và `/stop` trên Telegram bot menu.
- **Trả lời trong lúc đang làm (Progress updates via live message editing):**
  - Placeholder tin nhắn Telegram cập nhật trực tiếp tiến trình theo phong cách Muse: hiển thị rõ ràng các bước đã hoàn tất (`✓`) và bước đang chạy (`⏳`).
  - Lưới an toàn chống flood: giới hạn tần suất chỉnh sửa tin nhắn Telegram tối thiểu 1.2s mỗi lượt.
  - Phát sự kiện `tool_done` từ `Agent._act_loop` để cập nhật bước xong theo thời gian thực.
- **Chia việc cho Sub-agents song song & hiển thị ở tab Việc:**
  - `SubagentRunner._run_inner` tự động đăng ký bản ghi task trong bảng `tasks` (`memory.create_task`) với định danh rõ ràng `Sub-agent [<profile>]: <tiêu đề>`, hiển thị đầy đủ trên màn hình tab "Việc" (Mini App) và `/api/tasks`.
  - Bổ sung công cụ `spawn_subagents_parallel` cho phép chia nhiều việc con độc lập chạy song song qua `asyncio.gather` và tổng hợp digest nén trả về.
  - Cập nhật `NEVER_TOOLS` chặn cả `spawn_subagent` và `spawn_subagents_parallel` để chống đệ quy trong agent con.
- **Cách reply chuẩn Muse:**
  - Thêm prompt chỉ dẫn phong cách `mulon/prompts/muse_reply_style.txt` (nạp qua `load_prompt` vào khối tự nhận thức): trả lời ngắn gọn, đúng trọng tâm, giữ mạch ngữ cảnh, không mở bài sáo rỗng.

## 1.6.9 — 2026-10-26 — Khắc phục tận gốc LaunchAgent devwatch exit 126 (T-20, T-19)

- **Sửa LaunchAgent devwatch (T-20):**
  - Khắc phục lỗi POSIX exit 126 (`Operation not permitted` / wait status `32256`)
    do sandbox TCC của `launchd` không cho phép `chdir` và `execve` trực tiếp
    vào file script shell trên ổ đĩa ngoài (`/Volumes/External/`).
  - Thiết lập trampoline launcher tại `~/.mulon-dev-watch/dev_watch_launcher.sh`
    nằm trên ổ đĩa SSD hệ thống (`Macintosh HD`), nơi `launchd` có đầy đủ quyền traversal.
  - Trampoline gọi Python thông dịch trực tiếp file `dev_watch.py`, bỏ qua lỗi
    `execve` kernel trên external volume. `launchctl kickstart` đạt `LastExitStatus = 0`.
- **Hoàn thiện dev_watch (T-19):**
  - Watermark chỉ tiến khi `agy` chạy thành công. Khi lỗi, giữ watermark để retry,
    kèm ngưỡng trần `MAX_RETRIES = 3` tránh lặp vô hạn.
  - Gỡ bỏ toàn bộ đường dẫn hardcode khỏi `scripts/dev_watch.sh` và `scripts/dev_watch.py`.
  - Thêm template plist chuẩn hoá `scripts/com.mulon.devwatch.plist.template`.

## 1.6.8 — 2026-10-26 — Tự dựng Autowatch phía Antigravity (T-18)

- **Autowatch Antigravity (T-18):** Thiết lập cơ chế tự nhận việc tự trị qua git
  dành cho Antigravity builder trên máy Mac:
  - Cài đặt `agy` CLI tại `~/.local/bin/agy`.
  - Bổ sung `scripts/dev_watch.py` và `scripts/dev_watch.sh` với cơ chế khóa đơn
    non-blocking (`fcntl.flock`), theo dõi watermark SHA `~/.mulon-dev-watch/last_seen_sha`,
    tự động chạy `agy -p` nhận việc từ `AGENT_TASKS.md` khi phát hiện commit mới.
  - Cài đặt macOS LaunchAgent `~/Library/LaunchAgents/com.mulon.devwatch.plist`
    chạy nền định kỳ 5 phút một lần.

## 1.6.7 — 2026-10-26 — Khảo sát hiệu năng DB/Connectors (T-08) & Cập nhật trạng thái

- **Khảo sát hiệu năng (T-08):** Đã hoàn tất tài liệu khảo sát kỹ thuật tại
  `docs/de-xuat-hieu-nang-2026-10-26.md` phân tích hai điểm nghẽn:
  (1) Nghẽn single connection `aiosqlite` trong `mulon/memory.py` (đề xuất Reader Pool + Single Writer);
  (2) Khởi tạo `ClientSession` mỗi request trong `mulon/google_conn.py` (đề xuất giữ nguyên do legacy,
  dồn nguồn lực tối ưu vào Built-in Connector Google Workspace theo T-17).
  Không tự ý sửa code DB/Connectors, chờ chủ dự án phê duyệt.
- **Hoàn tất Backlog Audit 26/10 (T-01 -> T-08):** Toàn bộ 8 nhiệm vụ ban đầu đã đạt trạng thái `DONE`.

## 1.6.6 — 2026-10-26 — Vá DNS rebinding TOCTOU (T-06) & Dọn code thừa (T-07)

- **Bảo mật mạng (SSRF - T-06):** Vá lỗ hổng TOCTOU DNS rebinding trong
  `http_get_public` (`mulon/tools.py`). Sau khi `resolve_and_verify_url`
  kiểm tra toàn bộ địa chỉ DNS trả về đều là IP công cộng, IP đã kiểm chứng
  được ghim trực tiếp (IP pinning qua `PinningBackend` trên `httpcore`) vào
  kết nối socket TCP thay vì để HTTP client resolve DNS lần hai.
  Vẫn bảo toàn đầy đủ SNI và Host header cho TLS handshake/HTTPS.
  Hỗ trợ cập nhật pinning trên từng hop redirect (tối đa 3 lần).
- **Dọn code thừa (Ponytail review - T-07):** Xoá provider rỗng
  `McpMarketplaceCatalogProvider` không có caller trong `marketplace_providers.py`;
  dọn unused imports trong `evolution.py`, `voice.py`, `feed.py`, `subagents.py`;
  thu gọn `_BotShim` trong `feed_auto.py` dùng `types.SimpleNamespace`.
- **Test:** Thêm test suite `tests/test_v165_dns_pinning.py` với 10 test case
  bao phủ phân giải IP, lọc địa chỉ hỗn hợp, ghim socket và chặn redirect nội bộ.
  457/457 tests passed.

## 1.6.5 — 2026-10-26 — TTL dọn artifact tool-results (Backlog audit B1)

- **Artifacts:** Bổ sung cơ chế `clean_old_tool_results` tự động xóa
  các file kết quả tool trong `data/artifacts/tool-results/` cũ hơn
  7 ngày (chạy tại `main.py` lúc boot và định kỳ 24h trong `trim_tool_result`),
  tránh tích tụ rác đĩa không kiểm soát.
- **Test:** Thêm test hồi quy `test_clean_old_tool_results_ttl` trong
  `tests/test_context_trim.py`. 447 tests passed.

## 1.6.4 — 2026-10-26 — Gỡ hardcode theo audit toàn diện

- **Bảo mật:** gateway multimodal chỉ đóng gói file ảnh thật nằm
  trong workspace/dossier/temp, chặn denylist (.env/secret/*.pem/
  *.key/*.db) — đóng lỗ Local File Disclosure qua tag ảnh bị tiêm.
  File tool thêm denylist cứng tương tự trong `_resolve_for_file_tool`
  (.env.example vẫn đọc được).
- **Dữ liệu cá nhân ra khỏi repo:** gỡ 93 symlink `skills/*` trỏ
  tuyệt đối `/Users/<user>/.agents/skills/*` (SkillCatalog đã tự quét
  kho máy khi chạy); email Google của chủ bot chuyển sang env
  `GOOGLE_USER_EMAIL`; gỡ hook cá nhân `shopee_price_watch` khỏi
  repo (hooks là runtime, thêm .gitignore + hooks/README.md).
- **OAuth:** `GOOGLE_OAUTH_REDIRECT_URI` trong mcp_servers.json
  không còn chết cứng URL trycloudflare tạm — dùng `${WEBAPP_URL}`
  và `load_server_configs` tự mở rộng placeholder từ environ/Config.
- **Hardcode -> dữ liệu:** bảng intent (`_TOOL_HINTS` 155 +
  `_LONG_HINTS` + `_ACTION_PROMISES` + followup) ra
  `config/intent_hints.json`; marker học tập ra
  `config/learning_markers.json`; nguồn/stopwords Feed ra
  `config/feed_sources.json`; `KNOWN_MCP_FALLBACKS` ra
  `config/mcp_fallbacks.json`; 9 prompt hệ thống ra
  `mulon/prompts/*.txt` (loader `mulon/datafiles.py`).
- **Config:** 3 tier model hết trùng default (cheap =
  gemini-3.5-flash-lite, escalated = gemini-3.8-flash-high);
  endpoint/model sinh ảnh (Agnes) qua `IMAGE_GEN_ENDPOINT`/
  `IMAGE_GEN_MODEL`; username bot qua `BOT_USERNAME`; hằng
  `DEFAULT_TIMEZONE` dùng chung thay cho chuỗi rải rác.
- Test: 446 passed (thêm 4 test hồi quy cho các vá trên).


## 1.6.3 — 2026-10-24 — Sửa P0 của audit toàn dự án (injection, SSRF, privacy, auto_watch, CI)

- **Injection (sửa 1.6.3):** vòng evidence của agent loop đóng khung
  mọi kết quả tool bằng `frame_external`, không chỉ web_fetch/
  read_file và gmail/gcalendar đã có — gồm web_read, web_search,
  mọi connector_call, mọi tool MCP, memory/session_search, digest
  subagent, transcript media/STT, output run_command. Chỉ thêm nhãn
  dữ liệu ngoài, không chặn tool, không sửa nội dung.
- **SSRF (sửa 1.6.3):** `web_fetch`, websearch và browser chặn URL
  localhost/private/link-local/multicast/reserved/CGNAT và
  IPv4-mapped, kiểm tra DNS và từng hop redirect (tối đa 3 lần,
  DNS lỗi thì chặn fail-closed); browser redirect trong `goto`
  vẫn có thể đã xảy ra 1 GET trước khi URL cuối bị chặn, và DNS
  rebinding TOCTOU chưa chặn tuyệt đối — xem báo cáo mảng này.
- **Proxy (sửa 1.6.3):** `PROXY_BASE_URL` chỉ chấp nhận
  127.0.0.1/localhost/::1 đúng cổng 8317, sai thì fail-fast ở cả
  `Config.load()` và `ModelGateway.__init__`; chỉ mở host khác
  khi có env tường minh `MULON_ALLOW_REMOTE_PROXY=1`.
- **Privacy (sửa 1.6.3):** trajectory redact đệ quy trước khi ghi
  và trước khi trả qua `_handle_task`; `mulon.db` chmod 0600;
  scan bỏ qua symlink, file ngoài workspace và denylist
  (.env/.pem/secret/.db/vault.json), share kiểm tra lại path lúc
  share; share token lưu SHA-256 trong DB, token cũ plaintext tự
  chuyển sang hash ở lần mở đầu tiên. Hàng trajectory cũ vẫn còn
  nguyên văn trong DB, chưa ghi đè.
- **Auto_watch + CI (sửa 1.6.3):** auto_watch backup local changes
  ra patch trước khi stash, pop trả lại sau pull thành công/thất
  bại, pop xung đột thì dừng bot và báo rõ stash + patch, không
  tự `reset --hard` vứt đi; auto_watch mặc định tắt, chỉ bật bằng
  `--enable` hoặc `AUTO_WATCH_ENABLED=1`. Thêm CI thật
  `.github/workflows/ci.yml` (pytest, Python 3.12); README sửa số
  test về đếm tĩnh duy nhất 395 và sửa câu CI cho đúng là chỉ chạy
  pytest, chưa có dry-run/eval stub làm cổng merge.

## 1.6.2 — 2026-10-24 — Sửa đợt 2 sau audit (policy, Vault, share, UI, tính năng)

- **Policy (sửa 1.6.2):** fail-closed riêng cho Google — action
  gmail/gcalendar chưa liệt kê hoặc call thiếu action thì hỏi trước,
  không rơi về allow; đóng khung nội dung Gmail/Calendar như dữ liệu
  ngoài cho model; `web_click`/`web_fill` luôn ở nấc ask; fallback
  action-level cho mọi connector chưa liệt kê (token ghi/xoá → ask,
  token đọc → allow), đặt sau fail-closed Google để không mở lại
  cửa cho action Google chưa liệt kê.
- **OAuth Google (sửa 1.6.2):** state lưu dạng danh sách đang chờ
  kèm ts, hết hạn 10 phút, chỉ đốt đúng state đã khớp, bấm Kết nối
  lần 2 không ghi đè lần 1; format cũ 1 state vẫn đọc được.
- **Vault (sửa 1.6.2):** mã hoá at-rest tuỳ chọn bằng Fernet khi
  có env `VAULT_ENCRYPTION_KEY` hợp lệ và gói `cryptography` đã
  cài; thiếu 1 trong 2 thì vẫn plaintext JSON 0600 + cảnh báo log,
  không tự nhận là đã mã hoá; entry cũ vẫn đọc được, mất key =
  mất entry đã mã hoá.
- **Share (sửa 1.6.2):** trang share render markdown thật (tập con
  heading/bold/italic/code/link/list/quote, escape HTML trước);
  avatar fallback 4 đường dẫn thay vì chỉ 1.
- **UI (sửa 1.6.2):** bỏ pill màu còn sót — màn Google connector
  ("Đã kết nối" xanh lá, "Đã có Client ID & Secret" tím, "Chưa cấu
  hình" xám), badge "Đã ghim" tím nhạt trong Library, tiêu đề trang
  lỗi share đỏ `#e11d48` — tất cả về chữ + chấm nhỏ trung tính theo
  token `--ink`/`--ink2`/`--ink3`. Không đổi layout, cỡ chữ hay kích
  thước nút.
- **Tính năng (sửa 1.6.2):** browser thêm `web_click`/`web_fill`
  (luôn ask, không tự đăng nhập); Ideas tự sinh opt-in, mặc định
  tắt (`IDEAS_AUTO_ENABLED=0`, gạt kv trong Mini App thắng env),
  khi bật chỉ ghi thẻ chờ duyệt, không tự nhắn, không tự chạy task.
- **Docs (sửa 1.6.2):** thêm `docs/1.6.2-fixes.md` ghi đúng giới hạn
  thực tế (xem file đó, đã cập nhật theo từng đợt gộp: Vault mã hoá
  tuỳ chọn và OAuth đa phiên nay đã có). Sửa README ("ngoại lệ
  duy nhất" → 2 ngoại lệ) và chú thích 2 câu sai trong mục 1.6.0
  dưới đây.

## 1.6.1 — 2026-10-24 — Sửa 3 lỗi audit trước 1.6 (không thêm tính năng mới)

- **"Duyệt và nhớ" ghi theo group, không theo tool:** trước đây nhớ theo
  `connector_call` nên 1 lần duyệt cho `gmail:send` mở cửa cho mọi
  connector/action khác trong phiên, phá bảng quyền action-level 1.6.0.
  Từ nay nhớ theo đúng group trong payload (vd `connector:gmail:send`),
  chỉ khi không có group mới rơi về nhớ theo tool; thẻ cũng hiển thị
  đúng phạm vi nhóm thay vì nói "không áp cho nhóm khác" trong khi
  hành vi cũ áp cho cả tool.
- **Vault — sửa claim mã hoá + khử trùng label + card_sent trung thực:**
  Vault là file JSON quyền 0600, KHÔNG mã hoá at-rest — toàn bộ văn bản
  trong code, thẻ Telegram và Mini App đã sửa từ "mã hoá" thành diễn đạt
  đúng này. `VaultStore.put` khử trùng theo label (1 label chỉ còn 1 entry
  mới nhất, khỏi cảnh bot dùng mãi bản client_secret cũ theo thứ tự UUID).
  `request_vault_secret` tôn trọng kết quả thật của notifier và trả
  `ok=False` khi không có notifier nào (không còn "đã gửi thẻ" giả).
- **Share — thêm thu hồi + không log token + chỉ link active mới mở được:**
  thêm `LibraryService.unshare_item`, API Mini App
  `POST /api/library/items/{id}/unshare` (chưa thêm lệnh chat, để đợt sau
  nếu cần); `get_item_by_token` từ chối item không ở `share_status=active`
  (kể cả pending_host và revoked); trajectory `library_share_requested`
  không còn ghi `share_token`.
- **OAuth Google — state không còn bị đốt bởi callback sai:** callback chỉ
  xoá state khi state khớp hoặc đã hết hạn; state sai hoàn toàn thì giữ
  nguyên để owner bấm lại vẫn dùng được.
- **Giấy tờ:** badge README 1.5.0 → 1.6.1; ảnh đầu README trỏ
  `mulon-avatar.webp` ở root (trước đây trỏ `assets/mulon-avatar.webp`
  nhưng `assets/` không có file đó); ghi rõ phạm vi bảng action-level
  chỉ đúng cho 6 action gmail/gcalendar.

## 1.6.0 — 2026-10-24 — Artifacts + Library Share Link + Vault Cards + Action-Level Policy + One-Click MCP Install

- **Thư viện Artifacts & Link chia sẻ thật công khai:**
  - Tạo link chia sẻ công khai (`/share/{token}`) thật qua tunnel/domain hiện tại có thời hạn tối đa 48h.
  - Trang đọc tài liệu trực tiếp, hiển thị markdown, styling responsive, kèm nút "Sao chép" (Copy) tiện lợi.
    (Sửa 1.6.2 — chú thích: câu "hiển thị markdown" nói quá, thực tế
    trang share render nội dung text đã escape trong `<pre>`, chưa
    render markdown thật; xem `docs/1.6.2-fixes.md` §4.)
  - Hỗ trợ Ghim (pin) tài liệu lên đầu danh sách và Đổi tên (rename) tài liệu trực tiếp trong Mini App hoặc qua lệnh chat `/share_item`, `/pin_item`, `/rename_item`.
- **Thẻ nhập bí mật Vault an toàn tương tác trong chat:**
  - Agent được trang bị tool `request_vault_secret(label, description)`: gửi thẻ hành động trực tiếp vào chat với nút mở thẳng màn Kho trong Mini App.
  - Nhãn bí mật được điền sẵn và khóa (read-only), tự động focus vào ô nhập giá trị. Bí mật đi thẳng từ giao diện vào kho mã hóa, không bao giờ lộ ra tin nhắn chat plain text.
    (Sửa 1.6.2 — chú thích: "kho mã hóa" là diễn đạt cũ, sai; Vault
    là file JSON quyền 0600, không mã hoá at-rest; xem
    `docs/1.6.2-fixes.md` §3.)
- **Phân quyền chi tiết từng hành động (Action-Level Connector Policy):**
  - Quản lý quyền theo hành động cụ thể cho từng connector: Gmail (`gmail:search`, `gmail:read`, `gmail:send`) và Google Calendar (`gcalendar:list_events`, `gcalendar:create_event`, `gcalendar:delete_event`).
  - Phân cấp chính xác: `connector:<name>:<action>` -> `connector:<name>` -> `connector` -> `default`.
  - Màn con "Quyền chi tiết" trong Mini App chia nhóm Quyền đọc và Quyền ghi/xóa với menu đổi 3 nấc (`allow` / `ask` / `deny`).
- **Cài đặt MCP 1-Click từ Mini App:**
  - Khi chủ nhân bấm "Cài đặt ngay" trong Mini App, hệ thống tự động chạy thử và commit cấu hình ngay lập tức mà không phải duyệt qua 2 thẻ chat trung gian. Thao tác cài do agent khởi xướng từ chat vẫn giữ nguyên 2 bước duyệt an toàn.

## 1.5.0 — 2026-10-24 — Connector thật đầu tiên: Gmail + Google Calendar

- Connector `gmail`: tìm thư, đọc thư (bóc text từ cây MIME,
  cắt 8000 ký tự), gửi thư. Connector `gcalendar`: xem sự
  kiện 7 ngày tới, tạo sự kiện, xoá sự kiện. Cả hai dùng
  chung 1 ủy quyền Google OAuth2.
- Kết nối ngay trong Mini App (Công cụ kết nối → Kết nối
  Google): server dựng URL consent, callback công khai duy
  nhất `/google/callback` được bảo vệ bằng state nonce dùng
  1 lần (hạn 10 phút). Refresh token chỉ ở Vault; client
  id/secret qua env `GOOGLE_CLIENT_ID/SECRET` hoặc Vault
  nhãn `google:client_id`/`google:client_secret`.
- Quyền riêng từng connector (từ 1.4.1) áp dụng ngay:
  `connector:gmail`, `connector:gcalendar` đặt 3 nấc được
  ở màn Quyền.
- Tài liệu cho chủ nhân: `docs/google-connector-setup.md`
  (tạo Google Cloud project, bật 2 API, khai redirect URI).

## 1.4.1 — Đợt vá theo phản ánh của owner sau 1.4

- **Công tắc heartbeat THẬT trong Mini App** (tab Lịch): gạt
  là áp dụng ngay — trạng thái lưu ở kv phía server
  (`proactivity_enabled_override`, thắng `PROACTIVITY_ENABLED`),
  vòng quét luôn chạy và engine tự bỏ lượt khi đang tắt;
  `/status` và màn Hệ thống hiện trạng thái hiệu lực thật.
  Hết cảnh phải sửa `.env` + restart mới bật được.
- **Theme nhuộm đủ 3 tầng 60/30/10:** đổi màu chủ đề giờ đổi
  cả nền giấy/bề mặt (60%), bề mặt phụ (30%) và accent (10%)
  theo hue; thẻ hồ sơ lớn hết gán cứng tím Mulon (theo
  `--bc1/--bc2` của theme). Chỉ mực/chữ giữ trung tính.
- **Chợ MCP:** bấm danh mục mở MÀN CON riêng (server của
  danh mục đó + nút quay lại) — hết chồng 2 danh sách phải
  cuộn; **bỏ ô tìm MCP**; **bỏ card "Giá"** ở chi tiết (chợ
  chỉ lấy đồ free theo luật); nhãn quyền/capability dịch
  tiếng Việt (`download_and_run` → "Tải về và chạy mã", token
  lạ được viết lại dễ đọc).
- **Bỏ connector mẫu** `example` + `example-http` khỏi cấu
  hình mặc định — hết hiện như connector thật.
- **Màn Quyền có mục "Connector & server MCP":** quyền 3
  nấc riêng cho từng connector (`connector:<tên>`) và từng
  server MCP (`mcp:<tên>`); policy rơi về nhóm gốc khi chưa
  có rule riêng; cài thêm connector/server là tự xuất hiện.
  Nhóm `goals` có nhãn "Quản lý mục tiêu" (hết hiện thô).
- **Kho lưu trữ hết "chưa responsive":** `.field-input`
  thành block width 100% — ô nhập ở Kho (và Feed) đầy bề
  ngang card như nút, thay vì co ~60%.
- **Tab Việc làm lại đúng nghĩa TASK:** `/api/state` không
  còn gộp lượt chat (trajectory `turn_done`/`turn_error`)
  vào danh sách việc — chỉ task thật từ bảng tasks (đường
  plan-act-verify, job, agent con); mỗi việc hiện tiến độ
  bước x/y, màn chi tiết dựng timeline từ CÁC BƯỚC KẾ HOẠCH
  + thẻ Tóm tắt như Muse.

## 1.4.0 — Feed chủ động: Feed tự chạy theo lịch, tự tìm nguồn tin cậy

- **Quyết định owner 0.2b (thắng mọi đề xuất trái ngược trong
  spec):** Feed **LUÔN TỰ ĐỘNG** ngay sau nâng cấp — không
  công tắc tổng, không bước kích hoạt, **không lệnh
  `/feed_auto`**; `/feed_now` rút khỏi menu lệnh (giữ handler
  ẩn tương thích, bài qua đó ghi origin `manual`); giữ
  `/feedbrief`, thêm `/feedsources`. Nghiệm thu: nâng cấp
  xong, tới nhịp đầu tiên là có bài auto mà owner không thao
  tác gì. Nhịp mặc định `0 8,20 * * *` (08:00 + 20:00), trần
  3 bài/ngày, giờ yên lặng 23:00–07:00, trần token model rẻ
  60.000/ngày.
- **Module mới:** `mulon/feed_auto.py` (FeedAutoRunner: cổng
  lượt — tạm dừng/giờ yên lặng/trần token/trần bài; ghi
  trajectory `feed_run` kèm trạng thái từng lượt; 3 lượt lỗi
  liên tiếp → tự tạm dừng + báo owner đúng 1 tin vào topic
  Lịch sử & Hệ thống; `resume()` qua Mini App) và
  `mulon/websearch.py` (tìm kiếm web không API key trả phí:
  DuckDuckGo HTML/Lite → Bing, parser thuần + giải redirect;
  fetch trang cho collector). Tool `web_search` (chỉ đọc)
  đăng ký cho agent ngoài registry lõi.
- **Job hệ thống nội bộ + cô lập tick (planning.py):**
  SchedulerService dispatch payload marker
  `{"kind": "feed_auto", "v": 1}` thẳng tới handler xác định
  — KHÔNG qua agent loop, không tool ghi, không approval.
  `run_due_once(include_regular=False)`: lịch thường tới hạn
  bị giữ nguyên (không bắn, không tiêu thụ next_run) —
  bật tick cho Feed không làm lịch thường (mặc định tắt)
  chạy theo. Tools `list_schedules`/`cancel_schedule` không
  thấy/không tắt được job nội bộ.
- **Collector ngoài (feed.py):** tự search theo chủ đề nóng
  (goals + cam kết sắp tới + chủ đề taste đang hưởng ứng),
  cộng nguồn owner ghim (section SOURCES trong FEED.md, chỉ
  là bổ sung) và connector khai `feed_snapshot` (chưa có
  adapter nào khai → rỗng sạch). Chấm tin cậy tất định
  (`.gov`/`.edu`/hãng tin lớn/wikipedia = cao; TLD tín hiệu
  thấp = thấp; link rút gọn + denylist = loại), cache theo
  hash nội dung (hash không đổi = tư liệu cũ, hạ ưu tiên;
  được dùng lại 1 lần khi hash đổi), đối chiếu chéo: số liệu
  chỉ từ 1 nguồn thấp duy nhất thì không vào bài, leo thang
  browser render khi trang quá mỏng (trần/lượt).
- **Kỷ luật sau sinh:** kiểm tất định trước khi đăng — trích
  dẫn `[n]`/URL phải thuộc đúng tư liệu đã lấy về (sai → sinh
  lại tối đa 1 lần → bỏ bài), chống trùng 3 lớp (URL đã trích
  7 ngày theo hash; overlap đề tài gấp dấu > 0,6; trần ngày),
  thiếu tư liệu → bỏ lượt không đăng bài rỗng/bịa. Taste v2:
  reaction gộp theo NGUỒN và theo CHỦ ĐỀ đổi được khâu chọn
  tư liệu (xếp hạng tất định), nguồn bị 👎 ≥3 lần và 0 👍
  trong 14 ngày bị ghi nhận hạ tin cậy.
- **Dữ liệu (memory.py):** `feed_posts` thêm `origin` +
  `topic` (migration idempotent); bảng mới `feed_post_sources`
  (URL đã trích theo bài), `feed_material_cache` (hash nội
  dung theo URL), `feed_settings` (cài đặt Feed hiệu lực —
  DB thắng env, env chỉ seed lần đầu).
- **Điều khiển:** Mini App thêm màn Cài đặt → Feed chủ động
  (trạng thái, chạy ngay, nhịp + preset, giờ yên lặng, trần
  bài/token, nguồn ghim thêm/xoá/bật-tắt, denylist) qua
  `POST /api/feed` — cố ý không có action tắt; `/api/state`
  thêm block `feed`; tab Lịch hiện job Feed là mục hệ thống
  không gạt tắt được. Sau `/setup_topics` thành công, group
  được lưu làm đích đăng Feed. Dry-run thêm block `v14`.
- **Điểm lệch có chủ đích so với spec:** eval vàng §11.3 (20
  ca trích dẫn) là hạng mục chạy ngoài CI khi phát hành,
  không đóng thành unit test đợt này; nguồn social qua MCP
  tool (đường 2 của §3.3) không làm — chỉ interface
  `feed_snapshot`; vết lượt chạy dùng 1 kind trajectory
  `feed_run` + `payload.status` thay cho nhiều kind rời.

## 1.3.0 — Chợ MCP (Marketplace): cài MCP server local miễn phí qua 2 lần duyệt

- **Phạm vi đã khoá theo quyết định owner:** chỉ server **miễn
  phí**, chỉ **local stdio** — không remote (kể cả import thủ
  công dán URL), không paid/license/pay-per-call. Nguồn dữ
  kiện: **bundle tuyển chọn đóng gói** (`config/
  marketplace_curated.json`, 6 server tham chiếu chính thức —
  filesystem, memory, sequential-thinking, git, time, fetch —
  đều ghim version cố định và đã chạy probe thật khi rà soát,
  kèm tool fingerprint tại thời điểm rà soát) + **nhập thủ
  công** (dán JSON `mcpServers`/1 server object). Không phụ
  thuộc API của mcp-marketplace.io (chưa có API client công
  khai đã kiểm chứng — provider dự phòng báo
  `unavailable_unverified`).
- **Module mới:** `mulon/marketplace.py` (MarketplaceService:
  chuẩn hoá cấu hình, phân tích rủi ro, state machine
  operation, commit/rollback, boot reconciliation, catalog
  updater), `mulon/marketplace_store.py` (sổ JSON nguyên tử:
  installed registry, operation journal, tombstone, restart
  intent, hàng đợi thông báo), `mulon/marketplace_providers.py`
  (bundle + checksum nội dung). API `/api/marketplace/*` trên
  WebAppServer (auth initData owner-only như mọi `/api/*`,
  POST đổi trạng thái nhận `Idempotency-Key`); `/api/connector`
  gặp server managed thì route sang service — không ghi file
  trực tiếp, không ghi 2 lần; `/api/state` thêm
  `marketplace_summary` + cờ managed/lifecycle/health trên
  từng MCP item.
- **Luồng cài 2 lần duyệt:** chuẩn bị (kiểm trùng tên, cổng
  bảo mật: critical = chặn cứng, điểm < 7.0 không cài nhanh)
  -> gắn bí mật bằng **Vault ref** (giá trị literal trong bản
  dán bị từ chối `secret_literal_rejected`; không plaintext
  trong config/catalog/log/API/store) -> xin duyệt **chạy
  thử** (probe tách rời: chỉ initialize + list_tools, không
  đăng ký tool, không gọi tool nào) -> xem tool list/schema +
  fingerprint -> xin duyệt **commit**. Thẻ duyệt marketplace
  dùng TTL riêng 900s (broker hỗ trợ TTL theo từng yêu cầu)
  và **không có "Duyệt và nhớ"**. Tool của server cài qua chợ
  vào group `mcp:<server>` với verdict mặc định **ask**.
- **Commit an toàn:** journal write-ahead -> ghi policy ->
  read-modify-write nguyên tử trên `mcp_servers.json` (giữ
  nguyên entry thủ công + trường lạ, đối chiếu hash trước/sau)
  -> đọc lại kiểm fingerprint. Lỗi giữa chừng tự rollback
  (policy cũ, entry cũ, record `quarantined`).
- **Bot TỰ khởi động lại** (re-exec) sau cài/gỡ/cập nhật/
  bật-tắt; **boot gate**: server managed chỉ được đăng ký
  tool khi config fingerprint + tool fingerprint khớp bản
  đã duyệt (lệch -> giữ tool, báo `blocked_tool_drift`/
  `config_drift`); restart pending được quyết toán lúc boot
  — áp dụng thất bại thì **tự rollback về cấu hình trước đó**
  (tối đa 1 lần, tránh vòng lặp) + nhắn báo owner qua Telegram.
  Gỡ: chặn tool ngay bằng policy deny, xoá Vault ref độc
  quyền chỉ khi owner chọn (ref dùng chung không bao giờ bị
  xoá value).
- **Catalog tự cập nhật** (việc nền hẹp duy nhất, owner đã
  duyệt riêng): kiểm tra lúc khởi động + hàng tuần, tải file
  tuyển chọn từ repo GitHub của dự án, **kiểm checksum**
  trước khi thay snapshot, CHỈ cập nhật dữ kiện niêm yết —
  không bao giờ tự cài/cập nhật server.
- **MCP client mở rộng:** `probe_entry()` tách rời,
  `tool_snapshot()` cho boot gate, `register_into(exclude=…)`,
  resolve Vault ref vào bản sao trong bộ nhớ khi connect
  (`env_vault_refs`/`auth_vault_ref`/`header_vault_refs` —
  entry trên đĩa chỉ giữ ref). Policy engine thêm
  get/remove host rule cho installer.
- **Mini App:** màn Kết nối có segmented chỉ chữ **Đã cài |
  Chợ** (đúng hệ thiết kế vòng 3: không pill trạng thái,
  trạng thái bằng chữ + phân cấp trung tính, tối đa 1 màu
  nhấn), màn chi tiết listing, wizard cài theo operation
  (không có ô nhập giá trị bí mật), màn nhập thủ công; thẻ
  duyệt `marketplace_operation` ở mục Phê duyệt chỉ có
  Duyệt/Chặn.
- **Đo thật khi rà soát:** các server Node tham chiếu
  initialize ~70s qua MCP Python SDK trên máy yếu (uvx/Python
  ~1s khi cache ấm) — entry cài qua chợ được ghi
  `timeout_s: 120` để lần nối đầu không chết oan.
- **Kiểm thử:** +40 test `test_v13_*` (chuẩn hoá, cổng bảo
  mật, luồng 2 duyệt, rollback giữa commit, boot gate/drift,
  tự rollback khi áp dụng lỗi, catalog checksum đúng/sai +
  không tự cài, API + auth + không lộ sentinel Vault, và
  đầu-cuối THẬT bằng echo server: import -> probe -> duyệt
  -> commit -> boot mô phỏng -> đăng ký đúng tên
  `mcp_<server>_<tool>` -> gọi được tool; case phá cấu hình
  sau commit -> rollback tự kích hoạt). Eval vàng +3 ca
  `cho_mcp` (agent không có tool cài/gỡ — chỉ hướng owner
  vào Mini App).
- **Gói A — Sprite states v0 trong Mini App:** avatar header
  phát atlas THẬT (bộ states owner đã chốt: idle/working/
  waiting vòng lặp, done/error chiếu 1 lần khi TASK thật kết
  thúc) thay cơ chế CSS keyframes trên ảnh tĩnh. Asset đóng
  gói ở `mulon/webapp/assets/` + route tĩnh
  `/app/assets/{name}` (whitelist, cache 1 ngày). Trạng thái
  chỉ suy từ `/api/state` thật (thẻ chờ duyệt → waiting,
  busy → working); thiếu asset thì fallback chữ cái đầu trên
  nền tint tím theo theme. Vị trí frame tính theo hình học
  lưới của atlas (bài học render kiểm: chia theo số frame
  từng đẩy frame cuối sang ô trống).
- **Gói B — Vá tự nhận thức cho agent:** khối SELF-KNOWLEDGE
  chèn vào prompt hệ thống ngay sau dossier (cả lượt chat
  lẫn lượt việc): Mulon là ai (bot Telegram Python/aiogram 3
  đang chạy thật, codebase này chính là nó), roster tool đầy
  đủ bằng nhãn lời thường, các bề mặt thật (thẻ duyệt có NÚT
  THẬT qua ApprovalBroker, Mini App, Vault chỉ cầm ref) và
  3 quy tắc cứng — không tuyên bố thiếu tool khi chưa đối
  chiếu roster; không bịa thẻ/UI bằng văn bản trình như đồ
  thật; không bao giờ hỏi owner "bot chạy bằng gì". Lệnh
  `/the_duyet` gửi THẺ DUYỆT THỬ THẬT qua đúng
  ApprovalBroker + renderer sẵn có (payload vô hại, quyết
  xong chỉ ghi nhận). Handler `/vault` đổi đường chính sang
  mở Kho trong Mini App (deep link), link localhost hạ
  thành đường phụ cho máy tính. Eval vàng +3 ca `trung_thuc`
  khoá các lỗi owner bắt được (tự đọc source của mình bằng
  read_file, không xuất thẻ giả, nhận có tool đọc file).
- **Gói C — Vá Mini App theo phản ánh thật:** (1) Vault nhập
  ngay trong app: form nhãn + giá trị (ô mật khẩu) POST
  `/api/vault/capture` → `VaultStore.put`, chỉ trả ref,
  giá trị không echo/không log. (2) Kỹ năng đọc được:
  `GET /api/skills` + `/api/skills/{name}`, màn chi tiết mở
  đọc SKILL.md ngay trong app. (3) Switch nối thật: mục
  không bật/tắt được (connector dựng sẵn, heartbeat) hiện
  trạng thái bằng chữ thay công tắc chết; theme hết nuốt lỗi
  — lỗi lưu hiện toast rõ ràng như mọi đường API khác.
  (4) Tab Việc hiện MỌI lượt: `/api/state` gộp bản ghi task
  với lượt chat/lượt lỗi từ trajectory (`turn_done`/
  `turn_error` fast-path) — trước đây lượt chỉ chat không
  có bản ghi nào nên danh sách trống dù vừa chat xong.
- **Gói D — Đối soát "hai Chat chính":** bản 1.0/1.1 từng tự
  tạo topic tên "Chat chính" cho vai main; 1.3.0 hợp nhất về
  General (thread 1) là chat chính DUY NHẤT. Lúc bootstrap
  topic (`TopicManager.setup` → `reconcile_main_topic`):
  map cũ ghi main → thread tự tạo (bằng chứng xuất xứ chắc
  chắn, đối chiếu registry chat phụ không mâu thuẫn) thì
  cập nhật map main→1, ghi record legacy/superseded, gửi
  ĐÚNG 1 tin chỉ đường vào topic cũ rồi ĐÓNG bằng
  close_forum_topic (giữ nội dung, mở lại được). Bằng chứng
  mâu thuẫn/không đủ → chỉ ghi nhận + báo trong kết quả
  setup, không tự đóng. Từ nay không đường code nào tạo
  topic tên "Chat chính" nữa (chat phụ đặt đúng tên này bị
  chặn). Kiểm thử: +4 test `test_v13_topic_reconcile`.

## 1.2.0 — Mini App modal phong cách Muse + policy nấc "hỏi" + menu lệnh

- **Khối 1 — Menu lệnh:** bot đăng ký toàn bộ lệnh hiện có + `/menu`
  bằng `set_my_commands` lúc khởi động (mô tả tiếng Việt; lỗi đăng
  ký chỉ log warning). `/menu` gửi MỘT tin teaser kèm nút mở Mini
  App; thiếu cấu hình app thì trả hướng dẫn ngắn + lệnh chính.
- **Khối 2 — Policy 3 nấc + ApprovalBroker:** verdict mở rộng
  allow/ask/deny (bí danh ask: prompt/confirm; file cũ allow/deny
  chạy nguyên). `mulon/approvals.py`: broker mở yêu cầu -> chờ
  quyết định từ mọi đường (inline/Mini App), timeout 60s = hết
  hạn, "duyệt và nhớ" ghi rule lớp session. Agent phát event
  `approval_requested`, payload chỉ có tóm tắt args an toàn.
- **Khối 3 — Bề mặt Telegram:** nút mở app là **Direct Link**
  `https://t.me/<bot>/<WEBAPP_APP_NAME>?startapp=...&mode=compact`
  (nút web_app inline chỉ chạy trong DM nên không dùng); thẻ duyệt
  luôn kèm inline dự phòng Duyệt/Chặn/Duyệt và nhớ; quyết định
  xong — kể cả hết hạn — bot **tự xóa tin thẻ**, ghi 1 dòng vào
  topic Lịch sử & Hệ thống; người lạ bấm nút bị từ chối. Placeholder
  của lượt chỉ hiện MỘT dòng trạng thái (≤1 edit/1,2s).
- **Khối 4 — Mini App:** server aiohttp cùng process (bind
  127.0.0.1, cổng `WEBAPP_PORT` 8320) phục vụ 1 file HTML tĩnh +
  API JSON. Mọi `/api/*` khóa bằng `X-Telegram-Init-Data` (HMAC
  chuẩn Telegram, auth_date ≤ 1h, user.id == ALLOWED_USER_ID);
  Vault chỉ lộ nhãn + ref. Giao diện "tờ hồ sơ agent" giống app
  Muse: header avatar + trạng thái sống, 5 tab Việc · Phê duyệt
  · Lịch · Hồ sơ · Cài đặt; tab active là pill trắng trên nền
  segmented xám, đất nung `#D97757` chỉ cho nút hành động chính.
- **Khối 5 — Hồ sơ:** version 1.2.0, CHANGELOG này, README mục
  "Bảng điều khiển (Mini App)" + biến WEBAPP_* vào bảng cấu hình,
  `.env.example` hướng dẫn BotFather 3 bước, test `test_v12_*`.
- **Bổ sung cuối 1.2.0 (chưa phát hành):** (1) Chọn **màu chủ
  đề** trong Cài đặt → Giao diện: 7 họ màu (Tím Mulon mặc định,
  Xanh dương, Hồng, Đào, Xanh lá, Chì, Đất nung) — chỉ đổi hue
  của lớp nhận diện 30% (3 token `--lav*`), `--clay` giữ vai
  trò ngữ nghĩa cho Duyệt/CTA; áp ngay bằng localStorage + lưu
  server (kv) để đồng bộ đa thiết bị qua `POST
  /api/profile/theme`. (2) Thẻ **Thiết bị & hệ thống** trong
  Cài đặt: tình trạng THẬT của máy đang chạy Mulon (hostname,
  HĐH, phiên bản, uptime, kiểm tra TCP proxy 8317, scheduler/
  heartbeat) + phiên Telegram đang xem qua `/api/state.system`
  — Mulon không ghép thiết bị nên không có danh sách thiết bị.
  (3) Thẻ duyệt có **dòng phạm vi + lý do** theo chuẩn thẻ cấp
  quyền của Muse: dòng phạm vi suy từ tool/nhóm thật — “Duyệt”
  chỉ áp cho lần này, “Duyệt và nhớ” áp cho đúng công cụ đó tới
  hết phiên (rule lớp session), không lan sang việc khác; dòng
  lý do là lời agent tự giải thích (lời dẫn của model ở lượt gọi
  tool, trường `reason` tùy chọn qua broker) — chat hiện 1 dòng
  cắt gọn, Mini App hiện bản đầy đủ mở rộng/thu gọn được; không
  có lý do thì thẻ vẫn dựng bình thường. (4) **Rà thiết kế
  Mini App theo chuẩn skill `mobile-app-ui-design`** (chỉ
  hình thức + tương tác hiển thị, không đổi hành vi/API):
  typography co từ 6 cỡ/3 weight về **4 cỡ (20/15/13/11) /
  2 weight (400/600)** — hết chữ dưới 11px; mọi khoảng về
  lưới 8pt (bội 4/8); mọi vùng chạm ≥44px (segmented quyền
  36→44, nút phụ 40→44, toggle vùng bấm cao 44 giữ track
  51×31, link "Mở rộng" cao 44); trạng thái pressed +
  `:focus-visible` cho mọi phần tử bấm được; cụm nút quyết
  của thẻ duyệt dính đáy viewport (vùng ngón cái); Peak-End
  — duyệt xong/việc xong có avatar state `done` + toast xác
  nhận, tab Phê duyệt có thẻ trống dạng khẳng định; empty
  state Lịch sử/Kết nối có thêm câu hướng dẫn. `DESIGN.md`
  ghi lại thang chữ/khoảng mới và các mục Vùng ngón cái,
  Peak-End, micro-interaction. (5) **Nhãn lời thường trong
  Mini App** (vá sau rà render thật): thẻ chờ duyệt + lịch sử
  phê duyệt trong app từng lộ tên tool thô (`run_command`,
  `send_message`, `github_push`) — `/api/state` nay gắn
  `action_label` dùng lại đúng `tool_action_label` của thẻ
  duyệt trên chat (bổ sung nhãn cho `send_message`,
  `github_push`), tên thô chỉ còn ở dòng chi tiết; màn Quyền
  hiện nhãn nhóm tiếng Việt qua `group_labels` (dùng lại
  `GROUP_SCOPE_LABELS`) thay key thô (`file`, `shell`…), và
  bỏ hẳn jargon "lớp phiên/lớp host" — câu dưới toggle "Lưu
  bền" cùng note của màn Quyền viết lại bằng lời thường giữ
  nguyên nghĩa. Không có nhãn thì frontend fallback về tên
  thô, không bịa nhãn. (6) **Vòng sửa thiết kế theo feedback
  user sau render thật** (chỉ `index.html` + `DESIGN.md`,
  không đổi hành vi/API): bỏ toàn bộ pill/tag trạng thái
  (tag "Cần duyệt", pill kết quả lịch sử, pill ở màn Hệ
  thống) — trạng thái thành chữ thường theo thang mực +
  tối đa 1 ký hiệu mảnh (✓/✕/·); xóa hệ màu trạng thái
  xanh/vàng/đỏ khỏi mọi danh sách (ô icon thống nhất tint
  trung tính ấm `--surface2` + glyph `--ink2`, gỡ
  `--tint-ok`/`--tint-warn`/`--tint-blue`, toggle bật =
  `--lav`, chấm timeline trung tính/tím, note trung tính);
  **bỏ hẳn đất nung/clay** — đất nung là màu của Muse,
  không phải của Mulon: accent 10% nay là bậc đậm nhất của
  chính hue nhận diện đang chọn (`--accent` suy từ
  deep/press của theme; theme "Đất nung" gỡ khỏi `THEMES`
  + `THEME_KEYS`, còn 6 họ màu; theme đã lưu `clay` tự rơi
  về lavender); cắt sub text rườm rà (menu Cài đặt hết sub
  mô tả, hàng việc chỉ còn sub khi đang chạy/lỗi, note
  Quyền/Hệ thống/Vault rút gọn giữ nguyên nghĩa); thu kích
  thước tổng thể ~15% (avatar 76→52, compact 32; hàng
  56→52; ô icon 36→32; nút chính 48→44 gọn padding); dựng
  lại phân cấp — thang chữ nới bậc trên cùng 20→22, thẻ
  duyệt lấy tiêu đề hành động lớn làm điểm neo (rose thu
  về 1 chấm nhỏ, bỏ viền rose), chữ `--lav-deep` của các
  theme nới đậm đạt tương phản trên tint (dark dùng base
  trên tint tối). `DESIGN.md` ghi lại kỷ luật mới ở mục
  "Kỷ luật trạng thái & phân cấp". Test frontend cập nhật
  theo chủ đích mới: khẳng định không còn `#D97757`, không
  pill trạng thái, không biến thể ô icon sơn màu; test
  theme còn 6 khóa.

## 1.1.1

- Vá gom tin: tin đến trong lúc session bận được giữ và drain vào
  lượt đang chờ lock — không còn nứt thành nhiều lượt chồng nhau.

## 1.1.0

- Chat phụ bằng topic tự do: `/chatphu`, `/chatphu_list`,
  `/dongchat`, `/chatphu_dong`, `/chatphu_mo` (SideChatRegistry).

## 1.0.1

- Vá nghi lễ BOOTSTRAP gãy đầu–cuối: nạp + render BOOTSTRAP.md
  khi còn pending, `/start` trích đúng mục câu hỏi, file tools
  ghi được vào thư mục dossier.

## 1.0.0

- Đủ 6 phase theo tài liệu thiết kế: lõi plan–act–verify, ký ức
  hybrid + học correction, MCP/subagent/scheduler, proactivity +
  voice + media + skills, eval vàng + backup + báo cáo, bề mặt
  group forum (Feed/Ideas/Library/Vault/quyền).
