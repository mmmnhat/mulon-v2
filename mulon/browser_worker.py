"""Browser worker tối thiểu (thiết kế mục 6) — Phase 3 + 4.

Playwright (Chromium headless) cho việc cần render thật:
- web_read: mở URL, trích text chính (bỏ nav/footer/script...).
- web_screenshot: chụp PNG lưu vào workspace, trả đường dẫn.

Phase 4 thêm profile bền tuỳ chọn: đặt BROWSER_PROFILE_DIR thì
Chromium dùng persistent context ở thư mục đó — cookie/đăng nhập
sống qua các lần chạy. Mặc định (không đặt) vẫn profile tạm, mỗi
lần mở là sạch như cũ.

Phân biệt với web_fetch (đọc nhanh bằng HTTP thuần): web_read dành
cho trang cần JS. Playwright/Chromium vắng hoặc khởi động lỗi ->
tool trả unavailable SẠCH, không bao giờ làm sập agent.
"""

from __future__ import annotations

import html as html_lib
import logging
import re
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Optional

from .tools import ToolSpec

logger = logging.getLogger("mulon.browser")

_BLOCK_TAGS = (
    "script", "style", "noscript", "iframe", "svg", "head", "nav",
    "header", "footer", "aside", "form", "button",
)


def extract_main_text(raw_html: str, max_chars: int = 12_000) -> str:
    """Trích text chính từ HTML — hàm thuần, test không cần mạng.

    Ưu tiên nội dung trong <article>/<main>; không có thì dùng toàn
    trang sau khi gọt các khối không phải nội dung.
    """
    if not raw_html:
        return ""
    text = raw_html
    for tag in ("script", "style", "noscript", "iframe", "svg", "head"):
        text = re.sub(rf"<{tag}[\s\S]*?</{tag}>", " ", text,
                      flags=re.IGNORECASE)
    chunks: list[str] = []
    for tag in ("article", "main"):
        chunks = re.findall(rf"<{tag}[^>]*>([\s\S]*?)</{tag}>", text,
                            flags=re.IGNORECASE)
        if chunks:
            break
    if not chunks:
        body = re.search(r"<body[^>]*>([\s\S]*?)</body>", text,
                         flags=re.IGNORECASE)
        segment = body.group(1) if body else text
        for tag in ("nav", "header", "footer", "aside", "form"):
            segment = re.sub(rf"<{tag}[\s\S]*?</{tag}>", " ", segment,
                             flags=re.IGNORECASE)
        chunks = [segment]
    joined = " ".join(chunks)
    joined = re.sub(r"<[^>]+>", " ", joined)
    joined = html_lib.unescape(re.sub(r"\s+", " ", joined)).strip()
    return joined[:max_chars]


def playwright_available() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except Exception:
        return False


class BrowserWorker:
    def __init__(self, cfg):
        self.cfg = cfg

    # ---------- profile (Phase 4) ----------
    def profile_dir(self) -> Optional[Path]:
        """Thư mục profile cố định, None = profile tạm (mặc định)."""
        raw = getattr(self.cfg, "browser_profile_dir", None)
        return Path(raw) if raw else None

    def uses_persistent_profile(self) -> bool:
        return self.profile_dir() is not None

    @asynccontextmanager
    async def _open_page(self):
        """Mở 1 page Chromium: persistent context khi có profile
        dir (giữ đăng nhập), browser tạm như cũ khi không."""
        from playwright.async_api import async_playwright

        async with async_playwright() as pw:
            profile = self.profile_dir()
            if profile is not None:
                profile.mkdir(parents=True, exist_ok=True)
                context = await pw.chromium.launch_persistent_context(
                    str(profile), headless=True)
                try:
                    page = (context.pages[0] if context.pages
                            else await context.new_page())
                    yield page
                finally:
                    await context.close()
            else:
                browser = await pw.chromium.launch(headless=True)
                try:
                    yield await browser.new_page()
                finally:
                    await browser.close()

    async def _fetch_rendered(self, url: str) -> tuple[str, str]:
        """Mở trang bằng Chromium, trả (title, html)."""
        async with self._open_page() as page:
            await page.goto(
                url,
                timeout=int(self.cfg.browser_timeout_s * 1000),
                wait_until="domcontentloaded",
            )
            title = await page.title()
            content = await page.content()
            return title, content

    async def _capture_png(self, url: str, out_path: Path) -> None:
        async with self._open_page() as page:
            await page.goto(
                url,
                timeout=int(self.cfg.browser_timeout_s * 1000),
                wait_until="domcontentloaded",
            )
            await page.screenshot(path=str(out_path), full_page=True)

    def _unavailable(self, reason: str) -> dict:
        return {
            "ok": False,
            "unavailable": True,
            "error": f"browser_unavailable: {reason}",
        }

    async def read(self, url: str,
                   max_chars: Optional[int] = None) -> dict:
        if not playwright_available():
            return self._unavailable(
                "chưa cài playwright (pip install playwright && "
                "playwright install chromium)"
            )
        try:
            title, content = await self._fetch_rendered(url)
        except Exception as exc:
            return self._unavailable(f"{type(exc).__name__}: {exc}")
        limit = int(max_chars or self.cfg.browser_max_chars)
        return {
            "ok": True,
            "url": url,
            "title": title,
            "content": extract_main_text(content, limit),
        }

    async def screenshot(self, url: str) -> dict:
        if not playwright_available():
            return self._unavailable(
                "chưa cài playwright (pip install playwright && "
                "playwright install chromium)"
            )
        out_dir = Path(self.cfg.workspace_dir) / "screenshots"
        out_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
        out_path = out_dir / f"shot-{stamp}.png"
        try:
            await self._capture_png(url, out_path)
        except Exception as exc:
            return self._unavailable(f"{type(exc).__name__}: {exc}")
        return {"ok": True, "url": url, "path": str(out_path)}


def register_browser_tools(registry, cfg) -> BrowserWorker:
    worker = BrowserWorker(cfg)

    async def web_read(url: str, max_chars: int = 0):
        return await worker.read(url, max_chars or None)

    async def web_screenshot(url: str):
        return await worker.screenshot(url)

    registry.register(ToolSpec(
        name="web_read",
        description=(
            "Mở URL bằng trình duyệt thật (render JS) và trích text "
            "chính. Dùng khi web_fetch không đủ vì trang cần JS. Cần "
            "Playwright — vắng thì báo unavailable."
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "max_chars": {"type": "integer", "default": 0},
            },
            "required": ["url"],
        },
        group="web",
        timeout_s=90,
        handler=web_read,
    ))
    registry.register(ToolSpec(
        name="web_screenshot",
        description=(
            "Chụp ảnh toàn trang của URL bằng trình duyệt thật, lưu "
            "PNG vào workspace/screenshots, trả đường dẫn file."
        ),
        parameters={
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
        group="web",
        timeout_s=90,
        handler=web_screenshot,
    ))
    return worker
