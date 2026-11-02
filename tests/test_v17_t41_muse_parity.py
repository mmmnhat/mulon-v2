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
    assert "Lịch trình<" in content
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


def test_t41_slice3_dom_structure():
    """Kiểm tra cấu trúc DOM theo Lát cắt 3 (Mục 6, 7, 8, 9, 10, 11, 13, 19, 20)."""
    content = WEBAPP_INDEX.read_text(encoding="utf-8")

    # 1. Tab Lịch: Heartbeat trên cùng, không có schedule-banner (Mục 6, 7)
    assert 'id="schedule-banner"' not in content, "Phải gỡ bỏ schedule-banner rườm rà"
    assert 'id="card-heartbeat-item"' in content, "Heartbeat card phải nằm trên cùng tab Lịch"

    # 2. Màn Cài đặt: Có screen-api-settings, không còn screen-feed, screen-brand, screen-all-tools-policy (Mục 13, 19, 20)
    assert 'id="screen-api-settings"' in content, "Phải có màn Thiết lập API gộp"
    assert 'id="screen-feed"' not in content, "Màn Feed chủ động phải bị loại bỏ"
    assert 'id="screen-all-tools-policy"' not in content, "Màn Tất cả công cụ phải bị loại bỏ"
    assert 'data-open="screen-api-settings"' in content, "Row mở màn Thiết lập API phải có trong Cài đặt"

    # 4. Bỏ văn bản giải thích phụ, sub-text rườm rà dưới các thẻ (Mục 11)
    assert 'id="theme-design-note"' not in content, "Ghi chú 60/30/10 phải bị loại bỏ"


@pytest.mark.asyncio
async def test_t41_slice3_api_settings_endpoint(tmp_path):
    """Kiểm tra API POST /api/model hỗ trợ tier='all' gộp cập nhật Model + Proxy + API Key (Mục 20)."""
    from dataclasses import replace
    from unittest.mock import AsyncMock
    from aiohttp.test_utils import make_mocked_request
    from mulon.config import Config
    from mulon.vault import VaultStore
    from mulon.context import Dossier
    from mulon.policy import PolicyEngine
    from mulon.tools import build_default_registry
    from mulon.connectors import build_default_connectors
    from tests.test_v12_webapp_auth import OWNER, TOKEN, make_init_data
    from tests.conftest import open_memory

    cfg = Config.load()
    vault_file = tmp_path / "test_vault.json"
    cfg = replace(
        cfg,
        telegram_bot_token=TOKEN,
        allowed_user_id=OWNER,
        webapp_port=0,
        vault_path=vault_file,
    )
    memory = await open_memory(cfg)
    vault_store = VaultStore(cfg.vault_path)
    policy = PolicyEngine(cfg.policy_path, memory=memory)
    dossier = Dossier.load(cfg.dossier_dir)
    registry = build_default_registry(cfg, memory, dossier=dossier)
    connectors = build_default_connectors(cfg)

    server = WebAppServer(
        cfg,
        memory=memory,
        policy=policy,
        broker=None,
        connectors=connectors,
        mcp_manager=None,
        vault_store=vault_store,
        registry=registry,
        dossier=dossier,
    )

    # Gửi request POST /api/model với tier="all"
    payload = {
        "tier": "all",
        "brain": "claude-3-7-sonnet",
        "cheap": "gemini-2.0-flash",
        "escalated": "o3-mini",
        "proxy_base_url": "http://127.0.0.1:8317/v1",
        "api_key": "sk-secret-new-token",
    }
    req = make_mocked_request(
        "POST",
        "/api/model",
        headers={"X-Telegram-Init-Data": make_init_data()},
    )
    req.json = AsyncMock(return_value=payload)

    resp = await server._handle_model_post(req)
    assert resp.status == 200
    res_data = json.loads(resp.text)
    assert res_data.get("ok") is True
    assert res_data.get("brain") == "claude-3-7-sonnet"
    assert res_data.get("cheap") == "gemini-2.0-flash"
    assert res_data.get("escalated") == "o3-mini"
    assert res_data.get("proxy_base_url") == "http://127.0.0.1:8317/v1"

    # Kiểm tra secret đã được lưu vào Vault an toàn
    assert vault_store.resolve("llm:api_key") == "sk-secret-new-token"
    await memory.close()


def test_t41_slice3_renders_verification():
    """Kiểm chứng 3 file render thật của Muse với đo đạc mean RGB và SHA256 (Mục Chưa đạt 3)."""
    import hashlib
    from PIL import Image
    import numpy as np

    renders_dir = Path(__file__).resolve().parent.parent / "docs" / "audits" / "renders"
    p_light = renders_dir / "01_dashboard_light.png"
    p_dark = renders_dir / "02_dashboard_dark.png"
    p_tasks = renders_dir / "04_tasks_dark.png"

    assert p_light.is_file(), f"{p_light} phải tồn tại"
    assert p_dark.is_file(), f"{p_dark} phải tồn tại"
    assert p_tasks.is_file(), f"{p_tasks} phải tồn tại"

    hashes = {}
    means = {}
    for p in (p_light, p_dark, p_tasks):
        data = p.read_bytes()
        hashes[p.name] = hashlib.sha256(data).hexdigest()
        im = Image.open(p).convert("RGB")
        arr = np.array(im)
        means[p.name] = float(np.mean(arr))

    # SHA256 khác nhau đôi một
    assert len(set(hashes.values())) == 3, "3 ảnh chụp render phải có SHA256 phân biệt rõ ràng"

    # Mean RGB Light phải sáng (> 200)
    assert means["01_dashboard_light.png"] > 200.0, f"Light theme phải có mean RGB sáng (> 200), thực tế là {means['01_dashboard_light.png']}"

    # Mean RGB Dark phải tối (< 80)
    assert means["02_dashboard_dark.png"] < 80.0, f"Dark theme phải có mean RGB tối (< 80), thực tế là {means['02_dashboard_dark.png']}"
    assert means["04_tasks_dark.png"] < 80.0, f"Dark tasks phải có mean RGB tối (< 80), thực tế là {means['04_tasks_dark.png']}"


def test_t41_slice3_narrow_fixes_verification():
    """Kiểm tra 4 điểm sửa hẹp Lát cắt 3 theo verdict của Muse: backrow, brand section, tab Lịch, policy guard."""
    content = WEBAPP_INDEX.read_text(encoding="utf-8")

    # 1. Bỏ toàn bộ .backrow ở mọi màn con (Mục 15)
    import re
    backrows = re.findall(r'class="backrow"', content)
    assert len(backrows) == 0, f"Phải xoá sạch mọi .backrow trong DOM (còn {len(backrows)})"

    # 2. Section #screen-brand chết phải được xoá sạch (Mục 11)
    assert '<section id="screen-brand"' not in content, "Section #screen-brand chết phải được dọn khỏi DOM"

    # 3. Tab Lịch chỉ còn 1 danh sách Lịch trình duy nhất (Mục 7)
    assert 'id="upcoming-list"' not in content, "Tab Lịch không còn danh sách #upcoming-list riêng biệt"
    assert 'id="schedule-list"' in content, "Tab Lịch phải có danh sách hợp nhất #schedule-list"

    # 4. Guard an toàn cho policy-tools-sub
    assert '$("policy-tools-sub")' in content
    assert 'if (pts)' in content or 'if ($("policy-tools-sub"))' in content, "Phải có null-check an toàn cho policy-tools-sub"



