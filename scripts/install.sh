#!/usr/bin/env bash
# ==============================================================================
# Mulon Installer — Cài đặt tự động cho macOS và Linux (T-15)
# ==============================================================================
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
cd "$PROJECT_ROOT"

echo "=================================================================="
echo "          MuLon Automated Installer (macOS & Linux)               "
echo "=================================================================="

# 1. Kiểm tra Python
PYTHON_BIN=""
for cmd in python3.12 python3 python; do
    if command -v "$cmd" >/dev/null 2>&1; then
        VER="$($cmd -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
        if [ "$VER" = "3.12" ] || [ "$VER" = "3.13" ] || [ "$VER" = "3.14" ]; then
            PYTHON_BIN="$(command -v "$cmd")"
            break
        fi
    fi
done

if [ -z "$PYTHON_BIN" ]; then
    echo "❌ Không tìm thấy Python 3.12 trở lên!"
    echo "   Vui lòng cài đặt Python 3.12 (qua brew trên macOS hoặc apt/dnf trên Linux)."
    exit 1
fi
echo "✓ Tìm thấy Python: $PYTHON_BIN ($($PYTHON_BIN --version))"

# 2. Tạo virtualenv nếu chưa có
VENV_DIR="$PROJECT_ROOT/.venv"
if [ ! -d "$VENV_DIR" ]; then
    echo "📦 Đang khởi tạo môi trường ảo .venv..."
    "$PYTHON_BIN" -m venv "$VENV_DIR"
fi
VENV_PY="$VENV_DIR/bin/python"

# 3. Cài đặt dependencies
echo "📦 Đang cài đặt thư viện cần thiết từ requirements.txt..."
"$VENV_PY" -m pip install --upgrade pip -q
"$VENV_PY" -m pip install -r requirements.txt -q
if [ -f requirements-dev.txt ]; then
    "$VENV_PY" -m pip install -r requirements-dev.txt -q
fi
echo "✓ Cài đặt dependencies thành công!"

# 4. Chạy Setup Wizard
echo ""
"$VENV_PY" -m mulon.setup

# 5. Hỏi cài đặt dịch vụ chạy ngầm
echo ""
read -p "Bạn có muốn cài đặt MuLon chạy ngầm tự khởi động cùng máy không? (y/N): " -n 1 -r
echo ""
if [[ $REPLY =~ ^[Yy]$ ]]; then
    "$VENV_PY" -m mulon.service install
fi

echo "=================================================================="
echo "🎉 Cài đặt hoàn tất! Bạn có thể khởi động bot bất cứ lúc nào:"
echo "   .venv/bin/python -m mulon.main"
echo "=================================================================="
