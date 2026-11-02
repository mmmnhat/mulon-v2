"""Test hồi quy toàn diện cho [T-42] Phần quyền Telegram Business trong Mini App.

Kiểm tra:
1. Backend trích xuất trọn vẹn 12 quyền BusinessBotRights (extract_business_rights).
2. Lưu đầy đủ object rights vào connection record và SQLite KV Memory.
3. API GET /api/business/status phơi bày rights, rights_groups, reply_mode.
4. API POST /api/business/config cập nhật cấu hình enabled và reply_mode ("auto" | "draft").
5. Cơ chế reply_mode == "draft" chuyển auto-reply thành draft_approval an toàn.
6. Frontend index.html có điểm vào Telegram Business trong màn Quyền và màn con #screen-business.
7. Test Playwright Chromium 390x844: render 3 nhóm quyền, điều khiển bot, 0 pageerror (Light & Dark).
"""

from pathlib import Path
import json
import pytest
from unittest.mock import AsyncMock, MagicMock
from aiohttp.test_utils import make_mocked_request

from mulon.business import (
    TelegramBusinessService,
    extract_business_rights,
    ALL_BUSINESS_RIGHTS_KEYS,
    BUSINESS_RIGHTS_GROUPS,
    BusinessActionKind,
)
from mulon.webapp_server import WebAppServer

WEBAPP_INDEX = Path(__file__).resolve().parent.parent / "mulon" / "webapp" / "index.html"


class MockRightsPydantic:
    """Mock đối tượng pydantic BusinessBotRights (aiogram 3.x)."""
    def __init__(self, data: dict):
        self._data = data

    def model_dump(self):
        return dict(self._data)


class MockConnection:
    """Mock đối tượng BusinessConnection của Telegram."""
    def __init__(self, conn_id: str, rights_data: dict, can_reply: bool = True, is_enabled: bool = True):
        self.id = conn_id
        self.user_chat_id = 123456789
        self.can_reply = can_reply
        self.is_enabled = is_enabled
        self.rights = MockRightsPydantic(rights_data)
        user_mock = MagicMock()
        user_mock.id = 987654321
        self.user = user_mock


class SimpleFallbackConn:
    """Đối tượng connection đơn giản không có rights object để test fallback."""
    def __init__(self, can_reply: bool = True):
        self.can_reply = can_reply
        self.rights = None


class MockMemory:
    """Mock in-memory KV store cho TelegramBusinessService."""
    def __init__(self):
        self.store: dict[str, str] = {}

    async def kv_get(self, key: str):
        return self.store.get(key)

    async def kv_set(self, key: str, val: str):
        self.store[key] = str(val)

    async def kv_del(self, key: str):
        self.store.pop(key, None)


def test_t42_extract_business_rights():
    """Kiểm tra hàm extract_business_rights trích xuất chính xác 12 quyền Telegram."""
    # 1. Pydantic model dump
    sample_data = {
        "can_reply": True,
        "can_read_messages": True,
        "can_delete_sent_messages": True,
        "can_delete_all_messages": False,
        "can_edit_name": False,
        "can_edit_username": False,
        "can_change_gift_settings": False,
        "can_view_gifts_and_stars": False,
        "can_convert_gifts_to_stars": False,
        "can_transfer_and_upgrade_gifts": False,
        "can_transfer_stars": False,
        "can_manage_stories": False,
    }
    pydantic_obj = MockRightsPydantic(sample_data)
    mock_conn = MagicMock()
    mock_conn.rights = pydantic_obj
    rights = extract_business_rights(mock_conn)

    assert len(rights) == 12, "Phải trích xuất đầy đủ 12 quyền BusinessBotRights"
    for k in ALL_BUSINESS_RIGHTS_KEYS:
        assert k in rights, f"Quyền {k} phải có trong kết quả"
        assert isinstance(rights[k], bool)

    assert rights["can_reply"] is True
    assert rights["can_read_messages"] is True
    assert rights["can_delete_sent_messages"] is True
    assert rights["can_delete_all_messages"] is False

    # 2. Dict input trực tiếp
    dict_conn = {"rights": sample_data}
    rights_from_dict = extract_business_rights(dict_conn)
    assert rights_from_dict == sample_data

    # 3. Fallback khi không có rights object nhưng conn có can_reply
    conn_fallback = SimpleFallbackConn(can_reply=True)
    rights_fallback = extract_business_rights(conn_fallback)
    assert rights_fallback["can_reply"] is True
    assert rights_fallback["can_read_messages"] is False


