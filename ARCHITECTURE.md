# Kiến trúc (tóm tắt)

Tài liệu thiết kế đầy đủ — nguồn sự thật của dự án — là
`docs/thiet-ke-ky-thuat-muse-clone.md` (17 mục + phụ lục repo
open-source). File này chỉ tóm tắt để đọc nhanh trong repo.

## Luồng 1 lượt chat

```
Telegram (DM / group forum topic)
  -> allowlist + gom tin (debounce) + reaction ack
  -> phát hiện correction (heuristic + model rẻ) -> ghi sự kiện học
  -> ContextEngine: dossier snapshot + BÀI HỌC (facts lesson:*)
     + recall hybrid (vector 70% + BM25 30%, trần token, đo ms)
     + history (tóm tắt + lượt gần), đếm token theo ngân sách 200K
  -> Agent:
       chat thường -> 1 lời gọi streaming (fast path)
       việc có tool/dài -> plan (lưu DB) -> act (tool song song,
         kết quả qua trim/offload) -> verify độc lập -> report thật
  -> history lưu CHỈ câu trả lời sạch; trace vào trajectory
  -> nền (không chặn lượt): review fork ghi digest/fact;
     consolidation (khi được bật) trích fact, supersede, backfill
     embedding; message/fact được embed ngay lúc ghi

Việc hẹn giờ (chỉ khi SCHEDULER_ENABLED=1): scheduler quét
schedules tới hạn -> tính + ghi lần kế tiếp trước -> Agent.handle
trong session hệ thống -> trajectory 'schedule_fired'.
Việc con: agent gọi spawn_subagent -> SubagentRunner (semaphore 4)
-> Agent con với registry đã lọc theo profile + gateway đếm token
-> trả digest nén cho agent chính.
Tool MCP: registry chứa mcp_<server>_<tool> -> MCPManager.call_tool
-> ClientSession của SDK (stdio hoặc streamable HTTP) -> tự
reconnect khi session chết.
Tin thoại: Telegram voice -> tải file -> faster-whisper chép lời
-> model rẻ hiểu ngữ -> bản đã hiểu vào batcher như tin chữ;
session bật /voiceon thì câu trả lời được đọc thêm bằng TTS qua
proxy (POST /audio/speech).
Heartbeat (chỉ khi PROACTIVITY_ENABLED=1): đọc checklist
HEARTBEAT.md + PROACTIVE_PREFERENCES.md -> ngữ cảnh nhẹ + 1 lượt
model rẻ -> không có gì: trajectory 'heartbeat' HEARTBEAT_OK, im
lặng; có việc: xếp hàng proactive_notes (pending) chờ bề mặt
Phase 6 trình — không tự gửi.
```

## Module

