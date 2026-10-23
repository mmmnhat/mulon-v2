# Mulon — Muse clone (Phase 1)

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
  Recall hybrid: FTS/BM25 là chính, sqlite-vec là optional (không có
  thì tự degrade BM25-only).
- **Tool registry** (`mulon/tools.py`): read/write/edit file, list_dir,
  run_command (cwd tường minh, có timeout), web_fetch, memory_search,
  memory_get, add_memory_fact, now. Mọi tool bọc lỗi thành cấu trúc.
  File tool bị neo trong `workspace/` trừ khi bật cờ cho phép ra ngoài.
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

MCP client, scheduler/goals, proactivity/heartbeat runner, subagents,
voice (Whisper + LLM / OpenAI Voice), browser worker, media pipeline,
consolidation worker đầy đủ + vòng học lỗi, eval vàng + Langfuse,
Mini App — **không** làm (đã chốt: group forum là bề mặt chính).
Xem roadmap mục 13 của tài liệu thiết kế.

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
