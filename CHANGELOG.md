# CHANGELOG

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
