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


def test_detect_task_platform_rule0_and_normalization():
    """Kiểm tra logic nhận diện nền tảng Rule 0 và trường additive platform (ADR-003, [T-40] Lát cắt 2)."""
    from mulon.webapp_server import _detect_task_platform, _normalize_task_view

    # 1. Fallback chuẩn: Khi không có manh mối nền tảng -> None (không đoán bừa)
    neutral_task = {
        "id": "t_neutral",
        "title": "Kiểm tra tính toàn vẹn cơ sở dữ liệu nội bộ",
        "status": "done",
    }
    assert _detect_task_platform(neutral_task) is None
    norm_neutral = _normalize_task_view(neutral_task)
    assert "platform" in norm_neutral
    assert norm_neutral["platform"] is None

    # 2. Nhận diện qua title các nền tảng
    cases = [
        ("Đăng bài lên Facebook fanpage bán hàng", "facebook", "FA", "facebook.com"),
        ("Quét bài viết mới nhất trên Threads", "threads", "TH", "threads.net"),
        ("Cập nhật dữ liệu vào Google Sheets", "sheets", "GS", "Google Sheets"),
        ("Gửi thông báo qua Zalo OA khách hàng", "zalo", "ZL", "Zalo"),
        ("Cào dữ liệu thị trường từ web tin tức", "web", "WB", "Web"),
    ]
    for title, expected_key, expected_code, expected_name in cases:
        t = {"id": f"t_{expected_key}", "title": title, "status": "done"}
        detected = _detect_task_platform(t)
        assert detected is not None, f"Phải nhận diện được {expected_key} từ title '{title}'"
        assert detected["key"] == expected_key
        assert detected["code"] == expected_code
        assert detected["name"] == expected_name
        norm = _normalize_task_view(t)
        assert norm["platform"] == detected

    # 3. Nhận diện qua steps chi tiết khi title chung chung
    step_task = {
        "id": "t_step",
        "title": "Thực hiện tác vụ tự động #42",
        "status": "running",
    }
    steps = [
        {"idx": 0, "title": "Khởi tạo môi trường", "status": "done"},
        {"idx": 1, "title": "Mở bảng tính spreadsheet cập nhật dòng mới", "status": "doing"},
    ]
    step_detected = _detect_task_platform(step_task, norm_steps=steps)
    assert step_detected is not None
    assert step_detected["code"] == "GS"
    assert step_detected["name"] == "Google Sheets"

    # 4. Tôn trọng platform khai báo rõ ràng (explicit)
    explicit_task = {
        "id": "t_explicit",
        "title": "Đồng bộ đơn hàng",
        "platform": {"code": "FA", "name": "facebook.com"},
    }
    assert _detect_task_platform(explicit_task) == {"code": "FA", "name": "facebook.com"}


def test_muse_activity_stream_and_platform_badges():
    """Kiểm tra Activity Stream Cards, Date Grouping và Platform Badges trong DOM (ADR-003, [T-40] Lát cắt 2)."""
    content = WEBAPP_INDEX.read_text(encoding="utf-8")

    # 1. CSS Design Tokens & Styles cho Activity Stream
    assert ".stream-group" in content, "Phải có CSS .stream-group cho phân nhóm thời gian"
    assert ".stream-group-title" in content, "Phải có CSS .stream-group-title ('Hôm nay', 'Hôm qua')"
    assert ".stream-group-items" in content, "Phải có CSS .stream-group-items bọc danh sách thẻ"
    assert ".row.stream-card" in content, "Phải có CSS .row.stream-card kế thừa .row"
    assert ".stream-status-glyph" in content, "Phải có CSS .stream-status-glyph cho icon trạng thái tròn"
    assert ".stream-platform-badge" in content, "Phải có CSS .stream-platform-badge"
    assert ".badge-code" in content, "Phải có CSS .badge-code (FA, TH, GS, ZL, WB)"
    assert ".badge-name" in content, "Phải có CSS .badge-name"

    # 2. Touch target & Ranh giới an toàn
    assert re.search(r"\.row\.stream-card\s*\{[^}]*min-height:\s*56px", content), "Stream card min-height 56px >= 44px"

    # 3. Hàm render JS trong Client Script
    assert "function renderPlatformBadge(" in content, "Client script phải có renderPlatformBadge"
    assert "function renderStatusGlyph(" in content, "Client script phải có renderStatusGlyph"
    assert "getDayGroupKey(t.created_at)" in content, "renderTasks phải phân nhóm theo getDayGroupKey"
    assert 'class="row stream-card"' in content, "renderTasks phải gán class 'row stream-card' để giữ tương thích ngược"


def test_muse_split_view_desktop_responsive_and_glyph_cancelled():
    """Kiểm tra Responsive Split-View Telegram Desktop (>= 768px) và glyph cancelled (ADR-003, [T-40] Lát cắt 3)."""
    content = WEBAPP_INDEX.read_text(encoding="utf-8")

    # 1. Bổ sung rule CSS cho .stream-status-glyph.cancelled (theo ghi chú nghiệm thu Lát cắt 2 của Muse)
    assert ".stream-status-glyph.cancelled" in content, "Phải có rule CSS riêng cho .stream-status-glyph.cancelled"

    # 2. Breakpoint min-width: 768px thay thế cap 600px cũ
    assert "@media (min-width:768px)" in content or "@media (min-width: 768px)" in content, "Phải có breakpoint min-width: 768px"
    assert "max-width:960px" in content or "max-width: 960px" in content, "Body mở rộng max-width: 960px cho màn hình Desktop"

    # 3. Split-View 2 cột trên #tab-viec
    assert re.search(r"#tab-viec\s*\{[^}]*display:\s*grid", content), "#tab-viec phải dùng grid ở Desktop"
    assert re.search(r"#tab-viec\s*\{[^}]*grid-template-columns:", content), "#tab-viec phải chia 2 cột"
    assert "#tasks-overview-bar" in content, "Thanh overview bar phải nằm trong CSS Desktop"
    assert "#card-goals" in content, "Card goals phải định vị ở cột 2 Desktop"





