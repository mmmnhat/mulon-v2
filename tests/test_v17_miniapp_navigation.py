"""Kiểm thử hồi quy điều hướng Mini App (T-23.1, QA Q-01):
1. Không còn CSS ẩn nút quay lại (.has-tg-back .backrow display:none).
2. Toàn bộ 14 màn con đều có nút quay lại chuẩn (.backrow, data-back).
3. Hàng điều hướng có user-select:none và pointer-events:none trên đường chia tránh nuốt click.
4. Lịch sử Heartbeat không còn chevron chết (không dead affordance).
5. Điều hướng đa cấp (L1 -> L2 -> L3 -> L2 -> L1) hoạt động nhất quán, không kẹt trạng thái.
"""

import re
from pathlib import Path
import pytest

INDEX_HTML_PATH = Path(__file__).resolve().parent.parent / "mulon" / "webapp" / "index.html"


def test_no_backrow_hidden_rule():
    html = INDEX_HTML_PATH.read_text(encoding="utf-8")
    # Không được có luật display:none trên .backrow khi có has-tg-back
    assert ".has-tg-back .backrow{display:none !important}" not in html
    assert ".has-tg-back .backrow { display: none" not in html
    assert ".has-tg-back .backrow{display:none" not in html


def test_row_user_select_and_divider_pointer_events():
    html = INDEX_HTML_PATH.read_text(encoding="utf-8")
    # .row phải có user-select:none để tránh bôi đen chữ nuốt click trên thân hàng
    assert "user-select:none" in html or "user-select: none" in html
    # Đường chia hàng .row + .row:before phải có pointer-events:none
    assert "pointer-events:none" in html or "pointer-events: none" in html


def test_all_subscreens_have_backrow():
    html = INDEX_HTML_PATH.read_text(encoding="utf-8")
    
    expected_subscreens = [
        "screen-task",
        "screen-profile",
        "screen-skill",
        "screen-system",
        "screen-feed",
        "screen-connectors",
        "screen-google-config",
        "screen-mktcat",
        "screen-listing",
        "screen-install",
        "screen-import",
        "screen-vault",
        "screen-policy",
        "screen-connector-policy",
    ]
    
    for scr_id in expected_subscreens:
        pattern = rf'<section[^>]*id=["\']{scr_id}["\'][^>]*>(.*?)</section>'
        m = re.search(pattern, html, re.DOTALL)
        assert m is not None, f"Màn {scr_id} phải tồn tại trong index.html"
        sec_content = m.group(1)
        assert 'class="backrow"' in sec_content or "class='backrow'" in sec_content, f"Màn {scr_id} phải có nút quay lại (.backrow)"
        assert "data-back" in sec_content, f"Nút quay lại của {scr_id} phải có thuộc tính data-back"
        assert "<svg" in sec_content, f"Nút quay lại của {scr_id} phải có icon SVG"


def test_heartbeat_run_history_no_dead_chevron():
    html = INDEX_HTML_PATH.read_text(encoding="utf-8")
    # Kiểm tra hàm renderHeartbeatRunList không chứa SVG chevron trong run-item
    assert '<svg viewBox="0 0 24 24" width="12" height="12" fill="none" stroke="currentColor" stroke-width="2.2"' not in html


def test_screen_titles_and_navigation_labels_match():
    html = INDEX_HTML_PATH.read_text(encoding="utf-8")
    
    # Hàng Nhập thủ công trong connectors và tiêu đề screen-import phải khớp nhau
    m_conn = re.search(r'id=["\']conn-add-manual["\'][^>]*>.*?class=["\']r-title["\']>\s*([^<]+)', html, re.DOTALL)
    assert m_conn is not None
    assert "Nhập thủ công" in m_conn.group(1)
    
    m_import = re.search(r'id=["\']screen-import["\'][^>]*>.*?class=["\']screen-title["\']>\s*([^<]+)', html, re.DOTALL)
    assert m_import is not None
    assert "Nhập thủ công" in m_import.group(1)


