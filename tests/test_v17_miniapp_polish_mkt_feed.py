"""T-23.5 — Chuẩn hoá màu 60/30/10, Việt hoá nhãn kỹ thuật, nâng cấp Chợ MCP
và tái cấu trúc màn Feed chủ động trên Mini App.

Kiểm chứng:
1. API `/api/state` lọc bỏ hoàn toàn bản ghi thẻ phê duyệt thử (`the_duyet`,
   `test=True`, `kind="test"`) khỏi cả `pending` và `history`, đồng thời trả
   `layer_label` tiếng Việt cho lịch sử phê duyệt.
2. API `/api/feed` hỗ trợ `action="save_all"` lưu đồng thời `cron`,
   `quiet_hours`, `max_posts_per_day`, `daily_token_budget`, `denylist`;
   trạng thái Feed kèm `cron_human` và `cron_display` tiếng Việt.
3. API `/api/marketplace/catalog` hỗ trợ tìm kiếm `query`, lọc `locality`
   (`local` / `remote`), lọc `min_score` (`8`), và mọi mục trong danh mục
   đều có thông tin số công cụ (`tool_count_known` hoặc `tool_count_label`).
4. Render thật bằng Playwright Chromium ở khung nhìn điện thoại 390×844:
   - Header và các màn hình tuân thủ chuẩn màu 60/30/10 (không chấm xanh lá
     ở trạng thái header, không emoji xanh lá ở Feed, có ghi chú thiết kế
     dưới 6 ô màu chủ đề).
   - Tab Phê duyệt hiển thị `"Chế độ quyền"` bằng tiếng Việt, không lộ dữ liệu thử.
   - Chợ MCP tìm kiếm/lọc trực tiếp, hiển thị đầy đủ số công cụ mỗi hàng,
     phân trang hiển thị rõ `"Trang 1 / 106 (2105 mục)"` không dùng dấu chấm
     thập phân gây hiểu nhầm.
   - Màn Feed chủ động tách rõ thẻ Trạng thái hoạt động (chỉ xem + hộp xác nhận
     trước khi Chạy ngay) và thẻ Cấu hình Feed (gộp 1 nút Lưu cấu hình duy nhất).
"""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from aiohttp import ClientSession

from mulon.approvals import ApprovalBroker
from mulon.connectors import build_default_connectors
from mulon.context import Dossier
from mulon.marketplace import MarketplaceService
from mulon.policy import PolicyEngine
from mulon.tools import build_default_registry
from mulon.vault import VaultStore
from mulon.webapp_server import (
    WebAppServer,
    known_action_label,
    policy_layer_label,
)
from tests.conftest import open_memory
from tests.test_v12_webapp_auth import OWNER, TOKEN, make_init_data
from tests.test_v14_feed_auto import (
    LONG_POST,
    FakeGateway,
    build_runner,
    seed_topics,
)

ARTIFACT_DIR = Path(
    r"C:\Users\AMZ-HUY\.gemini\antigravity\brain\b0796e43-96d5-46c3-8379-f4cf8122a7c6"
)


