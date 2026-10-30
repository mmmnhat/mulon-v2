"""Test hồi quy cho [T-39.4b]: Module hoá JS Client Mini App (ISSUE-08) — Lát cắt 1.

Kiểm chứng:
1. Namespace window.Mulon tồn tại trong khối <script>.
2. Subsystem Mulon.TG đóng gói đầy đủ các helper Telegram WebApp SDK và HapticFeedback.
3. Subsystem Mulon.API đóng gói fetch client, auth initData và RFC 7807 error parsing.
4. Shim re-export window.api, window.haptic, window.getInitData bảo toàn 100% tương thích ngược.
5. Triệt tiêu dead code: Toàn bộ 5 utility classes (.flex-center, .flex-between, .flex-col, .touch-target-44, .text-sub-12) đều có sử dụng thực tế ở markup HTML/template.
"""
from pathlib import Path
import re
import pytest

WEBAPP_INDEX = Path(__file__).resolve().parent.parent / "mulon" / "webapp" / "index.html"


def test_index_html_exists():
    assert WEBAPP_INDEX.exists(), "mulon/webapp/index.html phải tồn tại"


def test_mulon_namespace_and_subsystems_declared():
    """Kiểm tra khai báo window.Mulon, Mulon.TG và Mulon.API trong script."""
    content = WEBAPP_INDEX.read_text(encoding="utf-8")

    # 1. Khai báo namespace toàn cục
    assert "window.Mulon = window.Mulon || {};" in content, "Namespace window.Mulon phải được khởi tạo"

    # 2. Khai báo Subsystem Mulon.TG
    assert "Mulon.TG = {" in content, "Mulon.TG phải được định nghĩa"
    assert "get raw()" in content, "Mulon.TG phải cung cấp getter raw"
    assert "get isAvailable()" in content, "Mulon.TG phải cung cấp getter isAvailable"
    assert "updateInsets: updateTgInsets" in content, "Mulon.TG phải liên kết updateTgInsets"
    assert "haptic: haptic" in content, "Mulon.TG phải liên kết haptic"

    # 3. Khai báo Subsystem Mulon.API
    assert "Mulon.API = {" in content, "Mulon.API phải được định nghĩa"
    assert "call: api" in content, "Mulon.API phải liên kết call: api"


def test_backward_compatibility_shims_present():
    """Kiểm tra các shim re-export toàn cục để giữ nguyên 100% tương thích ngược."""
    content = WEBAPP_INDEX.read_text(encoding="utf-8")

    assert "window.api = api;" in content, "Phải shim window.api"
    assert "window.haptic = haptic;" in content, "Phải shim window.haptic"
    assert "window.getInitData = getInitData;" in content, "Phải shim window.getInitData"


def test_api_rfc7807_error_handling_present():
    """Kiểm tra hàm api() bắt lỗi theo định dạng RFC 7807 (detail, error, title)."""
    content = WEBAPP_INDEX.read_text(encoding="utf-8")

    api_fn_match = re.search(r"async function api\(path, method, body\)\s*\{([\s\S]*?)\n\}", content)
    assert api_fn_match, "Hàm api(path, method, body) phải tồn tại"
    api_body = api_fn_match.group(1)

    assert "data.detail || data.error || data.title" in api_body, "api() phải parse detail/error/title từ RFC 7807 response"
    assert "err.rfc7807 = data;" in api_body, "api() phải đính kèm data RFC 7807 vào Error object"


def test_utility_classes_have_actual_markup_usage():
    """Kiểm chứng cả 5 utility classes đều được sử dụng thực tế trong markup, không có dead code."""
    content = WEBAPP_INDEX.read_text(encoding="utf-8")

    utility_classes = {
        "flex-center": 0,
        "flex-between": 0,
        "flex-col": 0,
        "touch-target-44": 0,
        "text-sub-12": 0,
    }

    for cls in utility_classes:
        # Đếm số lần xuất hiện ở dạng class="... cls ..." hoặc class='... cls ...'
        pattern = rf'class=[\'"][^\'"]*\b{re.escape(cls)}\b[^\'"]*[\'"]'
        matches = re.findall(pattern, content)
        count = len(matches)
        utility_classes[cls] = count
        assert count >= 1, f"Utility class '{cls}' không được dùng ở markup nào (dead code)!"

    # Khẳng định số lượng cụ thể đã kiểm chứng
    assert utility_classes["flex-center"] >= 2, f".flex-center phải dùng ít nhất 2 lần, thực tế: {utility_classes['flex-center']}"
    assert utility_classes["flex-col"] >= 3, f".flex-col phải dùng ít nhất 3 lần, thực tế: {utility_classes['flex-col']}"
