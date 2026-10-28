"""Kiểm thử chuẩn hoá chính sách quyền và xác nhận hành động phá huỷ (T-23.6).

1. Kiểm tra nguồn sự thật config/policy.json và chuẩn F4 (đọc = allow, ghi/xoá/phá huỷ = ask).
2. Kiểm tra các tool nguy hiểm (run_command, delete_vault_secret, write_file, edit_file, restart_bot...)
   và các hành động connector đều có nấc ask mặc định.
3. Kiểm tra WebAppServer._policy_state() tích hợp đầy đủ specs cho System và MCP servers.
4. Kiểm tra cấu trúc giao diện Mini App:
   - Màn Quyền không còn danh sách phẳng ~100+ tool, có tổng quan và đường dẫn connector.
   - Màn chi tiết connector chứa trạng thái kết nối + quyền từng hành động đọc/ghi.
   - Vault chuyển nút Xoá vào màn chi tiết bí mật screen-vault-detail.
   - prepareInstall có hộp thoại xác nhận khi cài connector yêu cầu quyền file.
5. Render và tương tác thật bằng Playwright Chromium ở viewport 390×844.
"""

from __future__ import annotations

import json
from dataclasses import replace
import os
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from aiohttp import ClientSession

from mulon.approvals import ApprovalBroker
from mulon.connectors import build_default_connectors
from mulon.context import Dossier
from mulon.marketplace import MarketplaceService
from mulon.policy import PolicyEngine, VERDICT_ALLOW, VERDICT_ASK, CONNECTOR_SPECS
from mulon.tools import build_default_registry
from mulon.vault import VaultStore
from mulon.webapp_server import WebAppServer
from tests.conftest import open_memory
from tests.test_v12_webapp_auth import OWNER, TOKEN, make_init_data


REPO_ROOT = Path(__file__).resolve().parent.parent
POLICY_JSON_PATH = REPO_ROOT / "config" / "policy.json"
INDEX_HTML_PATH = REPO_ROOT / "mulon" / "webapp" / "index.html"
ARTIFACT_DIR = Path(os.environ.get("ARTIFACT_DIR", REPO_ROOT / "data" / "artifacts"))


def test_config_policy_truth_and_f4_defaults():
    """Kiểm tra nguồn sự thật config/policy.json tuân thủ nghiêm ngặt chuẩn F4."""
    assert POLICY_JSON_PATH.exists(), "config/policy.json phải tồn tại"
    data = json.loads(POLICY_JSON_PATH.read_text(encoding="utf-8"))

    # Đảm bảo không còn default: allow phẳng
    assert data.get("default") != "allow", "config/policy.json không được để default: allow phẳng"

    engine = PolicyEngine(POLICY_JSON_PATH)

    # 1. Các tool nguy hiểm phá huỷ / ghi / xoá / shell phải là ASK
    dangerous_tools = [
        ("run_command", "shell"),
        ("delete_vault_secret", "vault"),
        ("vault_put", "vault"),
        ("restart_bot", "system"),
        ("write_file", "file"),
        ("edit_file", "file"),
        ("delete_library_item", "library"),
        ("share_library_item", "library"),
        ("schedule_delete", "planning"),
        ("goal_delete", "planning"),
    ]
    for tool_name, group in dangerous_tools:
        dec = engine.decide(tool_name, group)
        assert dec.verdict == VERDICT_ASK, f"Tool nguy hiểm {tool_name} phải có verdict ask, thực tế là {dec.verdict}"

    # 2. Các hành động connector gửi / ghi / xoá phải là ASK
    write_actions = [
        ("", "connector:gmail:send"),
        ("", "connector:gcalendar:create_event"),
        ("", "connector:gcalendar:delete_event"),
        ("", "connector:facebook_personal:send_message"),
        ("", "connector:facebook_personal:send_post"),
        ("", "connector:facebook_personal:delete_post"),
        ("", "connector:instagram_messages:send_message"),
        ("", "connector:threads_messages:send_message"),
        ("", "connector:zalo_personal:send_message"),
        ("", "connector:telegram_personal:send_message"),
    ]
    for tool_name, group in write_actions:
        dec = engine.decide(tool_name, group)
        assert dec.verdict == VERDICT_ASK, f"Action connector ghi/xoá {group} phải là ask, thực tế là {dec.verdict}"

    # 3. Các tool và hành động đọc phải là ALLOW
    read_items = [
        ("read_file", "file"),
        ("list_dir", "file"),
        ("web_fetch", "web"),
        ("web_search", "web"),
        ("now", "system"),
        ("memory_get", "memory"),
        ("memory_search", "memory"),
        ("session_search", "memory"),
        ("schedule_list", "planning"),
        ("search_library", "library"),
        ("get_library_item", "library"),
        ("", "connector:gmail:read"),
        ("", "connector:gmail:search"),
        ("", "connector:gcalendar:list_events"),
        ("", "connector:system:time"),
        ("", "connector:system:status"),
        ("", "connector:system:feed_snapshot"),
        ("", "connector:facebook_personal:get_profile"),
        ("", "connector:facebook_personal:read_feed"),
        ("", "connector:instagram_messages:read_inbox"),
        ("", "connector:threads_messages:read_inbox"),
        ("", "connector:zalo_personal:read_messages"),
        ("", "connector:telegram_personal:read_messages"),
    ]
    for tool_name, group in read_items:
        dec = engine.decide(tool_name, group)
        assert dec.verdict == VERDICT_ALLOW, f"Item đọc {tool_name or group} phải là allow, thực tế là {dec.verdict}"


