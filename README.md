# Mulon — Muse clone (Phase 1 + 2 + 3)

Personal AI agent chạy **chỉ trên Telegram**, model **chỉ qua proxy
local tương thích OpenAI** (không dùng API chính thức), xây theo tài
liệu thiết kế `docs/thiet-ke-ky-thuat-muse-clone.md`. Repo này thay thế
toàn bộ Mulon/Nistroly cũ: giữ ý tưởng tốt (Telegram gateway, tool
registry, dossier), bỏ toàn bộ code lõi cũ.

## Đã có ở bản này (Phase 1)

- **Model gateway** (`mulon/gateway.py`): LiteLLM trỏ vào proxy; streaming;
  retry backoff + circuit breaker; đếm token (estimator LiteLLM +
  fallback ký tự); mọi lời gọi ghi trajectory kèm latency/token.
- **Context engine** (`mulon/context.py`): dossier snapshot đóng băng;
  ngân sách cửa sổ 200K token, đếm trước khi gọi; trim kết quả tool
  (trần 8K ký tự, thừa offload ra file artifact); compaction có
  **memory flush trích fact trước khi nén**; đóng khung dữ liệu ngoài
  chống injection.
- **Agent core** (`mulon/agent.py`): vòng **plan–act–verify** — kế
  hoạch lưu DB, tool độc lập chạy song song (`asyncio.gather`), verify
  độc lập bằng prompt kiểm chứng, fail thì retry kèm chẩn đoán; cấm
  báo "đã xong" khi chưa kiểm chứng. Trace chỉ vào trajectory, không
  vào history.
- **Ký ức** (`mulon/memory.py`): SQLite WAL; `messages` + FTS5 (có
  gấp dấu tiếng Việt); `memory_facts` **bi-temporal** (fact cũ bị thay
  thế, không xóa); tasks/task_steps; ledger append-only kèm SHA-256.

## Đã có thêm ở Phase 2 — ký ức sống

- **Hybrid recall thật** (`mulon/memory.py` + `mulon/embeddings.py`):
  FTS/BM25 + vector `sqlite-vec` hợp nhất theo trọng số **70% vector /
  30% BM25** (điểm từng nhánh chuẩn hoá trước khi trộn). Embedding
  local **bge-m3 qua FastEmbed** (lazy-load; cần `pip install
  fastembed`), vắng hoặc lỗi thì **degrade sạch xuống BM25-only** +
  ghi trajectory. Đánh chỉ mục **lúc ghi** (message/fact vừa ghi được
  embed ngay); lúc đọc chỉ embed đúng 1 câu truy vấn; **không dùng
  LLM rerank** trong đường chat. Mọi lần recall đều đo mili-giây và
  ghi trajectory.
- **Consolidation worker** (`mulon/consolidation.py`): đọc episode
  chưa xử lý → model rẻ trích fact ứng viên (JSON chặt, parse phòng
  thủ) → trùng thì bỏ, cùng chủ đề mà khác nội dung thì **supersede**
  theo cơ chế bi-temporal + ghi ledger; watermark theo phiên chống
  xử lý trùng. Chạy tay: `python -m mulon.consolidation --once`;
  trong bot: vòng lặp nền chỉ khi `CONSOLIDATION_ENABLED=1`, và lệnh
  `/new` kích hoạt cho phiên vừa đóng.
- **Học từ correction** (`mulon/learning.py`): user sửa → heuristic
  tiếng Việt bắt tín hiệu ngay trong lượt → model rẻ phân loại theo
  taxonomy 5 loại (dữ kiện / quy trình / giọng-format / tool / trí
  nhớ) → ghi bảng `corrections`. Đủ ngưỡng chống overfit (≥1 lần sửa
  rõ ràng, ≥2 lần lặp, hoặc lỗi tiền/an toàn chỉ cần 1 lần) thì rút
  thành **bài học** dạng fact, nạp vào ngữ cảnh ở mục riêng mỗi lượt.
  Correction nghiêm trọng tự sinh test case vào `evals/cases.jsonl`.
- **Background review fork**: sau mỗi lượt, một fork nhẹ chạy nền
  (model rẻ, trần token cấu hình được) rà soát lượt vừa rồi, ghi
  digest vào `turn_digests` + fact bền. Lỗi của fork không ảnh hưởng
  lượt chính.
- **Session search**: tool `session_search` tìm trong các phiên
  trước, trả **nguyên văn** tin gốc kèm session id + thời gian.

## Đã có thêm ở Phase 3 — tay chân

- **MCP client thật** (`mulon/mcp_client.py`): SDK MCP chính thức,
  kết nối server qua **stdio** theo `config/mcp_servers.json` (kèm
  server ví dụ ở trạng thái tắt), liệt kê tool của server và đăng
  ký vào registry chung với tên `mcp_<server>_<tool>`, schema MCP
  ánh xạ thẳng sang schema nội bộ, gọi tool qua session có timeout
  và **tự reconnect** khi session chết. Server lỗi hoặc chưa cấu
  hình thì degrade sạch — bot vẫn chạy.
