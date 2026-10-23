"""Mulon — Muse clone (Phase 1 + 2 + 3).

Lõi agent mỏng tự viết theo tài liệu thiết kế
``thiet-ke-ky-thuat-muse-clone.md``: gateway model qua LiteLLM trỏ vào
proxy OpenAI-compatible, context engine chống context rot, vòng lặp
plan-act-verify, ký ức SQLite bi-temporal, bề mặt Telegram duy nhất.
Phase 2 thêm ký ức sống: hybrid recall (vector + BM25), consolidation
worker, học từ correction, background review fork.
Phase 3 thêm tay chân: MCP client thật (SDK chính thức), subagents
(agent loop đầy đủ, toolset thu hẹp), scheduler + goals/tracking,
browser worker (Playwright), khung connector trung tính.
"""

__version__ = "0.3.0"