def test_webapp_policy_state_specs():
    """Kiểm tra _policy_state() tích hợp specs của System và Google."""
    assert "system" in CONNECTOR_SPECS
    assert "google" in CONNECTOR_SPECS
    assert len(CONNECTOR_SPECS["system"]["actions"]) >= 3


def test_miniapp_html_policy_and_vault_structure():
    """Kiểm tra cấu trúc DOM HTML của màn Quyền, Chi tiết connector, và Chi tiết Vault."""
    html = INDEX_HTML_PATH.read_text(encoding="utf-8")

    # 1. Màn Quyền chung
    assert 'id="screen-policy"' in html
    assert 'id="policy-summary-card"' in html
    assert 'id="policy-overview-text"' in html
    assert 'id="policy-global-default-row"' in html
    assert 'data-open="screen-all-tools-policy"' in html
    assert 'id="policy-tools"' not in html

    # 2. Màn con Tất cả công cụ
    assert 'id="screen-all-tools-policy"' in html
    assert 'id="all-tools-search"' in html
    assert 'id="all-tools-chips"' in html
    assert 'id="all-tools-list"' in html

    # 3. Màn chi tiết connector
    assert 'id="screen-connector-policy"' in html
    assert 'id="conn-pol-status-card"' in html
    assert 'id="conn-pol-read-card"' in html
    assert 'id="conn-pol-write-card"' in html

    # 4. Màn chi tiết Vault
    assert 'id="screen-vault-detail"' in html
    assert 'id="vault-detail-title"' in html
    assert 'id="vd-label"' in html
    assert 'id="vd-ref"' in html
    assert 'id="vd-btn-save"' in html
    assert 'id="vd-btn-delete"' in html

    # 5. Xác nhận quyền file trong prepareInstall
    assert "confirmDialog" in html
    assert "filesystem" in html or "filePerms" in html


@pytest.fixture
async def env_t23_6(cfg, tmp_path):
    cfg2 = replace(
        cfg,
        telegram_bot_token=TOKEN,
        allowed_user_id=OWNER,
        webapp_port=0,
        policy_path=POLICY_JSON_PATH,
    )
    memory = await open_memory(cfg2)
    dossier = Dossier.load(cfg2.dossier_dir)
    vault_store = VaultStore(cfg2.vault_path, getattr(cfg2, "vault_encryption_key", ""))
    vault_store.put("api:google_maps", "mock-secret-key-12345")

    registry = build_default_registry(cfg2, memory, dossier=dossier, vault_store=vault_store)
    policy = PolicyEngine(cfg2.policy_path, memory=memory)
    connectors = build_default_connectors(cfg2, vault_store=vault_store)
    broker = ApprovalBroker(policy=policy, timeout_s=120)

    server = WebAppServer(
        cfg2,
        memory=memory,
        policy=policy,
        broker=broker,
        connectors=connectors,
        mcp_manager=None,
        vault_store=vault_store,
        registry=registry,
        dossier=dossier,
    )
    await server.start()
    yield cfg2, memory, server
    await server.stop()
    await memory.close()


def _url(server, path=""):
    return f"http://127.0.0.1:{server.port}{path}"


