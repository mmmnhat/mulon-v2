# CHANGELOG

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
