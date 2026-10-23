# AUDIT MULON (NISTROLY) + CHIẾN LƯỢC CLONE MUSE

Repo: https://github.com/mmmnhat/mulon — Audit ngày 2026-10-23, đọc toàn bộ code lõi (~8.900 dòng Python), đối chiếu tài liệu và quét toàn repo 2.559 file.

---

## PHẦN 1 — KẾT LUẬN AUDIT: cảm giác "sai sai" là đúng, và đây là lý do

Khung xương của Mulon là đồ thật: agent loop, tool registry, Telegram gateway, DB SQLite+FTS5, scheduler, voice 2 chiều, tự học skill — đều có code chạy được. Nhưng có 3 gốc rễ khiến nó "sai sai":

### Gốc 1 (ĐÍNH CHÍNH 2026-10-23): Sentinel không phê duyệt là do user yêu cầu — KHÔNG phải lỗi
Bản audit đầu kết luận "lớp duyệt là vỏ" — sai khung. User xác nhận: chính user ra lệnh cho Mulon không cần phê duyệt (khớp chỉ thị trong MEMORY.md của repo: "Cho phép nó sửa toàn bộ dự án luôn" — toàn quyền tự động duyệt). Hành vi auto-duyệt là **đúng spec của user**, không tính là khuyết điểm.
- Việc cần sửa duy nhất ở mục này: `ARCHITECTURE.md` mô tả "mọi mutation đều phải qua duyệt" trong khi hành vi thật (theo lệnh user) là không duyệt — tài liệu lệch code, bản clone viết lại cho khớp.
- Ghi nhận kỹ thuật (không phải lỗi): fallthrough ở `sentinel.py:152-156` khiến cả tool lạ lẫn tác vụ nền cũng auto-duyệt — nhất quán với yêu cầu toàn quyền của user.

### Gốc 2: Lệnh flagship gãy ở lớp nối commands ↔ tools
Không phải logic khó — toàn lỗi khóa/chữ ký không khớp giữa 2 file:
- `/repurpose` (tính năng chính!): parser tách lệnh sai → link bị hiểu thành giọng đọc → **không bao giờ chạy được qua chat thường** (`commands.py:262-276` vs `1562`).
- `/tasks add`: gọi sai chữ ký hàm → TypeError 100% (`commands.py:1867` vs `schedule_tools.py:44-50`).
- `/tasks` list: đọc sai tên khóa DB → luôn hiện rỗng/"0 phút".
- `/subagent run`: thành công nhưng báo "[LỖI] ... thành công" (kiểm tra `=="success"` trong khi tool trả `"dispatched"`).
- `/skills info`: luôn rỗng (đọc khóa `content`, tool trả khóa `skill_md`).
- `/gmail send`, `/calendar add`, `/calendar week`, `/gws docs`: quảng cáo trong usage nhưng **không tồn tại** — gõ vào lặng lẽ chạy việc khác.
- `/thinking`: nút placebo — setting được lưu nhưng không code nào đọc khi chạy.
- Heartbeat: tác vụ chạy >15s bị bắn trùng nhiều bản song song (không khóa ở tầng tác vụ) — nguy hiểm với tác vụ gửi tin/thanh toán.

### Gốc 3: Nửa repo là "tính năng trên giấy"
- `memory_facts` (memory consolidation): có bảng, có hàm — **0 caller**. Dead code.
- Trajectory "reflection": chỉ ghi JSONL, không ai đọc lại.
- `interrupt()`: không ai gọi.
- `plugins/catalog/`: 756 file YAML — không một dòng Python nào đọc.
- `mcps/`: 68 MCP manifest — chỉ tra cứu được, **không có MCP client** để kết nối thật (ngoại lệ duy nhất: Meta MCP viết tay).
- `mcp_servers/`: 3 server TypeScript có code thật — **không tiến trình nào gọi**.
- ARCHITECTURE.md mô tả 2 file không tồn tại (`openclaw_tools.py`, `media_tools.py`). Số liệu mỗi nơi một kiểu: "50+ skills" / "350+ kỹ năng" / "65+ MCP" — thực tế 424 SKILL.md, 68 manifest, 62 tool.

