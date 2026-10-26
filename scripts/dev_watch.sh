#!/bin/bash
set -euo pipefail

# Suy PATH từ $HOME và các đường dẫn chuẩn của hệ thống, không hardcode path cá nhân
HOME_DIR="${HOME:-$(eval echo ~)}"
EXTRA_PATHS="${HOME_DIR}/.local/bin:/opt/homebrew/bin:/usr/local/bin"
export PATH="${EXTRA_PATHS}:${PATH:-/usr/bin:/bin:/usr/sbin:/sbin}"

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="${DEV_WATCH_PYTHON:-$(which python3 2>/dev/null || true)}"

if [ -z "$PYTHON_BIN" ] || [ ! -x "$PYTHON_BIN" ]; then
    echo "[ERROR] dev_watch.sh: Không tìm thấy python3 trên hệ thống." >&2
    exit 127
fi

exec "$PYTHON_BIN" "$REPO_DIR/scripts/dev_watch.py" "$@"
