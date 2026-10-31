"""Phase 3 — browser worker: trích text là hàm thuần (không mạng),
Playwright vắng thì tool báo unavailable sạch."""

import mulon.browser_worker as bw
from mulon.tools import ToolRegistry

HTML = """
<html><head><title>Trang test</title><style>.x{color:red}</style>
<script>alert(1)</script></head>
<body>
  <nav>Menu điều hướng</nav>
  <header>Đầu trang</header>
  <article>
    <h1>Tiêu đề chính</h1>
    <p>Nội dung quan trọng &amp; chi tiết của bài viết.</p>
  </article>
  <footer>Chân trang bản quyền</footer>
</body></html>
"""


def test_extract_prefers_article_and_strips_noise():
    text = bw.extract_main_text(HTML)
    assert "Tiêu đề chính" in text
    assert "Nội dung quan trọng & chi tiết" in text
    assert "Menu điều hướng" not in text  # article thắng, nav bị bỏ
    assert "alert" not in text  # script bị gọt
    assert "color:red" not in text  # style bị gọt


def test_extract_fallback_body_without_article():
    html = ("<html><body><nav>NAV</nav><p>Thân bài ở đây</p>"
            "<footer>FOOT</footer></body></html>")
    text = bw.extract_main_text(html)
    assert "Thân bài ở đây" in text
    assert "NAV" not in text and "FOOT" not in text


def test_extract_respects_max_chars():
    html = "<body><p>" + ("a" * 5000) + "</p></body>"
    assert len(bw.extract_main_text(html, max_chars=100)) == 100
    assert bw.extract_main_text("") == ""


async def test_browser_tools_degrade_when_playwright_missing(cfg, monkeypatch):
    monkeypatch.setattr(bw, "playwright_available", lambda: False)
    reg = ToolRegistry()
    bw.register_browser_tools(reg, cfg)
    read = await reg.execute("web_read", {"url": "https://example.com"})
    assert read["ok"] is False
    assert read["unavailable"] is True
    shot = await reg.execute("web_screenshot",
                             {"url": "https://example.com"})
    assert shot["ok"] is False
    assert shot["unavailable"] is True


async def test_browser_worker_uses_injected_render(cfg, monkeypatch):
    """Có Playwright (giả lập tầng fetch) thì read trả text đã trích."""
    worker = bw.BrowserWorker(cfg)
    monkeypatch.setattr(bw, "playwright_available", lambda: True)

    async def fake_fetch(url):
        return "Trang test", HTML

    worker._fetch_rendered = fake_fetch
    out = await worker.read("https://example.com")
    assert out["ok"] is True
    assert out["title"] == "Trang test"
    assert "Nội dung quan trọng" in out["content"]


async def test_browser_worker_launch_channel_fallback(cfg):
    """Khi thiếu bundled chromium_headless_shell (thường gặp trên Windows),
    BrowserWorker tự fallback sang msedge/chrome trước khi báo lỗi."""
    worker = bw.BrowserWorker(cfg)
    attempts: list[dict] = []

    class FakeChromium:
        async def launch(self, **kwargs):
            attempts.append(dict(kwargs))
            if kwargs.get("channel") != "msedge":
                raise RuntimeError("Executable doesn't exist")
            return "edge-browser-handle"

    class FakePW:
        chromium = FakeChromium()

    handle = await worker._launch_browser(FakePW())
    assert handle == "edge-browser-handle"
    assert attempts == [
        {"headless": True},
        {"headless": True, "channel": "msedge"},
    ]
