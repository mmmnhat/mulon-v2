"""Script chụp render thật Mini App viewport 390x844 bằng Playwright Chromium headless.
Tuân thủ AGENTS.md mục 6 (Cấm mock vẽ tay, tỉ lệ 60/30/10, màu nhấn tím #7C3AED, touch target >= 44px).
"""
import asyncio
import hashlib
import hmac
import json
import os
import sys
import threading
import time
from pathlib import Path
from urllib.parse import urlencode

from mulon.approvals import ApprovalBroker
from mulon.config import Config
from mulon.connectors import build_default_connectors
from mulon.context import Dossier
from mulon.memory import Memory
from mulon.policy import PolicyEngine
from mulon.tools import build_default_registry
from mulon.vault import VaultStore
from mulon.webapp_server import WebAppServer

try:
    from playwright.sync_api import sync_playwright
except ImportError:
    print("Playwright not installed, skipping screenshot capture")
    sys.exit(0)

BOT_TOKEN = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"
OWNER_ID = 123456789


def make_init_data() -> str:
    user_json = json.dumps({"id": OWNER_ID, "first_name": "Nhat"}, separators=(",", ":"))
    pairs = {
        "auth_date": str(int(time.time())),
        "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
        "user": user_json,
    }
    data_check = "\n".join(f"{k}={v}" for k, v in sorted(pairs.items()))
    secret = hmac.new(b"WebAppData", BOT_TOKEN.encode(), hashlib.sha256).digest()
    sig = hmac.new(secret, data_check.encode(), hashlib.sha256).hexdigest()
    pairs["hash"] = sig
    return urlencode(pairs)


def main():
    root = Path(__file__).resolve().parent.parent
    render_dir = root / "docs" / "audits" / "renders"
    render_dir.mkdir(parents=True, exist_ok=True)

    db_path = root / "workspace" / "test_renders.db"
    if db_path.exists():
        db_path.unlink()

    cfg = Config(
        telegram_bot_token=BOT_TOKEN,
        allowed_user_id=OWNER_ID,
        db_path=Path(db_path),
        dossier_dir=root / "dossier",
        policy_path=root / "config" / "policy.json",
        vault_path=root / "workspace" / "test_vault.json",
        bot_username="Mulon_bot",
    )

    port_holder = {}
    stop_ev = threading.Event()

    def run_server():
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)

        async def _serve():
            mem = await Memory.open(cfg.db_path)
            await mem.create_task("task-01", "default", "Tổng hợp tin tức công nghệ", [])
            await mem.add_task_step("task-01", "Cào tin tức từ Hacker News", status="done")
            await mem.add_task_step("task-01", "Phân tích nội dung", status="doing")

            policy = PolicyEngine(cfg.policy_path, memory=mem)
            registry = build_default_registry(cfg, mem)
            server = WebAppServer(
                cfg,
                memory=mem,
                policy=policy,
                broker=ApprovalBroker(policy=policy, timeout_s=30),
                connectors=build_default_connectors(cfg),
                mcp_manager=None,
                vault_store=VaultStore(cfg.vault_path),
                registry=registry,
                dossier=Dossier.load(cfg.dossier_dir),
            )
            from aiohttp import web
            runner = web.AppRunner(server.build_app())
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

    for _ in range(50):
        if "port" in port_holder:
            break
        time.sleep(0.1)

    port = port_holder["port"]
    url = f"http://127.0.0.1:{port}/"
    init_data = make_init_data()

    with sync_playwright() as p:
        browser = None
        for ch in (None, "chrome", "msedge"):
            try:
                kw = {"headless": True}
                if ch:
                    kw["channel"] = ch
                browser = p.chromium.launch(**kw)
                break
            except Exception:
                pass

        if not browser:
            print("Could not launch Chromium")
            stop_ev.set()
            return

        ctx = browser.new_context(
            viewport={"width": 390, "height": 844},
            user_agent="Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15",
        )
        ctx.add_init_script(f"""
            window.Telegram = {{
                WebApp: {{
                    initData: "{init_data}",
                    initDataUnsafe: {{ user: {{ id: {OWNER_ID}, first_name: "Nhat" }} }},
                    ready: function(){{}},
                    expand: function(){{}},
                    close: function(){{}},
                    enableClosingConfirmation: function(){{}},
                    BackButton: {{ show: function(){{}}, hide: function(){{}}, onClick: function(cb){{}} }},
                    HapticFeedback: {{
                        selectionChanged: function(){{}},
                        impactOccurred: function(s){{}},
                        notificationOccurred: function(t){{}}
                    }},
                    setHeaderColor: function(c){{}},
                    setBackgroundColor: function(c){{}},
                    isExpanded: true,
                    viewportHeight: 844,
                    viewportStableHeight: 844,
                    colorScheme: "dark",
                    themeParams: {{
                        bg_color: "#0B0C10",
                        text_color: "#F5F5F7",
                        hint_color: "#8E8E93",
                        link_color: "#7C3AED",
                        button_color: "#7C3AED",
                        button_text_color: "#FFFFFF",
                        secondary_bg_color: "#161822"
                    }}
                }}
            }};
        """)

        page = ctx.new_page()
        page.goto(url, wait_until="networkidle")
        page.wait_for_timeout(1000)

        # Chụp Dashboard Dark
        page.screenshot(path=str(render_dir / "02_dashboard_dark.png"))
        print(f"Captured: {render_dir / '02_dashboard_dark.png'}")

        # Chuyển sang Tab Việc
        tasks_tab = page.locator("#tab-viec")
        if tasks_tab.is_visible():
            tasks_tab.click()
            page.wait_for_timeout(600)
            page.screenshot(path=str(render_dir / "04_tasks_dark.png"))
            print(f"Captured: {render_dir / '04_tasks_dark.png'}")

        # Chụp theme Light
        page.evaluate("""() => {
            document.documentElement.setAttribute('data-theme', 'light');
        }""")
        page.wait_for_timeout(300)
        page.screenshot(path=str(render_dir / "01_dashboard_light.png"))
        print(f"Captured: {render_dir / '01_dashboard_light.png'}")

        browser.close()

    stop_ev.set()
    th.join(timeout=3)
    if db_path.exists():
        db_path.unlink()
    print("Render captures completed successfully.")


if __name__ == "__main__":
    main()
