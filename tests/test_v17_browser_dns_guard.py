"""Test nghiệm thu T-39.2: Chốt chặn DNS-rebinding TOCTOU và Redirect Pre-flight cho Chromium Browser Worker.

Kiểm chứng 3 trường hợp theo ĐK4 của Muse:
1. Redirect từ URL sang 127.0.0.1 / IP nội bộ bị abort ở tầng route guard, 0 request chạm mock local.
2. URL trỏ tới IP private / loopback bị chặn ngay tại hop 1.
3. Redirect an toàn public -> public follow thành công và tải đầy đủ nội dung trang cuối (chống hồi quy kẹt 3xx).
"""

import asyncio
from pathlib import Path

import pytest
from aiohttp import web

import mulon.browser_worker as bw
from mulon.browser_worker import BrowserWorker, playwright_available
from mulon.config import Config

pytestmark = pytest.mark.skipif(
    not playwright_available(),
    reason="Yêu cầu Playwright Chromium đã cài đặt",
)


@pytest.fixture
def browser_cfg(tmp_path: Path) -> Config:
    dossier = tmp_path / "dossier"
    dossier.mkdir(parents=True, exist_ok=True)
    return Config(
        workspace_dir=tmp_path / "workspace",
        dossier_dir=dossier,
        browser_timeout_s=5.0,
    )


@pytest.mark.asyncio
async def test_redirect_to_private_ip_is_aborted_without_touching_local_server(browser_cfg, monkeypatch):
    """Test 1 (T-39.2): Redirect từ URL ngoài sang 127.0.0.1 bị chặn đứng ở route guard, mock local không bị chạm."""
    local_touched = False

    # Server 1: Giả lập site A (public hop 1)
    app1 = web.Application()

    async def handle_start(request):
        # Trả redirect sang server 2 (nội bộ)
        return web.HTTPFound("http://127.0.0.1:19992/secret-admin")

    app1.router.add_get("/start", handle_start)
    runner1 = web.AppRunner(app1)
    await runner1.setup()
    site1 = web.TCPSite(runner1, "127.0.0.1", 19991)
    await site1.start()

    # Server 2: Giả lập dịch vụ nội bộ (private server)
    app2 = web.Application()

    async def handle_secret(request):
        nonlocal local_touched
        local_touched = True
        return web.Response(text="LEAKED SENSITIVE DATA", status=200)

    app2.router.add_get("/secret-admin", handle_secret)
    runner2 = web.AppRunner(app2)
    await runner2.setup()
    site2 = web.TCPSite(runner2, "127.0.0.1", 19992)
    await site2.start()

    try:
        # Giả lập assert_url_public và resolve_and_verify_url:
        # Cho phép hop 1 (19991) coi như public để mô phỏng attacker site, nhưng 19992 bị chặn
        from mulon import tools

        async def fake_resolve_and_verify(url: str):
            if "19992" in url:
                return "url_ip_blocked: private loopback target", None
            return None, "1.2.3.4"

        monkeypatch.setattr(tools, "resolve_and_verify_url", fake_resolve_and_verify)
        monkeypatch.setattr(bw, "assert_url_public", lambda url: asyncio.sleep(0, result=None))

        worker = BrowserWorker(browser_cfg)
        result = await worker.read("http://127.0.0.1:19991/start")

        # Nghiệm thu: read thất bại an toàn, và server 2 nội bộ KHÔNG bị chạm tới
        assert result["ok"] is False
        assert result["unavailable"] is True
        assert not local_touched, "VI PHẠM AN NINH: Server nội bộ 19992 đã bị chạm tới!"
    finally:
        await runner1.cleanup()
        await runner2.cleanup()


@pytest.mark.asyncio
async def test_initial_url_private_ip_is_blocked_at_hop_one(browser_cfg, monkeypatch):
    """Test 2 (T-39.2): URL khởi đầu trỏ vào IP loopback/private bị chặn ngay tại route guard."""
    from mulon import tools

    async def fake_resolve_and_verify(url: str):
        return "url_ip_blocked: loopback 127.0.0.1", None

    monkeypatch.setattr(tools, "resolve_and_verify_url", fake_resolve_and_verify)
    monkeypatch.setattr(bw, "assert_url_public", lambda url: asyncio.sleep(0, result=None))

    worker = BrowserWorker(browser_cfg)
    result = await worker.read("http://malicious-internal-rebind.com/probe")

    assert result["ok"] is False
    assert result["unavailable"] is True
    assert "ERR_BLOCKED_BY_CLIENT" in result["error"] or "blocked" in result["error"].lower()


@pytest.mark.asyncio
async def test_safe_public_redirect_follows_and_loads_final_content(browser_cfg, monkeypatch):
    """Test 3 (T-39.2): Chuỗi redirect an toàn (public -> public) follow thành công và tải đầy đủ nội dung trang cuối."""
    app = web.Application()

    async def handle_start(request):
        resp = web.HTTPFound("/final-page")
        resp.set_cookie("auth", "session_ok_999", path="/")
        return resp

    async def handle_final(request):
        return web.Response(
            text="<html><head><title>Trang Đích An Toàn</title></head><body><h1>Nội dung đã tới đích</h1></body></html>",
            content_type="text/html",
        )

    app.router.add_get("/start-redirect", handle_start)
    app.router.add_get("/final-page", handle_final)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 19993)
    await site.start()

    try:
        from mulon import tools

        # Cả 2 hop đều an toàn
        monkeypatch.setattr(tools, "resolve_and_verify_url", lambda url: asyncio.sleep(0, result=(None, "8.8.8.8")))
        monkeypatch.setattr(bw, "assert_url_public", lambda url: asyncio.sleep(0, result=None))

        worker = BrowserWorker(browser_cfg)
        result = await worker.read("http://127.0.0.1:19993/start-redirect")

        assert result["ok"] is True
        assert result["title"] == "Trang Đích An Toàn"
        assert "Nội dung đã tới đích" in result["content"]
    finally:
        await runner.cleanup()
