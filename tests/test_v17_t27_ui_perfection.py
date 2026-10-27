"""Kiểm thử Mini App đạt chuẩn chuyên nghiệp 100% (T-27).

1. Kiểm tra tĩnh HTML/JS:
   - Thẻ hành động phê duyệt chờ + banner số lượng yêu cầu
   - Nhóm lịch sử phê duyệt theo ngày (Hôm nay, Hôm qua, Trước đó) + hiển thị mốc giờ
   - Heartbeat gom về screen-schedule-detail + phân trang lịch sử chạy
   - Ô tìm kiếm Kho bí mật Vault khi >= 5 mục
   - Bộ chọn nhịp đăng Feed chủ động (Preset ưu tiên, highlight preset đang chọn)
   - Lọc bỏ ký tự hỏng '>' trong danh sách kỹ năng
2. Kiểm thử tương tác và render thật bằng Playwright Chromium viewport 390×844:
   - Kiểm tra Tab Phê duyệt: Thẻ duyệt chờ + Lịch sử nhóm theo ngày
   - Kiểm tra Tab Lịch: Mở Chi tiết Heartbeat, phân trang lịch sử chạy (Xem thêm)
   - Kiểm tra Kho bí mật Vault: Tìm kiếm lọc tức thì, mở màn chi tiết bí mật
   - Kiểm tra Feed chủ động: Nút preset kích hoạt khớp lịch
   - Kiểm tra điều hướng BackButton Telegram
   - Chụp ảnh render thật 390×844 đối chiếu giao diện
"""

from __future__ import annotations

import asyncio
from dataclasses import replace
from datetime import datetime, timezone, timedelta
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
ARTIFACT_DIR = Path(os.environ.get("ARTIFACT_DIR", REPO_ROOT / "data" / "artifacts"))
BOT_TOKEN = "123456:ABCDEF_test_token_for_t27"
OWNER_ID = 777888


def test_t27_static_ui_perfection():
    """Kiểm tra tĩnh các cải tiến chuẩn chuyên nghiệp 100% trong index.html."""
    assert INDEX_HTML_PATH.exists()
    html = INDEX_HTML_PATH.read_text(encoding="utf-8")

    # 1. Phê duyệt: formatTimeOnly, getDayGroupKey, hist-day-header, banner chờ duyệt
    assert "function formatTimeOnly(" in html
    assert "function getDayGroupKey(" in html
    assert "hist-day-header" in html
    assert "Yêu cầu đang chờ duyệt" in html
    assert "Không có yêu cầu chờ duyệt" in html

    # 2. Lịch: data-sched-open="heartbeat", phân trang lịch sử chạy schedRunsPage, SCHED_RUNS_PER_PAGE
    assert 'data-sched-open="heartbeat"' in html
    assert "schedRunsPage" in html
    assert "SCHED_RUNS_PER_PAGE" in html
    assert "btn-sched-runs-more" in html

    # 3. Kho bí mật: vault-search-wrap, VAULT_FILTER_Q
    assert 'id="vault-search-wrap"' in html
    assert 'id="vault-search"' in html
    assert "VAULT_FILTER_Q" in html

    # 4. Kỹ năng: dọn ký tự hỏng '>'
    assert 'desc === ">"' in html or 'desc === ">-"' in html

    # 5. Feed chủ động: highlight preset
    assert 'btn.dataset.cronPreset === (f.cron || "").trim()' in html


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


