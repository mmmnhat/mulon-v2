"""Kiểm thử tính năng Thương hiệu, Mascot và Đổi tên hiển thị (T-13).

1. Cấu hình & Dữ liệu:
   - Config.bot_display_name (mặc định 'Mulon', đọc từ BOT_DISPLAY_NAME)
   - Config.bot_mascot (mặc định 'mulon_v0', đọc từ BOT_MASCOT)
   - config/mascots.json chứa bộ sưu tập linh vật trong vũ trụ Mulon (mulon_v0, mulon_spark, mulon_cosmo, mulon_zen)
2. API Backend (/api/brand):
   - GET /api/brand trả về bot_name, bot_username, mascot_id, mascots
   - POST /api/brand cho phép đổi tên hiển thị và chọn mascot, lưu bền vững vào KV
   - Xác thực hợp lệ: từ chối mascot lạ, từ chối tên quá 50 ký tự
3. Telegram Bot Helper:
   - get_bot_display_name đọc đúng tên từ KV hoặc fallback
4. Giao diện Mini App & Render thật Playwright Chromium 390×844:
   - Hàng điều hướng trong Cài đặt mở màn #screen-brand
   - Hiển thị đầy đủ lưu ý giới hạn Telegram (BotFather: /setusername, /setname, /setuserpic)
   - Tương tác đổi tên và chọn mascot thật trên browser
   - Chụp ảnh màn hình lưu tại data/artifacts/t13_*.png
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
import hashlib
import hmac
import json
import os
from pathlib import Path
import threading
import time
from urllib.parse import urlencode

import pytest
from aiohttp import web

from mulon.approvals import ApprovalBroker
from mulon.config import Config
from mulon.connectors import build_default_connectors
from mulon.context import Dossier
from mulon.datafiles import load_json_data
from mulon.memory import Memory
from mulon.policy import PolicyEngine
from mulon.telegram_bot import get_bot_display_name
from mulon.tools import build_default_registry
from mulon.vault import VaultStore
from mulon.webapp_server import WebAppServer


REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML_PATH = REPO_ROOT / "mulon" / "webapp" / "index.html"
MASCOTS_JSON_PATH = REPO_ROOT / "config" / "mascots.json"
ARTIFACT_DIR = Path(os.environ.get("ARTIFACT_DIR", REPO_ROOT / "data" / "artifacts"))
BOT_TOKEN = "123456:ABCDEF_test_token_for_t13"
OWNER_ID = 888999


def test_t13_config_and_mascots_data():
    """Kiểm tra cấu hình mặc định và file dữ liệu mascots.json."""
    cfg = Config.load()
    assert hasattr(cfg, "bot_display_name")
    assert cfg.bot_display_name == "Mulon"
    assert hasattr(cfg, "bot_mascot")
    assert cfg.bot_mascot == "mulon_v0"

    assert MASCOTS_JSON_PATH.exists()
    mascots = load_json_data("mascots.json", [])
    assert len(mascots) >= 4
    ids = [m["id"] for m in mascots]
    assert "mulon_v0" in ids
    assert "mulon_spark" in ids
    assert "mulon_cosmo" in ids
    assert "mulon_zen" in ids

    # Bản chính thức phải là mulon_v0
    v0 = next(m for m in mascots if m["id"] == "mulon_v0")
    assert v0["is_default"] is True
    assert "Sprite v0" in v0["tagline"]


@pytest.mark.asyncio
async def test_t13_brand_api_and_kv_persistence(tmp_path: Path):
    """Kiểm tra API /api/brand (GET & POST) và lưu trữ bền vững trong Memory KV."""
    db_file = tmp_path / "test_brand.db"
    mem = await Memory.open(db_file)
    cfg = Config(
        db_path=db_file,
        telegram_bot_token=BOT_TOKEN,
        allowed_user_id=OWNER_ID,
        bot_display_name="Mulon",
        bot_mascot="mulon_v0",
        bot_username="Mulon_bot",
    )

    policy = PolicyEngine(cfg.policy_path, memory=mem)
    server = WebAppServer(
        cfg,
        memory=mem,
        policy=policy,
        broker=ApprovalBroker(policy=policy, timeout_s=30),
        connectors=build_default_connectors(cfg),
        mcp_manager=None,
        vault_store=VaultStore(cfg.vault_path),
        registry=build_default_registry(cfg, mem),
        dossier=Dossier.load(cfg.dossier_dir),
    )

    # 1. Trạng thái ban đầu
    brand = await server._brand_state()
    assert brand["bot_name"] == "Mulon"
    assert brand["bot_username"] == "Mulon_bot"
    assert brand["mascot_id"] == "mulon_v0"
    assert len(brand["mascots"]) >= 4

    # 2. Telegram helper fallback
    tg_name = await get_bot_display_name(mem, cfg)
    assert tg_name == "Mulon"

    class _MockReq:
        def __init__(self, payload: dict):
            self._payload = payload
        async def json(self):
            return self._payload

    # 3. Đổi tên hiển thị bot
    resp = await server._handle_brand_post(_MockReq({"bot_name": "Miu Con"}))
    data = json.loads(resp.text)
    assert data["ok"] is True
    assert data["bot_name"] == "Miu Con"

    # Kiểm tra đã lưu vào KV
    assert await mem.kv_get("brand_bot_name") == "Miu Con"
    assert await get_bot_display_name(mem, cfg) == "Miu Con"

    # 4. Đổi mascot sang mulon_spark
    resp2 = await server._handle_brand_post(_MockReq({"mascot_id": "mulon_spark"}))
    data2 = json.loads(resp2.text)
    assert data2["ok"] is True
    assert data2["mascot_id"] == "mulon_spark"
    assert await mem.kv_get("brand_mascot_id") == "mulon_spark"

    # 5. Từ chối mascot không hợp lệ
    resp_inv = await server._handle_brand_post(_MockReq({"mascot_id": "mascot_alien_999"}))
    assert resp_inv.status == 400
    assert "không hợp lệ" in json.loads(resp_inv.text)["error"]

    # 6. Từ chối tên quá dài
    resp_long = await server._handle_brand_post(_MockReq({"bot_name": "A" * 60}))
    assert resp_long.status == 400
    assert "50 ký tự" in json.loads(resp_long.text)["error"]

    await mem.close()


def test_t13_static_html_elements():
    """Kiểm tra tĩnh cấu trúc HTML và thông tin BotFather trong index.html."""
    assert INDEX_HTML_PATH.exists()
    html = INDEX_HTML_PATH.read_text(encoding="utf-8")

    # 1. Hàng điều hướng và màn hình
    assert 'data-open="screen-brand"' in html
    assert 'id="screen-brand"' in html
    assert 'id="brand-summary-sub"' in html
    assert 'id="app-brand-name"' in html

    # 2. Các phần tử tương tác
    assert 'id="input-bot-name"' in html
    assert 'id="btn-save-bot-name"' in html
    assert 'id="mascot-grid"' in html

    # 3. Thông tin giới hạn Telegram qua BotFather (theo đúng spec T-13)
    assert "/setusername" in html
    assert "/setname" in html
    assert "/setuserpic" in html
    assert "BotFather" in html


def _launch_chromium(p):
    last_err = None
    for channel in (None, "msedge", "chrome"):
        try:
            kwargs = {"headless": True}
            if channel:
                kwargs["channel"] = channel
            return p.chromium.launch(**kwargs)
        except Exception as e:
            last_err = e
    pytest.skip(f"Chromium/Edge not available for Playwright: {last_err}")


def make_init_data(bot_token: str = BOT_TOKEN, user_id: int = OWNER_ID) -> str:
    user_json = json.dumps({"id": user_id, "first_name": "Nhat"}, separators=(",", ":"))
    pairs = {
        "auth_date": str(int(time.time())),
        "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
        "user": user_json,
    }
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    sig = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    pairs["hash"] = sig
    return urlencode(pairs)


def test_playwright_t13_brand_and_mascot(cfg: Config):
    """Kiểm thử render thật và tương tác đổi tên, chọn mascot bằng Chromium viewport 390x844."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("Playwright not installed")

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    port_holder = {}
    stop_ev = threading.Event()

    def run_server():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def _serve():
            mem = await Memory.open(cfg.db_path)
            policy = PolicyEngine(cfg.policy_path, memory=mem)
            registry = build_default_registry(cfg, mem)
            srv = WebAppServer(
                replace(cfg, telegram_bot_token=BOT_TOKEN, allowed_user_id=OWNER_ID, webapp_port=0),
                memory=mem,
                policy=policy,
                broker=ApprovalBroker(policy=policy, timeout_s=30),
                connectors=build_default_connectors(cfg),
                mcp_manager=None,
                vault_store=VaultStore(cfg.vault_path),
                registry=registry,
                dossier=Dossier.load(cfg.dossier_dir),
            )

            runner = web.AppRunner(srv.build_app())
            await runner.setup()
            site = web.TCPSite(runner, "127.0.0.1", 0)
            await site.start()
            port_holder["port"] = site._server.sockets[0].getsockname()[1]
            while not stop_ev.is_set():
                await asyncio.sleep(0.05)
            await runner.cleanup()
            await mem.close()

        loop.run_until_complete(_serve())

    th = threading.Thread(target=run_server, daemon=True)
    th.start()
    for _ in range(100):
        if "port" in port_holder:
            break
        time.sleep(0.05)
    assert "port" in port_holder
    base_url = f"http://127.0.0.1:{port_holder['port']}"

    try:
        with sync_playwright() as p:
            browser = _launch_chromium(p)
            context = browser.new_context(
                viewport={"width": 390, "height": 844},
                user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 16_0 like Mac OS X) AppleWebKit/605.1.15",
            )
            page = context.new_page()
            page.route(
                "**/telegram-web-app.js*",
                lambda route: route.fulfill(status=200, content_type="application/javascript", body=""),
            )

            init_data = make_init_data()
            page.add_init_script(
                f"""
                window.Telegram = {{
                    WebApp: {{
                        initData: {json.dumps(init_data)},
                        initDataUnsafe: {{ user: {{ id: {OWNER_ID} }} }},
                        colorScheme: "dark",
                        ready: function() {{}},
                        expand: function() {{}},
                        disableVerticalSwipes: function() {{}},
                        isVersionAtLeast: function(v) {{ return true; }},
                        requestFullscreen: function() {{}},
                        HapticFeedback: {{
                            impactOccurred: function(k) {{}},
                            selectionChanged: function() {{}},
                            notificationOccurred: function(k) {{}}
                        }},
                        BackButton: {{
                            isVisible: false,
                            show: function() {{ this.isVisible = true; }},
                            hide: function() {{ this.isVisible = false; }},
                            onClick: function(fn) {{ this._cb = fn; }}
                        }},
                        addToHomeScreen: function() {{ window._homeScreenRequested = true; }}
                    }}
                }};
                """
            )
            page.goto(f"{base_url}/app", wait_until="networkidle")

            # ---------------- 1. MỞ MÀN THƯƠNG HIỆU & MASCOT ----------------
            page.locator('button[data-tab="caidat"]').click()
            page.wait_for_selector("#tab-caidat:not(.hidden)")

            # Kiểm tra hàng điều hướng
            assert "Thương hiệu & Mascot" in page.locator('[data-open="screen-brand"]').inner_text()
            page.locator('[data-open="screen-brand"]').click()
            page.wait_for_selector("#screen-brand:not(.hidden)")

            # Kiểm tra lưu ý BotFather hiển thị đầy đủ
            brand_screen_text = page.locator("#screen-brand").inner_text()
            assert "BotFather" in brand_screen_text
            assert "/setusername" in brand_screen_text
            assert "/setname" in brand_screen_text
            assert "/setuserpic" in brand_screen_text

            # Kiểm tra bộ sưu tập Mascot có ít nhất 4 lựa chọn
            mascot_cards = page.locator("#mascot-grid .card")
            assert mascot_cards.count() >= 4
            assert "Mulon Cổ Điển" in brand_screen_text
            assert "Mulon Spark" in brand_screen_text
            assert "Đang đại diện" in brand_screen_text

            if ARTIFACT_DIR.exists():
                page.screenshot(path=str(ARTIFACT_DIR / "t13_screen_brand.png"), full_page=True)

            # ---------------- 2. ĐỔI TÊN BOT VÀ CHỌN MASCOT MỚI ----------------
            # Nhập tên bot mới
            page.locator("#input-bot-name").fill("Mulon AI")
            page.locator("#btn-save-bot-name").click()
            page.wait_for_timeout(300)

            # Kiểm tra Header app đã cập nhật tên mới
            assert page.locator("#app-brand-name").inner_text() == "Mulon AI"

            # Chọn mascot Mulon Spark
            spark_btn = page.locator('button[data-select-mascot="mulon_spark"]')
            spark_btn.click()
            page.wait_for_timeout(300)

            # Kiểm tra Mulon Spark trở thành mascot đang đại diện
            new_screen_text = page.locator("#screen-brand").inner_text()
            assert "Mulon Spark" in new_screen_text

            if ARTIFACT_DIR.exists():
                page.screenshot(path=str(ARTIFACT_DIR / "t13_brand_updated.png"), full_page=True)

            # ---------------- 3. QUAY LẠI CÀI ĐẶT ----------------
            page.locator("#screen-brand .backrow").click()
            page.wait_for_selector("#tab-caidat:not(.hidden)")
            assert "Mulon AI · Mulon Spark" in page.locator("#brand-summary-sub").inner_text()

            browser.close()
    finally:
        stop_ev.set()
        th.join(timeout=3)