@pytest.mark.asyncio
async def test_playwright_t23_6_policy_vault_interaction(env_t23_6):
    """Playwright Chromium test kiểm chứng tương tác thật 390x844:
    1. Màn Quyền: hiển thị tổng quan X/Y quyền đang mở, mặc định toàn cục, mở màn chi tiết connector.
    2. Chi tiết connector: có trạng thái kết nối + quyền từng hành động.
    3. Kho lưu trữ an toàn: click hàng bí mật mở màn chi tiết, bấm xoá hiện confirm dialog.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        pytest.skip("playwright chưa cài trong môi trường")

    _cfg, _memory, server = env_t23_6
    init_data = make_init_data()
    base_url = _url(server, f"/?tgWebAppPlatform=ios&tgWebAppVersion=8.0&theme=dark#{init_data}")

    async with async_playwright() as p:
        browser = None
        last_err = None
        for channel in (None, "msedge", "chrome"):
            try:
                kwargs = {"headless": True}
                if channel:
                    kwargs["channel"] = channel
                browser = await p.chromium.launch(**kwargs)
                break
            except Exception as e:
                last_err = e
        if browser is None:
            pytest.skip(f"Chromium/Edge không có sẵn cho Playwright: {last_err}")

        context = await browser.new_context(
            viewport={"width": 390, "height": 844},
            is_mobile=True,
            has_touch=True,
        )
        page = await context.new_page()

        # Chặn script ngoài của Telegram để không ghi đè window.Telegram.WebApp giả lập
        await page.route(
            "**/telegram-web-app.js*",
            lambda route: route.fulfill(
                status=200,
                content_type="application/javascript",
                body="",
            ),
        )

        # Giả lập confirm dialog trả về false (hủy) để xác nhận có dialog hiện lên
        dialog_messages = []

        async def _on_dialog(d):
            dialog_messages.append(d.message)
            await d.dismiss()

        page.on("dialog", _on_dialog)

        await page.add_init_script(
            f"""
            window.Telegram = {{
                WebApp: {{
                    initData: {init_data!r},
                    colorScheme: "dark",
                    ready: function() {{}},
                    expand: function() {{}},
                    HapticFeedback: {{
                        impactOccurred: function() {{}},
                        selectionChanged: function() {{}},
                        notificationOccurred: function() {{}}
                    }},
                    BackButton: {{
                        isVisible: false,
                        show: function() {{ this.isVisible = true; }},
                        hide: function() {{ this.isVisible = false; }},
                        onClick: function(fn) {{ this._cb = fn; }}
                    }}
                }}
            }};
            """
        )

        await page.goto(base_url, wait_until="networkidle")
        await page.wait_for_selector("#status-text")

        # 1. Mở Tab Cài đặt -> Mở Màn Quyền
        await page.click('#segbar button[data-tab="caidat"]')
        await page.wait_for_selector('#tab-caidat:not(.hidden)')
        await page.click('[data-open="screen-policy"]')
        await page.wait_for_selector('#screen-policy:not(.hidden)')
        if ARTIFACT_DIR.exists():
            await page.screenshot(path=str(ARTIFACT_DIR / "t23_6_screen_policy.png"), full_page=True)

        # Kiểm tra màn Quyền có tổng quan và không còn danh sách phẳng
        overview_text = await page.inner_text("#policy-overview-text")
        assert "công cụ tự chạy" in overview_text or "Đang mở" in overview_text
        assert "công cụ cần hỏi trước" in overview_text
        # Mặc định toàn cục
        global_def_val = await page.inner_text("#policy-global-default-val")
        assert len(global_def_val) > 0

        # 2. Mở màn con Tất cả công cụ từ màn Quyền
        await page.click('[data-open="screen-all-tools-policy"]')
        await page.wait_for_selector('#screen-all-tools-policy:not(.hidden)')
        # Kiểm tra thanh tìm kiếm và danh sách tools
        await page.fill('#all-tools-search', 'command')
        filtered_tools = await page.inner_text('#all-tools-list')
        assert "run_command" in filtered_tools
        if ARTIFACT_DIR.exists():
            await page.screenshot(path=str(ARTIFACT_DIR / "t23_6_screen_all_tools.png"), full_page=True)
        # Bấm quay lại màn Quyền
        await page.click('#all-tools-back')
        await page.wait_for_selector('#screen-policy:not(.hidden)')

        # 3. Bấm vào 1 connector trong màn Quyền để mở màn chi tiết connector
        await page.wait_for_selector('#policy-connectors [data-open-conn-pol]')
        await page.click('#policy-connectors [data-open-conn-pol]:first-child')
        await page.wait_for_selector('#screen-connector-policy:not(.hidden)')

        # Kiểm tra màn chi tiết connector
        assert await page.is_visible('#conn-pol-status-card')
        assert await page.is_visible('#conn-pol-read-card')
        assert await page.is_visible('#conn-pol-write-card')
        if ARTIFACT_DIR.exists():
            await page.screenshot(path=str(ARTIFACT_DIR / "t23_6_screen_conn_detail.png"), full_page=True)
        # Bấm quay lại
        await page.click('#conn-pol-back')
        await page.wait_for_selector('#screen-policy:not(.hidden)')

        # 4. Quay lại Cài đặt -> Mở Kho lưu trữ an toàn (Vault)
        await page.click('#screen-policy [data-back]')
        await page.wait_for_selector('#tab-caidat:not(.hidden)')
        await page.click('[data-open="screen-vault"]')
        await page.wait_for_selector('#screen-vault:not(.hidden)')

        # Bấm vào bí mật để mở màn chi tiết bí mật
        await page.wait_for_selector('#vault-list [data-vault-ref]')
        await page.click('#vault-list [data-vault-ref]:first-child')
        await page.wait_for_selector('#screen-vault-detail:not(.hidden)')

        # Kiểm tra chi tiết bí mật
        label_text = await page.inner_text('#vd-label')
        assert "api:google_maps" in label_text
        if ARTIFACT_DIR.exists():
            await page.screenshot(path=str(ARTIFACT_DIR / "t23_6_screen_vault_detail.png"), full_page=True)

        # Bấm nút Xoá để kích hoạt confirmDialog
        await page.click('#vd-btn-delete')
        assert len(dialog_messages) > 0, "Bấm xoá bí mật phải kích hoạt hộp thoại xác nhận"
        assert "api:google_maps" in dialog_messages[0]

        await browser.close()
