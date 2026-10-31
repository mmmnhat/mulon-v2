"""Test hồi quy cho [T-39.4b]: Module hoá JS Client Mini App (ISSUE-08) — Lát cắt 1, 2 & 3.

Kiểm chứng:
1. Namespace window.Mulon tồn tại trong khối <script>.
2. Subsystem Mulon.TG đóng gói đầy đủ các helper Telegram WebApp SDK và HapticFeedback.
3. Subsystem Mulon.API đóng gói fetch client, auth initData và RFC 7807 error parsing.
4. Subsystem Mulon.State đóng gói Reactive State Store và Event Bus nội bộ (on, off, emit).
5. Subsystem Mulon.Mascot đóng gói bộ điều khiển Sprite Mascot Animator và voice indicators.
6. Subsystem Mulon.Tabs phân rã 5 tab (viec, pheduyet, lich, hoso, caidat) có lifecycle render/mount/cleanup.
7. Thống nhất chuyển tab/màn qua Mulon.State.setTab và setSubScreen (triệt tiêu 2 đường đổi state).
8. Shim re-export toàn cục (api, haptic, getInitData, spritePlay, spriteStop, spriteApplyBase, flashAvatar, showMain, showSub, renderAll) bảo toàn 100% tương thích ngược.
9. Triệt tiêu dead code: Toàn bộ 5 utility classes (.flex-center, .flex-between, .flex-col, .touch-target-44, .text-sub-12) đều có sử dụng thực tế ở markup HTML/template.
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


def test_mulon_state_subsystem_declared():
    """Kiểm tra khai báo Subsystem Mulon.State và Event Bus nội bộ (Lát cắt 2)."""
    content = WEBAPP_INDEX.read_text(encoding="utf-8")

    assert "Mulon.State = {" in content, "Mulon.State phải được định nghĩa"
    assert "get current()" in content, "Mulon.State phải cung cấp getter current"
    assert "get tab()" in content, "Mulon.State phải cung cấp getter tab"
    assert "get subScreen()" in content, "Mulon.State phải cung cấp getter subScreen"
    assert "set: function(newS)" in content, "Mulon.State phải có method set"
    assert "setTab: function(tab)" in content, "Mulon.State phải có method setTab"
    assert "setSubScreen: function(id)" in content, "Mulon.State phải có method setSubScreen"
    assert "on: function(event, handler)" in content, "Mulon.State phải cung cấp Event Bus on"
    assert "off: function(event, handler)" in content, "Mulon.State phải cung cấp Event Bus off"
    assert "emit: function(event, ...args)" in content, "Mulon.State phải cung cấp Event Bus emit"


def test_mulon_mascot_subsystem_declared():
    """Kiểm tra khai báo Subsystem Mulon.Mascot đóng gói Sprite controller (Lát cắt 2)."""
    content = WEBAPP_INDEX.read_text(encoding="utf-8")

    assert "Mulon.Mascot = {" in content, "Mulon.Mascot phải được định nghĩa"
    assert "getBaseState: spriteBaseState" in content, "Mulon.Mascot phải liên kết getBaseState"
    assert "applyBase: spriteApplyBase" in content, "Mulon.Mascot phải liên kết applyBase"
    assert "flash: flashAvatar" in content, "Mulon.Mascot phải liên kết flash"
    assert "stop: spriteStop" in content, "Mulon.Mascot phải liên kết stop"
    assert "play: function(name, once)" in content, "Mulon.Mascot phải có method play phát event mascot:state"


def test_mulon_tabs_subsystem_and_lifecycle():
    """Kiểm tra khai báo Subsystem Mulon.Tabs và lifecycle render/mount/cleanup (Lát cắt 3)."""
    content = WEBAPP_INDEX.read_text(encoding="utf-8")

    assert "Mulon.Tabs = {" in content, "Mulon.Tabs phải được định nghĩa"
    for tab in ["viec", "pheduyet", "lich", "hoso", "caidat"]:
        assert f"{tab}: {{" in content, f"Mulon.Tabs phải chứa tab {tab}"
    assert "renderAll: function()" in content, "Mulon.Tabs phải cung cấp method renderAll"
    assert "stopOpPoll()" in content, "Mulon.Tabs.caidat.cleanup phải gọi stopOpPoll"


def test_state_and_lifecycle_integration():
    """Kiểm tra tích hợp chuyển tab/màn và lifecycle qua Mulon.State & Mulon.Tabs."""
    content = WEBAPP_INDEX.read_text(encoding="utf-8")

    assert "window.Mulon.State.setTab(tab)" in content, "showMain phải gọi Mulon.State.setTab(tab)"
    assert "window.Mulon.State.setSubScreen(id)" in content, "showSub phải gọi Mulon.State.setSubScreen(id)"
    assert "window.Mulon.Tabs[prevTab].cleanup()" in content, "showMain phải gọi cleanup của tab trước"
    assert "window.Mulon.Tabs[tab].mount()" in content, "showMain phải gọi mount của tab mới"
    assert "window.Mulon.Tabs.renderAll()" in content, "renderAll phải uỷ quyền qua Mulon.Tabs.renderAll"
    assert "window.Mulon.State.set(S)" in content, "load() phải đồng bộ state qua Mulon.State.set(S)"


def test_backward_compatibility_shims_present():
    """Kiểm tra các shim re-export toàn cục để giữ nguyên 100% tương thích ngược."""
    content = WEBAPP_INDEX.read_text(encoding="utf-8")

    assert "window.api = api;" in content, "Phải shim window.api"
    assert "window.haptic = haptic;" in content, "Phải shim window.haptic"
    assert "window.getInitData = getInitData;" in content, "Phải shim window.getInitData"
    assert "window.spritePlay = spritePlay;" in content, "Phải shim window.spritePlay"
    assert "window.spriteStop = spriteStop;" in content, "Phải shim window.spriteStop"
    assert "window.spriteApplyBase = spriteApplyBase;" in content, "Phải shim window.spriteApplyBase"
    assert "window.flashAvatar = flashAvatar;" in content, "Phải shim window.flashAvatar"
    assert "window.showMain = showMain;" in content, "Phải shim window.showMain"
    assert "window.showSub = showSub;" in content, "Phải shim window.showSub"
    assert "window.renderAll = renderAll;" in content, "Phải shim window.renderAll"


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


def test_muse_clean_palette_tokens_present():
    """Kiểm tra hệ thống Design Tokens Muse Clean Palette (ADR-003, [T-40] Lát cắt 1)."""
    content = WEBAPP_INDEX.read_text(encoding="utf-8")

    # Light mode
    assert "--paper:#F8F9FA;" in content, "Light mode nền phải là xám Muse #F8F9FA"
    assert "--surface:#FFFFFF;" in content, "Light mode thẻ card phải là #FFFFFF"
    assert "--line:#EBECEF;" in content, "Light mode viền phải là #EBECEF"
    assert "--accent:#7C3AED;" in content, "Màu nhấn phải là Tím Mulon #7C3AED (tuân thủ lock thiết kế §6)"

    # Dark mode
    assert "--paper:#121214;" in content, "Dark mode nền phải là Muse dark #121214"
    assert "--surface:#1E1E22;" in content, "Dark mode card phải là #1E1E22"
    assert "--line:#2A2A30;" in content, "Dark mode viền phải là #2A2A30"


def test_muse_companion_hero_and_quick_switcher():
    """Kiểm tra Header Hero Muse Companion và 4 nút quick switcher (ADR-003, [T-40] Lát cắt 1)."""
    content = WEBAPP_INDEX.read_text(encoding="utf-8")

    # 1. Các phần tử danh tính chính của Hero
    assert 'id="avatar-box"' in content, "Avatar box phải tồn tại"
    assert 'id="app-brand-name"' in content, "Brand name bot phải tồn tại"
    assert 'id="status-dot"' in content, "Status dot phải tồn tại"
    assert 'id="status-text"' in content, "Status text phải tồn tại"
    assert 'id="hero-quick-nav"' in content, "Thanh 4 nút Hero Quick Nav phải tồn tại"

    # 2. Đủ 4 nút điều hướng nhanh với data attributes chuẩn
    assert 'data-hero-tab="viec"' in content, "Nút Hero Việc phải liên kết tab viec"
    assert 'data-hero-tab="pheduyet"' in content, "Nút Hero Quyền phải liên kết tab pheduyet"
    assert 'data-hero-tab="lich"' in content, "Nút Hero Lịch phải liên kết tab lich"
    assert 'data-hero-sub="screen-vault"' in content, "Nút Hero Kho phải liên kết subScreen screen-vault"

    # 3. Touch target >= 44px
    assert re.search(r"\.hero-quick-btn\s*\{[^}]*min-width:\s*48px", content), "Hero quick btn min-width >= 44px"
    assert re.search(r"\.hero-quick-btn\s*\{[^}]*min-height:\s*48px", content), "Hero quick btn min-height >= 44px"
    assert re.search(r"\.hero-quick-icon\s*\{[^}]*width:\s*48px", content), "Hero quick icon width >= 44px"

    # 4. Tích hợp chuyển tab đồng bộ
    assert "data.heroTab" in content or "dataset.heroTab" in content, "showMain/click handler phải xử lý heroTab"



