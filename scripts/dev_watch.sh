#!/bin/bash
set -euo pipefail

# Thiết lập PATH đầy đủ cho môi trường LaunchAgent trên macOS
export PATH="/Users/mmmnhat/.local/bin:/Volumes/External/homebrew/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin:${PATH:-}"

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON_BIN="/Volumes/External/homebrew/bin/python3"

if [ ! -x "$PYTHON_BIN" ]; then
    PYTHON_BIN="$(which python3)"
fi

exec "$PYTHON_BIN" "$REPO_DIR/scripts/dev_watch.py" "$@"
