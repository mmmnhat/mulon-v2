# Hooks là dữ liệu runtime của từng máy

Thư mục này chứa hook do bot/người dùng tạo khi chạy (manifest,
script, log). KHÔNG commit hook cụ thể của cá nhân vào repo —
trước đây `shopee_price_watch/` (kèm log vận hành) bị commit nhầm
và đã gỡ ở đợt audit hardcode 2026-10-26. `HookManager` tự tạo
thư mục khi cần.