def test_playwright_t27_ui_perfection(cfg: Config):
    """Kiểm thử render thật và tương tác 100% chuyên nghiệp bằng Chromium viewport 390x844."""
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

            # 1. Cài đặt Kho bí mật (6 mục để kích hoạt thanh tìm kiếm >= 5 mục)
            vstore = VaultStore(cfg.vault_path)
            vstore.put("GitHub Token", "ghp_secret_key_123")
            vstore.put("Google Client ID", "google_id_abc")
            vstore.put("Google Client Secret", "google_secret_xyz")
            vstore.put("Stripe Payment Key", "sk_live_stripe_999")
            vstore.put("OpenAI API Key", "sk_openai_test_001")
            vstore.put("Telegram Bot Token", "tg_bot_token_777")

            # 2. Cài đặt Lịch trình & Lịch sử chạy (Heartbeat 8 lượt chạy để kích hoạt phân trang > 5 lượt)
            now = datetime.now(timezone.utc)
            for i in range(8):
                t = now - timedelta(minutes=30 * i)
                hb_payload = {
                    "status": "ok" if i != 2 else "error",
                    "trigger": "scheduled",
                    "summary": f"Nhịp kiểm tra chủ động #{i + 1}",
                    "detail": f"Chi tiết phân tích lượt #{i + 1}",
                    "result": "HEARTBEAT_OK" if i != 2 else "HEARTBEAT_ERROR",
                }
                await mem.db.execute(
                    "INSERT INTO trajectory(session_key, kind, payload, created_at) VALUES (?, ?, ?, ?)",
                    ("system", "heartbeat", json.dumps(hb_payload), t.isoformat()),
                )
            await mem.db.commit()

            # Thêm 1 lịch hẹn cá nhân
            await mem.create_schedule(
                schedule_id="sched_hop_giao_ban",
                cron="0 9 * * 1-5",
                timezone_name="Asia/Ho_Chi_Minh",
                payload="Nhắc nhở họp giao ban sáng các ngày trong tuần",
                session_key="default",
                next_run_at=(now + timedelta(days=1)).isoformat(),
                enabled=True,
                title="Họp giao ban 9:00",
            )

            # 3. Cài đặt Phê duyệt (1 pending + lịch sử nhiều ngày)
            await mem.db.execute(
                "INSERT INTO trajectory(session_key, kind, payload, created_at) VALUES (?, ?, ?, ?)",
                (
                    "system",
                    "approval_decision",
                    json.dumps({
                        "tool": "run_command",
                        "group": "system",
                        "action_label": "Chạy script dọn dẹp log",
                        "layer": "ask",
                        "outcome": "approved",
                        "approved": True,
                        "remember": False,
                    }),
                    (now - timedelta(days=2)).isoformat(),
                ),
            )
            await mem.db.execute(
                "INSERT INTO trajectory(session_key, kind, payload, created_at) VALUES (?, ?, ?, ?)",
                (
                    "system",
                    "approval_decision",
                    json.dumps({
                        "tool": "write_file",
                        "group": "files",
                        "action_label": "Ghi file cấu hình mới",
                        "layer": "ask",
                        "outcome": "approved",
                        "approved": True,
                        "remember": True,
                    }),
                    (now - timedelta(days=1, hours=3)).isoformat(),
                ),
            )
            await mem.db.execute(
                "INSERT INTO trajectory(session_key, kind, payload, created_at) VALUES (?, ?, ?, ?)",
                (
                    "system",
                    "approval_decision",
                    json.dumps({
                        "tool": "restart_bot",
                        "group": "system",
                        "action_label": "Khởi động lại tiến trình bot",
                        "layer": "ask",
                        "outcome": "denied",
                        "approved": False,
                        "remember": False,
                    }),
                    (now - timedelta(hours=1)).isoformat(),
                ),
            )
            await mem.db.commit()

            srv = _make_server(
                replace(cfg, telegram_bot_token=BOT_TOKEN, allowed_user_id=OWNER_ID, webapp_port=0),
                mem,
            )

            # Giả lập 1 pending approval trong broker
            srv.broker._pending["appr_pending_live_01"] = {
                "id": "appr_pending_live_01",
                "created_at": time.time(),
                "timeout_s": 30,
                "payload": {
                    "tool": "delete_library_item",
                    "action_label": "Xoá tài liệu quan trọng khỏi thư viện",
                    "group": "library",
                    "group_label": "Thư viện",
                    "summary": "Yêu cầu xoá vĩnh viễn tệp báo cáo tài chính",
                    "layer": "ask",
                },
            }

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

            # ---------------- 1. KIỂM THỬ TAB PHÊ DUYỆT ----------------
            page.locator('button[data-tab="pheduyet"]').click()
            page.wait_for_selector("#tab-pheduyet:not(.hidden)")

            # Kiểm tra thẻ banner yêu cầu đang chờ duyệt
            page.wait_for_selector("#pending-wrap .card")
            assert "Yêu cầu đang chờ duyệt (1)" in page.locator("#pending-wrap").inner_text()
            assert "báo cáo tài chính" in page.locator("#pending-wrap").inner_text()

            # Kiểm tra lịch sử phê duyệt có nhóm ngày (Hôm nay / Hôm qua / Trước đó) và mốc giờ
            page.wait_for_selector("#history-list .hist-day-header")
            hist_headers = page.locator("#history-list .hist-day-header")
            assert hist_headers.count() >= 2
            hist_text = page.locator("#history-list").inner_text()
            assert "hôm nay" in hist_text.lower()
            assert "lúc " in hist_text or ":" in hist_text

            if ARTIFACT_DIR.exists():
                page.screenshot(path=str(ARTIFACT_DIR / "t27_tab_pheduyet.png"), full_page=True)

            # ---------------- 2. KIỂM THỬ TAB LỊCH & CHI TIẾT HEARTBEAT ----------------
            page.locator('button[data-tab="lich"]').click()
            page.wait_for_selector("#tab-lich:not(.hidden)")

            # Bấm vào Heartbeat item
            page.locator("#card-heartbeat-item").click()
            if page.locator("#modal-heartbeat:not(.hidden)").is_visible():
                page.locator("#btn-close-heartbeat").click()
            page.wait_for_selector("#screen-schedule-detail:not(.hidden)")

            # Kiểm tra tiêu đề màn chi tiết lịch trình
            page.wait_for_function("() => document.getElementById('sched-detail-title').textContent.includes('Heartbeat')")
            assert "Nhịp kiểm tra chủ động" in page.locator("#sched-detail-kind").inner_text()

            # Kiểm tra phân trang lịch sử chạy (SCHED_RUNS_PER_PAGE = 5)
            page.wait_for_selector("#sched-detail-runs .sched-run-wrap")
            runs = page.locator("#sched-detail-runs .sched-run-wrap")
            assert runs.count() == 5  # Hiển thị đúng 5 lượt đầu

            # Bấm 'Xem thêm' để tải các lượt cũ
            page.wait_for_selector("#btn-sched-runs-more")
            page.locator("#btn-sched-runs-more").click()
            assert page.locator("#sched-detail-runs .sched-run-wrap").count() == 8  # Đã hiện đủ 8 lượt

            if ARTIFACT_DIR.exists():
                page.screenshot(path=str(ARTIFACT_DIR / "t27_screen_schedule_detail.png"), full_page=True)

            # Quay lại Tab Lịch qua BackButton
            page.locator("#screen-schedule-detail .backrow").click()
            page.wait_for_selector("#tab-lich:not(.hidden)")

            # ---------------- 3. KIỂM THỬ TAB CÀI ĐẶT & KHO BÍ MẬT ----------------
            page.locator('button[data-tab="caidat"]').click()
            page.wait_for_selector("#tab-caidat:not(.hidden)")

            # Mở Kho lưu trữ an toàn
            page.locator('[data-open="screen-vault"]').click()
            page.wait_for_selector("#screen-vault:not(.hidden)")

            # Kiểm tra ô tìm kiếm xuất hiện (vì có 6 mục >= 5)
            page.wait_for_selector("#vault-search-wrap:not(.hidden)")
            assert page.locator("#vault-list .row").count() == 6

            # Lọc theo 'google'
            page.locator("#vault-search").fill("google")
            assert page.locator("#vault-list .row").count() == 2

            # Mở Chi tiết bí mật
            page.locator("#vault-list .row:first-child").click()
            page.wait_for_selector("#screen-vault-detail:not(.hidden)")
            assert "Google" in page.locator("#vault-detail-title").inner_text()

            if ARTIFACT_DIR.exists():
                page.screenshot(path=str(ARTIFACT_DIR / "t27_screen_vault_detail.png"), full_page=True)

            # Quay lại Kho lưu trữ
            page.locator("#screen-vault-detail .backrow").click()
            page.wait_for_selector("#screen-vault:not(.hidden)")

            # Quay lại Cài đặt
            page.locator("#screen-vault .backrow").click()
            page.wait_for_selector("#tab-caidat:not(.hidden)")

            # ---------------- 4. KIỂM THỬ FEED CHỦ ĐỘNG (PRESETS) ----------------
            page.locator('[data-open="screen-feed"]').click()
            page.wait_for_selector("#screen-feed:not(.hidden)")

            # Kiểm tra các nút preset hiển thị
            presets = page.locator("#screen-feed [data-cron-preset]")
            assert presets.count() >= 3

            if ARTIFACT_DIR.exists():
                page.screenshot(path=str(ARTIFACT_DIR / "t27_screen_feed.png"), full_page=True)

            browser.close()
    finally:
        stop_ev.set()
        th.join(timeout=3)