@pytest.mark.asyncio
async def test_t42_handle_business_connection_persists_rights():
    """Kiểm tra handle_business_connection lưu trữ đầy đủ rights vào SQLite KV Memory."""
    memory = MockMemory()

    cfg = MagicMock()
    cfg.allowed_user_id = 987654321
    cfg.telegram_business_enabled = True

    svc = TelegramBusinessService(cfg=cfg, memory=memory)

    sample_rights = {
        "can_reply": True,
        "can_read_messages": True,
        "can_delete_sent_messages": True,
        "can_delete_all_messages": True,
        "can_edit_name": False,
        "can_edit_username": False,
        "can_change_gift_settings": False,
        "can_view_gifts_and_stars": False,
        "can_convert_gifts_to_stars": False,
        "can_transfer_and_upgrade_gifts": False,
        "can_transfer_stars": False,
        "can_manage_stories": False,
    }
    conn = MockConnection("conn_test_01", sample_rights, can_reply=True, is_enabled=True)

    record = await svc.handle_business_connection(conn)

    assert record["connection_id"] == "conn_test_01"
    assert record["can_reply"] is True
    assert "rights" in record
    assert record["rights"]["can_read_messages"] is True
    assert record["rights"]["can_edit_name"] is False

    # Kiểm tra lưu vào Memory
    saved_raw = await memory.kv_get("business:connection:conn_test_01")
    assert saved_raw is not None
    saved_data = json.loads(saved_raw)
    assert saved_data["rights"]["can_read_messages"] is True
    assert saved_data["rights"]["can_reply"] is True

    # Kiểm tra get_status_report
    report = await svc.get_status_report()
    assert report["active_connection_id"] == "conn_test_01"
    assert report["rights"]["can_read_messages"] is True
    assert "messages" in report["rights_groups"]
    assert "profile" in report["rights_groups"]
    assert "gifts_and_stars" in report["rights_groups"]


@pytest.mark.asyncio
async def test_t42_update_config_and_reply_mode():
    """Kiểm tra cấu hình enabled, reply_mode ('auto' / 'draft') và hành vi soạn nháp."""
    memory = MockMemory()

    cfg = MagicMock()
    cfg.telegram_business_enabled = True
    cfg.allowed_user_id = 11111

    svc = TelegramBusinessService(cfg=cfg, memory=memory)

    # Mặc định ban đầu
    assert await svc.is_enabled() is True
    assert await svc.get_reply_mode() == "auto"

    # Cập nhật sang reply_mode = "draft"
    res = await svc.update_config(enabled=True, reply_mode="draft")
    assert res["ok"] is True
    assert res["reply_mode"] == "draft"
    assert await svc.get_reply_mode() == "draft"

    # Giả lập connection đang active
    conn = MockConnection("conn_active", {"can_reply": True}, can_reply=True, is_enabled=True)
    await svc.handle_business_connection(conn)

    # Giả lập tin nhắn chào hỏi vốn dĩ là AUTO_REPLY
    msg = MagicMock()
    msg.business_connection_id = "conn_active"
    msg.text = "Chào shop ơi, shop có ship COD không?"
    from_user = MagicMock()
    from_user.id = 22222
    from_user.first_name = "Khách Test"
    msg.from_user = from_user
    chat = MagicMock()
    chat.id = 33333
    msg.chat = chat

    # Với reply_mode == "draft", tin nhắn phải chuyển thành DRAFT_APPROVAL
    process_res = await svc.process_business_message(msg)
    assert process_res["action"] == BusinessActionKind.DRAFT_APPROVAL, "Khi reply_mode == 'draft', mọi tin auto-reply phải chuyển thành soạn nháp"
    assert "chế độ soạn nháp" in process_res["reason"]

    # Đổi lại sang reply_mode = "auto"
    await svc.update_config(reply_mode="auto")
    assert await svc.get_reply_mode() == "auto"

    # Tắt enabled
    await svc.update_config(enabled=False)
    assert await svc.is_enabled() is False


