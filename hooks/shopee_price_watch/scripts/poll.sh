#!/usr/bin/env bash
set -euo pipefail
# Script Bash kiểm tra thay đổi giá deal (chuẩn Muse: không secret, timeout ngắn)
# Kết thúc bằng đúng 1 terminal decision: "silent" hoặc "wake" (+ reason, payload)

echo '{"decision": "silent", "reason": "Giá sản phẩm đang ổn định, chưa có flash sale", "payload": {"item_id": 12345, "current_price": 250000}}'
