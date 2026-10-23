"""Mulon — Muse clone (Phase 1 + 2 + 3 + 4 + 5).

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
"""

__version__ = "0.5.0"
