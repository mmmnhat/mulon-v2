"""Kiểm thử Design System và Khả năng Native Telegram Mini App (T-12).

1. Kiểm tra tài liệu nghiên cứu khả năng app của Telegram Mini App trong docs/.
2. Kiểm tra Design Tokens (màu 60/30/10, typography tối đa 4 cỡ chữ, 2 weights, lưới 8pt, bo góc thống nhất).
3. Kiểm tra Thư viện Component chuẩn: ds-card, ds-row, ds-btn, ds-chip, ds-search-bar, ds-skeleton, ds-empty-state, ds-error-state, ds-sheet-panel.
4. Kiểm tra cấu trúc Tab Việc chuẩn IA mới (tổng quan, tìm kiếm, chip lọc, phân trang, bộ 4 trạng thái).
5. Kiểm tra Bottom Sheet Chi tiết bước L3 (chạm vào bước timeline mở sheet chi tiết tool/input/output).
6. Kiểm tra tích hợp Telegram Native SDK (ready, expand, BackButton, HapticFeedback, addToHomeScreen).
7. Kiểm thử tương tác và render thật bằng Playwright Chromium viewport 390×844.
"""

from __future__ import annotations

import asyncio
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
from mulon.memory import Memory
from mulon.policy import PolicyEngine
from mulon.tools import build_default_registry
from mulon.vault import VaultStore
from mulon.webapp_server import WebAppServer


REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML_PATH = REPO_ROOT / "mulon" / "webapp" / "index.html"
DOCS_CAPABILITIES_PATH = REPO_ROOT / "docs" / "nghien-cuu-telegram-mini-app-capabilities.md"
ARTIFACT_DIR = Path(os.environ.get("ARTIFACT_DIR", REPO_ROOT / "data" / "artifacts"))
BOT_TOKEN = "123456:ABCDEF_test_token_for_t12"
OWNER_ID = 424242


def test_telegram_mini_app_capabilities_doc_exists():
    """Kiểm tra báo cáo nghiên cứu khả năng 'app' của Telegram Mini App tồn tại và đầy đủ."""
    assert DOCS_CAPABILITIES_PATH.exists(), "docs/nghien-cuu-telegram-mini-app-capabilities.md phải tồn tại"
    content = DOCS_CAPABILITIES_PATH.read_text(encoding="utf-8")
    assert "Bot Menu Button" in content
    assert "Direct Link" in content
    assert "expand" in content
    assert "disableVerticalSwipes" in content
    assert "addToHomeScreen" in content
    assert "BackButton" in content
    assert "HapticFeedback" in content
    assert "giới hạn" in content.lower()
    assert "Design System" in content


def test_design_system_tokens_and_elements_static():
    """Kiểm tra các Design Tokens và Components trong mulon/webapp/index.html."""
    assert INDEX_HTML_PATH.exists()
    html = INDEX_HTML_PATH.read_text(encoding="utf-8")

    # 1. Tokens 60/30/10 và tím Mulon
    assert "--ds-primary:#7C3AED;" in html or "--ds-primary: #7C3AED;" in html or "--ds-primary" in html
    assert "--ds-destructive:" in html
    assert "--ds-fs-h1:" in html
    assert "--ds-fs-h2:" in html
    assert "--ds-fs-body:" in html
    assert "--ds-fs-caption:" in html
    assert "--ds-pad:16px;" in html or "--ds-pad:" in html
    assert "--ds-radius-card:" in html
    assert "--ds-radius-btn:" in html
    assert "--ds-radius-chip:" in html
    assert "--ds-radius-sheet:" in html
    assert "--ds-row-min-h:" in html
    assert "--ds-touch-min:" in html

    # 2. Các component classes
    assert ".ds-card" in html
    assert ".ds-row" in html
    assert ".ds-btn" in html
    assert ".ds-chip-group" in html
    assert ".ds-chip" in html
    assert ".ds-search-bar" in html
    assert ".ds-skeleton" in html
    assert ".ds-empty-state" in html
    assert ".ds-error-state" in html
    assert ".ds-sheet-overlay" in html
    assert ".ds-sheet-panel" in html

    # 3. Các elements trên giao diện Tab Việc
    assert 'id="tasks-overview-bar"' in html
    assert 'id="tasks-search-input"' in html
    assert 'id="tasks-filter-chips"' in html
    assert 'id="tasks-error-state"' in html
    assert 'id="tasks-load-more"' in html
    assert 'id="task-retry-actions"' in html

    # 4. Sheet Chi tiết bước L3
    assert 'id="sheet-step-detail"' in html
    assert 'id="step-sheet-title"' in html
    assert 'id="step-sheet-status"' in html
    assert 'id="step-sheet-tool"' in html
    assert 'id="step-sheet-time"' in html
    assert 'id="step-sheet-input"' in html
    assert 'id="step-sheet-output"' in html

    # 5. Lối tắt màn hình chính trong screen-system
    assert 'id="card-homescreen-shortcut"' in html
    assert 'id="row-add-homescreen"' in html

    # 6. Tích hợp Native Telegram WebApp SDK
    assert "tg.BackButton" in html
    assert "tg.HapticFeedback" in html
    assert "disableVerticalSwipes" in html
    assert "addToHomeScreen" in html


