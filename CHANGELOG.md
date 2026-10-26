# CHANGELOG

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
