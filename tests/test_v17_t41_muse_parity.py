"""Test hồi quy cho [T-41] Muse-parity vòng 2 (Lát cắt 1).

Kiểm tra:
1. Bỏ hàng icon Hero (#hero-quick-nav).
2. Nút chỉnh sửa danh tính #btn-edit-identity và Modal #modal-edit-identity (5 mascot chuẩn).
3. Whitelist route static asset mascot /app/assets/mascots/{id}/{filename}.
4. Cấu hình config/mascots.json chuẩn 5 mascot.
5. Luật toàn cục CSS ẩn .backrow, .r-sub, search/chips.
6. Gỡ bỏ văn bản trong ngoặc đơn ở các tiêu đề chính.
"""

from pathlib import Path
import json
import pytest
from aiohttp.test_utils import make_mocked_request
from mulon.webapp_server import WebAppServer

WEBAPP_INDEX = Path(__file__).resolve().parent.parent / "mulon" / "webapp" / "index.html"
MASCOTS_JSON = Path(__file__).resolve().parent.parent / "config" / "mascots.json"


def test_t41_hero_and_identity_edit_modal():
    """Kiểm tra Hero không còn quick-nav và có modal đổi tên + mascot (Mục 1, 12)."""
    content = WEBAPP_INDEX.read_text(encoding="utf-8")

    # 1. Bỏ hàng icon tròn Hero
    assert '<div class="hero-quick-nav" id="hero-quick-nav">' not in content, "Không còn HTML hero-quick-nav"

    # 2. Có icon sửa danh tính cạnh tên
    assert 'id="btn-edit-identity"' in content, "Phải có nút chỉnh sửa danh tính"
    assert 'id="app-brand-name"' in content, "Phải có nhãn tên bot"

    # 3. Có modal đổi tên & mascot
    assert 'id="modal-edit-identity"' in content, "Phải có modal đổi tên và mascot"
    assert 'id="identity-bot-name-input"' in content, "Phải có input nhập tên bot trong modal"
    assert 'id="identity-mascot-picker"' in content, "Phải có container chọn 5 mascot trong modal"
    assert 'id="btn-save-identity"' in content, "Phải có nút lưu thay đổi danh tính"


def test_t41_mascots_config_and_assets():
    """Kiểm tra danh sách đúng 5 mascot chính thức (Mục 12)."""
    data = json.loads(MASCOTS_JSON.read_text(encoding="utf-8"))
    ids = {m["id"] for m in data}
    expected_ids = {"mulon", "bach-tuoc", "meo-hoodie", "may-sam", "nam-sao"}
    assert ids == expected_ids, f"Danh sách ID mascot phải chính xác bằng đúng 5 mascot chính thức: {expected_ids}"

    # Kiểm tra nút edit identity đạt chuẩn touch target >= 44px
    content = WEBAPP_INDEX.read_text(encoding="utf-8")
    assert 'min-width:44px' in content and 'min-height:44px' in content, "Nút edit identity phải đạt chuẩn touch target >= 44px"

    # Kiểm tra asset tồn tại trên đĩa
    mascot_dir = Path(__file__).resolve().parent.parent / "mulon" / "webapp" / "assets" / "mascots"
    for mid in expected_ids:
        cur_dir = mascot_dir / mid
        assert cur_dir.is_dir(), f"Thư mục mascot {mid} phải tồn tại"
        assert (cur_dir / "avatar.webp").is_file(), f"File avatar.webp của {mid} phải tồn tại"
        assert (cur_dir / "manifest-anim.json").is_file(), f"File manifest-anim.json của {mid} phải tồn tại"
        assert (cur_dir / "atlas-anim.webp").is_file(), f"File atlas-anim.webp của {mid} phải tồn tại"


def test_t41_global_css_rules():
    """Kiểm tra luật bỏ hàng icon tròn Hero (Mục 1)."""
    content = WEBAPP_INDEX.read_text(encoding="utf-8")
    assert ".hero-quick-nav" in content, "CSS phải có selector .hero-quick-nav"
    assert "display: none !important;" in content or "display:none !important;" in content, "Phải có rule ẩn hàng icon tròn Hero"


def test_t41_no_parentheses_in_major_titles():
    """Kiểm tra đã gỡ bỏ văn bản trong ngoặc đơn ở các tiêu đề chính (Mục 20)."""
    content = WEBAPP_INDEX.read_text(encoding="utf-8")
    assert "Mục tiêu &amp; Cây tiến triển (Goals)" not in content
    assert "Sắp tới (Upcoming)" not in content
    assert "Sắp tới<" in content
    assert "Mỗi 30 phút (*/30 * * * *)" not in content
    assert "Mỗi 30 phút<" in content