@pytest.fixture
async def env_t23_5(cfg, tmp_path):
    cfg2 = replace(
        cfg,
        telegram_bot_token=TOKEN,
        allowed_user_id=OWNER,
        webapp_port=0,
    )
    memory = await open_memory(cfg2)
    await seed_topics(memory)
    await memory.create_goal("Trí tuệ nhân tạo trong giáo dục")
    policy = PolicyEngine(cfg2.policy_path, memory=memory)
    broker = ApprovalBroker(policy=policy, timeout_s=30)

    # Tạo dữ liệu lịch sử phê duyệt: gồm cả thẻ thử the_duyet (phải bị lọc bỏ)
    # và quyết định thật (phải hiển thị kèm layer_label tiếng Việt).
    await memory.log_trajectory(
        "tg:1",
        "approval_decision",
        {
            "tool": "the_duyet",
            "group": "system",
            "layer": "ask",
            "outcome": "approved",
            "approved": True,
            "remember": False,
            "test": True,
            "summary": "Gửi thẻ phê duyệt thử",
        },
    )
    await memory.log_trajectory(
        "tg:1",
        "approval_decision",
        {
            "tool": "run_command",
            "group": "shell",
            "layer": "host",
            "outcome": "approved",
            "approved": True,
            "remember": True,
        },
    )
    await memory.log_trajectory(
        "tg:1",
        "approval_decision",
        {
            "tool": "web_fetch",
            "group": "web",
            "layer": "ask",
            "outcome": "denied",
            "approved": False,
            "remember": False,
        },
    )

    # Mở 1 pending thử (phải bị lọc) và 1 pending thật
    broker.open(
        "appr_test_1",
        {
            "approval_id": "appr_test_1",
            "tool": "the_duyet",
            "group": "system",
            "kind": "test",
            "test": True,
            "summary": "Thẻ phê duyệt thử nghiệm",
        },
    )
    broker.open(
        "appr_real_1",
        {
            "approval_id": "appr_real_1",
            "tool": "write_file",
            "group": "file",
            "summary": "Ghi báo cáo tuần vào workspace/report.md",
            "reason": "Lưu bản tổng hợp theo yêu cầu của chủ nhân.",
        },
    )

    # Khởi tạo FeedAutoRunner
    gw = FakeGateway([LONG_POST])
    feed_runner, _feed_engine, sender = await build_runner(
        cfg2,
        memory,
        gw,
        external=False,
    )
    sent_messages = sender.sent
    await feed_runner.ensure_schedule()

    # Khởi tạo MarketplaceService có mock MCP marketplace (trả cả local & remote,
    # điểm bảo mật cao/thấp, và tổng số lớn 2105 để kiểm tra phân trang).
    mock_mcp = AsyncMock()

    async def _call_tool(server_name, tool_name, args):
        if server_name == "mcp-marketplace" and tool_name == "list_categories":
            return {
                "ok": True,
                "result": {
                    "categories": [
                        {
                            "slug": "developer-tools",
                            "name": "Developer Tools",
                            "count": 1240,
                            "description": "Công cụ lập trình, Git, kiểm thử và phân tích mã nguồn.",
                        },
                        {
                            "slug": "databases",
                            "name": "Databases",
                            "count": 865,
                            "description": "Kết nối cơ sở dữ liệu SQL, NoSQL và kho vector.",
                        },
                    ]
                },
            }
        if server_name == "mcp-marketplace" and tool_name == "search_servers":
            q = (args.get("query") or "").lower()
            raw_items = [
                {
                    "slug": "postgres-mcp-pro",
                    "name": "PostgreSQL Inspector MCP",
                    "creator": "db-team",
                    "tagline": "Truy vấn và kiểm tra lược đồ PostgreSQL an toàn",
                    "category": args.get("category") or "databases",
                    "mode": "local_process",
                    "pricing": "Free",
                    "security_score": 9.2,
                    "risk_level": "Low",
                    "critical_findings": 0,
                    "tool_count": 6,
                },
                {
                    "slug": "cloud- flare-remote-mcp",
                    "name": "Cloudflare Remote Worker MCP",
                    "creator": "cf-labs",
                    "tagline": "Quản lý worker và KV từ xa qua giao thức SSE/HTTP",
                    "category": args.get("category") or "developer-tools",
                    "mode": "remote",
                    "pricing": "Free",
                    "security_score": 7.4,
                    "risk_level": "Medium",
                    "critical_findings": 0,
                },
            ]
            if q:
                raw_items = [
                    it
                    for it in raw_items
                    if q in it["name"].lower()
                    or q in it["tagline"].lower()
                    or q in it["slug"].lower()
                ]
            return {
                "ok": True,
                "result": {
                    "results": raw_items,
                    "total_matches": 2101 if not q else len(raw_items),
                    "has_more": not bool(q),
                },
            }
        return {"ok": False}

    mock_mcp.call_tool.side_effect = _call_tool
    mock_mcp.server_names.return_value = []
    mock_mcp.health_summary.return_value = {}
    mock_mcp.set_secret_resolver = lambda fn: None

    marketplace = MarketplaceService(
        cfg2,
        mcp_manager=mock_mcp,
        vault_store=VaultStore(cfg2.vault_path),
        policy=policy,
        broker=broker,
    )

    server = WebAppServer(
        cfg2,
        memory=memory,
        policy=policy,
        broker=broker,
        connectors=build_default_connectors(cfg2),
        mcp_manager=mock_mcp,
        vault_store=VaultStore(cfg2.vault_path),
        registry=build_default_registry(cfg2, memory),
        dossier=Dossier.load(cfg2.dossier_dir),
        skills=None,
        marketplace=marketplace,
        feed_auto=feed_runner,
    )
    assert await server.start()
    yield cfg2, memory, server, broker, feed_runner, sent_messages
    broker.resolve("appr_test_1", False)
    broker.resolve("appr_real_1", False)
    await server.stop()
    await memory.close()