### Điểm từng module (audit core)
| Module | Điểm | Ghi chú |
|---|---|---|
| session.py | 8 | Sạch, đúng, deterministic |
| skills/registry.py | 8 | Xương sống thật, bọc lỗi tốt |
| main.py | 7 | Boot rõ ràng |
| schedule_tools.py | 7 | File này không lỗi — lỗi ở bên gọi nó |
| memory.py | 6 | DB/FTS5 tử tế; recall nhiễu, không gấp dấu tiếng Việt, memory_facts chết |
| gateway/__init__.py | 6 | Ingress/egress hoàn chỉnh; nhiều except câm |
| gateway/audio.py | 6 | STT/TTS thật; transcribe chặn event loop |
| system_tools.py | 6 | Tool lõi chắc; read_file không giới hạn path |
| agent.py | 5 | Loop chạy; **không try/except quanh lời gọi LLM** (API sập là mất cả lượt + mất tin user), không quản trị context, lưu cả trace HTML vào history làm ô nhiễm ngữ cảnh |
| hermes_tools.py | 5 | Học skill thật; lỗi JSON registry bị nuốt rồi ghi đè mất dữ liệu |
| config.py | 5 | Commit cứng Telegram ID thật + tên thật làm mặc định |
| commands.py | 4 | Xem Gốc 2 |
| heartbeat.py | 4 | Chỉ chạy scheduled tasks; trùng tác vụ; không consolidation/health như tài liệu |
| trajectory.py | 5 | Ghi ổn định, write-only |
| sentinel.py | — | Hành vi auto-duyệt đúng yêu cầu của user (xem đính chính Gốc 1); không chấm điểm lỗi |
| subagent_tools.py | 3 | "Fan-out đa tác tử" = 1 lần gọi LLM, không tool, không loop, không dùng model đang active |

### Hygiene & security
- Repo 86MB nhưng code thật chỉ **408KB (~0,5%)**. Phình vì: `bin/gog` — **binary macOS arm64 40MB commit thẳng vào git** (máy khác clone về vô dụng, mà code đã có fallback tìm gog ngoài); `skills/` vendor 21MB (gồm dump tài liệu Unsloth 1,1MB).
- `requirements.txt`: 8 gói, chỉ ghim `>=`, không lock. **Thiếu ít nhất 6 gói** so với tính năng công bố: `sherpa-onnx` (transcriber), `yt-dlp`, `piper`, `numpy`, `soundfile` (pipeline video), `ddgs` (web_search). Cài theo README trên máy mới là pipeline video + web search chết ngay.
- Hardcode đường dẫn máy tác giả `/Volumes/External/auto/...` ở nhiều connector (AccessTrade, Agnes, Meta token) + binary arm64 → **dự án chỉ chạy đúng trên đúng chiếc Mac của ní**.
- Tests của dự án: **0**. CI: không có. Git history: 1 commit duy nhất.
- Secrets: code lõi sạch (key đi qua `.env` đúng chuẩn). `.gitignore` khá tốt nhưng chỉ phủ `*.db`/media trong `data/` — file sinh ở thư mục khác sẽ lọt. 1 trường `client_secret` literal trong manifest vendor Asana cần đối chiếu upstream.

### Bản đồ THẬT / NỬA / VỎ (rút gọn)
- **THẬT:** agent loop, 62 tool, Telegram gateway (21 lệnh/43 sub), approval card, memory FTS5, scheduled tasks, voice 2 chiều, vision, tự học skill + hot-reload, tự sửa code + reboot, Meta connector, Google Workspace (qua gog), trajectory log.
- **NỬA:** subagent (1 LLM call trần), kho 424 SKILL.md (chỉ đọc văn bản, không thực thi), TikTok (có OAuth, không có publish), AccessTrade/Agnes (hardcode Mac), browser (chỉ đọc text, không click/form), pipeline video (đủ code nhưng thiếu deps + model ngoài repo).
- **VỎ/KHÔNG CÓ:** memory consolidation, MCP client tổng quát, plugin loader, proactivity/feed, goals & tracking, artifacts, memory tự tổng hợp alignment, đa kênh (chỉ Telegram), tách lớp dossier SOUL/USER/MEMORY.

