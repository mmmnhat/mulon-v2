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
```

## Module

| File | Vai |
|---|---|
| `mulon/config.py` | Cấu hình qua env, không hardcode giá trị cá nhân |
| `mulon/gateway.py` | LiteLLM -> proxy; retry, circuit breaker, đo latency/token |
| `mulon/context.py` | Dossier snapshot, mục bài học, ngân sách token, trim, compaction + memory flush |
| `mulon/memory.py` | SQLite WAL: messages/FTS5, facts bi-temporal, bảng vec0 + chỉ mục lúc ghi, corrections, turn_digests, tasks, trajectory, ledger |
| `mulon/embeddings.py` | Interface Embedder: FastEmbed bge-m3 (lazy, tuỳ chọn) + stub tất định cho test |
| `mulon/learning.py` | Phát hiện correction, phân loại taxonomy, rút bài học chống overfit, sinh eval case |
| `mulon/consolidation.py` | Worker tổng hợp ký ức: trích fact, khử trùng, supersede, backfill embedding; CLI `--once` |
| `mulon/tools.py` | Registry + tool lõi (gồm session_search); contract tên/schema bị khóa bởi test |
| `mulon/policy.py` | Policy 2 lớp (host thắng session), mặc định full-auto |
| `mulon/agent.py` | Vòng plan-act-verify, ngân sách tác vụ, hook correction + review fork nền |
| `mulon/telegram_bot.py` | aiogram 3: batching, streaming edit, chunk HTML, session theo topic, /new kích hoạt consolidation |
| `mulon/main.py` | Boot + `--dry-run` smoke test; vòng consolidation nền khi được bật |

## Nguyên tắc bất biến (rút từ mục 0 của thiết kế)

1. Cảm giác do harness bảo đảm, không phụ thuộc model — model là
   linh kiện thay bằng cấu hình.
2. Không bao giờ báo xong khi chưa kiểm chứng.
3. Việc dài không khóa hội thoại; mỗi session 1 lượt active.
4. Ký ức là hồ sơ chắt lọc + fact có vòng đời, không lục rác.
5. Trace không vào prompt/history.
6. Mặc định full-auto theo lệnh user; policy tồn tại để siết khi cần
   và để truy vết, không phải để chặn mặc định.