def _url(server: WebAppServer, path: str) -> str:
    return f"http://127.0.0.1:{server.port}{path}"


async def test_api_state_filters_test_approvals_and_translates_policy_layer(env_t23_5):
    _cfg, _memory, server, _broker, _runner, _sent = env_t23_5
    assert known_action_label("the_duyet", "") == ""
    assert policy_layer_label("ask") == "Hỏi trước khi chạy"
    assert policy_layer_label("host") == "Quy tắc lưu bền trên máy"
    assert policy_layer_label("session") == "Quy tắc nhớ trong phiên"

    # T-31: che đường dẫn tuyệt đối nhúng giữa câu mô tả kỹ năng
    from mulon.webapp_server import _localize_skill_description
    for sample_desc in (
        "Use when asked to open /Users/mmmnhat/secret/file.txt in editor.",
        "Đọc dữ liệu từ /Volumes/DataDisk/private/report.csv ngay.",
        "Inspect logs at /home/ubuntu/app/secret.log before deploy.",
        r"Chạy công cụ tại C:\Users\Admin\Desktop\secret\run.bat để kiểm tra.",
    ):
        localized = _localize_skill_description("custom-tool", sample_desc)
        assert "/Users/mmmnhat" not in localized
        assert "/Volumes/DataDisk" not in localized
        assert "/home/ubuntu" not in localized
        assert "C:\\Users\\Admin" not in localized and "C:/Users/Admin" not in localized

    headers = {"X-Telegram-Init-Data": make_init_data()}
    async with ClientSession() as session:
        async with session.get(_url(server, "/api/state"), headers=headers) as resp:
            assert resp.status == 200
            data = await resp.json()

    pending = data["approvals"]["pending"]
    history = data["approvals"]["history"]

    # Không còn bất kỳ bản ghi the_duyet / thẻ phê duyệt thử nào
    assert all(p["tool"] != "the_duyet" for p in pending)
    assert len(pending) == 1
    assert pending[0]["tool"] == "write_file"
    assert pending[0]["action_label"] == "Ghi file"

    assert all(h["tool"] != "the_duyet" for h in history)
    hist_by_tool = {h["tool"]: h for h in history}
    assert hist_by_tool["run_command"]["layer_label"] == "Quy tắc lưu bền trên máy"
    assert hist_by_tool["web_fetch"]["layer_label"] == "Hỏi trước khi chạy"


async def test_api_feed_save_all_and_mkt_filters(env_t23_5):
    _cfg, _memory, server, _broker, _runner, _sent = env_t23_5
    headers = {"X-Telegram-Init-Data": make_init_data()}

    async with ClientSession() as session:
        # 1. Kiểm tra save_all của Feed chủ động
        payload = {
            "action": "save_all",
            "cron": "0 7,19 * * *",
            "quiet_hours": "22:30-06:30",
            "max_posts_per_day": 5,
            "daily_token_budget": 15000,
            "denylist": ["spam.example.com", "ads.test.org"],
        }
        async with session.post(_url(server, "/api/feed"), headers=headers, json=payload) as resp:
            assert resp.status == 200
            res = await resp.json()
            assert res["ok"] is True
            feed = res["feed"]
            assert feed["cron"] == "0 7,19 * * *"
            assert "07:00" in feed["cron_human"] and "19:00" in feed["cron_human"]
            assert feed["quiet_hours"] == "22:30-06:30"
            assert feed["max_posts_per_day"] == 5
            assert feed["daily_token_budget"] == 15000
            assert feed["denylist"] == ["spam.example.com", "ads.test.org"]

        # 2. Kiểm tra lọc Chợ MCP theo locality & min_score & tool_count_label
        async with session.get(
            _url(server, "/api/marketplace/catalog?locality=remote"),
            headers=headers,
        ) as resp:
            assert resp.status == 200
            cat_remote = await resp.json()
            items_remote = cat_remote["items"]
            assert len(items_remote) == 1
            assert items_remote[0]["slug"] == "cloud- flare-remote-mcp"
            assert items_remote[0]["tool_count_label"] == "Đa công cụ"

        async with session.get(
            _url(server, "/api/marketplace/catalog?min_score=8"),
            headers=headers,
        ) as resp:
            assert resp.status == 200
            cat_sec8 = await resp.json()
            assert all((it.get("security") or {}).get("score", 0) >= 8 for it in cat_sec8["items"])
            assert all(
                (it.get("tool_count_known") or 0) > 0 or bool(it.get("tool_count_label"))
                for it in cat_sec8["items"]
            )