### So với Muse — khoảng trống cốt lõi
Mulon thiếu đúng những thứ làm nên "Muse": (1) dossier tách lớp + tự cập nhật từ hội thoại (alignment), (2) goals & cam kết dài hạn, (3) proactivity — tự quét và đề xuất thay vì chỉ chạy task đặt trước, (4) đa kênh, (5) subagent có tool thật, (6) artifacts/tài liệu có vòng đời. Ngược lại Mulon có 2 thứ rất đáng giữ mà Muse bản consumer không có: **tự sửa code + tự reboot** và **tự học skill bằng code + hot-reload**.

---

## PHẦN 2 — CHIẾN LƯỢC CLONE

### Nguyên tắc
1. **Không vá trên nền cũ.** Lấy Mulon làm mỏ linh kiện: giữ khung xương tốt (registry, session, gateway, DB, học skill), viết lại các phần rỗng (sentinel, subagent), cắt toàn bộ catalog chết. Đích: repo mới sạch, cài máy nào cũng chạy.
2. **Định nghĩa "clone Muse" theo lớp:** Lõi agent (persona + memory sống + tools + duyệt thật) → Hành vi Muse (goals, proactivity, đa kênh) → Bề mặt (UI) sau cùng. Không làm UI trước.
3. **Mọi tuyên bố trong README/ARCHITECTURE phải trỏ được vào code chạy.** Hết tính năng trên giấy.

### Giữ nguyên (đã tốt)
- `skills/registry.py` (tool registry + OpenAI schema export)
- `session.py` (session routing)
- `memory.py` phần DB/FTS5 (bỏ tầng facts chết, làm lại ở Phase 2)
- `gateway/__init__.py` khung ingress/egress Telegram + approval card UI
- `hermes_tools.py` cơ chế học skill + hot-reload + auto-load
- `system_tools.py` bộ tool lõi (thêm giới hạn path)
- Pipeline media `nistroly/media/` (đủ code — chỉ cần khai báo deps + bỏ hardcode)
- `meta_mcp.py` (Meta connector viết tay, 17 tool thật)

### Viết lại
- **Sentinel → policy engine thật:** mặc định DENY với tool lạ; mọi mutation ra ngoài (gửi mail, đăng bài, tạo lịch, thanh toán, shell ngoài whitelist hẹp) bắt buộc qua duyệt; duyệt áp dụng cả cho tác vụ nền (hàng đợi duyệt bất đồng bộ thay vì bỏ qua). Đây là Phase 1, ưu tiên số 1 — clone Muse mà lớp duyệt là vỏ thì vô nghĩa.
- **Subagent → agent con có tool:** dùng lại chính agent loop + registry (giới hạn tool theo vai trò), dùng model đang active, có giới hạn concurrency.
- **Context builder:** token budget, cắt tỉa tool result, tóm tắt history dài; không lưu trace HTML vào history (trace chỉ để hiển thị).
- **Commands layer:** viết lại theo hợp đồng chặt với tools (test chữ ký tự động), sửa toàn bộ lỗi Gốc 2.

### Cắt bỏ
- `plugins/` (756 YAML chết), `mcps/` manifests (thay bằng MCP client thật ở Phase 3), `mcp_servers/` mồ côi (chuyển tiktok/rednote thành connector trong core hoặc bỏ), `bin/gog` khỏi git (cài qua brew/install script), dump tài liệu vendor trong `skills/` (chỉ giữ SKILL.md + script cần thiết), toàn bộ dead code (memory_facts cũ, interrupt rỗng, import thừa).

### Lộ trình
**Phase 0 — Dọn nền (nhanh, làm trước):** fork repo → repo mới; gỡ binary + catalog chết khỏi git (repo từ 86MB xuống ~2-3MB); `requirements.txt` đầy đủ + pin version + lock; bỏ mọi hardcode `/Volumes/External` → config/env; gỡ ID/tên thật khỏi config mặc định; `.gitignore` phủ `*.db`/media toàn repo; thêm smoke test tối thiểu (boot + registry + vài lệnh).

