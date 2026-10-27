"""Bridge gửi DM Instagram qua web — giải quyết mục chặn T-22.3.

API Instagram Graph không mở endpoint nhắn tin cá nhân cho tài khoản thường (chỉ cấp cho Business qua Meta Inbox),
và connector ``instagram_messages`` trước đây trả ``sent: True`` giả khi không có session runner — tin chưa hề gửi đi.
Đường thật là browser bridge trên phiên Instagram web đã đăng nhập của người cài (sử dụng lại ``BROWSER_PROFILE_DIR``).

Nguyên tắc của bridge này (tương tự ThreadsBrowserBridge):
- Chỉ gửi vào hội thoại đã có từ trước hoặc recipient xác định.
- Không tự đăng nhập, không lưu password, không đọc cookie từ Vault để đăng nhập web.
  Đăng nhập web sống trong profile Chromium bền do người cài tự tạo trước (``BROWSER_PROFILE_DIR``).
- Chưa có profile thì báo ``ok: False, unsupported: True`` rõ ràng, không báo thành công giả.
- Không bao giờ trả thành công khi chưa xác minh: sau khi gửi, bridge xác minh nội dung vừa gửi
  xuất hiện trong hội thoại thì mới trả ``sent: True``.
- Selector lưu ở ``config/instagram_web_selectors.json`` (nạp qua ``datafiles``).
- Gửi tin là thao tác ghi: policy của connector ở nấc ``ask`` (hỏi trước).
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Callable, Optional

logger = logging.getLogger("mulon.instagram_browser_bridge")

DEFAULT_BASE_URL = "https://www.instagram.com"
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36"
)

DEFAULT_SELECTORS = {
    "inbox_path": "/direct/inbox/",
    "conversation_link_selector": "a[href*=\"/direct/t/\"]",
    "composer_selectors": [
        "div[contenteditable=\"true\"]",
        "textarea",
        "div[role=\"textbox\"]",
    ],
    "send_button_selectors": [
        "button[type=\"button\"]",
        "div[role=\"button\"]",
        "button[type=\"submit\"]",
    ],
}

ERR_NO_PROFILE = (
    "Instagram DM chưa có đường gửi thật trên bản cài này: chưa cấu "
    "hình BROWSER_PROFILE_DIR đã đăng nhập Instagram web. Hãy mở "
    "Instagram web bằng profile đó, đăng nhập 1 lần, rồi gửi lại. "
    "Bot không tự đăng nhập và không lưu password."
)
ERR_NO_PLAYWRIGHT = (
    "Instagram DM chưa gửi được: chưa cài Playwright/Chromium trên "
    "máy (pip install playwright && playwright install chromium)."
)
ERR_NOT_LOGGED_IN = (
    "Instagram web trong profile này chưa đăng nhập (bị chuyển về "
    "trang đăng nhập) — hãy đăng nhập Instagram web bằng profile đó "
    "rồi gửi lại."
)


def _load_selectors(overrides: Optional[dict] = None) -> dict:
    """Nạp selector từ config, fallback về mặc định khi vắng/hỏng."""
    data: dict = dict(DEFAULT_SELECTORS)
    if overrides:
        data.update(overrides)
        return data
    try:
        from .datafiles import load_json_data

        cfg = load_json_data("instagram_web_selectors.json")
        if isinstance(cfg, dict):
            data.update(cfg)
    except Exception as exc:
        logger.debug("nạp config/instagram_web_selectors.json thất bại: %s "
                     "— dùng fallback mặc định", exc)
    return data


def _playwright_available() -> bool:
    try:
        import playwright.async_api  # noqa: F401
        return True
    except Exception:
        return False


def _normalize_name(value: str) -> str:
    """Chuẩn hoá tên để khớp: bỏ @, hoa/thường, khoảng trắng, gạch dưới."""
    import re as _re
    return _re.sub(r"[^a-z0-9]", "", (value or "").lower().lstrip("@"))


def _match_conversation(href: str, label: str, thread_id: str,
                        participant: Optional[str] = None) -> bool:
    """Khớp hội thoại trong hộp thư web Instagram."""
    href_l = (href or "").lower()
    tid = (thread_id or "").strip().lower()
    if tid and tid in href_l:
        return True
    if participant:
        name = _normalize_name(participant)
        if name and (name in _normalize_name(href)
                     or name in _normalize_name(label)):
            return True
    return False


class PlaywrightInstagramDriver:
    """Driver Playwright thật cho Instagram Web Direct Messages."""

    def __init__(self, profile_dir: Path, base_url: str,
                 timeout_s: float, selectors: dict):
        self.profile_dir = Path(profile_dir)
        self.base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self.timeout_s = float(timeout_s or 30.0)
        self.selectors = selectors

    async def _first_matching(self, page, selectors: list[str]):
        """Trả locator đầu tiên khớp đúng 1 phần tử, None nếu không có."""
        for sel in selectors:
            try:
                loc = page.locator(sel)
                if await loc.count() == 1:
                    return loc
            except Exception:
                continue
        return None

    async def send(self, thread_id: str, text: str,
                   participant: Optional[str] = None) -> dict:
        """Gửi 1 tin vào hội thoại có sẵn, xác minh rồi mới báo ok."""
        from playwright.async_api import async_playwright

        timeout_ms = int(self.timeout_s * 1000)
        self.profile_dir.mkdir(parents=True, exist_ok=True)
        async with async_playwright() as pw:
            context = await pw.chromium.launch_persistent_context(
                str(self.profile_dir), headless=True,
                user_agent=DEFAULT_USER_AGENT)
            try:
                page = (context.pages[0] if context.pages
                        else await context.new_page())
                # 1. Mở hộp thư web
                inbox_url = f"{self.base_url}{self.selectors.get('inbox_path', '/direct/inbox/')}"
                await page.goto(inbox_url, timeout=timeout_ms,
                                wait_until="domcontentloaded")
                if "accounts/login" in (page.url or "").lower() or "login" in (page.url or "").lower():
                    return {"ok": False, "error": ERR_NOT_LOGGED_IN}

                # 2. Vào hội thoại
                if (thread_id or "").startswith("http"):
                    await page.goto(thread_id, timeout=timeout_ms,
                                    wait_until="domcontentloaded")
                else:
                    link_sel = self.selectors.get(
                        "conversation_link_selector",
                        "a[href*=\"/direct/t/\"]")
                    try:
                        links = await page.locator(link_sel).all()
                    except Exception as exc:
                        return {"ok": False,
                                "error": f"không đọc được hộp thư Instagram web: {exc}"}
                    target = None
                    for link in links:
                        try:
                            href = await link.get_attribute("href") or ""
                            label = await link.inner_text() or ""
                        except Exception:
                            continue
                        if _match_conversation(href, label, thread_id, participant):
                            target = link
                            break
                    if target is None:
                        return {
                            "ok": False,
                            "error": (
                                "Không thấy hội thoại có sẵn khớp "
                                f"'{thread_id}' trong hộp thư Instagram "
                                "web — chỉ gửi hội thoại đã có."
                            ),
                        }
                    await target.click(timeout=timeout_ms)
                    await page.wait_for_timeout(1000)

                # 3. Soạn tin
                composer = await self._first_matching(
                    page, list(self.selectors.get("composer_selectors", [])))
                if composer is None:
                    return {"ok": False,
                            "error": "không thấy ô soạn tin Instagram web — giao diện có thể đã đổi, "
                                     "cần cập nhật config/instagram_web_selectors.json"}
                await composer.click(timeout=timeout_ms)
                await page.keyboard.type(text)

                # 4. Bấm gửi hoặc Enter
                send_btn = await self._first_matching(
                    page, list(self.selectors.get("send_button_selectors", [])))
                if send_btn is not None:
                    try:
                        await send_btn.click(timeout=timeout_ms)
                    except Exception:
                        await page.keyboard.press("Enter")
                else:
                    await page.keyboard.press("Enter")

                # 5. Xác minh tin xuất hiện trong hội thoại
                for _ in range(10):
                    await page.wait_for_timeout(1000)
                    try:
                        content = await page.content()
                    except Exception:
                        content = ""
                    if text in content:
                        return {"ok": True, "sent": True,
                                "verified": True,
                                "thread_id": thread_id,
                                "transport": "instagram_web_browser"}
                return {"ok": False,
                        "error": "đã bấm gửi nhưng không xác minh được tin xuất hiện trong hội thoại "
                                 "Instagram web — không báo thành công giả"}
            finally:
                await context.close()


class InstagramBrowserBridge:
    """Bridge gửi DM Instagram qua web, có thể tiêm driver cho test."""

    def __init__(self, cfg=None, driver=None,
                 driver_factory: Optional[Callable[[], Any]] = None,
                 selectors: Optional[dict] = None):
        self.cfg = cfg
        self._driver = driver
        self._driver_factory = driver_factory
        self.selectors = _load_selectors(selectors)

    def base_url(self) -> str:
        raw = getattr(self.cfg, "instagram_web_base_url", None) if self.cfg else None
        return (raw or DEFAULT_BASE_URL).rstrip("/")

    def profile_dir(self) -> Optional[Path]:
        raw = getattr(self.cfg, "browser_profile_dir", None) if self.cfg else None
        return Path(raw) if raw else None

    def timeout_s(self) -> float:
        raw = getattr(self.cfg, "browser_timeout_s", None) if self.cfg else None
        try:
            return float(raw) if raw else 30.0
        except Exception:
            return 30.0

    def availability(self) -> tuple[bool, str]:
        """(True, '') nếu có thể gửi; ngược lại (False, lý do)."""
        if self._driver is not None or self._driver_factory is not None:
            return True, ""
        if self.profile_dir() is None:
            return False, ERR_NO_PROFILE
        if not _playwright_available():
            return False, ERR_NO_PLAYWRIGHT
        return True, ""

    def health_check(self) -> dict:
        ok, reason = self.availability()
        return {
            "ok": ok,
            "name": "instagram_browser_bridge",
            "configured": self.profile_dir() is not None,
            "profile_dir": (str(self.profile_dir())
                            if self.profile_dir() else None),
            "base_url": self.base_url(),
            "detail": reason or "Bridge Instagram web sẵn sàng.",
        }

    async def send_message(self, thread_id: str, text: str,
                           participant: Optional[str] = None) -> dict:
        """Gửi 1 tin qua web. Chỉ trả sent True khi đã xác minh."""
        thread_id = (thread_id or "").strip()
        text = text or ""
        if not thread_id and not participant:
            return {"ok": False,
                    "error": "Thiếu thread_id hoặc participant của hội thoại Instagram."}
        if not text.strip():
            return {"ok": False,
                    "error": "Thiếu nội dung tin nhắn (text)."}
        ok, reason = self.availability()
        if not ok:
            return {"ok": False, "error": reason, "unsupported": True}
        driver = self._driver
        if driver is None and self._driver_factory is not None:
            driver = self._driver_factory()
        if driver is None:
            profile = self.profile_dir()
            assert profile is not None
            driver = PlaywrightInstagramDriver(
                profile, self.base_url(), self.timeout_s(),
                self.selectors)
        try:
            res = driver.send(thread_id, text, participant)
            if asyncio.iscoroutine(res) or hasattr(res, "__await__"):
                res = await res
        except Exception as exc:
            return {"ok": False,
                    "error": f"browser bridge lỗi: {type(exc).__name__}: {exc}"}
        if not isinstance(res, dict):
            return {"ok": False,
                    "error": "browser bridge trả kết quả không hợp lệ — không báo thành công giả"}
        if res.get("ok") and not res.get("verified"):
            return {"ok": False,
                    "error": "browser bridge báo ok nhưng không xác minh được tin đã gửi — không báo thành công giả"}
        out = dict(res)
        out.setdefault("transport", "instagram_web_browser")
        return out

    async def send_reaction(self, thread_id: str, message_id: str,
                            reaction: str = "❤️") -> dict:
        """Thả reaction vào tin nhắn qua web. Chỉ trả ok khi có driver hỗ trợ."""
        thread_id = (thread_id or "").strip()
        message_id = (message_id or "").strip()
        if not thread_id or not message_id:
            return {"ok": False, "error": "Thiếu thread_id hoặc message_id để thả reaction."}
        ok, reason = self.availability()
        if not ok:
            return {"ok": False, "error": reason, "unsupported": True}
        driver = self._driver
        if driver is None and self._driver_factory is not None:
            driver = self._driver_factory()
        if driver is not None and hasattr(driver, "react"):
            try:
                res = driver.react(thread_id, message_id, reaction)
                if asyncio.iscoroutine(res) or hasattr(res, "__await__"):
                    res = await res
                if isinstance(res, dict):
                    out = dict(res)
                    out.setdefault("transport", "instagram_web_browser")
                    return out
            except Exception as exc:
                return {"ok": False, "error": f"browser bridge react lỗi: {exc}"}
        return {
            "ok": False,
            "unsupported": True,
            "error": "Instagram web driver chưa hỗ trợ tự động tìm và thả reaction emoji trên DOM. Không báo thành công giả.",
        }