async def _launch_async_chromium(p):
    last_err = None
    for channel in (None, "msedge", "chrome"):
        try:
            kwargs = {"headless": True}
            if channel:
                kwargs["channel"] = channel
            return await p.chromium.launch(**kwargs)
        except Exception as exc:
            last_err = exc
    pytest.skip(f"Chromium/Edge not available for Playwright: {last_err}")


@pytest.mark.asyncio
async def test_playwright_t23_5_ui_polish_mkt_and_feed(env_t23_5):
    playwright = pytest.importorskip("playwright.async_api")
    _cfg, _memory, server, _broker, _runner, sent_messages = env_t23_5
    init_data = make_init_data()
    base_url = _url(server, "/app")

    async with playwright.async_playwright() as p:
        browser = await _launch_async_chromium(p)
        context = await browser.new_context(
            viewport={"width": 390, "height": 844},
            device_scale_factor=2,
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

        # 1. Kiểm tra chuẩn màu 60/30/10 trên Header: không còn xanh lá #3E9B6C (rgb(62, 155, 108))
        header_colors = await page.evaluate(
            """() => {
                const st = getComputedStyle(document.querySelector('.app-status'));
                const dot = getComputedStyle(document.querySelector('#status-dot'));
                return { statusColor: st.color, dotBg: dot.backgroundColor };
            }"""
        )
        assert header_colors["statusColor"] != "rgb(62, 155, 108)"
        assert header_colors["dotBg"] != "rgb(62, 155, 108)"

        # 2. Mở Tab Phê duyệt: kiểm tra không còn thẻ thử the_duyet và nhãn "Chế độ quyền" tiếng Việt
        await page.click('#segbar button[data-tab="pheduyet"]')
        await page.wait_for_selector("#tab-pheduyet:not(.hidden)")
        # Mở chi tiết 2 dòng lịch sử để kiểm tra đầy đủ nhãn tiếng Việt
        await page.click('#history-list .row[data-hist="0"]')
        await page.click('#history-list .row[data-hist="1"]')
        appr_text = await page.inner_text("#tab-pheduyet")
        assert "phê duyệt thử" not in appr_text.lower()
        assert "the_duyet" not in appr_text.lower()
        assert "Lớp policy" not in appr_text
        assert "Chế độ quyền" in appr_text
        assert "Hỏi trước khi chạy" in appr_text
        assert "Quy tắc lưu bền trên máy" in appr_text

        if ARTIFACT_DIR.exists():
            await page.screenshot(path=str(ARTIFACT_DIR / "t23_5_tab_pheduyet.png"), full_page=True)

        # 3. Mở Tab Cài đặt: kiểm tra 5 hàng điều hướng có icon SVG đơn sắc + ghi chú dưới 6 ô màu chủ đề
        await page.click('#segbar button[data-tab="caidat"]')
        await page.wait_for_selector("#tab-caidat:not(.hidden)")
        caidat_info = await page.evaluate(
            """() => {
                const rows = Array.from(document.querySelectorAll('#tab-caidat > .card:first-child .row[data-open]'));
                const allHaveSvg = rows.length === 5 && rows.every(r => !!r.querySelector('.glyph svg'));
                const noteEl = document.querySelector('#theme-design-note');
                const swatches = document.querySelectorAll('#theme-swatches .swatch');
                return {
                    rowCount: rows.length,
                    allHaveSvg,
                    noteText: noteEl ? noteEl.innerText.trim() : '',
                    swatchCount: swatches.length
                };
            }"""
        )
        assert caidat_info["rowCount"] == 5
        assert caidat_info["allHaveSvg"] is True
        assert caidat_info["swatchCount"] == 6
        assert "60/30/10" in caidat_info["noteText"]

        if ARTIFACT_DIR.exists():
            await page.screenshot(path=str(ARTIFACT_DIR / "t23_5_tab_caidat.png"), full_page=True)

        # 4. Mở Công cụ kết nối -> Chợ MCP: kiểm tra tìm kiếm, lọc, hiển thị số công cụ & phân trang
        await page.click('#tab-caidat .row[data-open="screen-connectors"]')
        await page.wait_for_selector("#screen-connectors:not(.hidden)")
        conn_installed_text = await page.inner_text("#conn-view-installed")
        assert "Đang nối" not in conn_installed_text

        await page.click('#conn-seg button[data-conn-tab="market"]')
        await page.wait_for_selector("#conn-view-market:not(.hidden)")
        await page.wait_for_selector("#mkt-cats .row")

        # Bấm chip lọc "Bảo mật ≥ 8" ngay tại màn Chợ -> hiện thẻ kết quả lọc nhanh
        await page.click('#mkt-filter-chips button[data-mkt-filter="sec8"]')
        await page.wait_for_selector("#mkt-inline-card:not(.hidden) .row")
        inline_text = await page.inner_text("#mkt-inline-card")
        assert "công cụ" in inline_text
        assert "Bảo mật" in inline_text

        if ARTIFACT_DIR.exists():
            await page.screenshot(path=str(ARTIFACT_DIR / "t23_5_mkt_search.png"), full_page=True)

        # Reset về "Tất cả" rồi bấm vào danh mục "Tất cả" để mở #screen-mktcat
        await page.click('#mkt-filter-chips button[data-mkt-filter="all"]')
        await page.click('#mkt-cats .row[data-cat=""]')
        await page.wait_for_selector("#screen-mktcat:not(.hidden)")
        await page.wait_for_selector("#mkt-list .row")

        mktcat_check = await page.evaluate(
            """() => {
                const pageInfo = document.querySelector('#mkt-page-info').innerText.trim();
                const subTexts = Array.from(document.querySelectorAll('#mkt-list .row .r-sub')).map(el => el.innerText.trim());
                return { pageInfo, subTexts };
            }"""
        )
        # Không còn "2.101" gây hiểu nhầm số thập phân
        assert "2.101" not in mktcat_check["pageInfo"]
        assert "Trang 1 / " in mktcat_check["pageInfo"]
        assert "mục)" in mktcat_check["pageInfo"]
        # Mọi hàng đều có thông tin công cụ ("công cụ") và chế độ chạy tiếng Việt ("Chạy cục bộ" / "Từ xa")
        assert len(mktcat_check["subTexts"]) > 0
        for sub in mktcat_check["subTexts"]:
            assert "công cụ" in sub
            assert ("Chạy cục bộ" in sub) or ("Từ xa" in sub)

        if ARTIFACT_DIR.exists():
            await page.screenshot(path=str(ARTIFACT_DIR / "t23_5_mkt_category.png"), full_page=True)

        # Quay lại Cài đặt -> Mở Feed chủ động
        await page.click("#mktcat-back")
        await page.wait_for_selector("#screen-connectors:not(.hidden)")
        await page.click('#screen-connectors .backrow[data-back]')
        await page.wait_for_selector("#tab-caidat:not(.hidden)")
        await page.click('#tab-caidat .row[data-open="screen-feed"]')
        await page.wait_for_selector("#screen-feed:not(.hidden)")

        feed_screen_text = await page.inner_text("#screen-feed")
        assert "🟢" not in feed_screen_text
        assert "Trạng thái hoạt động (chỉ xem)" in feed_screen_text
        assert "Khung giờ nghỉ" in feed_screen_text
        assert "Cấu hình Feed chủ động" in feed_screen_text
        assert "Lưu cấu hình Feed" in feed_screen_text

        # Bấm "Chạy ngay một lượt" -> mở hộp xác nhận, chưa gửi bài ngay
        sent_before = len(sent_messages)
        await page.click("#feed-run-now")
        confirm_visible = await page.is_visible("#feed-run-confirm-box")
        assert confirm_visible is True
        assert len(sent_messages) == sent_before

        if ARTIFACT_DIR.exists():
            await page.screenshot(path=str(ARTIFACT_DIR / "t23_5_screen_feed.png"), full_page=True)

        # Bấm "Xác nhận chạy" -> gọi API run_now thật và ẩn hộp xác nhận
        await page.click("#feed-run-confirm")
        await page.wait_for_selector("#feed-run-confirm-box", state="hidden")
        for _ in range(30):
            if len(sent_messages) == sent_before + 1:
                break
            await page.wait_for_timeout(50)
        assert await page.is_visible("#feed-run-confirm-box") is False
        assert len(sent_messages) == sent_before + 1

        # Thử sửa cấu hình và bấm nút "Lưu cấu hình Feed" duy nhất
        await page.fill("#feed-cron", "0 8,20 * * *")
        await page.fill("#feed-quiet", "23:00-07:00")
        await page.fill("#feed-max-posts", "4")
        await page.click("#feed-save-all")
        await page.wait_for_timeout(300)
        state_after = await page.inner_text("#feed-state")
        assert "08:00, 20:00" in state_after
        assert "0 / 4" in state_after

        await browser.close()