**Phase 1 — Lõi tin cậy được:** sentinel đổi thành policy cấu hình được, mặc định full-auto như user muốn (chỉ sửa tài liệu cho khớp hành vi, không ép cơ chế duyệt); agent loop bọc try/except + retry/fallback model + timeout quanh LLM; context budget; sửa toàn bộ lệnh gãy ở commands.py; heartbeat khóa tác vụ chống chạy trùng; recall FTS gấp dấu tiếng Việt + loại session hiện tại. Xong phase này: bot chạy trên máy bất kỳ, duyệt thật, không lệnh flagship nào gãy.

**Phase 2 — Hồn Muse:** tách dossier thành `SOUL.md` / `USER.md` / `MEMORY.md` + thư mục people/groups; vòng consolidation chạy nền: đọc trajectory + history → chắt lọc fact → cập nhật dossier (hồi sinh memory_facts đúng nghĩa, có đọc có ghi); goals & tracked commitments (bảng + tool + lệnh); proactivity engine: heartbeat nâng cấp thành quét nguồn (tin nhắn mới, lịch, hạn chót trong goals) → tổng hợp → chỉ nhắn khi đáng, có cơ chế chọn lọc như Muse.

**Phase 3 — Tay chân Muse:** MCP client tổng quát (stdio + remote + OAuth) để 68 manifest thành connector chạy thật; browser automation có tương tác (click/form/login, dùng phiên trình duyệt thật); thêm kênh Messenger/WhatsApp qua connector sẵn có của ní; artifacts: tài liệu/báo cáo do agent tạo có vòng đời (tạo → sửa → mở lại), tối thiểu qua file + Google Docs.

**Phase 4 — Bề mặt (tùy chọn):** web UI kiểu Muse (chat + goals + feed) chạy local; hoặc giữ Telegram làm bề mặt chính nếu ní thấy đủ. Quyết định sau Phase 2 dựa trên nhu cầu dùng thật.

### Thứ tự bắt tay
Phase 0 → 1 là bắt buộc và nên làm liền một mạch (đó là phần biến "cảm giác sai sai" thành hết sai). Phase 2 là phần biến nó thành Muse chứ không chỉ là "bot Telegram sửa xong". Phase 3-4 mở rộng dần theo nhu cầu.

### Ngoài lề nhưng đáng nói
Mulon là agent đơn người dùng, tự sửa code, chạy shell auto-duyệt — toàn quyền này là lựa chọn có ý thức của user, không phải vấn đề. Khuyến nghị duy nhất còn lại: tài liệu của bản clone phải mô tả đúng hành vi thật (không duyệt), tránh người đọc sau này hiểu lầm như bản audit đầu đã hiểu lầm.

---

## PHẦN 3 — LỚP CẢM GIÁC: vì sao dùng Mulon không giống dùng Muse (bổ sung 2026-10-23 theo nhận xét của user)

Tính năng giống nhau mà cảm giác khác hẳn, vì "giống Muse" nằm ở lớp suy luận + tương tác, không nằm ở danh sách tool. 6 nguyên nhân, tất cả có bằng chứng trong code:

### 1. Model nền yếu hơn hẳn
Mulon chạy `gemini-3.8-flash-high` qua proxy local (config.py). Flash là dòng model nhanh/rẻ: suy luận nông, bám chỉ thị kém, tiếng Việt dễ sáo và liệt kê máy móc. Muse chạy model lớn chuyên cho agent (Muse Spark). **Đây là nguyên nhân lớn nhất của cảm giác "nó cứ ngu ngu"** — cùng một prompt, model flash cho ra cộng sự cấp thấp hơn. Clone muốn giống cảm giác thì phải cắm model mạnh làm mặc định (đống API Claude kredi trong shop là một nguồn sẵn có), flash chỉ để làm việc vặt.

### 2. Mulon "nhớ" bằng cách lục thùng rác, Muse nhớ bằng hồ sơ đã chắt lọc
Mỗi lượt, Mulon ném nguyên câu user vào FTS5, tách từng từ rồi OR hết (memory.py:207-213) → "ký ức liên quan" phần lớn là nhiễu, lại còn lẫn chính hội thoại đang diễn ra. Muse thì có dossier phân lớp (SOUL/USER/MEMORY + people/groups) được tổng hợp lại sau mỗi giai đoạn: nó biết user là ai, đang kẹt ở đâu, ghét bị hỏi lại cái gì — nên câu trả lời trúng ngay mà không cần lục. Mulon có MEMORY.md tĩnh do người viết tay, không bao giờ tự cập nhật → càng dùng càng lệch, trong khi Muse càng dùng càng hiểu.