def test_browser_navigation_flow_with_playwright():
    """Kiểm thử hành vi click và điều hướng thực tế trên trình duyệt Chromium."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("Playwright không được cài đặt trong môi trường này")
        
    with sync_playwright() as p:
        try:
            browser = p.chromium.launch(headless=True)
        except Exception as e:
            pytest.skip(f"Chromium không khởi động được: {e}")
            
        page = browser.new_page(viewport={"width": 390, "height": 844})
        
        # Giả lập môi trường Telegram WebApp
        init_script = """
        window.Telegram = {
            WebApp: {
                initData: 'query_id=test&user=%7B%22id%22%3A42%7D&auth_date=1729700000&hash=mock',
                initDataUnsafe: { user: { id: 42 } },
                platform: 'tdesktop',
                ready: function(){},
                expand: function(){},
                BackButton: {
                    show: function(){ this.isVisible = true; },
                    hide: function(){ this.isVisible = false; },
                    onClick: function(fn){ this._cb = fn; },
                    isVisible: false
                },
                HapticFeedback: {
                    impactOccurred: function(){},
                    selectionChanged: function(){}
                }
            }
        };
        """
        page.add_init_script(init_script)
        page.goto(INDEX_HTML_PATH.resolve().as_uri())
        page.wait_for_timeout(200)
        
        # Màn đầu là Việc
        assert page.evaluate("mainTab") == "viec"
        assert page.evaluate("subScreen") is None
        
        # Chuyển sang Cài đặt
        page.locator("#segbar button[data-tab='caidat']").click()
        page.wait_for_timeout(100)
        assert page.evaluate("mainTab") == "caidat"
        assert page.locator("#tab-caidat").is_visible()
        
        # Thử mở từng hàng trong Cài đặt và quay lại
        screens = [
            ("screen-connectors", "Công cụ kết nối"),
            ("screen-vault", "Kho lưu trữ an toàn"),
            ("screen-policy", "Quyền"),
            ("screen-feed", "Feed chủ động"),
            ("screen-system", "Thiết bị & hệ thống")
        ]
        
        for scr_id, _ in screens:
            # Nhấp trực tiếp vào thân hàng (.r-title)
            row = page.locator(f"#tab-caidat .row[data-open='{scr_id}']")
            assert row.is_visible()
            row.locator(".r-title").click()
            page.wait_for_timeout(100)
            
            # Phải mở đúng màn con ngay lần đầu
            assert page.evaluate("subScreen") == scr_id
            scr_el = page.locator(f"#{scr_id}")
            assert scr_el.is_visible()
            assert not page.locator("#tab-caidat").is_visible()
            
            # Nút quay lại phải hiển thị và bấm được
            back_btn = scr_el.locator(".backrow")
            assert back_btn.is_visible()
            back_btn.click()
            page.wait_for_timeout(100)
            
            # Trạng thái quay về Cài đặt sạch sẽ
            assert page.evaluate("subScreen") is None
            assert page.locator("#tab-caidat").is_visible()
            assert not scr_el.is_visible()
            
        # Kiểm tra điều hướng đa cấp (Connectors -> Import -> Back -> Back)
        page.locator("#tab-caidat .row[data-open='screen-connectors']").click()
        page.wait_for_timeout(100)
        assert page.evaluate("subScreen") == "screen-connectors"
        
        page.locator("#conn-add-manual").click()
        page.wait_for_timeout(100)
        assert page.evaluate("subScreen") == "screen-import"
        assert page.locator("#screen-import").is_visible()
        
        # Back về connectors
        page.locator("#screen-import .backrow").click()
        page.wait_for_timeout(100)
        assert page.evaluate("subScreen") == "screen-connectors"
        assert page.locator("#screen-connectors").is_visible()
        
        # Back về caidat
        page.locator("#screen-connectors .backrow").click()
        page.wait_for_timeout(100)
        assert page.evaluate("subScreen") is None
        assert page.locator("#tab-caidat").is_visible()

        # Kiểm tra tab Lịch -> nhấn thân hàng Heartbeat mở modal ngay cả trước khi API trả về
        page.locator("#segbar button[data-tab='lich']").click()
        page.wait_for_timeout(100)
        assert page.evaluate("mainTab") == "lich"
        page.locator("#card-heartbeat-item").click()
        page.wait_for_timeout(100)
        assert not page.locator("#modal-heartbeat").evaluate("el => el.classList.contains('hidden')")
        page.locator("#btn-close-heartbeat").click()
        page.wait_for_timeout(100)
        assert page.locator("#modal-heartbeat").evaluate("el => el.classList.contains('hidden')")

        # Kiểm tra tab Hồ sơ -> nhấn 4 hàng điều hướng mở 4 màn con + nút Quay lại (T-23.3)
        page.locator("#segbar button[data-tab='hoso']").click()
        page.wait_for_timeout(100)
        for card_id, screen_id in [
            ("#card-dossier", "screen-sub-dossier"),
            ("#card-memory", "screen-sub-memory"),
            ("#card-skills", "screen-sub-skills"),
            ("#card-library", "screen-sub-library"),
        ]:
            page.locator(card_id).click()
            page.wait_for_timeout(100)
            assert page.evaluate("subScreen") == screen_id
            assert page.locator(f"#{screen_id}").is_visible()
            page.locator(f"#{screen_id} .backrow").click()
            page.wait_for_timeout(100)
            assert page.evaluate("subScreen") is None
            assert page.locator("#tab-hoso").is_visible()

        browser.close()
