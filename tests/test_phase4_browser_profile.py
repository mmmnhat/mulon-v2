"""Phase 4 — browser profile bền: mặc định profile tạm (hành vi
cũ), đặt BROWSER_PROFILE_DIR thì dùng persistent context ở thư
mục đó. Test ở mức cấu hình + degrade + đường render tiêm giả."""

from dataclasses import replace

import mulon.browser_worker as bw
from mulon.tools import ToolRegistry

HTML = ("<html><body><article><h1>Trang đã đăng nhập</h1>"
        "<p>Nội dung sau login.</p></article></body></html>")


def test_profile_defaults_to_ephemeral(cfg):
    worker = bw.BrowserWorker(cfg)
    assert worker.profile_dir() is None
    assert worker.uses_persistent_profile() is False


def test_profile_dir_from_config(cfg, tmp_path):
    profile = tmp_path / "browser-profile"
    cfg2 = replace(cfg, browser_profile_dir=profile)
    worker = bw.BrowserWorker(cfg2)
    assert worker.profile_dir() == profile
    assert worker.uses_persistent_profile() is True


async def test_profile_mode_still_degrades_without_playwright(
        cfg, tmp_path, monkeypatch):
    monkeypatch.setattr(bw, "playwright_available", lambda: False)
    cfg2 = replace(cfg, browser_profile_dir=tmp_path / "prof")
    reg = ToolRegistry()
    bw.register_browser_tools(reg, cfg2)
    out = await reg.execute("web_read", {"url": "https://example.com"})
    assert out["ok"] is False and out["unavailable"] is True


async def test_profile_mode_reads_via_injected_render(
        cfg, tmp_path, monkeypatch):
    cfg2 = replace(cfg, browser_profile_dir=tmp_path / "prof")
    worker = bw.BrowserWorker(cfg2)
    monkeypatch.setattr(bw, "playwright_available", lambda: True)

    async def fake_fetch(url):
        # đường persistent profile đi qua cùng _fetch_rendered —
        # tiêm giả lập để không cần Chromium thật trong test.
        assert worker.uses_persistent_profile() is True
        return "Trang đã đăng nhập", HTML

    worker._fetch_rendered = fake_fetch
    out = await worker.read("https://example.com/private")
    assert out["ok"] is True
    assert "Nội dung sau login" in out["content"]