- **Subagents thật** (`mulon/subagents.py`): subagent là **agent
  loop đầy đủ** (cùng core plan-act-verify), không phải 1 lời gọi
  LLM trần. Toolset thu hẹp theo profile: `researcher` (chỉ đọc +
  web), `coder` (file + lệnh trong workspace), `default` (tối
  thiểu, chỉ đọc); trần vòng lặp + trần token riêng; tối đa **4
  chạy đồng thời**; kết quả trả **digest nén** (trạng thái + tóm
  tắt + số liệu), không trả transcript. Tool: `spawn_subagent`.
- **Scheduler + goals/tracking** (`mulon/planning.py` +
  `mulon/cron.py`): bảng `schedules` (cron 5 trường tự viết, múi
  giờ tường minh mặc định Asia/Ho_Chi_Minh), `goals` (2 trạng
  thái, activity log, không bao giờ tự đóng), `tracked_items`.
  Tools: `schedule_task`, `list_schedules`, `cancel_schedule`,
  `create_goal`, `list_goals`, `log_goal_activity`, `close_goal`.
  Vòng lặp scheduler **mặc định TẮT** (`SCHEDULER_ENABLED=1` mới
  chạy) — tới hạn thì tính lần kế tiếp và ghi trước (chống bắn
  trùng) rồi giao việc cho agent trong session hệ thống.
- **Browser worker tối thiểu** (`mulon/browser_worker.py`):
  Playwright/Chromium headless — `web_read` (mở URL, trích text
  chính) và `web_screenshot` (PNG lưu vào `workspace/screenshots`).
  Playwright là optional: vắng thì tool báo `unavailable` sạch.
- **Khung connector trung tính** (`mulon/connectors.py`): interface
  `health_check()` + `call(action, args)`, đăng ký lazy (chưa cấu
  hình thì vắng mặt sạch), kiểm tra trạng thái qua
  `connector_health` / `connector_call`. Kèm adapter ví dụ `system`
  (giờ + trạng thái máy) để chứng minh khung; adapter dịch vụ thật
  cắm vào cùng interface ở phase sau. Luật của khung: credential
  không bao giờ xuất hiện trong kết quả/log/trajectory.

## Thành phần Phase 1 (nền)

- **Tool registry** (`mulon/tools.py`): read/write/edit file, list_dir,
  run_command (cwd tường minh, có timeout), web_fetch, memory_search,
  memory_get, add_memory_fact, session_search, now. Mọi tool bọc lỗi
  thành cấu trúc. File tool bị neo trong `workspace/` trừ khi bật cờ
  cho phép ra ngoài.
- **Policy engine 2 lớp** (`mulon/policy.py`): file host
  `config/policy.json` thắng mọi cấu hình phiên; mặc định full-auto
  theo lệnh user; mọi quyết định ghi trajectory.
- **Telegram** (`mulon/telegram_bot.py`): aiogram 3, allowlist cứng,
  gom tin liên tiếp (debounce 2.5s), ack bằng reaction, streaming bằng
  edit tại chỗ, chunk HTML an toàn thẻ, session theo (chat, topic).
  Lệnh: `/start` `/status` `/new` (chốt phiên) `/memory`.
- **Dossier mẫu** trong `dossier/`: SOUL / IDENTITY / USER / MEMORY /
  AGENTS / TOOLS / HEARTBEAT / BOOTSTRAP / alignment.

## Chưa có (khung chờ các phase sau)

Proactivity engine + heartbeat runner (scheduler đã có hạ tầng
nhưng pipeline chấm điểm/chủ động nhắn thì chưa), voice (Whisper +
LLM / OpenAI Voice), media pipeline, adapter connector cho dịch vụ
thật (hiện mới có khung + adapter ví dụ `system`), MCP qua HTTP
streamable + OAuth (hiện mới stdio), học skill mới dạng SKILL.md
đăng ký nóng, alignment synthesis worker (tổng hợp `alignment.md`
hằng ngày), consolidation tách fact thành
`people/*.md`/`groups/*.md` (hiện mới ghi vào DB), thủ tục hóa từ
trajectory (mục 4.5), chạy bộ eval vàng tự động (mới sinh case) +
Langfuse, Mini App — **không** làm (đã chốt: group forum là bề
mặt chính). Xem roadmap mục 13 của tài liệu thiết kế.

## Chạy

```bash
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
cp .env.example .env   # điền TELEGRAM_BOT_TOKEN + ALLOWED_USER_ID
.venv/bin/python -m mulon.main --dry-run   # smoke test, không cần token
.venv/bin/python -m mulon.main             # chạy bot
```

Hoặc Docker: `docker compose up -d`.

## Kiểm thử

```bash
.venv/bin/pip install -r requirements-dev.txt
.venv/bin/python -m pytest tests/ -q
```