@pytest.mark.asyncio
async def test_t42_webapp_api_status_and_config():
    """Kiểm tra endpoint API GET /api/business/status và POST /api/business/config."""
    memory = MockMemory()

    cfg = MagicMock()
    cfg.telegram_business_enabled = True
    cfg.allowed_user_id = 12345

    server = WebAppServer(
        cfg=cfg,
        memory=memory,
        policy=MagicMock(),
        broker=MagicMock(),
        connectors=MagicMock(),
        mcp_manager=MagicMock(),
        vault_store=MagicMock(),
        registry=MagicMock(),
    )

    # 1. Test GET /api/business/status
    req_status = make_mocked_request("GET", "/api/business/status")
    resp_status = await server._handle_business_status(req_status)
    assert resp_status.status == 200
    data_status = json.loads(resp_status.text)
    assert data_status["ok"] is True
    biz = data_status["business"]
    assert "rights" in biz
    assert "rights_groups" in biz
    assert "reply_mode" in biz
    assert biz["reply_mode"] == "auto"

    # 2. Test POST /api/business/config hợp lệ
    req_cfg = make_mocked_request("POST", "/api/business/config")
    req_cfg.json = AsyncMock(return_value={"enabled": True, "reply_mode": "draft"})
    resp_cfg = await server._handle_business_config(req_cfg)
    assert resp_cfg.status == 200
    data_cfg = json.loads(resp_cfg.text)
    assert data_cfg["ok"] is True
    assert data_cfg["enabled"] is True
    assert data_cfg["reply_mode"] == "draft"

    # Kiểm tra lại status sau khi cập nhật config
    resp_status2 = await server._handle_business_status(req_status)
    data_status2 = json.loads(resp_status2.text)
    assert data_status2["business"]["reply_mode"] == "draft"

    # 3. Test POST /api/business/config với reply_mode không hợp lệ
    req_bad = make_mocked_request("POST", "/api/business/config")
    req_bad.json = AsyncMock(return_value={"reply_mode": "invalid_mode"})
    resp_bad = await server._handle_business_config(req_bad)
    assert resp_bad.status == 400
    data_bad = json.loads(resp_bad.text)
    assert data_bad["ok"] is False


def test_t42_frontend_markup_and_rules():
    """Kiểm tra frontend index.html tuân thủ Rule §6, 3 nhóm quyền và điểm vào Business."""
    content = WEBAPP_INDEX.read_text(encoding="utf-8")

    # 1. Điểm vào trong màn Quyền
    assert 'data-open="screen-business"' in content, "Màn Quyền phải có hàng điều hướng data-open='screen-business'"
    assert 'id="policy-business-card"' in content, "Phải có card Telegram Business trong màn Quyền"
    assert 'id="policy-biz-status-text"' in content, "Phải có nhãn tóm tắt trạng thái Telegram Business"

    # 2. Màn con #screen-business
    assert '<section id="screen-business"' in content, "Phải có section #screen-business"
    assert 'id="biz-conn-status-badge"' in content, "Phải có badge trạng thái kết nối chữ trung tính"
    assert 'id="biz-enabled-tgl"' in content, "Phải có toggle bật/tắt Telegram Business"
    assert 'id="biz-mode-auto"' in content, "Phải có nút chọn chế độ trả lời Tự động"
    assert 'id="biz-mode-draft"' in content, "Phải có nút chọn chế độ trả lời Soạn nháp"

    # 3. Ba nhóm quyền Telegram
    assert 'id="biz-rights-messages"' in content, "Phải có container Quản lý tin nhắn"
    assert 'id="biz-rights-profile"' in content, "Phải có container Hồ sơ"
    assert 'id="biz-rights-gifts"' in content, "Phải có container Quà & Sao"

    # 4. Thống kê và ghi chú trung thực
    assert 'id="biz-stat-total"' in content, "Phải có thống kê tổng tin nhắn"
    assert 'id="biz-stat-auto"' in content, "Phải có thống kê tin tự động trả lời"
    assert 'id="biz-stat-drafts"' in content, "Phải có thống kê bản nháp"
    assert "Cài đặt Telegram" in content and "Chatbots" in content, "Phải có ghi chú trung thực về quyền Telegram"

    # 5. Tuân thủ Rule §6: không dùng màu xanh lá / đỏ cho trạng thái
    assert 'background: green' not in content and 'color: green' not in content, "Không dùng màu xanh lá cho trạng thái theo luật §6"


