"""Mulon — Muse clone 1.1.0 (Phase 1 + 2 + 3 + 4 + 5 + 6).

Lõi agent mỏng tự viết theo tài liệu thiết kế
``thiet-ke-ky-thuat-muse-clone.md``: gateway model qua LiteLLM trỏ vào
proxy OpenAI-compatible, context engine chống context rot, vòng lặp
plan-act-verify, ký ức SQLite bi-temporal, bề mặt Telegram duy nhất.
Phase 2 thêm ký ức sống: hybrid recall (vector + BM25), consolidation
worker, học từ correction, background review fork.
Phase 3 thêm tay chân: MCP client thật (SDK chính thức), subagents
(agent loop đầy đủ, toolset thu hẹp), scheduler + goals/tracking,
browser worker (Playwright), khung connector trung tính.
Phase 4 thêm chủ động + tiếng nói + media: proactivity engine
(heartbeat gom việc, mặc định tắt, chỉ xếp hàng đề xuất), voice hai
chiều (faster-whisper + hiểu ngữ / TTS qua proxy), media pipeline
tools (ffmpeg), MCP streamable HTTP, browser profile bền, skills
system SKILL.md (progressive disclosure + vet tĩnh).
Phase 5 thêm cứng hóa: bộ eval vàng chạy thật (golden + case từ
correction, cổng pass rate), CI GitHub Actions, Langfuse tracing
tuỳ chọn (chỉ metadata, không nội dung), backup/restore có
checksum, báo cáo sức khỏe + đường cong học theo tuần.
Phase 6 hoàn thiện bề mặt group (mục 16): topic = tab trong
supergroup forum (setup + ghim mục lục), Feed tự viết từ tư liệu
nội bộ + taste học từ reaction, thẻ Ideas hết hạn 14 ngày và
'làm luôn' thành goal + task, trình duyệt proactive notes,
Library có thùng rác 30 ngày + chia sẻ <=48h chờ host, Secure
Vault bằng form một lần (giá trị không qua chat/log), bộ nhớ có
bề mặt (truy nguồn, quên có kế hoạch + xác nhận, export/import),
quyền bằng lời thường + lịch sử duyệt.
"""

__version__ = "1.1.0"
