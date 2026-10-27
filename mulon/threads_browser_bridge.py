"""Bridge gửi DM Threads qua web — spike cho T-22.3.

Vấn đề cần giải quyết (ghi trong AGENT_TASKS.md mục T-22.3):
API Threads chính thức không mở endpoint DM, và connector
``threads_messages`` trước đây trả ``sent: True`` giả khi không có
session runner — tin chưa hề gửi đi. Đường thật duy nhất đã xác
định là browser bridge trên phiên Threads web đã đăng nhập của
người cài, theo mẫu bridge Zalo ở T-22.1 (một phiên làm việc duy
nhất, mở hộp thư thật -> vào hội thoại có sẵn -> gõ -> gửi).

Nguyên tắc của bridge này (không nới):
- Chỉ gửi vào hội thoại ĐÃ CÓ từ trước. Guard giới hạn cứng nằm ở
  ``ThreadsMessagesConnector`` và chạy TRƯỚC khi bridge được gọi;
  bridge không tự mở DM mới tới người lạ, không tự suy ra người
  nhận từ @handle.
- Không tự đăng nhập, không lưu password, không đọc cookie từ
  Vault để đăng nhập web. Đăng nhập web sống trong profile
  Chromium bền do người cài tự tạo trước (``BROWSER_PROFILE_DIR``)
  — bridge chỉ dùng lại profile đó. Chưa có profile thì báo
  ``ok: False`` rõ ràng, không báo thành công giả.
- Không bao giờ trả thành công khi chưa xác minh: sau khi bấm gửi,
  bridge phải thấy nội dung vừa gửi xuất hiện trong hội thoại thì
  mới trả ``sent: True``; không thấy thì trả lỗi.
- Selector của giao diện web Threads nằm ở
  ``config/threads_web_selectors.json`` (nạp qua ``datafiles``),
  không nằm chết trong code, để lần chạy thật đầu tiên trên tài
  khoản chủ có thể chỉnh selector mà không cần sửa code. File
  config vắng/hỏng thì dùng fallback trong module này và ghi log.
- Gửi tin là thao tác ghi: policy của connector đã ở nấc ``ask``
  (xem test policy cho ``threads_messages:send_message``), bridge
  không tự nới quyền đó.

Cách dùng trong connector (xem ``personal_connectors.py``):
``ThreadsMessagesConnector(..., browser_bridge=ThreadsBrowserBridge(cfg))``.
Khi không có session runner, connector gọi bridge thay cho nhánh
stub cũ; khi cả runner lẫn bridge đều vắng, connector trả lỗi
"chưa có đường gửi thật" thay vì ``sent: True`` giả.

Kiểm thử không cần Playwright hay tài khoản thật: ``driver`` có
thể tiêm vào (fake driver trong test chỉ ghi lại lệnh và trả kết
quả xác minh giả lập). Driver thật (``PlaywrightThreadsDriver``)
chỉ được dựng khi Playwright đã cài và profile đã cấu hình.
"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

logger = logging.getLogger("mulon.threads_browser_bridge")

# Endpoint chính thức của nhà cung cấp — được phép để trong code
# theo AGENTS.md mục 4 (không phải giá trị theo máy/người/phiên).
DEFAULT_BASE_URL = "https://www.threads.net"

# Fallback khi config/threads_web_selectors.json vắng/hỏng.
# Đây là điểm khởi đầu cho spike, không phải chân lý về giao diện
# Threads: lần chạy thật đầu tiên sẽ xác nhận/chỉnh lại qua file
# config, không sửa code.
DEFAULT_SELECTORS = {
    "inbox_path": "/messages",
    "conversation_link_selector": "a[href*=\"/messages/\"]",
    "composer_selectors": [
        "div[contenteditable=\"true\"]",
        "textarea",
        "[role=\"textbox\"]",
    ],
    "send_button_selectors": [
        "button[aria-label*=\"Send\"]",
        "button[aria-label*=\"Gửi\"]",
        "button[type=\"submit\"]",
    ],
}

# Lỗi trả về khi bridge không thể gửi — caller (connector) giữ
# nguyên chuỗi này để người dùng biết vì sao, không biến thành
# thành công giả.
ERR_NO_PROFILE = (
    "Threads DM chưa có đường gửi thật trên bản cài này: chưa cấu "
    "hình BROWSER_PROFILE_DIR đã đăng nhập Threads web. Hãy mở "
    "Threads web bằng profile đó, đăng nhập 1 lần, rồi gửi lại. "
    "Bot không tự đăng nhập và không lưu password."
)
ERR_NO_PLAYWRIGHT = (
    "Threads DM chưa gửi được: chưa cài Playwright/Chromium trên "
    "máy (pip install playwright && playwright install chromium)."
)
ERR_NOT_LOGGED_IN = (
    "Threads web trong profile này chưa đăng nhập (bị chuyển về "
    "trang đăng nhập) — hãy đăng nhập Threads web bằng profile đó "
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

        loaded = load_json_data("threads_web_selectors.json",
                                DEFAULT_SELECTORS)
        if isinstance(loaded, dict):
            data.update(loaded)
    except Exception as exc:  # pragma: no cover - degrade sạch
        logger.warning("nạp threads_web_selectors lỗi (%s) — dùng "
                       "fallback", exc)
    return data


def _playwright_available() -> bool:
    try:
        import playwright  # noqa: F401
        return True
    except Exception:
        return False


def _normalize_name(value: str) -> str:
    """Chuẩn hoá tên để khớp: bỏ @, hoa/thường, khoảng trắng,
    gạch dưới và ký tự không phải chữ/số ("Known Friend" khớp
    "known_friend" — tên hiển thị web khác username)."""
    import re as _re
    return _re.sub(r"[^a-z0-9]", "", (value or "").lower().lstrip("@"))


def _match_conversation(href: str, text: str, thread_id: str,
                        participant: Optional[str]) -> bool:
    """Khớp 1 link hội thoại với thread_id hoặc participant.

    Hàm thuần, test không cần Playwright: thread_id khớp khi xuất
    hiện trong href; participant khớp khi tên chuẩn hoá xuất hiện
    trong href chuẩn hoá hoặc text hiển thị chuẩn hoá.
    """
    href_l = (href or "").lower()
    tid = (thread_id or "").strip().lower()
    if tid and tid in href_l:
        return True
    if participant:
        name = _normalize_name(participant)
        if name and (name in _normalize_name(href)
                     or name in _normalize_name(text)):
            return True
    return False


class PlaywrightThreadsDriver:
    """Driver thật: 1 phiên Playwright duy nhất cho cả lượt gửi.

    Khác với BrowserWorker (mỗi click/fill mở page mới rồi đóng):
    gửi DM cần giữ nguyên 1 page qua các bước mở hộp thư -> chọn
    hội thoại -> soạn -> gửi -> xác minh, nên driver này giữ
    persistent context trong suốt lượt gửi rồi mới đóng.
    """

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
                # 1. Mở hộp thư web.
                inbox_url = f"{self.base_url}{self.selectors.get('inbox_path', '/messages')}"
                await page.goto(inbox_url, timeout=timeout_ms,
                                wait_until="domcontentloaded")
                if "login" in (page.url or "").lower():
                    return {"ok": False, "error": ERR_NOT_LOGGED_IN}
                # 2. Nếu thread_id chính là URL thì vào thẳng;
                #    nếu không, tìm link hội thoại trong hộp thư.
                if (thread_id or "").startswith("http"):
                    await page.goto(thread_id, timeout=timeout_ms,
                                    wait_until="domcontentloaded")
                else:
                    link_sel = self.selectors.get(
                        "conversation_link_selector",
                        "a[href*=\"/messages/\"]")
                    try:
                        links = await page.locator(link_sel).all()
                    except Exception as exc:
                        return {"ok": False,
                                "error": f"không đọc được hộp thư "
                                         f"Threads web: {exc}"}
                    target = None
                    for link in links:
                        try:
                            href = await link.get_attribute("href") or ""
                            label = await link.inner_text() or ""
                        except Exception:
                            continue
                        if _match_conversation(href, label, thread_id,
                                               participant):
                            target = link
                            break
                    if target is None:
                        return {
                            "ok": False,
                            "error": (
                                "Không thấy hội thoại có sẵn khớp "
                                f"'{thread_id}' trong hộp thư Threads "
                                "web — chỉ gửi hội thoại đã có, "
                                "không mở DM mới."
                            ),
                        }
                    await target.click(timeout=timeout_ms)
                    await page.wait_for_timeout(1000)
                # 3. Soạn tin: click ô soạn rồi gõ bằng bàn phím
                #    (ô contenteditable không dùng fill như input).
                composer = await self._first_matching(
                    page, list(self.selectors.get("composer_selectors", [])))
                if composer is None:
                    return {"ok": False,
                            "error": "không thấy ô soạn tin Threads "
                                     "web — giao diện có thể đã đổi, "
                                     "cần cập nhật "
                                     "config/threads_web_selectors.json"}
                await composer.click(timeout=timeout_ms)
                await page.keyboard.type(text)
                # 4. Bấm gửi.
                send_btn = await self._first_matching(
                    page, list(self.selectors.get("send_button_selectors", [])))
                if send_btn is None:
                    return {"ok": False,
                            "error": "không thấy nút gửi Threads web "
                                     "— giao diện có thể đã đổi, cần "
                                     "cập nhật "
                                     "config/threads_web_selectors.json"}
                await send_btn.click(timeout=timeout_ms)
                # 5. Xác minh: nội dung vừa gửi phải xuất hiện trong
                #    hội thoại. Không thấy thì KHÔNG báo thành công.
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
                                "transport": "threads_web_browser"}
                return {"ok": False,
                        "error": "đã bấm gửi nhưng không xác minh "
                                 "được tin xuất hiện trong hội thoại "
                                 "Threads web — không báo thành công giả"}
            finally:
                await context.close()


class ThreadsBrowserBridge:
    """Bridge gửi DM Threads qua web, có thể tiêm driver cho test."""

    def __init__(self, cfg=None, driver=None,
                 driver_factory: Optional[Callable[[], Any]] = None,
                 selectors: Optional[dict] = None):
        self.cfg = cfg
        self._driver = driver
        self._driver_factory = driver_factory
        self.selectors = _load_selectors(selectors)

    def base_url(self) -> str:
        raw = getattr(self.cfg, "threads_web_base_url", None) if self.cfg else None
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
            "name": "threads_browser_bridge",
            "configured": self.profile_dir() is not None,
            "profile_dir": (str(self.profile_dir())
                            if self.profile_dir() else None),
            "base_url": self.base_url(),
            "detail": reason or "Bridge Threads web sẵn sàng.",
        }

    async def send_message(self, thread_id: str, text: str,
                           participant: Optional[str] = None) -> dict:
        """Gửi 1 tin qua web. Chỉ trả sent True khi đã xác minh."""
        thread_id = (thread_id or "").strip()
        text = text or ""
        if not thread_id:
            return {"ok": False,
                    "error": "Thiếu thread_id của hội thoại đã có."}
        if not text.strip():
            return {"ok": False,
                    "error": "Thiếu nội dung tin nhắn (text)."}
        ok, reason = self.availability()
        if not ok:
            return {"ok": False, "error": reason,
                    "unsupported": True}
        driver = self._driver
        if driver is None and self._driver_factory is not None:
            driver = self._driver_factory()
        if driver is None:
            profile = self.profile_dir()
            assert profile is not None  # availability đã kiểm
            driver = PlaywrightThreadsDriver(
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
                    "error": "browser bridge trả kết quả không hợp lệ "
                             "— không báo thành công giả"}
        if res.get("ok") and not res.get("verified"):
            # Driver báo ok nhưng không xác minh: coi như chưa gửi.
            return {"ok": False,
                    "error": "browser bridge báo ok nhưng không xác "
                             "minh được tin đã gửi — không báo thành "
                             "công giả"}
        out = dict(res)
        out.setdefault("transport", "threads_web_browser")
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
                    out.setdefault("transport", "threads_web_browser")
                    return out
            except Exception as exc:
                return {"ok": False, "error": f"browser bridge react lỗi: {exc}"}
        return {
            "ok": False,
            "unsupported": True,
            "error": "Threads web driver chưa hỗ trợ tự động tìm và thả reaction emoji trên DOM. Không báo thành công giả.",
        }