def test_t42_playwright_render_business_screen(tmp_path):
    """Playwright Chromium 390x844: Render màn Telegram Business, kiểm tra 3 nhóm quyền, 0 pageerror."""
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 390, "height": 844},
            is_mobile=True,
            has_touch=True,
        )
        page = context.new_page()

        page_errors = []
        page.on("pageerror", lambda err: page_errors.append(str(err)))

        file_url = f"file://{WEBAPP_INDEX.resolve()}"
        page.goto(file_url)
        page.wait_for_timeout(300)

        # 1. Chuyển sang tab Cài đặt
        page.click("button[data-tab='caidat']")
        page.wait_for_timeout(200)

        # 2. Mở màn Quyền
        page.click("div[data-open='screen-policy']")
        page.wait_for_timeout(200)

        # 3. Mở màn Telegram Business
        page.click("div[data-open='screen-business']")
        page.wait_for_timeout(300)

        # Kiểm tra màn Telegram Business đã hiển thị
        biz_sec = page.locator("#screen-business")
        assert biz_sec.is_visible(), "Màn #screen-business phải hiển thị"

        # Đưa mock data vào và gọi renderBusinessStatus
        mock_biz = {
            "config_enabled": True,
            "reply_mode": "auto",
            "connection_info": {
                "connection_id": "conn_real_user_01",
                "user_id": 999999,
                "can_reply": True,
                "is_enabled": True,
            },
            "rights": {
                "can_reply": True,
                "can_read_messages": True,
                "can_delete_sent_messages": True,
                "can_delete_all_messages": False,
                "can_edit_name": False,
                "can_edit_username": False,
                "can_manage_stories": False,
                "can_change_gift_settings": False,
                "can_view_gifts_and_stars": False,
                "can_convert_gifts_to_stars": False,
                "can_transfer_and_upgrade_gifts": False,
                "can_transfer_stars": False,
            },
            "stats": {"auto_replies": 12, "drafts_created": 4},
            "products_count": 5,
            "faq_count": 3,
        }
        page.evaluate("(data) => { window.renderBusinessStatus(data); }", mock_biz)
        page.wait_for_timeout(200)

        # Kiểm tra trạng thái và số lượng quyền
        badge_text = page.locator("#biz-conn-status-badge").inner_text()
        assert "Đang kết nối" in badge_text, "Badge trạng thái phải hiển thị 'Đang kết nối'"

        msg_rows = page.locator("#biz-rights-messages .biz-right-row")
        assert msg_rows.count() == 4, "Nhóm Quản lý tin nhắn phải có đúng 4 quyền"

        prof_rows = page.locator("#biz-rights-profile .biz-right-row")
        assert prof_rows.count() == 3, "Nhóm Hồ sơ phải có đúng 3 quyền"

        gift_rows = page.locator("#biz-rights-gifts .biz-right-row")
        assert gift_rows.count() == 5, "Nhóm Quà & Sao phải có đúng 5 quyền"

        # Kiểm tra touch target các nút điều khiển
        auto_box = page.locator("#biz-mode-auto").bounding_box()
        draft_box = page.locator("#biz-mode-draft").bounding_box()
        assert auto_box["height"] >= 44, f"Nút Tự động phải có touch target >= 44px (đo được {auto_box['height']}px)"
        assert draft_box["height"] >= 44, f"Nút Soạn nháp phải có touch target >= 44px (đo được {draft_box['height']}px)"

        # Chụp ảnh render theme Light
        out_light = Path(__file__).resolve().parent.parent / "docs" / "audits" / "renders" / "05_business_light.png"
        out_light.parent.mkdir(parents=True, exist_ok=True)
        page.screenshot(path=str(out_light))

        # Đổi sang Dark theme và chụp ảnh
        page.evaluate("""() => {
            if (window.Telegram && window.Telegram.WebApp) window.Telegram.WebApp.colorScheme = 'dark';
            document.documentElement.dataset.scheme = 'dark';
            if (typeof syncColorScheme === 'function') syncColorScheme();
        }""")
        page.wait_for_timeout(300)
        out_dark = Path(__file__).resolve().parent.parent / "docs" / "audits" / "renders" / "06_business_dark.png"
        page.screenshot(path=str(out_dark))

        assert len(page_errors) == 0, f"Runtime không được có lỗi pageerror: {page_errors}"

        browser.close()
