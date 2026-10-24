"""Browser worker tối thiểu (thiết kế mục 6) — Phase 3 + 4.

Playwright (Chromium headless) cho việc cần render thật:
- web_read: mở URL, trích text chính (bỏ nav/footer/script...).
- web_screenshot: chụp PNG lưu vào workspace, trả đường dẫn.

Phase 4 thêm profile bền tuỳ chọn: đặt BROWSER_PROFILE_DIR thì
Chromium dùng persistent context ở thư mục đó — cookie/đăng nhập
sống qua các lần chạy. Mặc định (không đặt) vẫn profile tạm, mỗi
lần mở là sạch như cũ.

Sửa 1.6.2 — tương tác có duyệt (web_click/web_fill):
- Mỗi lần gọi tự mở 1 page mới, goto(url) rồi click/fill, xong đóng
  page. KHÔNG có page giữ qua các lần gọi: click/fill chỉ có hiệu
  lực "trong phiên browser hiện tại" của chính lần gọi đó, không
  nối tiếp trạng thái từ lần gọi trước (trừ profile bền Phase 4 mà
  owner đã tự cấu hình từ trước — hành vi đó không đổi).
- Cả 2 tool mặc định ở nấc policy ask (xem TOOL_DEFAULTS trong
  policy.py): agent không tự chạy khi chưa có thẻ duyệt.
- KHÔNG tự đăng nhập, KHÔNG lưu password: fill từ chối mọi ô
  type=password và mọi selector nhắc tới password; fill không bấm
  Enter/submit kèm theo, click không điền gì thêm.
- Giới hạn chống lạm dụng: selector CSS thuần, tối đa 200 ký tự,
  phải khớp đúng 1 phần tử; text điền tối đa 500 ký tự; kết quả
  fill không echo lại text.

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

from .tools import ToolSpec, assert_url_public

logger = logging.getLogger("mulon.browser")

# sửa 1.6.2: trần chống lạm dụng cho tool tương tác.
MAX_SELECTOR_LEN = 200
MAX_FILL_TEXT_LEN = 500
_SELECTOR_FORBIDDEN = ("xpath=", "text=", "role=", "javascript:",
                       "<", ">>", "`", "\n", "\r")


def validate_selector(selector: str) -> Optional[str]:
    """Trả lỗi (chuỗi) nếu selector không đạt, None nếu đạt.

    Chỉ cho CSS thuần: cấm tiền tố chọn kiểu Playwright (xpath=,
    text=, role=), cấm ký tự chèn HTML/JS. Hàm thuần, test không
    cần Playwright.
    """
    sel = selector or ""
    if not sel.strip():
        return "selector trống"
    if len(sel) > MAX_SELECTOR_LEN:
        return f"selector dài quá {MAX_SELECTOR_LEN} ký tự"
    lowered = sel.lower()
    for bad in _SELECTOR_FORBIDDEN:
        if bad in lowered:
            return f"selector cấm chứa {bad!r} (chỉ CSS thuần)"
    if "password" in lowered or "passwd" in lowered:
        return "selector nhắc tới password — từ chối để khỏi đăng nhập"
    return None


def validate_fill_text(text: str) -> Optional[str]:
    """Trả lỗi nếu text điền vượt trần, None nếu đạt."""
    if text is None or not str(text).strip():
        return "text điền trống"
    if len(str(text)) > MAX_FILL_TEXT_LEN:
        return f"text điền dài quá {MAX_FILL_TEXT_LEN} ký tự"
    return None


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
        """Mở trang bằng Chromium, trả (title, html).

        Sửa 1.6.3: SSRF guard cho browser. Browser KHÔNG dùng httpx
        nên không dùng được http_get_public; thay vào đó kiểm tra
        URL gốc (kèm DNS) trước goto, và kiểm tra lại URL cuối sau
        goto — nội dung của đích nội bộ (nếu redirect tới) bị vứt.
        Giới hạn còn lại, ghi rõ: Playwright tự theo redirect trong
        goto, nên 1 GET tới đích redirect nội bộ có thể đã xảy ra
        trước khi URL cuối bị chặn; chặn này vẫn ngăn agent ĐỌC và
        HÀNH ĐỘNG trên nội dung đó, nhưng không phải tường lửa
        pre-flight hoàn hảo như httpx. Đặt sau kiểm tra Playwright
        ở read()/screenshot() để test giả lập _fetch_rendered vẫn
        qua được (test tiêm fake_fetch, không cần DNS thật).
        """
        err = await assert_url_public(url)
        if err:
            raise ValueError(err)
        async with self._open_page() as page:
            await page.goto(
                url,
                timeout=int(self.cfg.browser_timeout_s * 1000),
                wait_until="domcontentloaded",
            )
            err = await assert_url_public(page.url)
            if err:
                raise ValueError(f"URL cuối sau redirect bị chặn: {err}")
            title = await page.title()
            content = await page.content()
            return title, content

    async def _capture_png(self, url: str, out_path: Path) -> None:
        # Sửa 1.6.3: cùng SSRF guard như _fetch_rendered.
        err = await assert_url_public(url)
        if err:
            raise ValueError(err)
        async with self._open_page() as page:
            await page.goto(
                url,
                timeout=int(self.cfg.browser_timeout_s * 1000),
                wait_until="domcontentloaded",
            )
            err = await assert_url_public(page.url)
            if err:
                raise ValueError(f"URL cuối sau redirect bị chặn: {err}")
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

    # ---------- sửa 1.6.2: tương tác có duyệt ----------
    async def _interact(self, url: str, selector: str,
                        text: Optional[str]) -> dict:
        """Goto(url) rồi click (text None) hoặc fill trong cùng 1
        page rồi đóng page. Không giữ page qua các lần gọi, không
        submit form, không chạm ô password."""
        if not playwright_available():
            return self._unavailable(
                "chưa cài playwright (pip install playwright && "
                "playwright install chromium)"
            )
        # Sửa 1.6.3: SSRF guard cho click/fill (đã duyệt vẫn phải
        # chặn đích nội bộ — duyệt là duyệt hành động, không phải
        # duyệt cho bot quét mạng nội bộ).
        err = await assert_url_public(url)
        if err:
            return {"ok": False, "error": err}
        err = validate_selector(selector)
        if err:
            return {"ok": False, "error": err}
        if text is not None:
            err = validate_fill_text(text)
            if err:
                return {"ok": False, "error": err}
        timeout_ms = int(self.cfg.browser_timeout_s * 1000)
        try:
            async with self._open_page() as page:
                await page.goto(
                    url, timeout=timeout_ms,
                    wait_until="domcontentloaded",
                )
                # Sửa 1.6.3: URL cuối sau redirect nội bộ thì dừng
                # trước khi bấm/điền (cùng giới hạn pre-flight như
                # _fetch_rendered: GET redirect có thể đã xảy ra).
                err = await assert_url_public(page.url)
                if err:
                    return {"ok": False,
                            "error": f"URL cuối sau redirect bị chặn: {err}"}
                loc = page.locator(selector)
                if await loc.count() != 1:
                    return {"ok": False, "error":
                            "selector phải khớp đúng 1 phần tử "
                            "(mơ hồ hoặc không thấy — từ chối để "
                            "khỏi bấm/điền nhầm)"}
                if text is not None:
                    info = await loc.evaluate(
                        "(el) => ({tag: el.tagName, type: el.type || '', "
                        "editable: !!el.isContentEditable})")
                    if str(info.get("type", "")).lower() == "password":
                        return {"ok": False, "error":
                                "ô password — từ chối điền "
                                "(không tự đăng nhập, không lưu "
                                "password)"}
                    if (str(info.get("tag", "")).upper()
                            not in ("INPUT", "TEXTAREA")
                            and not info.get("editable")):
                        return {"ok": False, "error":
                                "chỉ điền được ô INPUT/TEXTAREA "
                                "hoặc vùng soạn thảo"}
                    await loc.fill(text, timeout=timeout_ms)
                    # Không echo text, không bấm Enter/submit kèm.
                    return {"ok": True, "action": "fill",
                            "url": page.url,
                            "selector": selector,
                            "chars": len(text)}
                await loc.click(timeout=timeout_ms)
                content = await page.content()
                return {"ok": True, "action": "click",
                        "url": page.url, "title": await page.title(),
                        "selector": selector,
                        "snippet": extract_main_text(content, 2000)}
        except Exception as exc:
            return {"ok": False,
                    "error": f"{type(exc).__name__}: {exc}"}

    async def click(self, url: str, selector: str) -> dict:
        return await self._interact(url, selector, None)

    async def fill(self, url: str, selector: str, text: str) -> dict:
        return await self._interact(url, selector, text)


def register_browser_tools(registry, cfg) -> BrowserWorker:
    worker = BrowserWorker(cfg)

    async def web_read(url: str, max_chars: int = 0):
        return await worker.read(url, max_chars or None)

    async def web_screenshot(url: str):
        return await worker.screenshot(url)

    async def web_click(url: str, selector: str):
        return await worker.click(url, selector)

    async def web_fill(url: str, selector: str, text: str):
        return await worker.fill(url, selector, text)

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
    # sửa 1.6.2: tương tác có duyệt — group riêng "web:interact"
    # để host đặt rule riêng, và policy mặc định ask (TOOL_DEFAULTS).
    # Mỗi lần gọi mở page mới từ url rồi đóng: không nối trạng thái
    # qua các lần gọi, không đăng nhập, không lưu password.
    registry.register(ToolSpec(
        name="web_click",
        description=(
            "Mở URL bằng trình duyệt thật rồi click đúng 1 phần tử "
            "khớp selector CSS trong page đó (xong đóng page). Cần "
            "duyệt trước khi chạy (policy ask mặc định). Không nối "
            "trạng thái từ lần gọi trước, không tự đăng nhập."
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "selector": {"type": "string",
                             "description": "CSS thuần, tối đa 200 ký "
                                            "tự, phải khớp đúng 1 "
                                            "phần tử"},
            },
            "required": ["url", "selector"],
        },
        group="web:interact",
        timeout_s=90,
        handler=web_click,
    ))
    registry.register(ToolSpec(
        name="web_fill",
        description=(
            "Mở URL bằng trình duyệt thật rồi điền text vào 1 ô "
            "INPUT/TEXTAREA khớp selector CSS trong page đó (xong "
            "đóng page, không bấm Enter/submit kèm). Cần duyệt trước "
            "khi chạy (policy ask mặc định). Từ chối ô password, "
            "không tự đăng nhập, không lưu password, text tối đa "
            "500 ký tự và không echo lại trong kết quả."
        ),
        parameters={
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "selector": {"type": "string",
                             "description": "CSS thuần, tối đa 200 ký "
                                            "tự, phải khớp đúng 1 "
                                            "phần tử"},
                "text": {"type": "string"},
            },
            "required": ["url", "selector", "text"],
        },
        group="web:interact",
        timeout_s=90,
        handler=web_fill,
    ))
    return worker