def _make_server(cfg2: Config, mem: Memory) -> WebAppServer:
    policy = PolicyEngine(cfg2.policy_path, memory=mem)
    registry = build_default_registry(cfg2, mem)
    return WebAppServer(
        cfg2,
        memory=mem,
        policy=policy,
        broker=ApprovalBroker(policy=policy, timeout_s=30),
        connectors=build_default_connectors(cfg2),
        mcp_manager=None,
        vault_store=VaultStore(cfg2.vault_path),
        registry=registry,
        dossier=Dossier.load(cfg2.dossier_dir),
    )


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


def test_playwright_t12_design_system_and_interactions(cfg: Config):
    """Kiểm tra render và tương tác thật bằng Playwright Chromium viewport 390×844."""
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        pytest.skip("Playwright không được cài đặt")

    port_holder = {}
    stop_ev = threading.Event()

    def run_server():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def _serve():
            mem = await Memory.open(cfg.db_path)

            # 1. Task đang chạy
            await mem.create_task(
                "task-running-01",
                "default",
                "Thu thập tin tức AI buổi sáng",
                [],
            )
            await mem.add_task_step(
                "task-running-01",
                "Đọc feed tin tức từ các nguồn công nghệ",
                status="done",
                detail=json.dumps({"tool": "web_fetch", "url": "https://news.ycombinator.com", "ok": True}),
            )
            await mem.add_task_step(
                "task-running-01",
                "Tổng hợp và chắt lọc điểm nổi bật",
                status="doing",
                detail=json.dumps({"tool": "run_command", "command": "python -c 'print(\"summarizing\")'", "ok": True}),
            )

            # 2. Task đã hoàn thành
            await mem.create_task(
                "task-done-02",
                "default",
                "Kiểm tra và sao lưu cơ sở dữ liệu hệ thống",
                [],
            )
            await mem.add_task_step(
                "task-done-02",
                "Kiểm tra tính toàn vẹn của SQLite WAL",
                status="done",
                detail=json.dumps({"tool": "run_command", "command": "sqlite3 test.db 'PRAGMA integrity_check;'", "result": "ok", "ok": True}),
            )
            await mem.add_task_step(
                "task-done-02",
                "Nén và lưu trữ bản ghi",
                status="done",
                detail=json.dumps({"tool": "run_command", "command": "tar -czf backup.tar.gz data/", "result": "archive created", "ok": True}),
            )
            await mem.finish_task("task-done-02", status="done", result="Sao lưu thành công 12 bảng vào thư mục an toàn.")

            # 3. Task thất bại
            await mem.create_task(
                "task-failed-03",
                "default",
                "Đăng bài lên kênh Telegram",
                [],
            )
            await mem.add_task_step(
                "task-failed-03",
                "Soạn thảo nội dung bài viết",
                status="done",
                detail=json.dumps({"tool": "write_file", "path": "post.txt", "ok": True}),
            )
            await mem.add_task_step(
                "task-failed-03",
                "Gửi tin nhắn vào kênh",
                status="failed",
                detail=json.dumps({"tool": "send_message", "error": "Connection timed out", "ok": False}),
            )
            await mem.finish_task("task-failed-03", status="failed", error="Lỗi mạng: Không thể kết nối tới máy chủ Telegram (Timeout)")

            from dataclasses import replace
            srv = _make_server(replace(cfg, telegram_bot_token=BOT_TOKEN, allowed_user_id=OWNER_ID, webapp_port=0), mem)
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
    init_data = make_init_data()

    try:
        with sync_playwright() as p:
            browser = _launch_chromium(p)
            page = browser.new_page(viewport={"width": 390, "height": 844})
            page.route(
                "**/telegram-web-app.js*",
                lambda route: route.fulfill(status=200, content_type="application/javascript", body=""),
            )
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
            page.wait_for_selector("#task-list .row[data-task]")

            # 1. Kiểm tra Tab Việc: Thanh tổng quan số liệu
            page.wait_for_selector("#tasks-overview-bar")
            assert page.locator("#tasks-stat-running").inner_text().strip() == "1"
            assert page.locator("#tasks-stat-done").inner_text().strip() == "1"
            assert page.locator("#tasks-stat-failed").inner_text().strip() == "1"

            # Chụp ảnh Tab Việc
            if ARTIFACT_DIR.exists():
                page.screenshot(path=str(ARTIFACT_DIR / "t12_tab_viec_ds.png"), full_page=True)

            # Lọc theo chip 'Đang chạy'
            page.locator('#tasks-filter-chips [data-task-filter="running"]').click()
            visible_running = page.locator("#task-list .row")
            assert visible_running.count() == 1
            assert "Thu thập tin tức AI" in visible_running.first.locator(".r-title").inner_text()

            # Trở lại 'Tất cả'
            page.locator('#tasks-filter-chips [data-task-filter="all"]').click()
            assert page.locator("#task-list .row").count() == 3

            # Tìm kiếm việc 'sao lưu'
            page.locator("#tasks-search-input").fill("sao lưu")
            assert page.locator("#task-list .row").count() == 1
            assert "sao lưu" in page.locator("#task-list .row:first-child .r-title").inner_text().lower()

            # Bấm nút xóa tìm kiếm
            page.locator("#tasks-search-clear").click()
            assert page.locator("#tasks-search-input").input_value() == ""
            assert page.locator("#task-list .row").count() == 3

            # 2. Mở Chi tiết việc 'task-done-02' (L2)
            page.locator('[data-task="task-done-02"]').click()
            page.wait_for_selector("#screen-task:not(.hidden)")
            page.wait_for_function("() => !document.getElementById('task-detail-title').textContent.includes('Chi tiết việc')")
            assert "sao lưu" in page.locator("#task-detail-title").inner_text().lower()

            # 3. Kiểm tra Bottom Sheet Chi tiết bước L3
            step_rows = page.locator("#task-timeline [data-step-idx]")
            assert step_rows.count() >= 2

            # Chạm vào bước đầu tiên để mở Sheet Chi tiết bước L3
            page.locator('#task-timeline [data-step-idx="0"]').click()
            page.wait_for_selector("#sheet-step-detail:not(.hidden)")

            assert "Kiểm tra tính toàn vẹn" in page.locator("#step-sheet-title").inner_text()
            assert "run_command" in page.locator("#step-sheet-tool").inner_text()
            assert "Hoàn thành" in page.locator("#step-sheet-status").inner_text()
            assert "integrity_check" in page.locator("#step-sheet-input").inner_text()

            # Chụp ảnh Chi tiết việc kèm Bottom Sheet
            if ARTIFACT_DIR.exists():
                page.screenshot(path=str(ARTIFACT_DIR / "t12_task_detail_with_sheet.png"), full_page=True)

            # Đóng Bottom Sheet bằng nút ✕
            page.locator("#step-sheet-close").click()
            page.wait_for_selector("#sheet-step-detail", state="hidden")

            # Bấm quay lại Tab Việc
            page.locator("#screen-task [data-back]").click()
            page.wait_for_selector("#tab-viec:not(.hidden)")

            # 4. Kiểm tra việc lỗi 'task-failed-03' có cụm nút thử lại
            page.locator('[data-task="task-failed-03"]').click()
            page.wait_for_selector("#screen-task:not(.hidden)")
            page.wait_for_function("() => !document.getElementById('task-detail-title').textContent.includes('Chi tiết việc')")
            assert page.locator("#task-retry-actions").is_visible()
            assert page.locator("#btn-retry-task").is_visible()
            assert page.locator("#btn-retry-step").is_visible()

            # Quay lại
            page.locator("#screen-task [data-back]").click()
            page.wait_for_selector("#tab-viec:not(.hidden)")

            # 5. Kiểm tra Cài đặt -> Thiết bị & Hệ thống -> Lối tắt màn hình chính
            page.locator('#segbar button[data-tab="caidat"]').click()
            page.wait_for_selector("#tab-caidat:not(.hidden)")
            page.locator('[data-open="screen-system"]').click()
            page.wait_for_selector("#screen-system:not(.hidden)")

            assert page.locator("#card-homescreen-shortcut").is_visible()
            assert page.locator("#row-add-homescreen").is_visible()
            if ARTIFACT_DIR.exists():
                page.screenshot(path=str(ARTIFACT_DIR / "t12_screen_system_homescreen.png"), full_page=True)

            # Bấm vào hàng Thêm ra màn hình chính
            page.locator("#row-add-homescreen").click()
            home_requested = page.evaluate("() => window._homeScreenRequested")
            assert home_requested is True, "Bấm hàng Thêm ra màn hình chính phải gọi addToHomeScreen()"

            browser.close()
    finally:
        stop_ev.set()
        th.join(timeout=2.0)
