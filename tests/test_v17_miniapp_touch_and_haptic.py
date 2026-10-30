"""Test hồi quy cho [T-39.4a]: Touch target >= 44px, Haptic Feedback & Utility classes."""
from pathlib import Path
import re
import pytest

WEBAPP_INDEX = Path(__file__).resolve().parent.parent / "mulon" / "webapp" / "index.html"


def test_index_html_exists():
    assert WEBAPP_INDEX.exists(), "mulon/webapp/index.html phải tồn tại"


def test_touch_target_rules_enforced():
    """Kiểm tra không còn các khai báo height hoặc min-height nhỏ hơn 44px (như 32px, 36px, 38px, 42px)
    ở các thành phần tương tác chính đã được chuẩn hóa trong T-39.4a."""
    content = WEBAPP_INDEX.read_text(encoding="utf-8")

    # 1. Segbar & Segbar buttons
    assert re.search(r"\.segbar\s*\{[^}]*min-height:\s*48px", content), "Segbar phải có min-height >= 48px"
    assert re.search(r"\.segbar\s+button\s*\{[^}]*min-height:\s*44px", content), "Segbar buttons phải có min-height >= 44px"

    # 2. Search bar
    assert re.search(r"\.ds-search-bar\s*\{[^}]*min-height:\s*44px", content), "Search bar phải có min-height >= 44px"

    # 3. Filter chips
    assert re.search(r"(\.filter-chip|\.fchip)\s*\{[^}]*min-height:\s*44px", content), "Filter chips phải có min-height >= 44px"

    # 4. Lib more button
    assert re.search(r"\.lib-more-btn\s*\{[^}]*height:\s*44px;\s*min-width:\s*44px;\s*min-height:\s*44px", content), "Lib more button phải đạt 44x44px"

    # 5. Buttons trong các màn hình (Task detail, Heartbeat confirm, Library Trash, Bot name)
    assert 'id="btn-stop-task-detail"' in content
    btn_stop_ctx = content[content.find('id="btn-stop-task-detail"') - 100 : content.find('id="btn-stop-task-detail"') + 200]
    assert ('min-height:44px' in btn_stop_ctx or 'touch-target-44' in btn_stop_ctx)

    assert 'id="btn-heartbeat-confirm-pause"' in content
    hb_ctx = content[content.find('id="btn-heartbeat-confirm-pause"') - 50 : content.find('id="btn-heartbeat-confirm-pause"') + 200]
    assert ('min-height:44px' in hb_ctx or 'touch-target-44' in hb_ctx)

    assert 'id="btn-save-bot-name"' in content
    bot_ctx = content[content.find('id="btn-save-bot-name"') - 50 : content.find('id="btn-save-bot-name"') + 200]
    assert ('min-height:44px' in bot_ctx or 'touch-target-44' in bot_ctx)


def test_haptic_feedback_implementation():
    """Kiểm tra hàm haptic hỗ trợ đa hình: select/selection, impact (light/medium/heavy...), notification (success/error/warning)."""
    content = WEBAPP_INDEX.read_text(encoding="utf-8")
    assert "function haptic(kind)" in content
    assert "tg.HapticFeedback.selectionChanged()" in content
    assert "tg.HapticFeedback.notificationOccurred(" in content
    assert "tg.HapticFeedback.impactOccurred(" in content


def test_utility_classes_present():
    """Kiểm tra sự hiện diện của các utility classes chuẩn hóa trong T-39.4a."""
    content = WEBAPP_INDEX.read_text(encoding="utf-8")
    for cls in [".flex-center", ".flex-between", ".flex-col", ".touch-target-44", ".text-sub-12"]:
        assert cls in content, f"Thiếu utility class {cls}"
