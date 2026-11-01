"""Script chụp bằng chứng render 2 theme thật (Light & Dark) bằng Playwright Chromium 390x844.

Đo đạc:
- Chiều cao Header + Segbar <= 160px
- SHA256 và mean RGB của 3 ảnh:
  1. docs/audits/renders/01_dashboard_light.png
  2. docs/audits/renders/02_dashboard_dark.png
  3. docs/audits/renders/04_tasks_dark.png
"""

import asyncio
import hashlib
from pathlib import Path
from PIL import Image
import numpy as np

from mulon.approvals import ApprovalBroker
from mulon.config import Config
from mulon.connectors import build_default_connectors
from mulon.context import Dossier
from mulon.memory import Memory
from mulon.policy import PolicyEngine
from mulon.tools import build_default_registry
from mulon.vault import VaultStore
from mulon.webapp_server import WebAppServer
from tests.test_v12_webapp_auth import OWNER, TOKEN, make_init_data
from tests.conftest import open_memory


REPO_ROOT = Path(__file__).resolve().parent.parent
RENDERS_DIR = REPO_ROOT / "docs" / "audits" / "renders"


async def main():
    RENDERS_DIR.mkdir(parents=True, exist_ok=True)

    cfg = Config.load()
    from dataclasses import replace
    # Tùy chỉnh config cho test server
    import tempfile
    td = tempfile.TemporaryDirectory()
    tmp_db = Path(td.name) / "test_memory.db"
    cfg = replace(
        cfg,
        telegram_bot_token=TOKEN,
        allowed_user_id=OWNER,
        webapp_port=0,
        db_path=tmp_db,
    )

    memory = await open_memory(cfg)
    # Seed một số dữ liệu việc để tab Việc hiển thị đẹp
    await memory.create_schedule(
        schedule_id="sched_1",
        cron="0 8 * * *",
        timezone_name="Asia/Ho_Chi_Minh",
        payload="Đọc các bài viết mới về LLM trên Arxiv và HackerNews",
        session_key="tg:424242",
        next_run_at="2026-11-02T08:00:00+07:00",
        enabled=True,
        title="Đọc báo và tổng hợp tin tức AI",
    )
    await memory.create_schedule(
        schedule_id="sched_2",
        cron="*/30 * * * *",
        timezone_name="Asia/Ho_Chi_Minh",
        payload="Kiểm tra trạng thái proxy và gateway",
        session_key="tg:424242",
        next_run_at="2026-11-02T00:30:00+07:00",
        enabled=True,
        title="Kiểm tra nhịp tim hệ thống và pin",
    )

    dossier = Dossier.load(cfg.dossier_dir)
    policy = PolicyEngine(cfg.policy_path, memory=memory)
    registry = build_default_registry(cfg, memory, dossier=dossier)
    connectors = build_default_connectors(cfg)
    vault_store = VaultStore(cfg.vault_path)

    server = WebAppServer(
        cfg,
        memory=memory,
        policy=policy,
        broker=ApprovalBroker(policy=policy, timeout_s=30),
        connectors=connectors,
        mcp_manager=None,
        vault_store=vault_store,
        registry=registry,
        dossier=dossier,
    )

    assert await server.start()
    port = server.port
    print(f"[+] Server started on http://127.0.0.1:{port}")

    init_data = make_init_data()
    base_url = f"http://127.0.0.1:{port}/app"

    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        context = await browser.new_context(
            viewport={"width": 390, "height": 844},
            is_mobile=True,
            has_touch=True,
            device_scale_factor=2,
        )
        page = await context.new_page()

        await page.route(
            "**/telegram-web-app.js*",
            lambda route: route.fulfill(
                status=200,
                content_type="application/javascript",
                body="",
            ),
        )

        await page.add_init_script(
            f"""
            window.Telegram = {{
                WebApp: {{
                    initData: {init_data!r},
                    colorScheme: "light",
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
        await page.wait_for_timeout(500)

        # 1. Đo chiều cao Header + Segbar
        geom = await page.evaluate(
            """() => {
                const header = document.querySelector('header.app-header');
                const segbar = document.querySelector('#segbar');
                const btnEdit = document.querySelector('#btn-edit-identity');
                const hRect = header.getBoundingClientRect();
                const sRect = segbar.getBoundingClientRect();
                const bRect = btnEdit ? btnEdit.getBoundingClientRect() : { width: 0, height: 0 };
                return {
                    headerHeight: hRect.height,
                    segbarHeight: sRect.height,
                    totalHeight: hRect.height + sRect.height,
                    btnWidth: bRect.width,
                    btnHeight: bRect.height
                };
            }"""
        )
        print(f"[+] Geometry measurements:")
        print(f"    - Header height: {geom['headerHeight']:.2f}px")
        print(f"    - Segbar height: {geom['segbarHeight']:.2f}px")
        print(f"    - Total height:  {geom['totalHeight']:.2f}px (target <= 160px)")
        print(f"    - Edit button:   {geom['btnWidth']:.2f}x{geom['btnHeight']:.2f}px (target >= 44x44px)")

        # 2. Chụp Dashboard Light
        await page.evaluate("""() => {
            window.Telegram.WebApp.colorScheme = 'light';
            document.documentElement.dataset.scheme = '';
            if (typeof syncColorScheme === 'function') syncColorScheme();
        }""")
        await page.wait_for_timeout(400)
        img_light_path = RENDERS_DIR / "01_dashboard_light.png"
        await page.screenshot(path=str(img_light_path))
        print(f"[+] Captured: {img_light_path}")

        # 3. Chụp Dashboard Dark
        await page.evaluate("""() => {
            window.Telegram.WebApp.colorScheme = 'dark';
            document.documentElement.dataset.scheme = 'dark';
            if (typeof syncColorScheme === 'function') syncColorScheme();
        }""")
        await page.wait_for_timeout(400)
        img_dark_path = RENDERS_DIR / "02_dashboard_dark.png"
        await page.screenshot(path=str(img_dark_path))
        print(f"[+] Captured: {img_dark_path}")

        # 4. Chụp Tab Việc Dark
        await page.click('#segbar button[data-tab="viec"]')
        await page.wait_for_selector('#tab-viec:not(.hidden)')
        await page.wait_for_timeout(500)
        img_tasks_path = RENDERS_DIR / "04_tasks_dark.png"
        await page.screenshot(path=str(img_tasks_path))
        print(f"[+] Captured: {img_tasks_path}")

        await browser.close()

    await server.stop()
    await memory.close()

    # Tính toán SHA256 & mean RGB
    print("\n[+] Verification & Image Analysis:")
    for path in [img_light_path, img_dark_path, img_tasks_path]:
        data = path.read_bytes()
        sha = hashlib.sha256(data).hexdigest()
        im = Image.open(path).convert("RGB")
        arr = np.array(im)
        mean_r = np.mean(arr[:, :, 0])
        mean_g = np.mean(arr[:, :, 1])
        mean_b = np.mean(arr[:, :, 2])
        mean_rgb = (mean_r + mean_g + mean_b) / 3.0
        print(f"  * {path.name}:")
        print(f"    - SHA256: {sha}")
        print(f"    - Mean RGB: {mean_rgb:.2f} (R: {mean_r:.1f}, G: {mean_g:.1f}, B: {mean_b:.1f})")


if __name__ == "__main__":
    asyncio.run(main())