### 3. Mulon trả lời như máy chạy job, Muse trả lời như người đang chat
- Mọi câu trả lời của Mulon bị gắn khối `[AGENT TRACE]` HTML ở đầu (agent.py:284-327): user luôn nhìn thấy nhật ký máy trước khi thấy câu trả lời. Đã thế trace còn bị lưu vào history → các lượt sau model phải đọc lại đống HTML đó, ngữ cảnh bẩn dần theo thời gian.
- Trong lúc chạy, bot spam tin trạng thái kiểu "Dang suy luan vong 2...", "[read_file] Dang doc..." — cảm giác đứng nhìn terminal chạy. Muse giấu phần máy móc, chỉ hiện kết quả; việc dài thì nhận việc rồi làm nền, người dùng vẫn chat tiếp được.
- Mulon chạy tool tuần tự trong 1 loop tối đa 15 vòng rồi mới trả lời: việc càng dài user càng bị treo chờ. Muse tách việc nặng cho agent con làm nền và giữ hội thoại chính luôn phản hồi.

### 4. Tương tác bằng lệnh vs tương tác bằng ý định
Mulon bắt user học 21 lệnh + 43 sub-command (`/repurpose`, `/tasks add`...) — gõ sai cú pháp là hỏng, đúng chất CLI đội lốt chat. Muse hiểu ngôn ngữ tự nhiên: user nói ý định, agent tự chọn tool, tự hỏi lại đúng chỗ thiếu. Đây là khác biệt cảm giác lớn thứ hai sau model.

### 5. Persona là luật cứng, không phải tính cách
Persona của Mulon là đoạn chỉ thị hardcode trong thân hàm `run()` (agent.py:96-108): cấm emoji tuyệt đối, xưng hô cố định, một giọng cho mọi tình huống. Kết quả là đều đều và gượng. Persona của Muse là file riêng (SOUL.md), có sở thích/quan điểm riêng, và **thích ứng theo năng lượng của user**: lúc cần ngắn thì ngắn, lúc cần sâu thì sâu, biết đùa đúng lúc, biết nhận sai một lần là nhớ luôn. Mulon không có cơ chế "học từ lần bị sửa" — memory_facts chết, trajectory không ai đọc → bị sửa lỗi giống nhau nhiều lần là chuyện thường.

### 6. Không có phán đoán về độ quan trọng
Muse biết việc nào tự làm luôn, việc nào hỏi một câu, việc nào im lặng làm nền (kỷ luật chú ý). Mulon thì mọi thứ qua cùng một khuôn: task nền bỏ qua duyệt hoàn toàn, còn task thường thì treo chờ duyệt 300s/lần. Cảm giác hoặc là bị làm phiền sai chỗ, hoặc là nó tự làm mà không ai hay.

### Hệ quả cho chiến lược clone — thêm "Phase 1.5: Lớp cảm giác" (làm cùng Phase 1-2)
1. **Đổi model mặc định** sang model mạnh (Claude qua API kredi hoặc tương đương); flash xuống vai phụ.
2. **Bỏ trace khỏi câu trả lời và khỏi history** — trace chỉ ghi log nội bộ; trạng thái chạy chỉ hiện khi việc thật sự dài.
3. **Việc dài → agent con nền có tool thật**, hội thoại chính không bị khóa (gộp với mục viết lại subagent ở Phase 1).
4. **Bỏ tư duy slash-command**: lệnh chỉ còn là lối tắt tùy chọn; đường chính là ngôn ngữ tự nhiên → agent tự lập kế hoạch tool.
5. **Persona thành file SOUL.md riêng** + cơ chế thích ứng giọng theo ngữ cảnh; bỏ các cấm đoán tuyệt đối kiểu "không bao giờ emoji".
6. **Vòng học từ sửa sai**: consolidation (Phase 2) phải đọc cả những lần user sửa/phàn nàn và ghi thành quy tắc bền — đây là thứ biến agent từ "nghe lời" thành "hiểu người".
7. **Chính sách chú ý**: phân loại việc theo mức tự chủ (tự làm / hỏi 1 câu / chỉ báo khi xong) thay cho cơ chế duyệt 1 khuôn — sentinel mới ở Phase 1 phải hỗ trợ 3 mức này.

