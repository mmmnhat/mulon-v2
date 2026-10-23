# Mulon — Muse clone (Phase 1 + 2)

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

MCP client, scheduler/goals, proactivity/heartbeat runner, subagents,
voice (Whisper + LLM / OpenAI Voice), browser worker, media pipeline,
alignment synthesis worker (tổng hợp `alignment.md` hằng ngày),
consolidation tách fact thành `people/*.md`/`groups/*.md` (hiện mới
ghi vào DB), thủ tục hóa từ trajectory (mục 4.5), chạy bộ eval vàng
tự động (mới sinh case) + Langfuse, Mini App — **không** làm (đã
chốt: group forum là bề mặt chính). Xem roadmap mục 13 của tài
liệu thiết kế.

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