@pytest.mark.asyncio
async def test_t41_mascot_asset_server_endpoint():
    """Kiểm tra route /app/assets/mascots/{id}/{filename} whitelist an toàn."""
    # 1. Mascot hợp lệ -> 200 OK
    req = make_mocked_request("GET", "/app/assets/mascots/mulon/avatar.webp", match_info={"id": "mulon", "filename": "avatar.webp"})
    resp = await WebAppServer._handle_mascot_asset(None, req)
    assert resp.status == 200
    assert resp.content_type == "image/webp"

    # 2. File json manifest -> 200 OK
    req_manifest = make_mocked_request("GET", "/app/assets/mascots/bach-tuoc/manifest-anim.json", match_info={"id": "bach-tuoc", "filename": "manifest-anim.json"})
    resp_manifest = await WebAppServer._handle_mascot_asset(None, req_manifest)
    assert resp_manifest.status == 200
    assert resp_manifest.content_type == "application/json"

    # 3. Mascot lạ -> 404
    req_fake = make_mocked_request("GET", "/app/assets/mascots/invalid_mascot/avatar.webp", match_info={"id": "invalid_mascot", "filename": "avatar.webp"})
    resp_fake = await WebAppServer._handle_mascot_asset(None, req_fake)
    assert resp_fake.status == 404

    # 4. File lạ (chống traversal) -> 404
    req_hack = make_mocked_request("GET", "/app/assets/mascots/mulon/hack.txt", match_info={"id": "mulon", "filename": "hack.txt"})
    resp_hack = await WebAppServer._handle_mascot_asset(None, req_hack)
    assert resp_hack.status == 404


def test_t41_slice2_task_list_elements_removed():
    """Kiểm tra loại bỏ các phần tử thừa ở tab Việc (Mục 2, 3, 4, 5)."""
    content = WEBAPP_INDEX.read_text(encoding="utf-8")

    # 1. Bỏ thanh thống kê việc (Mục 2)
    assert 'id="tasks-overview-bar"' not in content, "Thanh tổng quan việc phải bị loại bỏ khỏi HTML"

    # 2. Bỏ ô tìm kiếm việc (Mục 3)
    assert 'id="tasks-search-wrap"' not in content, "Thanh tìm kiếm việc phải bị loại bỏ khỏi HTML"
    assert 'id="tasks-search-input"' not in content, "Input tìm kiếm việc phải bị loại bỏ khỏi HTML"

    # 3. Bỏ 4 chip lọc ở tab Việc (Mục 5)
    assert 'id="tasks-filter-chips"' not in content, "4 chip lọc phải bị loại bỏ khỏi HTML"

    # 4. Bỏ card Goals ở tab Việc (Mục 4)
    assert 'id="card-goals"' not in content, "Card Goals phải bị loại bỏ khỏi HTML tab Việc"

    # 5. Có container stream phẳng trên nền giấy (Mục 476)
    assert 'id="tasks-stream-container"' in content, "Container stream phẳng phải tồn tại"
    assert 'id="task-list"' in content, "Khối task-list phải tồn tại"


def test_t41_slice2_task_row_density_and_styles():
    """Kiểm tra mật độ hàng việc <= 64px, title 1 dòng và glyph nhỏ trung tính (Mục 473, 475, 481)."""
    import re
    content = WEBAPP_INDEX.read_text(encoding="utf-8")

    # 1. Hàng việc <= 64px và >= 44px
    assert re.search(r"\.row\.stream-card\s*\{[^}]*max-height:\s*64px", content), "Hàng việc phải có max-height 64px"
    assert re.search(r"\.row\.stream-card\s*\{[^}]*min-height:\s*56px", content), "Hàng việc phải có min-height 56px"

    # 2. Glyph check tròn nhỏ trung tính ~20px
    assert re.search(r"\.stream-status-glyph\s*\{[^}]*width:\s*20px", content), "Glyph tròn nhỏ 20px"
    assert re.search(r"\.stream-status-glyph\s*\{[^}]*height:\s*20px", content), "Glyph tròn nhỏ 20px"

    # 3. Title 13px 1 dòng ellipsis
    assert re.search(r"\.row\.stream-card\s+\.r-title\s*\{[^}]*font-size:\s*13px", content), "Title 13px"
    assert re.search(r"\.row\.stream-card\s+\.r-title\s*\{[^}]*text-overflow:\s*ellipsis", content), "Title 1 dòng ellipsis"

    # 4. Sub-text 12px màu ink3
    assert re.search(r"\.row\.stream-card\s+\.r-sub\s*\{[^}]*font-size:\s*12px", content), "Sub 12px"
    assert re.search(r"\.row\.stream-card\s+\.r-sub\s*\{[^}]*color:\s*var\(--ink3\)", content), "Sub màu ink3"

    # 5. Badge nguồn monogram trung tính, ẩn badge-name
    assert ".stream-platform-badge .badge-name{display:none}" in content, "Ẩn badge-name cồng kềnh"