---

## PHẦN 4 — VÌ SAO SỬA HẾT BUG VẪN NGU VÀ CHẬM (bổ sung 2026-10-23, đọc trực tiếp agent.py)

Nhận định của user là đúng: đống bug ở Phần 1 chỉ làm Mulon "gãy", sửa xong thì hết gãy chứ không khôn lên. Ngu và chậm nằm ở kiến trúc vòng lặp, không nằm ở bug. Bằng chứng đọc thẳng từ `agent.py`:

### NGU — 4 nguyên nhân kiến trúc
1. **Trần năng lực là model.** Loop có hay đến đâu cũng không vượt được trần của Gemini Flash. Đây là yếu tố quyết định nhất, code không cứu được.
2. **Context tự đầu độc (context rot).** Kết quả tool được `json.dumps` nguyên khối nhét vào prompt, **không cắt, không đếm token, không nén** (agent.py: dòng append tool_results). Đọc 1 file dài hay 1 trang web là các vòng sau model phải "bơi" trong rác đó suốt 15 vòng lặp → càng làm việc dài càng ngu dần. History thì cố định 12 tin nhắn bất kể độ dài, không có compaction/tóm tắt khi hội thoại dài.
3. **Không có scaffolding suy luận.** Không bước lập kế hoạch (dòng chữ "Dang phan tich & lap ke hoach" chỉ là status hiển thị, không có plan thật), không bước tự kiểm chứng kết quả trước khi báo cáo, không phân rã việc lớn, không trạng thái công việc bền. Mọi thứ dồn vào 1 vòng lặp nông và trí nhớ của model trong vài nghìn token.
4. **Che giấu thất bại.** Hết 15 vòng mà không có câu trả lời thì bot đáp mẫu câu có sẵn "Da hoan thanh cac tac vu duoc giao." — báo xong việc dù chưa chắc xong. Cộng với việc không có try/except quanh lời gọi LLM: lỗi thì chết lượt, không retry, không fallback.

### CHẬM — 4 nguyên nhân kiến trúc
1. **Tool chạy tuần tự.** Model có trả nhiều tool call cùng lúc, code vẫn chạy từng cái một trong vòng `for` (agent.py, khối thực thi tool) — không `asyncio.gather`, không song song.
2. **Mỗi tool tốn thêm vài vòng Telegram.** Trước/sau mỗi tool là các lần sửa tin trạng thái chờ mạng trả lời (status callbacks await inline) — việc 10 tool là thêm ~20 lần round-trip mạng chỉ để hiển thị chữ "Đang...".
3. **Không streaming.** User chờ toàn bộ vòng lặp kết thúc mới thấy chữ đầu tiên của câu trả lời.
4. **Prompt phình theo cấp số nhân trong 1 lượt.** Vì kết quả tool không bao giờ được tỉa, mỗi lời gọi LLM trong cùng 1 lượt lại gửi lại toàn bộ rác của các vòng trước → vòng càng sau càng chậm và càng tốn.

### Kết luận chiến lược (sửa lại thứ tự ưu tiên)
- Vá bug (Phase 0-1 cũ) chỉ là vệ sinh tối thiểu, **không phải** phần làm nên Muse.
- Muốn hết ngu/chậm phải **thay não, giữ vỏ**: giữ Telegram gateway + tools + skills của Mulon; thay (a) model mạnh làm mặc định, (b) context engine — đếm token, cắt tỉa kết quả tool, compaction khi dài, recall có chọn lọc thay vì OR từ khóa, (c) loop có scaffolding — plan → chạy tool song song → tự kiểm chứng → mới báo cáo, có streaming và trạng thái việc bền qua restart.
- Nói cách khác: đừng "sửa Mulon thành Muse". Lấy Mulon làm bộ khung tay chân, viết lại bộ não theo kiến trúc Muse. Phần não là phần việc chính (~70% cảm giác khôn/nhanh), phần vá lỗi chỉ ~30%.