| File | Vai |
|---|---|
| `mulon/config.py` | Cấu hình qua env, không hardcode giá trị cá nhân |
| `mulon/gateway.py` | LiteLLM -> proxy; retry, circuit breaker, đo latency/token |
| `mulon/context.py` | Dossier snapshot, mục bài học, ngân sách token, trim, compaction + memory flush |
| `mulon/memory.py` | SQLite WAL: messages/FTS5, facts bi-temporal, bảng vec0 + chỉ mục lúc ghi, corrections, turn_digests, tasks, trajectory, ledger, schedules, goals/goal_activity/tracked_items, proactive_notes, feed_posts/feed_signals, idea_cards, library_items |
| `mulon/embeddings.py` | Interface Embedder: FastEmbed bge-m3 (lazy, tuỳ chọn) + stub tất định cho test |
| `mulon/learning.py` | Phát hiện correction, phân loại taxonomy, rút bài học chống overfit, sinh eval case |
| `mulon/consolidation.py` | Worker tổng hợp ký ức: trích fact, khử trùng, supersede, backfill embedding; CLI `--once` |
| `mulon/tools.py` | Registry + tool lõi (gồm session_search); contract tên/schema bị khóa bởi test |
| `mulon/policy.py` | Policy 2 lớp (host thắng session), mặc định full-auto |
| `mulon/agent.py` | Vòng plan-act-verify, ngân sách tác vụ, hook correction + review fork nền |
| `mulon/cron.py` | Cron 5 trường thuần: parse + tính lần chạy kế tiếp theo zoneinfo |
| `mulon/planning.py` | SchedulerService (quét hạn, chống trùng, giao việc cho agent) + tools lịch hẹn/goals |
| `mulon/mcp_client.py` | MCP client bằng SDK chính thức (stdio + streamable HTTP, auth header từ env): nối server theo config, đăng ký tool vào registry, tự reconnect |
| `mulon/subagents.py` | Subagent = Agent đầy đủ với registry lọc theo profile, trần token/vòng riêng, semaphore 4, digest nén |
| `mulon/browser_worker.py` | Playwright headless: web_read (trích text chính) + web_screenshot; profile bền tuỳ chọn (BROWSER_PROFILE_DIR); vắng Playwright thì báo unavailable |
| `mulon/connectors.py` | Khung connector trung tính (health_check + call, đăng ký lazy) + adapter ví dụ `system` |
| `mulon/proactivity.py` | Heartbeat gom việc: checklist HEARTBEAT.md + preferences, ngữ cảnh nhẹ, model rẻ; HEARTBEAT_OK im lặng hoặc xếp hàng proactive_notes; CLI `--once`; mặc định TẮT |
| `mulon/voice.py` | Voice tương tác (mục 8.1): faster-whisper + hiểu ngữ bằng model rẻ; TTS qua proxy chuẩn OpenAI speech; VoiceService cho bề mặt Telegram |
| `mulon/media_tools.py` | Media pipeline (mục 8.2): probe/extract_audio/trim/burn_subs/frames/transcribe bằng ffmpeg — công cụ dựng video, không phải giọng tương tác |
| `mulon/skills.py` | Skills SKILL.md: mục lục progressive disclosure, eligibility theo requires, vet tĩnh ghi trajectory; tool skill_list/skill_read |
| `mulon/telegram_bot.py` | aiogram 3: batching, streaming edit, chunk HTML, session theo topic, /new kích hoạt consolidation, tin thoại -> STT, /voiceon//voiceoff |
| `mulon/main.py` | Boot + `--dry-run` smoke test; vòng consolidation + scheduler + proactivity nền khi được bật đích danh |
| `mulon/evals.py` | Eval vàng: nạp golden.jsonl + cases.jsonl (từ correction), chạy Agent trong DB/workspace tạm từng case với StubGateway tất định (offline) hoặc gateway thật (EVAL_LIVE=1), chấm bằng máy, cổng pass rate -> exit code; CLI `python -m mulon.evals` |
| `mulon/tracing.py` | Langfuse tracing tuỳ chọn bọc gateway: chỉ metadata (model/token/latency/độ dài), không nội dung; thiếu env/gói -> no-op |
| `mulon/backup.py` | Backup .zip (DB qua SQLite backup API + dossier + config không secret + manifest SHA-256); restore kiểm checksum trước khi ghi đè; CLI create/list/restore |
| `mulon/report.py` | Báo cáo sức khỏe chỉ đọc: p50/p95 recall/model/task, đường cong học theo tuần ISO, correction rate 4 tuần, trạng thái ký ức; CLI `python -m mulon.report [--json]` |
| `mulon/surfaces.py` | Bề mặt group (Phase 6): định nghĩa 6 bề mặt + TopicManager (tạo topic, ghim mục lục, map trong kv_state), presenter/parser thuần cho note/ý tưởng/quyền, kế hoạch quên + export/import ký ức |
| `mulon/feed.py` | FeedEngine: brief trong dossier/FEED.md (mục đánh dấu), sinh bài từ tư liệu nội bộ bằng model rẻ, đăng + ghi feed_posts; reaction -> feed_signals -> taste summary |
| `mulon/ideas.py` | IdeaEngine: sinh thẻ ý tưởng (hết hạn theo config), dọn thẻ hết hạn, 'làm luôn' -> goal + task, bỏ qua |
| `mulon/library.py` | LibraryService: lập chỉ mục workspace, thùng rác 30 ngày (move file thật vào workspace/trash/), chia sẻ <=48h trạng thái chờ host |
| `mulon/vault.py` | Secure Vault: VaultStore (file JSON 0600, cửa đọc duy nhất resolve(ref)) + VaultFormServer (stdlib HTTP bind 127.0.0.1, token 1 lần + TTL); giá trị không qua chat/log/trajectory |
| `mulon/approvals.py` | ApprovalBroker (1.2.0): yêu cầu duyệt của policy nấc ask — open/wait/resolve, timeout = hết hạn, "duyệt và nhớ" ghi rule session, listener cho bề mặt tự gỡ thẻ; payload chỉ có tóm tắt args an toàn |
| `mulon/webapp_server.py` | Mini App server (1.2.0): aiohttp bind 127.0.0.1 cổng WEBAPP_PORT, phục vụ `mulon/webapp/index.html` (1 file tĩnh) + API JSON (state/task/profile/policy/connector/approve/schedule); mọi /api/* khóa bằng initData HMAC + ALLOWED_USER_ID; ActivityTracker cho trạng thái sống |

## Nguyên tắc bất biến (rút từ mục 0 của thiết kế)

1. Cảm giác do harness bảo đảm, không phụ thuộc model — model là
   linh kiện thay bằng cấu hình.
2. Không bao giờ báo xong khi chưa kiểm chứng.
3. Việc dài không khóa hội thoại; mỗi session 1 lượt active.
4. Ký ức là hồ sơ chắt lọc + fact có vòng đời, không lục rác.
5. Trace không vào prompt/history.
6. Mặc định full-auto theo lệnh user; policy tồn tại để siết khi cần
   và để truy vết, không phải để chặn mặc định.
