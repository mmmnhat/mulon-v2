"""Bề mặt Telegram (aiogram 3) — kênh duy nhất (thiết kế mục 16).

- Allowlist cứng theo ALLOWED_USER_ID: người khác ra lệnh không chạy.
- Gom tin liên tiếp (mục 16.1): debounce ~2.5s, cả chùm thành 1 lượt;
  tin tới trong lúc session đang bận bị giữ lại rồi drain/gộp vào
  lượt đang chờ lock hoặc lượt kế tiếp — không nứt lượt riêng lẻ.
- Ack bằng reaction thay tin trạng thái rác; streaming bằng edit tại chỗ.
- Session key theo (chat, topic): `agent:main:telegram:<loại>:<chat>:topic:<id>`.
- Group có người khác: chỉ đáp khi được mention/reply (GROUP_MENTION_ONLY).
- Lệnh lõi: /start /status /new /memory. Phase 6 thêm bề mặt group
  (mục 16): /setup_topics /topics, chat phụ bằng topic tự do
  (/chatphu /chatphu_list /dongchat /chatphu_dong /chatphu_mo),
  Feed (tự chạy theo lịch từ 1.4 —
  /feedbrief, /feedsources, reaction -> taste; /feed_now còn
  handler ẩn tương thích, không đăng ký menu), Ideas (/ideas
  /idea_do /idea_bo + reply
  'làm luôn'), duyệt note (/notes /note_ok /note_bo + reply
  'duyệt'/'bỏ'), Library (/library /trash_item /restore_item
  /share_item), /vault (form một lần qua DM), bộ nhớ có bề mặt
  (/forget + 'quên thật', /export_memory, import bằng file đính
  kèm), /quyen /approvals. Mọi tính năng khác đi bằng ngôn ngữ
  tự nhiên.
- Voice (Phase 4, mục 8.1): tin nhắn thoại -> STT (voice.py) ->
  bản đã hiểu ngữ đi tiếp vào agent như tin chữ. /voiceon /
  /voiceoff bật/tắt trả lời bằng giọng theo từng session.
"""

from __future__ import annotations

import asyncio
import html
import json
import logging
import os
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import deque
from pathlib import Path
from types import SimpleNamespace
from typing import Awaitable, Callable, Optional

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ChatType
from aiogram.types import (BotCommand, BusinessConnection, CallbackQuery, FSInputFile,
                           InlineKeyboardButton, InlineKeyboardMarkup,
                           InputMediaPhoto, Message, ReactionTypeEmoji)

from . import surfaces as surf
from .agent import clean_task_title
from .business import TelegramBusinessService
from .config import PROJECT_ROOT
from .datafiles import load_json_data
from .ideas import format_idea_card, parse_do_reply
from .proactivity import effective_enabled as heartbeat_effective
from .commands import (
    ALL_HANDLED_COMMANDS,
    BOT_COMMANDS,
    MENU_COMMANDS,
    format_help_text,
)
from .webapp_server import ActivityTracker, plain_step_label, \
    tool_action_label

logger = logging.getLogger("mulon.telegram")


def webapp_direct_link(cfg, bot_username: Optional[str],
                       start_param: str) -> Optional[str]:
    """Direct Link Mini App — đường mở app DUY NHẤT dùng cho cả
    group lẫn DM (nút inline kiểu web_app chỉ chạy trong DM nên
    không dùng). Thiếu WEBAPP_URL/WEBAPP_APP_NAME/username -> None
    để nơi gọi degrade về inline callback."""
    if not (getattr(cfg, "webapp_url", "") and
            getattr(cfg, "webapp_app_name", "") and bot_username):
        return None
    return (f"https://t.me/{bot_username}/{cfg.webapp_app_name}"
            f"?startapp={start_param}&mode=compact")

FlushFn = Callable[[str, str, list[str]], Awaitable[None]]


async def get_bot_display_name(memory, cfg) -> str:
    """Lấy tên hiển thị của bot: ưu tiên KV 'brand_bot_name' đã đổi qua Mini App,
    tiếp theo là cfg.bot_display_name, fallback 'Mulon'."""
    if memory is not None:
        try:
            val = await memory.kv_get("brand_bot_name")
            if val and isinstance(val, str) and val.strip():
                return val.strip()
        except Exception:
            pass
    return getattr(cfg, "bot_display_name", "Mulon") or "Mulon"


OPENERS = {
    "ê", "ê nè", "ê ní", "alo", "alo nè", "ơi", "ní ơi", "ad ơi", "bot ơi",
    "nè", "này", "chờ xíu", "từ từ", "đợi", "đợi xíu", "đợi tí", "hé lo",
    "hello", "hi", "tui có", "tui có cái", "có này", "cái này",
}


def _is_short_opener(text: str) -> bool:
    """True nếu tin nhắn là từ mở đầu/chào hỏi ngắn hoặc câu cụt (<= 2 từ),
    cần cửa sổ gom dài hơn một chút để người dùng kịp gõ tiếp câu sau."""
    stripped = (text or "").strip().lower()
    if not stripped:
        return True
    if stripped in OPENERS:
        return True
    words = stripped.split()
    if len(words) <= 2 and len(stripped) <= 20 and not any(c in stripped for c in "?!.:;"):
        return True
    return False


def _is_incomplete_fragment(text: str) -> bool:
    """True nếu tin nhắn chưa hoàn chỉnh (câu ngắn <= 4 từ không có dấu kết thúc
    ?!.; hoặc câu mở đầu, từ nối dở dang), người dùng gần như chắc chắn sẽ gõ tiếp."""
    stripped = (text or "").strip()
    if not stripped:
        return True
    if stripped[-1] in "?!.;":
        return False
    words = stripped.split()
    if len(words) <= 4 or len(stripped) <= 25:
        return True
    return False


def format_reply_context(message: Any, text: str) -> str:
    """Nếu message là reply tới một tin nhắn khác, đính kèm ngữ cảnh
    tin được trích dẫn (mục 16.1) để agent nắm được chủ đề/URL/dữ liệu."""
    replied = getattr(message, "reply_to_message", None)
    if replied is None:
        return text
    rep_content = (
        getattr(replied, "text", None)
        or getattr(replied, "caption", None)
        or ""
    ).strip()
    if not rep_content:
        doc = getattr(replied, "document", None)
        if doc and getattr(doc, "file_name", None):
            rep_content = f"[Tệp: {doc.file_name}]"
        elif getattr(replied, "photo", None):
            rep_content = "[Hình ảnh]"
    if not rep_content:
        return text
    from_user = getattr(replied, "from_user", None)
    sender = getattr(from_user, "first_name", None) if from_user else None
    sender = sender or "người dùng"
    prefix = f"[Đang trả lời tin của {sender}: \"{rep_content[:1000]}\"]"
    if text:
        return f"{prefix}\n{text}"
    return prefix


class MessageBatcher:
    """Gom các tin liên tiếp của cùng 1 session thành 1 lượt xử lý.

    Trạng thái bận theo key (mục 16.1): trong lúc một lượt của
    session đang chạy — hoặc một lượt khác đang chờ lock của
    session — tin mới chỉ bị GIỮ trong buffer, không hẹn giờ
    flush. Lượt chờ lock khi vào được lock sẽ drain cả buffer
    vào input của chính nó; lượt đang chạy xong thì release()
    kick một nhịp debounce mới cho phần tin còn lại. Nhờ vậy tin
    gõ trong lúc bot còn đang xử lý không bao giờ nứt thành
    nhiều lượt riêng lẻ chồng nhau.
    """

    def __init__(self, debounce_s: float, on_flush: FlushFn):
        self.debounce_s = debounce_s
        self.on_flush = on_flush
        self._buffers: dict[str, list[str]] = {}
        self._timers: dict[str, asyncio.Task] = {}
        self._busy: dict[str, int] = {}

    # ---- trạng thái bận (bề mặt gọi quanh mỗi lượt) ----
    def is_busy(self, key: str) -> bool:
        return self._busy.get(key, 0) > 0

    def mark_busy(self, key: str) -> None:
        """Một lượt bắt đầu (kể cả còn đang chờ lock): đếm +1.

        Đếm thay vì cờ bật/tắt vì lượt đang chạy và lượt đang
        chờ lock có thể chồng nhau — chỉ khi lượt cuối cùng nhả
        ra thì session mới hết bận thật sự.
        """
        self._busy[key] = self._busy.get(key, 0) + 1

    def _compute_delay(self, key: str, text: str) -> float:
        buf = self._buffers.get(key, [])
        is_fragment = _is_short_opener(text) or _is_incomplete_fragment(text)
        is_media = (text or "").strip().lower().startswith("[người dùng gửi")
        has_burst = len(buf) > 1

        if is_fragment or is_media:
            # Câu cụt, câu mở đầu, hoặc gửi ảnh: cần cửa sổ rộng (~6.0s) để user kịp gõ tiếp
            return self.debounce_s * 2.4
        elif has_burst:
            # Đang trong chuỗi tin liên tiếp: giữ cửa sổ gom vừa đủ (~4.0s)
            return self.debounce_s * 1.6
        else:
            # Câu hoàn chỉnh đơn lẻ: phản hồi nhanh (2.5s)
            return self.debounce_s

    def release(self, key: str) -> None:
        """Một lượt kết thúc: đếm -1. Khi đếm về 0 mà buffer
        còn tin bị giữ thì hẹn giờ flush theo debounce như
        bình thường, để các tin đó thành lượt kế tiếp (và vẫn
        kịp gộp với tin gõ ngay sau đó)."""
        left = self._busy.get(key, 0) - 1
        if left > 0:
            self._busy[key] = left
            return
        self._busy.pop(key, None)
        if self._buffers.get(key):
            last_msg = self._buffers[key][-1] if self._buffers[key] else ""
            delay = self._compute_delay(key, last_msg)
            self._schedule(key, delay)

    def has_pending(self, key: str) -> bool:
        """Kiểm tra xem session có tin đang trong bộ đệm chờ gộp hay không."""
        return bool(self._buffers.get(key) or (key in self._timers))

    def drain(self, key: str) -> list[str]:
        """Rút toàn bộ buffer (hủy timer tương ứng): tin tới
        trong lúc lượt chờ lock thuộc về chính lượt đó, không
        sinh lượt thừa."""
        timer = self._timers.pop(key, None)
        if timer is not None:
            timer.cancel()
        return self._buffers.pop(key, [])

    # ---- gom tin ----
    def _schedule(self, key: str, delay: Optional[float] = None) -> None:
        old = self._timers.get(key)
        if old is not None:
            old.cancel()
        wait_s = delay if delay is not None else self.debounce_s
        self._timers[key] = asyncio.create_task(self._delayed_flush(key, wait_s))

    async def add(self, key: str, text: str) -> None:
        self._buffers.setdefault(key, []).append(text)
        if self.is_busy(key):
            # Session đang bận: chỉ giữ tin, KHÔNG hẹn giờ.
            # Lượt chờ lock sẽ drain, hoặc release() của lượt
            # đang chạy sẽ kick nhịp debounce khi nó xong.
            return
        delay = self._compute_delay(key, text)
        self._schedule(key, delay)

    async def _delayed_flush(self, key: str, wait_s: Optional[float] = None) -> None:
        delay = wait_s if wait_s is not None else self.debounce_s
        try:
            await asyncio.sleep(delay)
        except asyncio.CancelledError:
            return
        parts = self._buffers.pop(key, [])
        self._timers.pop(key, None)
        if parts:
            await self.on_flush(key, "\n".join(parts), parts)

    async def flush_now(self, key: str) -> None:
        timer = self._timers.pop(key, None)
        if timer is not None:
            timer.cancel()
        parts = self._buffers.pop(key, [])
        if parts:
            await self.on_flush(key, "\n".join(parts), parts)


# ------------------------- chia tin an toàn HTML -------------------------

_VOID_TAGS = {"br", "hr"}
_KNOWN_TAGS = {"b", "strong", "i", "em", "u", "s", "code", "pre", "a",
               "blockquote", "tg-spoiler"}
_TAG_RE = re.compile(r"<(/?)([a-zA-Z][\w-]*)((?:\s[^<>]*)?)>")


def _open_tags(text: str) -> list[tuple[str, str]]:
    stack: list[tuple[str, str]] = []
    for m in _TAG_RE.finditer(text):
        closing, name, attrs = m.group(1), m.group(2).lower(), m.group(3) or ""
        if name in _VOID_TAGS:
            continue
        if closing:
            for i in range(len(stack) - 1, -1, -1):
                if stack[i][0] == name:
                    del stack[i:]
                    break
        else:
            stack.append((name, attrs))
    return stack


_CODE_OR_LINK_RE = re.compile(
    r"```([\s\S]*?)```|`([^`\n]+)`|\[([^\]]+)\]\((https?://[^\s)]+)\)")
_BOLD_RE = re.compile(r"\*\*([^*\n]+)\*\*")
_HEADING_RE = re.compile(r"^#{1,6}\s+(.+)$", flags=re.MULTILINE)
_HR_RE = re.compile(r"^[ \t]*([-*_][ \t]*){3,}$", flags=re.MULTILINE)


def clean_final_text(text: str) -> str:
    """Làm sạch văn bản đầu ra: loại bỏ các dòng phân cách thô (---, ***, ___) và chuẩn hóa dòng trống thừa (T-24.7)."""
    if not text:
        return ""
    cleaned = _HR_RE.sub("", text)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned


def safe_stream_markdown_to_html(text: str) -> str:
    """Chuyển đổi markdown đang stream thành HTML an toàn, tự đóng các thẻ dở dang để không bao giờ lộ markdown thô trên Telegram (T-24.7)."""
    if not text:
        return ""
    # Tự đóng code block dở dang (số lượng ``` lẻ)
    if text.count("```") % 2 == 1:
        text = text + "\n```"
    elif text.count("`") % 2 == 1:
        text = text + "`"
    if text.count("**") % 2 == 1:
        text = text + "**"
    html_text = md_to_html(text)
    chunks = chunk_html(html_text)
    return chunks[0] if chunks else ""


def md_to_html(text: str) -> str:
    """Converter Markdown -> HTML TỐI THIỂU và AN TOÀN cho câu
    trả lời của model (NC-1): code block/inline + link được trích
    ra và escape riêng trước, phần còn lại escape toàn bộ rồi mới
    áp **bold** và heading -> <b>. Nhờ escape trước, HTML thô do
    model (hoặc nội dung web) chèn vào không bao giờ thành thẻ
    thật — hết cảnh `**`/`##`/`[chữ](link)` hiện nguyên văn mà
    cũng không vỡ định dạng vì nội dung lạ."""
    stash: list[str] = []

    def _keep(m: re.Match) -> str:
        if m.group(1) is not None:
            part = "<pre>" + html.escape(m.group(1).strip("\n")) \
                + "</pre>"
        elif m.group(2) is not None:
            part = "<code>" + html.escape(m.group(2)) + "</code>"
        else:
            part = ('<a href="' + html.escape(m.group(4), quote=True)
                    + '">' + html.escape(m.group(3)) + "</a>")
        stash.append(part)
        return f"\x00{len(stash) - 1}\x00"

    out = _CODE_OR_LINK_RE.sub(_keep, text or "")
    out = _HR_RE.sub("", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    out = html.escape(out, quote=False)
    out = _BOLD_RE.sub(r"<b>\1</b>", out)
    out = _HEADING_RE.sub(r"\n<b>\1</b>\n", out)
    return re.sub("\x00(\\d+)\x00",
                  lambda m: stash[int(m.group(1))], out)


def chunk_html(text: str, max_chars: int = 3500) -> list[str]:
    """Chia text HTML thành các chunk <= max_chars, đóng/mở lại thẻ cân bằng."""
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    rest = text
    prefix = ""
    while rest:
        budget = max_chars - len(prefix)
        if len(rest) <= budget:
            chunks.append(prefix + rest)
            break
        window = rest[:budget]
        cut = max(window.rfind("\n\n"), window.rfind("\n"), window.rfind(" "))
        if cut < budget * 0.4:
            cut = budget
        piece, rest = rest[:cut], rest[cut:].lstrip("\n")
        stack = _open_tags(prefix + piece)
        closing = "".join(f"</{name}>" for name, _ in reversed(stack))
        chunks.append(prefix + piece + closing)
        prefix = "".join(
            f"<{name}{attrs}>" for name, attrs in stack if name in _KNOWN_TAGS
        )
    return [c for c in chunks if c.strip()]


def session_key_for(message: Message) -> str:
    chat = message.chat
    topic_id = 0
    if message.is_topic_message and message.message_thread_id:
        topic_id = message.message_thread_id
    if chat.type == ChatType.PRIVATE:
        return f"agent:main:telegram:dm:{chat.id}:topic:0"
    kind = "group" if chat.type in (ChatType.GROUP, ChatType.SUPERGROUP) else "channel"
    return f"agent:main:telegram:{kind}:{chat.id}:topic:{topic_id}"


def parse_session_key(session_key: str) -> tuple[Optional[int], Optional[int]]:
    """Tách (chat_id, thread_id) từ session_key của Telegram (chuẩn R15 định tuyến hội thoại)."""
    if not session_key or not session_key.startswith("agent:main:telegram:"):
        return None, None
    parts = session_key.split(":")
    if len(parts) >= 7 and parts[5] == "topic":
        try:
            cid = int(parts[4])
            tid = int(parts[6])
            return cid, (tid if tid > 0 else None)
        except ValueError:
            return None, None
    elif len(parts) >= 5:
        try:
            cid = int(parts[4])
            return cid, None
        except ValueError:
            return None, None
    return None, None


# --------------------- nghi lễ khởi tạo (mục 16.10) ---------------------

# Bộ câu hỏi dự phòng khi BOOTSTRAP.md không trích được mục
# "## Cần hỏi" — đủ 5 ý của nghi lễ, viết sẵn để /start không bao
# giờ gửi một tin chào cụt không có câu hỏi.
BOOTSTRAP_QUESTIONS_FALLBACK = (
    "1. Bạn muốn gọi agent là gì? Agent xưng hô với bạn thế nào?\n"
    "2. Bạn tên gì, muốn được gọi là gì? Múi giờ có đúng "
    "Asia/Ho_Chi_Minh?\n"
    "3. Bạn đang làm gì / quan tâm nhất chuyện gì thời gian này?\n"
    "4. Phong cách trả lời: ngắn tới mức nào, khi nào được tự làm "
    "luôn, khi nào phải hỏi trước?\n"
    "5. Có điều gì agent tuyệt đối không được tự làm không?"
)


def extract_bootstrap_questions(boot_text: str) -> str:
    """Trích đúng mục '## Cần hỏi' trong BOOTSTRAP.md.

    Chỉ phần câu hỏi mới được gửi cho user; phần mở đầu và các mục
    chỉ thị nội bộ ('## Sau khi hỏi xong'…) không bao giờ lọt vào
    tin nhắn. Không trích được thì trả '' để nơi gọi dùng bản
    dự phòng.
    """
    if not boot_text:
        return ""
    match = re.search(
        r"^##\s*Cần hỏi\s*$([\s\S]*?)(?=^##\s|\Z)",
        boot_text, flags=re.MULTILINE,
    )
    if not match:
        return ""
    return match.group(1).strip()


# ------------------------------- bot -------------------------------

def idea_card_keyboard(card_id: int) -> InlineKeyboardMarkup:
    """Bàn phím tương tác trực tiếp trên Thẻ ý tưởng: Làm luôn / Bỏ qua."""
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="Làm luôn", callback_data=f"idea:do:{card_id}"),
        InlineKeyboardButton(text="Bỏ qua", callback_data=f"idea:bo:{card_id}"),
    ]])


def pick_chat_reaction(text: str) -> str:
    """Chọn đúng 1 emoji reaction theo sắc thái tin nhắn (chuẩn Muse Tầng 1).
    - Tách khỏi nội dung trả lời, không thay thế câu trả lời, không đổi task state.
    - Sắc thái nhạy cảm/khó khăn -> phản ứng quan tâm (🤝/🙏), không đùa giỡn/ăn mừng.
    """
    t = text.lower().strip()
    # Nhạy cảm, khó khăn, tâm sự buồn -> quan tâm, đồng hành
    if any(w in t for w in ["buồn", "mệt", "áp lực", "stress", "nản", "chán", "thất bại", "khó quá", "bế tắc", "đau"]):
        return "🤝"
    # Cảm ơn, trân trọng
    if any(w in t for w in ["cảm ơn", "thank", "tks", "tuyệt", "hay quá", "quá đỉnh", "yêu", "mến"]):
        return "🙏"
    # Đồng ý, chốt việc, tán thành
    if any(w in t for w in ["ok", "oke", "được", "chốt", "duyệt", "triển", "nhất trí", "chuẩn"]):
        return "👌"
    # Thắc mắc, băn khoăn, tìm lỗi
    if any(w in t for w in ["sao ", "sao lại", "tại sao", "chưa được", "lỗi", "bug", "kỳ vậy", "đâu rồi"]):
        return "🤔"
    # Mặc định: tiếp nhận, đang xem
    return "👀"


_CANCELLATION_DATA = load_json_data("cancellation_markers.json", {})
_STOP_KEYWORDS = tuple(_CANCELLATION_DATA.get("stop_keywords", (
    "thôi", "thoi", "dừng", "dung", "dừng lại", "dung lai", "ngừng", "ngung",
    "stop", "cancel", "hủy", "huy", "bỏ qua", "bo qua", "đừng làm nữa",
    "dung lam nua", "khoan đã", "khoan da", "thôi khỏi", "thoi khoi", "đổi ý", "doi y",
    "/cancel", "/stop",
)))
_REDIRECT_MARKERS = tuple(_CANCELLATION_DATA.get("redirect_markers", (
    "thôi đừng", "thay vì vậy", "thay vì thế", "chuyển sang", "đổi sang",
    "làm cái này đi", "không làm cái đó nữa", "thôi khỏi", "đổi ý", "doi y",
)))
_CORRECTION_MARKERS = tuple(_CANCELLATION_DATA.get("correction_markers", (
    "á nhầm", "a nham", "nhầm rồi", "nham roi", "ý là", "y la", "không phải",
    "khong phai", "sửa lại", "sua lai", "nói nhầm", "noi nham", "nhầm á",
    "nham a", "nhầm rùi", "khoan nhầm", "nhầm nha"
)))


def is_cancellation_intent(text: str) -> tuple[bool, str]:
    """Phát hiện ý định huỷ / dừng / sửa ý / chuyển hướng lượt đang chạy.
    Trả về (is_cancel, remaining_text).
    """
    clean = (text or "").strip()
    lowered = clean.lower()
    if not lowered:
        return False, ""

    # 1. Chuyển hướng & sửa ý (redirect & correction markers): e.g. "á nhầm, bài hồi sáng á", "ý là làm B đi"
    for marker in (*_REDIRECT_MARKERS, *_CORRECTION_MARKERS):
        if marker in lowered:
            idx = lowered.find(marker)
            rest = clean[idx + len(marker):].strip()
            rest = re.sub(r"^(?:\b(?:nữa|mà|hãy|thì|là|ơi)\b|[,.:;\s])+", "", rest, flags=re.IGNORECASE).strip()
            return True, rest

    # 2. Xử lý từng dòng nếu tin nhắn nhiều dòng: e.g. dòng 2 có "thôi khỏi..." hoặc "đổi ý:..."
    lines = [ln.strip() for ln in clean.splitlines() if ln.strip()]
    if len(lines) > 1:
        for idx, line in enumerate(lines):
            sub_cancel, sub_rem = is_cancellation_intent(line)
            if sub_cancel:
                sub_rest = " ".join([sub_rem] + lines[idx + 1:]).strip() if sub_rem else " ".join(lines[idx + 1:]).strip()
                return True, sub_rest

    # 3. Dừng hẳn: so khớp từ khoá dừng ngắn hoặc câu bắt đầu bằng từ dừng
    tokens = lowered.split()
    first_two = " ".join(tokens[:2]) if len(tokens) >= 2 else (tokens[0] if tokens else "")
    first_word = tokens[0] if tokens else ""

    if clean.lower() in _STOP_KEYWORDS:
        return True, ""
    if first_two in _STOP_KEYWORDS or first_word in _STOP_KEYWORDS:
        if len(tokens) <= 5:
            return True, ""
        rest = " ".join(tokens[2:] if first_two in _STOP_KEYWORDS else tokens[1:]).strip()
        rest = re.sub(r"^(?:\b(?:đừng|không|hãy|nữa|khỏi)\b|[,.:;\s])+", "", rest, flags=re.IGNORECASE).strip()
        return True, rest

    return False, ""


class TelegramSurface:
    def __init__(self, cfg, agent, memory, dossier, consolidator=None,
                 voice=None, policy=None, surfaces=None, broker=None,
                 activity=None, marketplace=None):
        self.cfg = cfg
        self.agent = agent
        self.memory = memory
        self.dossier = dossier
        self.consolidator = consolidator
        # Marketplace 1.3.0: bề mặt trình thẻ duyệt operation +
        # chuyển thông báo đối chiếu sau restart cho owner. Gắn
        # presenter/notifier khi bot sẵn sàng trong run().
        self.marketplace = marketplace
        # ApprovalBroker (1.2.0): agent mở yêu cầu ở broker này;
        # bề mặt trình thẻ + đăng ký listener để TỰ GỠ thẻ và ghi
        # dòng lịch sử ngay khi có quyết định (kể cả hết hạn).
        self.broker = broker
        if broker is not None:
            broker.on_decided(self._on_approval_decided)
        # ActivityTracker dùng chung với Mini App server (header
        # trạng thái "đang xử lý / sẵn sàng").
        self.activity = activity or ActivityTracker()
        # VoiceService (mulon.voice) — None thì tính năng voice tắt
        # sạch: tin thoại được báo chưa sẵn sàng, /voiceon vô hiệu.
        self.voice = voice
        # Phase 6: PolicyEngine (cho /quyen) + bó dịch vụ bề mặt
        # {topics, feed, ideas, library, vault_server}. Thiếu dịch vụ
        # nào thì lệnh của bề mặt đó báo "chưa nối" sạch, không sập.
        self.policy = policy
        self.surfaces = surfaces or {}
        self.sidechats = surf.SideChatRegistry()
        self._voice_reply: set[str] = set()
        self.bot: Optional[Bot] = None
        self.dp = Dispatcher()
        self._locks: dict[str, asyncio.Lock] = {}
        self._sessions_meta: dict[str, Message] = {}
        self._active_tasks: dict[str, asyncio.Task] = {}
        self._seen_messages: set[tuple[int, int]] = set()
        self._seen_messages_order: deque[tuple[int, int]] = deque(maxlen=5000)
        self._recent_captured_vault: dict[str, float] = {}
        self._sent_approval_cards: set[str] = set()
        self._queued_placeholders: dict[str, Any] = {}
        self.batcher = MessageBatcher(cfg.debounce_seconds, self._on_batch)
        from .vault import VaultBroker
        self.vault_broker = VaultBroker()
        self._pending_vault_cards: dict[str, dict] = {}
        self._pending_vault_resumes: dict[str, dict] = {}
        if self.surfaces and "vault_store" in self.surfaces and self.surfaces["vault_store"] is not None:
            try:
                self.surfaces["vault_store"].on_captured(self.on_vault_secret_captured)
            except Exception as exc:
                logger.warning("đăng ký on_captured vault lỗi: %s", exc)
        # Telegram Business Chatbot (T-29)
        self.business_service = TelegramBusinessService(
            cfg=self.cfg, memory=self.memory, broker=self.broker, bot=self.bot
        )
        self._register_handlers()

    def _is_duplicate_message(self, message: Any) -> bool:
        """Kiểm tra tin nhắn trùng lặp từ Telegram (at-least-once delivery / retry sau sự cố)."""
        chat = getattr(message, "chat", None)
        msg_id = getattr(message, "message_id", None)
        if chat is None or msg_id is None:
            return False
        key = (int(getattr(chat, "id", 0)), int(msg_id))
        if key in self._seen_messages:
            logger.info("Bỏ qua tin nhắn trùng lặp từ Telegram: chat_id=%s, msg_id=%s", *key)
            return True
        self._seen_messages.add(key)
        self._seen_messages_order.append(key)
        if len(self._seen_messages) > 6000:
            self._seen_messages = set(self._seen_messages_order)
        return False

    # ---- chế độ trả lời bằng giọng (theo session) ----
    def voice_reply_enabled(self, key: str) -> bool:
        return key in self._voice_reply

    def set_voice_reply(self, key: str, on: bool) -> None:
        if on:
            self._voice_reply.add(key)
        else:
            self._voice_reply.discard(key)

    # ---- /start ----
    def start_message_text(self) -> str:
        """Nội dung trả lời /start.

        Dossier là snapshot đóng băng nên nạp lại từ đĩa trước khi
        xét: USER.md có thể đã đổi kể từ lúc boot. Lần chạy đầu
        (còn BOOTSTRAP_PENDING): câu chào + ĐÚNG phần câu hỏi của
        nghi lễ trích từ BOOTSTRAP.md — không dump cả file, không
        để lọt chỉ thị nội bộ; trích không được thì dùng bộ câu
        hỏi dự phòng trong code.
        """
        self.dossier.reload()
        if self.dossier.bootstrap_pending():
            boot = self.dossier.files.get("BOOTSTRAP.md", "")
            questions = extract_bootstrap_questions(boot) \
                or BOOTSTRAP_QUESTIONS_FALLBACK
            return (
                "Chào bạn, đây là lần chạy đầu tiên. Mình hỏi nhanh "
                "vài câu để dựng hồ sơ rồi làm việc luôn nhé.\n\n"
                + questions
            )
        identity = self.dossier.files.get("IDENTITY.md", "")
        return ("Mình đang chạy. Cứ nhắn việc bằng lời thường.\n\n"
                + identity[:1000])

    # ---- điều kiện đáp trong group ----
    def _should_respond(self, message: Message) -> bool:
        if message.chat.type == ChatType.PRIVATE:
            return True
        content = (message.text or message.caption or "").strip()
        if content.startswith("/"):
            return True
        if not self.cfg.group_mention_only:
            return True
        key = session_key_for(message)
        if self.batcher.has_pending(key):
            # Trong group: Nếu session này đã có tin chờ gộp (user đang gõ tiếp chuỗi ý), không bắt lặp @bot
            return True
        rep = getattr(message, "reply_to_message", None)
        rep_user = getattr(rep, "from_user", None) if rep else None
        if rep_user and self.bot is not None and getattr(rep_user, "id", None) == self.bot.id:
            return True
        username = getattr(self.bot, "_me_username", None) if self.bot else None
        if username and f"@{username}" in content:
            return True
        return False

    def _is_allowed(self, message: Message) -> bool:
        if not self.cfg.allowed_user_id and not getattr(self.cfg, "allowed_user_ids", ()):
            return False  # chưa cấu hình allowlist -> không phục vụ ai
        from_user = getattr(message, "from_user", None)
        if not from_user:
            return False
        if hasattr(self.cfg, "is_user_allowed"):
            return self.cfg.is_user_allowed(from_user.id)
        return bool(from_user.id == self.cfg.allowed_user_id)

    async def _send_typing(self, message: Any) -> None:
        """Gửi ngay tín hiệu 'đang nhập...' tới Telegram khi vừa nhận tin."""
        chat = getattr(message, "chat", None)
        if self.bot is None or chat is None:
            return
        chat_id = getattr(chat, "id", None)
        if chat_id is None:
            return
        try:
            kwargs: dict[str, Any] = {"chat_id": chat_id, "action": "typing"}
            if getattr(message, "is_topic_message", False) and getattr(message, "message_thread_id", None):
                kwargs["message_thread_id"] = message.message_thread_id
            await self.bot.send_chat_action(**kwargs)
        except Exception:
            pass

    async def _typing_loop(self, chat_id: int, thread_id: Optional[int], stop_ev: asyncio.Event) -> None:
        """Duy trì trạng thái 'đang nhập...' (typing) liên tục trong suốt lượt xử lý."""
        while not stop_ev.is_set():
            if self.bot is not None:
                try:
                    kwargs: dict[str, Any] = {"chat_id": chat_id, "action": "typing"}
                    if thread_id:
                        kwargs["message_thread_id"] = thread_id
                    await self.bot.send_chat_action(**kwargs)
                except Exception:
                    pass
            try:
                await asyncio.wait_for(stop_ev.wait(), timeout=4.0)
            except asyncio.TimeoutError:
                pass

    async def _notify_queued(self, key: str, message: Message) -> None:
        """Xác nhận xếp hàng ngay khi bot đang bận (T-24.7, X-06).

        Thả reaction ⏳ tức thì và gửi tin nhắn xếp hàng nếu session chưa có
        placeholder đang chờ. Tin nhắn này sẽ được tái sử dụng làm placeholder
        khi lượt xếp hàng bắt đầu, chỉnh sửa trực tiếp thành kết quả xử lý.
        """
        try:
            await message.react([ReactionTypeEmoji(emoji="⏳")])
        except Exception:
            pass
        if key not in self._queued_placeholders:
            try:
                msg = await message.answer(
                    "⏳ <i>Đã nhận, đang xếp hàng (chờ hoàn thành lượt trước)...</i>",
                    parse_mode="HTML",
                )
                self._queued_placeholders[key] = msg
            except Exception as e:
                logger.debug("Không thể gửi tin báo xếp hàng: %s", e)

    # ---- luồng xử lý 1 lượt ----
    async def _on_batch(self, key: str, joined: str, parts: list[str]) -> None:
        anchor = self._sessions_meta.get(key)
        if anchor is None:
            return
        # Đánh dấu bận NGAY, trước cả khi chờ lock: từ đây tới
        # lúc lượt xong, batcher chỉ giữ tin mới trong buffer,
        # không hẹn giờ flush thành lượt riêng (vá 1.1.1, mục
        # 16.1). try/finally bảo đảm luôn nhả bận kể cả khi
        # agent.handle ném lỗi — session không kẹt bận vĩnh viễn.
        self.batcher.mark_busy(key)
        self._active_tasks[key] = asyncio.current_task()
        chat = getattr(anchor, "chat", None)
        chat_id = getattr(chat, "id", None)
        thread_id = None
        if getattr(anchor, "is_topic_message", False):
            thread_id = getattr(anchor, "message_thread_id", None)

        typing_stop = asyncio.Event()
        typing_task = None
        if chat_id is not None and self.bot is not None:
            typing_task = asyncio.create_task(
                self._typing_loop(chat_id, thread_id, typing_stop)
            )
        try:
            lock = self._locks.setdefault(key, asyncio.Lock())
            placeholder = self._queued_placeholders.pop(key, None)
            if placeholder is None and lock.locked():
                # X-06: Tín hiệu hàng đợi khi kẹt lượt trước
                try:
                    placeholder = await anchor.answer("⏳ <i>Đang xếp hàng (chờ hoàn thành lượt trước)...</i>", parse_mode="HTML")
                except Exception:
                    placeholder = None

            async with lock:  # mỗi session tối đa 1 lượt active (mục 3.3)
                # Drain: tin tới trong lúc lượt này chờ lock
                # thuộc về chính lượt này — gộp vào input theo
                # đúng thứ tự, không sinh lượt thừa.
                extra = self.batcher.drain(key)
                if extra:
                    parts = parts + extra
                    joined = "\n".join(parts)
                try:
                    chosen_emoji = pick_chat_reaction(joined)
                    await anchor.react([ReactionTypeEmoji(emoji=chosen_emoji)])
                except Exception:
                    pass
                state = {"shown": "", "last_edit": 0.0}

                async def on_delta(piece: str) -> None:
                    state["shown"] += piece
                    now = asyncio.get_event_loop().time()
                    # T-24.7 (X-06/X-07): Hết lóe markdown thô:
                    # - Không edit ở độ dài quá ngắn (<50 ký tự) để câu trả lời ngắn đi thẳng một nhịp vào HTML hoàn chỉnh.
                    # - Khi stream (>= 50 ký tự, cách nhau >= 1.2s): luôn render qua safe_stream_markdown_to_html
                    #   kèm parse_mode="HTML" để không bao giờ lộ markdown thô (** hoặc ###) trên màn hình Telegram.
                    if placeholder is not None and len(state["shown"]) >= 50 and now - state["last_edit"] > 1.2:
                        state["last_edit"] = now
                        formatted_delta = safe_stream_markdown_to_html(state["shown"])
                        if formatted_delta:
                            try:
                                await placeholder.edit_text(formatted_delta, parse_mode="HTML")
                            except Exception as edit_err:
                                err_str = str(edit_err).lower()
                                if "message is not modified" not in err_str:
                                    logger.debug("on_delta edit error: %s", edit_err)

                if placeholder is not None:
                    try:
                        await placeholder.edit_text("⏳ <i>Đang xử lý...</i>", parse_mode="HTML")
                    except Exception:
                        pass
                else:
                    try:
                        placeholder = await anchor.answer("…")
                    except Exception:
                        placeholder = None
                # Ghi trạng thái nghi lễ TRƯỚC lượt: nếu lượt này bắt
                # đầu khi BOOTSTRAP còn chờ, agent có thể vừa hoàn tất
                # nghi lễ trên đĩa — cuối lượt phải nạp lại snapshot.
                was_bootstrap_pending = bool(
                    self.dossier is not None
                    and self.dossier.bootstrap_pending()
                )
                # Tiến trình trực quan chuẩn Muse: hiển thị các bước đã xong (✓)
                # và bước đang chạy (⏳) trên placeholder tin nhắn Telegram.
                # Chống flood: tối đa 1 edit/1.2s và không đè lên text đang stream.
                progress_steps: list[dict[str, str]] = []
                status_state = {"last": 0.0}

                async def _render_progress() -> None:
                    if placeholder is None or state["shown"]:
                        return
                    now = asyncio.get_event_loop().time()
                    if now - status_state["last"] < 1.2:
                        return
                    status_state["last"] = now
                    lines = ["<b>⏳ Đang xử lý:</b>"]
                    for step in progress_steps[-4:]:
                        icon = step.get("icon", "•")
                        stext = html.escape(step.get("text", ""))
                        lines.append(f"{icon} {stext}")
                    msg_text = "\n".join(lines)
                    try:
                        await placeholder.edit_text(msg_text, parse_mode="HTML")
                    except Exception:
                        pass

                async def on_event(kind: str, payload: dict) -> None:
                    label = plain_step_label(kind, payload)
                    if label:
                        self.activity.set_step(label)
                    if kind == "approval_requested":
                        thread_id = None
                        if getattr(anchor, "is_topic_message", False):
                            thread_id = anchor.message_thread_id
                        await self.send_approval_card(
                            anchor.chat.id, thread_id, payload)
                    elif kind == "task_start":
                        t_id = payload.get("task_id")
                        t_title = payload.get("title") or "Lập kế hoạch tác vụ"
                        progress_steps.append({"icon": "✓", "text": f"Kế hoạch: {t_title[:45]}"})
                        await _render_progress()
                        if t_id and self.activity:
                            cur_t = self._active_tasks.get(key) or asyncio.current_task()
                            self.activity.register_task(
                                t_id, cur_t, title=t_title, session_key=key,
                                current_step="Đang lập kế hoạch", kind="main"
                            )
                    elif kind == "tool_start":
                        t_id = payload.get("task_id")
                        step_t = payload.get("step_title") or label or f"Chạy {payload.get('tool', '')}"
                        if t_id and step_t and self.activity:
                            self.activity.update_task_step(t_id, step_t)
                        if payload.get("tool") == "request_vault_secret":
                            v_args = payload.get("args") or {}
                            v_lbl = str(v_args.get("label") or "").strip()
                            if v_lbl:
                                self._pending_vault_resumes[v_lbl] = {
                                    "chat_id": chat_id,
                                    "thread_id": thread_id,
                                    "session_key": key,
                                    "user_text": joined,
                                }
                        progress_steps.append({"icon": "⏳", "text": label or f"Chạy {payload.get('tool', '')}"})
                        await _render_progress()
                    elif kind == "tool_done":
                        step_t = payload.get("step_title") or label or "Đã xong bước"
                        t_id = payload.get("task_id")
                        if t_id and self.activity:
                            self.activity.update_task_step(t_id, f"Hoàn thành: {step_t}")
                        updated = False
                        for s in reversed(progress_steps):
                            if s.get("icon") == "⏳":
                                s["icon"] = "✓"
                                s["text"] = step_t
                                updated = True
                                break
                        if not updated:
                            progress_steps.append({"icon": "✓", "text": step_t})
                        await _render_progress()
                    elif kind == "verify":
                        t_id = payload.get("task_id")
                        if t_id and self.activity:
                            self.activity.update_task_step(t_id, "Kiểm chứng kết quả")
                        progress_steps.append({"icon": "⏳", "text": "Kiểm chứng kết quả..."})
                        await _render_progress()
                    elif kind in ("task_done", "turn_done"):
                        t_id = payload.get("task_id")
                        if t_id and self.activity:
                            self.activity.unregister_task(t_id)
                    elif label:
                        progress_steps.append({"icon": "⏳", "text": label})
                        await _render_progress()

                self.activity.start_turn(key, clean_task_title(joined))
                try:
                    result = await self.agent.handle(
                        key, joined, on_delta=on_delta,
                        on_event=on_event)
                except asyncio.CancelledError:
                    logger.info("Lượt xử lý %s đã bị hủy theo yêu cầu user", key)
                    try:
                        await self.memory.cancel_turn(key, reason="user_cancelled")
                    except Exception:
                        pass
                    if self.activity:
                        self.activity.stop_session_tasks(key)
                    if placeholder is not None:
                        try:
                            await placeholder.edit_text("<i>Đã dừng tác vụ theo yêu cầu.</i>", parse_mode="HTML")
                        except Exception:
                            pass
                    else:
                        try:
                            await anchor.answer("<i>Đã dừng tác vụ theo yêu cầu.</i>", parse_mode="HTML")
                        except Exception:
                            pass
                    raise
                except Exception as exc:
                    # HT-1: lỗi ở task path (gateway/proxy sập
                    # giữa lượt) KHÔNG được treo placeholder "…"
                    # vô hạn — thay bằng tin lỗi lời thường, ghi
                    # trajectory turn_error, chi tiết ở log.
                    logger.warning("lượt lỗi (đã báo user): %s", exc)
                    try:
                        await self.memory.log_trajectory(
                            key, "turn_error",
                            {"error": f"{type(exc).__name__}: "
                                      f"{exc}"[:500]})
                    except Exception:
                        pass
                    result = SimpleNamespace(
                        text="Đường gọi model đang lỗi, việc chưa "
                             "chạy xong — anh thử lại sau ít phút.")
                final = clean_final_text(result.text or "(không có nội dung)")
                chunks = chunk_html(md_to_html(final))
                sent_chunks = False
                try:
                    if placeholder is not None:
                        try:
                            await placeholder.edit_text(chunks[0], parse_mode="HTML")
                        except Exception as edit_err:
                            err_str = str(edit_err).lower()
                            if "message is not modified" in err_str:
                                # Placeholder đã có nội dung này (từ on_delta), không phải lỗi
                                pass
                            else:
                                # Thử lại với HTML escape trên placeholder thay vì gửi tin mới
                                escaped_first = chunk_html(html.escape(final))[0]
                                try:
                                    await placeholder.edit_text(escaped_first, parse_mode="HTML")
                                except Exception as esc_err:
                                    if "message is not modified" not in str(esc_err).lower():
                                        raise edit_err
                        sent_chunks = True
                        for extra in chunks[1:]:
                            await anchor.answer(extra, parse_mode="HTML")
                    else:
                        for chunk in chunks:
                            await anchor.answer(chunk, parse_mode="HTML")
                        sent_chunks = True
                except Exception as exc:
                    # Chỉ gửi tin mới nếu placeholder chưa từng được sửa thành công
                    if not sent_chunks:
                        for chunk in chunk_html(html.escape(final)):
                            await anchor.answer(chunk, parse_mode="HTML")
                    else:
                        logger.warning("Lỗi gửi chunk bổ sung sau khi placeholder đã cập nhật: %s", exc)
                await self._maybe_send_media_outputs(anchor, final)
                await self._maybe_send_voice(key, anchor, final)
                if was_bootstrap_pending and self.dossier is not None:
                    # Lượt vừa rồi có thể đã gỡ BOOTSTRAP_PENDING khỏi
                    # USER.md trên đĩa: nạp lại để /start và ngữ cảnh
                    # các lượt sau thấy trạng thái mới, khỏi chờ restart.
                    # Đây là cùng 1 instance Dossier mà ContextEngine
                    # đang giữ (main.build_system truyền chung).
                    try:
                        self.dossier.reload()
                    except Exception as exc:
                        logger.warning(
                            "nạp lại dossier sau lượt bootstrap lỗi: %s",
                            exc)
        finally:
            self._queued_placeholders.pop(key, None)
            self._active_tasks.pop(key, None)
            typing_stop.set()
            if typing_task is not None:
                typing_task.cancel()
            # Luôn nhả bận + kick nhịp debounce cho phần tin bị
            # giữ (nếu còn) — chạy cả khi lượt xử lý ném lỗi.
            self.activity.end_turn()
            self.batcher.release(key)

    # ---- media / photo / video / audio / document output ----
    async def _maybe_send_media_outputs(self, anchor: Message, final_text: str) -> None:
        """Tự động phát hiện nếu trong câu trả lời có file local (ảnh, video, audio, voice, tài liệu)
        hoặc link ảnh trực tiếp để gửi nội dung thật vào Telegram theo đúng phương thức.
        File vượt quá giới hạn hoặc định dạng lỗi được degrade báo rõ, không nuốt im lặng."""
        if not final_text:
            return
        from .library import ICON_MAP, kind_of, _denied_reason

        # 1. Tìm đường dẫn file local
        candidate_paths = re.findall(
            r"(?:/[a-zA-Z0-9_\-\./]+|\b(?:[a-zA-Z0-9_\-\.]+/)*[a-zA-Z0-9_\-]+\.(?:png|jpg|jpeg|webp|gif|mp4|mov|avi|webm|mkv|ogg|mp3|wav|m4a|flac|aac|pdf|docx|xlsx|csv|txt|md|json|zip|tar\.gz))\b",
            final_text, re.IGNORECASE,
        )
        candidate_paths = list(dict.fromkeys(candidate_paths))
        sent_any = False
        max_bytes = getattr(self.cfg, "telegram_max_file_size_bytes", 52428800)

        for p in candidate_paths:
            p_clean = p.rstrip(".,;:)\"'>]`")
            candidates = [
                Path(p_clean),
                Path(self.cfg.workspace_dir) / p_clean,
                Path(self.cfg.workspace_dir) / "images" / Path(p_clean).name,
                Path(self.cfg.workspace_dir) / "uploads" / Path(p_clean).name,
                Path(self.cfg.workspace_dir) / "media" / Path(p_clean).name,
                Path(self.cfg.workspace_dir) / Path(p_clean).name,
            ]
            for cand in candidates:
                if cand.is_file() and cand.stat().st_size > 0:
                    if _denied_reason(cand):
                        continue
                    ext = cand.suffix.lower()
                    caption = cand.name

                    # Kiểm tra kích thước tối đa của Telegram Bot API (mặc định 50MB)
                    if cand.stat().st_size > max_bytes:
                        size_mb = cand.stat().st_size / (1024 * 1024)
                        limit_mb = max_bytes // (1024 * 1024)
                        await anchor.answer(
                            f"Tệp <code>{html.escape(cand.name)}</code> ({size_mb:.1f} MB) vượt quá giới hạn "
                            f"{limit_mb}MB của Telegram Bot API. "
                            f"Bạn có thể truy cập tệp trực tiếp tại: <code>{html.escape(str(cand))}</code> hoặc qua Mini App Thư viện.",
                            parse_mode="HTML",
                        )
                        sent_any = True
                        break

                    try:
                        if ext in (".png", ".jpg", ".jpeg", ".webp", ".gif"):
                            await anchor.answer_photo(FSInputFile(str(cand)), caption=caption)
                            await self._post_media_to_library("photo", FSInputFile(str(cand)), f"[Thư viện] {cand.name}", chat_id=anchor.chat.id)
                        elif ext in (".mp4", ".mov", ".avi", ".webm", ".mkv"):
                            await anchor.answer_video(FSInputFile(str(cand)), caption=caption)
                            await self._post_media_to_library("video", FSInputFile(str(cand)), f"[Thư viện] {cand.name}", chat_id=anchor.chat.id)
                        elif ext in (".ogg",):
                            await anchor.answer_voice(FSInputFile(str(cand)), caption=caption)
                            await self._post_media_to_library("audio", FSInputFile(str(cand)), f"[Thư viện] {cand.name}", chat_id=anchor.chat.id)
                        elif ext in (".mp3", ".wav", ".m4a", ".flac", ".aac"):
                            await anchor.answer_audio(FSInputFile(str(cand)), caption=caption)
                            await self._post_media_to_library("audio", FSInputFile(str(cand)), f"[Thư viện] {cand.name}", chat_id=anchor.chat.id)
                        else:
                            await anchor.answer_document(FSInputFile(str(cand)), caption=caption)
                            await self._post_media_to_library("document", FSInputFile(str(cand)), f"[Thư viện] {cand.name}", chat_id=anchor.chat.id)

                        lib = self._svc("library")
                        if lib is not None:
                            await lib.index_file(cand, source="agent", caption=caption)
                        sent_any = True
                        break
                    except Exception as exc:
                        logger.warning("gửi tệp local qua telegram lỗi: %s", exc)
                        await anchor.answer(
                            f"Không thể gửi tệp <code>{html.escape(cand.name)}</code> qua Telegram ({html.escape(str(exc))}). "
                            f"Tệp đã được lưu an toàn tại: <code>{html.escape(str(cand))}</code>.",
                            parse_mode="HTML",
                        )
                        sent_any = True
                        break
            if sent_any:
                break

        if not sent_any:
            # 2. Tìm link URL ảnh
            urls = re.findall(r"https?://[^\s\)\]<>\"]+", final_text)
            for u in urls:
                clean_u = u.rstrip(".,;:\"'")
                is_img_url = (
                    any(clean_u.lower().endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp"))
                    or "platform-outputs.agnes-ai.space" in clean_u
                )
                if is_img_url:
                    try:
                        await anchor.answer_photo(clean_u, caption="Ảnh mới từ AI / Web")
                        await self._post_photo_to_library(
                            clean_u, "[Thư viện] Ảnh mới từ AI / Web",
                            chat_id=anchor.chat.id,
                        )
                        break
                    except Exception as exc:
                        logger.warning("gửi ảnh url qua telegram lỗi: %s", exc)

    async def _maybe_send_photo(self, anchor: Message, final_text: str) -> None:
        """Alias tương thích ngược."""
        await self._maybe_send_media_outputs(anchor, final_text)

    # ---- voice (Phase 4, mục 8.1) ----
    async def _maybe_send_voice(self, key: str, anchor: Message,
                                final_text: str) -> None:
        """Trả lời thêm bằng giọng khi session đang bật /voiceon.

        Lỗi TTS/gửi voice KHÔNG bao giờ làm hỏng lượt — text đã gửi
        xong trước đó rồi.
        """
        if self.voice is None or not self.voice_reply_enabled(key):
            return
        plain = re.sub(r"<[^>]+>", "", final_text).strip()
        if not plain:
            return
        try:
            out = await self.voice.speak_to_file(plain)
            if out.get("ok"):
                await anchor.answer_voice(FSInputFile(out["path"]))
            else:
                logger.warning("TTS lỗi (đã trả text, bỏ qua voice): %s",
                               out.get("error"))
        except Exception as exc:
            logger.warning("gửi voice trả lời lỗi (bỏ qua): %s", exc)

    def _should_respond_voice(self, message: Message) -> bool:
        """Tin thoại không có text để soi mention: DM thì đáp; group
        thì đáp khi reply đúng bot hoặc GROUP_MENTION_ONLY tắt."""
        if message.chat.type == ChatType.PRIVATE:
            return True
        if not self.cfg.group_mention_only:
            return True
        rep = getattr(message, "reply_to_message", None)
        rep_user = getattr(rep, "from_user", None) if rep else None
        return bool(
            rep_user
            and self.bot is not None
            and getattr(rep_user, "id", None) == self.bot.id
        )

    async def _process_voice_message(self, message: Message) -> None:
        """Tải voice -> STT -> bản đã hiểu ngữ vào batcher như tin chữ."""
        key = session_key_for(message)
        if self.voice is None or self.bot is None:
            await message.answer(
                "Tính năng nghe voice chưa sẵn sàng trên bản chạy này.")
            return
        try:
            tg_file = await self.bot.get_file(message.voice.file_id)
            in_dir = Path(self.cfg.workspace_dir) / "voice_in"
            in_dir.mkdir(parents=True, exist_ok=True)
            local = in_dir / f"{message.voice.file_unique_id}.ogg"
            await self.bot.download_file(
                tg_file.file_path, destination=str(local))
            lib = self._svc("library")
            if lib is not None and local.is_file():
                try:
                    await lib.index_file(local, source="user_upload", caption="Tin nhắn thoại Telegram")
                except Exception:
                    pass
        except Exception as exc:
            logger.warning("tải voice lỗi: %s", exc)
            await message.answer("Mình không tải được tin nhắn thoại này.")
            return
        result = await self.voice.transcribe_file(local)
        if not result.get("ok"):
            if result.get("unavailable"):
                await message.answer(
                    "Máy này chưa cài nhận diện giọng nói "
                    "(faster-whisper) nên mình chưa nghe được voice.")
            else:
                await message.answer(
                    "Mình chưa nghe rõ tin nhắn thoại này, "
                    "bạn nhắn chữ giúp mình nhé.")
            return
        text = (result.get("text_da_hieu")
                or result.get("text_tho") or "").strip()
        if not text:
            await message.answer(
                "Tin nhắn thoại này mình nghe ra trống — "
                "bạn thử lại giúp mình.")
            return
        self._sessions_meta[key] = message
        text = format_reply_context(message, text)
        if self.batcher.is_busy(key):
            await self._notify_queued(key, message)
        await self.batcher.add(key, text)

    # ---- Phase 6: helpers cho bề mặt group ----
    def _svc(self, name: str):
        return self.surfaces.get(name)

    async def _topic_thread(self, message: Message,
                            surface_key: str) -> Optional[int]:
        """Thread đích của 1 bề mặt trong chat hiện tại (theo map
        đã setup); chưa setup -> thread của tin hiện tại (hoặc DM)."""
        topics = self._svc("topics")
        if topics is not None and self.memory is not None:
            try:
                mapping = await topics.get_map(self.memory,
                                               message.chat.id)
                tid = topics.topic_for(mapping, surface_key)
                if tid:
                    return tid
            except Exception as exc:
                logger.warning("đọc map topic lỗi: %s", exc)
        if getattr(message, "is_topic_message", False):
            return message.message_thread_id
        return None

    # ---- 1.2.0: Mini App + thẻ duyệt tự gỡ ----
    def _bot_username(self) -> Optional[str]:
        if self.bot is None:
            return None
        return getattr(self.bot, "_me_username", None) \
            or getattr(self.bot, "username", None)

    def menu_payload(self) -> tuple[str, Optional[InlineKeyboardMarkup]]:
        """Nội dung /menu: có Direct Link -> tin teaser + nút mở
        app; thiếu cấu hình -> hướng dẫn 3 dòng + lệnh chính."""
        link = webapp_direct_link(self.cfg, self._bot_username(),
                                  "panel")
        if link:
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text="Mở bảng điều khiển",
                                     url=link)]])
            return (
                "<b>Bảng điều khiển Mulon</b>\n"
                "Tiến trình, phê duyệt, lịch, hồ sơ, kết nối, vault "
                "và quyền — tất cả ở trong app. Chạm nút để mở.",
                kb)
        return (
            "Bảng điều khiển (Mini App) chưa mở được vì thiếu "
            "cấu hình. Cần 3 bước:\n"
            "1. Đặt WEBAPP_URL (URL HTTPS, vd tunnel cloudflared / "
            "tailscale funnel về 127.0.0.1:" +
            str(getattr(self.cfg, "webapp_port", 8320)) +
            ") và WEBAPP_APP_NAME trong .env.\n"
            "2. BotFather: /myapps -> tạo app, short name = "
            "WEBAPP_APP_NAME, Web App URL = WEBAPP_URL.\n"
            "3. Khởi động lại bot.\n\n"
            "Trong lúc chờ, lệnh chính vẫn dùng được: /status "
            "/memory /quyen /approvals /topics /chatphu",
            None)

    def approval_keyboard(self, approval_id: str,
                          rememberable: bool = True
                          ) -> InlineKeyboardMarkup:
        """Bàn phím thẻ duyệt: hàng quyết định INLINE là đường
        chính (Duyệt / Chặn / Duyệt và nhớ — quyết ngay tại thẻ,
        không cần app). Có WEBAPP_URL thì thêm MỘT nút phụ hàng
        dưới "Xem chi tiết" (Direct Link vào màn Phê duyệt).
        ``rememberable=False`` (1.3.0: duyệt operation marketplace)
        -> CHỈ Duyệt / Chặn: không có "duyệt và nhớ" cho thao tác
        đổi hạ tầng."""
        buttons = [
            InlineKeyboardButton(
                text="Duyệt",
                callback_data=f"appr:1:{approval_id}"),
            InlineKeyboardButton(
                text="Chặn",
                callback_data=f"appr:0:{approval_id}"),
        ]
        if rememberable:
            buttons.append(InlineKeyboardButton(
                text="Duyệt và nhớ",
                callback_data=f"appr:2:{approval_id}"))
        rows: list[list[InlineKeyboardButton]] = [buttons]
        link = webapp_direct_link(self.cfg, self._bot_username(),
                                  f"approve_{approval_id}")
        if link:
            rows.append([InlineKeyboardButton(
                text="Xem chi tiết", url=link)])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    async def _resolve_group_chat_id(self, preferred: Optional[int] = None) -> int:
        """Tìm group chat forum đích để gửi vào các topic bề mặt."""
        if preferred:
            return preferred
        if self.memory is not None:
            try:
                raw = await self.memory.kv_get("feed:group_chat_id")
                if raw:
                    return int(raw)
                for k in await self.memory.kv_keys("topics:"):
                    try:
                        return int(k.split(":", 1)[1])
                    except Exception:
                        continue
            except Exception:
                pass
        return self.cfg.allowed_user_id

    async def publish_ideas(self, cards: list[dict], chat_id: Optional[int] = None) -> None:
        """Tự động đăng các thẻ ý tưởng mới vào topic Ideas kèm nút tương tác."""
        if not cards or self.bot is None:
            return
        cid = await self._resolve_group_chat_id(chat_id)
        if not cid:
            return
        from .ideas import format_idea_card
        topics = self._svc("topics")
        thread_id = None
        if topics is not None and self.memory is not None:
            try:
                mapping = await topics.get_map(self.memory, cid)
                thread_id = topics.topic_for(mapping, "ideas")
            except Exception:
                pass
        kwargs: dict[str, Any] = {}
        if thread_id:
            kwargs["message_thread_id"] = thread_id
        for card in cards:
            try:
                await self.bot.send_message(
                    cid,
                    format_idea_card(card),
                    reply_markup=idea_card_keyboard(card["id"]),
                    **kwargs,
                )
            except Exception as exc:
                logger.warning("gửi thẻ ý tưởng tự động lỗi: %s", exc)

    async def _post_media_to_library(self, media_type: str, media_input: Any,
                                     caption: str, chat_id: Optional[int] = None) -> None:
        """Tự động gửi media mới vào topic Library trong group forum nếu có."""
        if self.bot is None:
            return
        cid = await self._resolve_group_chat_id(chat_id)
        if not cid:
            return
        topics = self._svc("topics")
        lib_thread = None
        if topics is not None and self.memory is not None:
            try:
                mapping = await topics.get_map(self.memory, cid)
                lib_thread = topics.topic_for(mapping, "library")
            except Exception:
                pass
        if not lib_thread:
            return
        try:
            if media_type == "photo":
                await self.bot.send_photo(chat_id=cid, photo=media_input, caption=caption, message_thread_id=lib_thread)
            elif media_type == "video":
                await self.bot.send_video(chat_id=cid, video=media_input, caption=caption, message_thread_id=lib_thread)
            elif media_type == "audio":
                await self.bot.send_audio(chat_id=cid, audio=media_input, caption=caption, message_thread_id=lib_thread)
            else:
                await self.bot.send_document(chat_id=cid, document=media_input, caption=caption, message_thread_id=lib_thread)
        except Exception as exc:
            logger.warning("tự động gửi %s vào topic library lỗi: %s", media_type, exc)

    async def _post_photo_to_library(self, photo_input: Any, caption: str,
                                     chat_id: Optional[int] = None) -> None:
        """Tự động gửi ảnh mới vào topic Library để xây dựng kho ảnh visual."""
        await self._post_media_to_library("photo", photo_input, caption, chat_id=chat_id)

    async def send_to_session(self, session_key: str, text: str, **kwargs) -> bool:
        """Gửi tin nhắn về đúng chat và topic của session_key (chuẩn R15 định tuyến hội thoại)."""
        chat_id, thread_id = parse_session_key(session_key)
        if not chat_id or self.bot is None:
            return False
        send_kwargs = dict(kwargs)
        if thread_id:
            send_kwargs["message_thread_id"] = thread_id
        try:
            await self.bot.send_message(chat_id, text, **send_kwargs)
            return True
        except Exception as exc:
            logger.warning("send_to_session lỗi (%s): %s", session_key, exc)
            return False

    async def send_approval_card(self, chat_id: int,
                                 thread_id: Optional[int],
                                 payload: dict) -> Optional[int]:
        """Gửi tin thẻ duyệt vào đúng topic đang chạy + attach
        định tuyến vào broker để gỡ đúng thẻ khi có quyết định.
        Kiểm tra trạng thái đã phát (in-memory & KV sau restart) để không gửi lặp."""
        if self.bot is None or self.broker is None:
            return None
        import html as _html

        from .approvals import approval_scope

        approval_id = str(payload.get("approval_id") or "")
        # Kiểm tra trạng thái đã phát thẻ duyệt (chống phát lặp)
        if approval_id:
            if approval_id in self._sent_approval_cards:
                entry = self.broker._pending.get(approval_id) if self.broker else None
                if entry and entry.get("card"):
                    logger.info("Thẻ duyệt %s đã phát trong phiên, không gửi lại.", approval_id)
                    return entry["card"].get("message_id")
            if self.broker is not None:
                entry = self.broker._pending.get(approval_id)
                if entry and entry.get("card"):
                    logger.info("Thẻ duyệt %s đã attach card trước đó, không gửi lại.", approval_id)
                    return entry["card"].get("message_id")
            if self.memory is not None:
                try:
                    raw_appr = await self.memory.kv_get(f"approval_card_sent:{approval_id}")
                    if raw_appr:
                        logger.info("Thẻ duyệt %s đã phát trước khi restart, không gửi lại.", approval_id)
                        return json.loads(raw_appr).get("message_id")
                except Exception:
                    pass

        if payload.get("kind") == "marketplace_operation":
            return await self._send_marketplace_card(
                chat_id, thread_id, payload, approval_id)
        tool = str(payload.get("tool") or "")
        group = str(payload.get("group") or "")
        action = tool_action_label(tool, group)
        # Thẻ là UI CARD quyết định ngay trong chat (Mini App chỉ
        # là phụ): dòng 1 = hành động lời thường, dưới là bảng
        # trường thu nhỏ Hành động / Đích / Chi tiết, cuối là hạn.
        lines = [
            f"<b>{_html.escape(action)}</b>",
            f"Hành động: {_html.escape(action)}",
        ]
        target = str(payload.get("target") or "")
        if target:
            lines.append(f"Đích: <code>{_html.escape(target)}</code>")
        lines.append(
            f"Chi tiết: {_html.escape(str(payload.get('summary') or ''))}")
        lines.append(
            f"Công cụ: <code>{_html.escape(tool)}</code>"
            + (f" · nhóm {_html.escape(group)}" if group else ""))
        # Dòng phạm vi (chuẩn thẻ cấp quyền Muse): nói rõ "duyệt"
        # áp tới đâu và "duyệt và nhớ" nhớ tới đâu — suy từ tool/
        # nhóm thật + cơ chế rule session của broker, không ghi
        # cứng. Cả dòng escape vì chứa tên tool/nhóm.
        scope = approval_scope(payload)
        lines.append("Phạm vi: " + _html.escape(
            scope["once"].removesuffix(".") + " · "
            + scope["remember"]))
        # Lý do của agent (nếu lượt gọi tool có lời dẫn): chat chỉ
        # hiện 1 dòng cắt gọn; bản đầy đủ nằm ở Mini App.
        reason = " ".join(str(payload.get("reason") or "").split())
        if reason:
            if len(reason) > 140:
                reason = reason[:140].rstrip() + "…"
            lines.append(f"Lý do: {_html.escape(reason)}")
        lines.append(
            f"⏳ Thẻ hết hạn sau "
            f"{int(getattr(self.cfg, 'approval_timeout_s', 60))}s — "
            "không chọn coi như Chặn.")
        text = "\n".join(lines)
        kwargs: dict = {}
        if thread_id:
            kwargs["message_thread_id"] = thread_id
        try:
            msg = await self.bot.send_message(
                chat_id, text, parse_mode="HTML",
                reply_markup=self.approval_keyboard(approval_id),
                **kwargs)
        except Exception as exc:
            logger.warning("gửi thẻ duyệt lỗi: %s", exc)
            return None
        self.broker.attach(approval_id, {
            "chat_id": chat_id, "message_id": msg.message_id,
            "thread_id": thread_id})
        if approval_id:
            self._sent_approval_cards.add(approval_id)
            if self.memory is not None:
                try:
                    await self.memory.kv_set(f"approval_card_sent:{approval_id}", json.dumps({
                        "chat_id": chat_id, "message_id": msg.message_id,
                        "thread_id": thread_id, "created_at": time.time(),
                    }))
                except Exception:
                    pass
        return msg.message_id

    async def send_test_approval_card(
            self, chat_id: int,
            thread_id: Optional[int] = None) -> Optional[str]:
        """Lệnh /the_duyet (1.3.0): gửi một THẺ DUYỆT THỬ THẬT.

        Đi đúng đường thật — mở yêu cầu ở ApprovalBroker rồi
        trình bằng send_approval_card (renderer thẻ sẵn có, nút
        bấm thật, quyết qua callback/Mini App như thẻ thường).
        Payload VÔ HẠI: quyết xong chỉ ghi nhận + nhắn xác nhận,
        KHÔNG thực thi hành động nào. Đây là đường duy nhất để
        "xem thử thẻ duyệt" — agent bị cấm bịa thẻ mẫu bằng văn
        bản (xem khối TỰ NHẬN THỨC trong agent.py).
        """
        if self.broker is None:
            return None
        import uuid as _uuid

        approval_id = "test" + _uuid.uuid4().hex[:10]
        payload = {
            "approval_id": approval_id,
            "tool": "the_duyet",
            "group": "system",
            "summary": "Thẻ duyệt thử theo lệnh /the_duyet — "
                       "bấm nút chỉ để kiểm tra luồng duyệt, "
                       "không có hành động nào được thực thi.",
            "target": "",
            "reason": "Chủ nhân xin xem một thẻ phê duyệt THẬT.",
            "session_key": "",
            "task_id": "",
            "kind": "test",
        }
        self.broker.open(approval_id, payload)
        await self.send_approval_card(chat_id, thread_id, payload)
        asyncio.create_task(
            self._settle_test_approval(chat_id, thread_id,
                                        approval_id))
        return approval_id

    async def _settle_test_approval(
            self, chat_id: int, thread_id: Optional[int],
            approval_id: str) -> None:
        """Chờ quyết định của thẻ thử rồi nhắn xác nhận. Thẻ tự
        được gỡ bởi listener _on_approval_decided như thẻ
        thường; ở đây chỉ ghi vết + báo kết quả cho chủ nhân."""
        record = await self.broker.wait(approval_id)
        outcome = record.get("outcome", "")
        if self.memory is not None:
            try:
                await self.memory.log_trajectory(
                    "", "approval_decision",
                    {"tool": "the_duyet", "group": "system",
                     "approval_id": approval_id,
                     "outcome": outcome,
                     "approved": bool(record.get("approved")),
                     "remember": bool(record.get("remember")),
                     "test": True})
            except Exception:
                pass
        note = {
            "approved": "Đã ghi nhận: anh vừa DUYỆT thẻ thử.",
            "denied": "Đã ghi nhận: anh vừa CHẶN thẻ thử.",
            "expired": "Thẻ duyệt thử hết hạn — chưa có quyết "
                       "định nào.",
        }.get(outcome, "Đã ghi nhận quyết định thẻ thử.")
        text = (note + " Đây chỉ là thẻ thử để kiểm tra luồng "
                "duyệt — không có hành động nào được thực thi.")
        if self.bot is not None:
            kwargs: dict = {}
            if thread_id:
                kwargs["message_thread_id"] = thread_id
            try:
                await self.bot.send_message(chat_id, text, **kwargs)
            except Exception as exc:
                logger.warning("gửi xác nhận thẻ thử lỗi: %s", exc)

    async def _send_marketplace_card(self, chat_id: int,
                                     thread_id: Optional[int],
                                     payload: dict,
                                     approval_id: str
                                     ) -> Optional[int]:
        """Thẻ duyệt operation của Chợ MCP (1.3.0): tiêu đề +
        tóm tắt + đích + dấu vân tay + hạn TTL của operation.
        Chỉ 2 nút Duyệt / Chặn — không "duyệt và nhớ"."""
        if self.bot is None or self.broker is None:
            return None
        import html as _html

        ttl = int(payload.get("marketplace_ttl_s") or 900)
        lines = [
            f"<b>{_html.escape(str(payload.get('title') or 'Thao tác MCP'))}</b>",
            f"Chi tiết: {_html.escape(str(payload.get('summary') or ''))}",
        ]
        target = str(payload.get("target") or "")
        if target:
            lines.append(f"Đích: <code>{_html.escape(target)}</code>")
        if payload.get("fingerprint"):
            lines.append(
                f"Dấu vân tay: <code>{_html.escape(str(payload['fingerprint']))}</code>")
        lines.append(
            f"⏳ Thẻ hết hạn sau {ttl}s — không chọn coi như Chặn.")
        text = "\n".join(lines)
        kwargs: dict = {}
        if thread_id:
            kwargs["message_thread_id"] = thread_id
        try:
            msg = await self.bot.send_message(
                chat_id, text, parse_mode="HTML",
                reply_markup=self.approval_keyboard(
                    approval_id, rememberable=False),
                **kwargs)
        except Exception as exc:
            logger.warning("gửi thẻ duyệt marketplace lỗi: %s", exc)
            return None
        self.broker.attach(approval_id, {
            "chat_id": chat_id, "message_id": msg.message_id,
            "thread_id": thread_id})
        if approval_id:
            self._sent_approval_cards.add(approval_id)
            if self.memory is not None:
                try:
                    await self.memory.kv_set(f"approval_card_sent:{approval_id}", json.dumps({
                        "chat_id": chat_id, "message_id": msg.message_id,
                        "thread_id": thread_id, "created_at": time.time(),
                    }))
                except Exception:
                    pass
        return msg.message_id

    async def send_marketplace_card_to_owner(self,
                                             payload: dict
                                             ) -> Optional[int]:
        """Gửi thẻ duyệt marketplace về DM của owner (operation
        được mở từ Mini App nên không có topic chat neo sẵn)."""
        owner = int(getattr(self.cfg, "allowed_user_id", 0) or 0)
        if not owner:
            return None
        approval_id = str(payload.get("approval_id") or "")
        return await self.send_approval_card(owner, None, payload)

    async def send_vault_card_to_owner(self, info: dict) -> bool:
        """Gửi thẻ yêu cầu bí mật vào chat/DM (1.6.0 + 1.7.3 T-10.1 + 1.7.24 T-24.4).
        Kiểm tra trạng thái đã phát (in-memory & KV sau restart) để tránh phát 2 lần thẻ cho cùng một yêu cầu."""
        owner = int(getattr(self.cfg, "allowed_user_id", 0) or 0)
        label = str(info.get("label", "") or "").strip()
        if not label:
            return False
        target_chat = info.get("chat_id") or owner
        thread_id = info.get("thread_id")
        if label in self._pending_vault_resumes:
            r = self._pending_vault_resumes[label]
            target_chat = r.get("chat_id") or target_chat
            thread_id = r.get("thread_id") or thread_id

        if not target_chat or self.bot is None:
            return False

        now = time.time()
        desc = str(info.get("description", "") or "").strip()

        # 1. Kiểm tra in-memory: Thẻ cho nhãn này đã được phát và còn đang chờ người dùng nhập
        existing = self._pending_vault_cards.get(label)
        if existing and existing.get("chat_id") == target_chat:
            card_age = now - float(existing.get("created_at", 0.0))
            if card_age < 600.0:  # Trong vòng 10 phút, không phát thêm thẻ mới
                msg_id = existing.get("message_id")
                # Nếu mô tả mục đích có cập nhật nhẹ, sửa thẻ cũ thay vì gửi thêm thẻ mới
                if msg_id and desc and desc != existing.get("description"):
                    existing["description"] = desc
                    safe_param = info.get("startapp_param") or f"vault_{label.replace(':', '__')}"
                    direct_url = webapp_direct_link(self.cfg, self._bot_username(), safe_param)
                    lines = [
                        "<b>Yêu cầu bí mật vào Kho</b>",
                        f"Agent cần thông tin: <code>{label}</code>",
                        f"Mục đích: {desc}",
                        "",
                        "Bí mật được lưu vào Kho trên máy của bạn (file JSON quyền 0600, không mã hoá at-rest), không gửi qua chat.",
                    ]
                    kb = None
                    if direct_url:
                        kb = InlineKeyboardMarkup(inline_keyboard=[[
                            InlineKeyboardButton(text=f"Nhập {label} vào Kho", url=direct_url)
                        ]])
                    try:
                        await self.bot.edit_message_text(
                            "\n".join(lines), chat_id=target_chat, message_id=msg_id,
                            reply_markup=kb, parse_mode="HTML"
                        )
                    except Exception:
                        pass
                logger.info("Thẻ Vault cho '%s' đã phát trước đó (age=%.1fs), giữ nguyên không phát lặp.", label, card_age)
                return True

        # 2. Kiểm tra bộ nhớ bền sau restart (trạng thái đã phát qua KV)
        if self.memory is not None:
            try:
                raw_card = await self.memory.kv_get(f"vault_card_pending:{label}")
                if raw_card:
                    card_data = json.loads(raw_card)
                    c_age = now - float(card_data.get("created_at", 0.0))
                    if c_age < 600.0 and card_data.get("chat_id") == target_chat:
                        self._pending_vault_cards[label] = card_data
                        logger.info("Thẻ Vault cho '%s' đã phát trước khi restart (age=%.1fs), không phát lặp.", label, c_age)
                        return True
            except Exception as exc:
                logger.warning("Kiểm tra KV vault_card_pending lỗi: %s", exc)

        safe_param = info.get("startapp_param") or f"vault_{label.replace(':', '__')}"
        direct_url = webapp_direct_link(self.cfg, self._bot_username(), safe_param)
        lines = [
            "<b>Yêu cầu bí mật vào Kho</b>",
            f"Agent cần thông tin: <code>{label}</code>",
        ]
        if desc:
            lines.append(f"Mục đích: {desc}")
        lines.append("")
        lines.append("Bí mật được lưu vào Kho trên máy của bạn (file JSON quyền 0600, không mã hoá at-rest), không gửi qua chat.")
        kb = None
        if direct_url:
            kb = InlineKeyboardMarkup(inline_keyboard=[[
                InlineKeyboardButton(text=f"Nhập {label} vào Kho", url=direct_url)
            ]])
        try:
            kwargs: dict = {}
            if thread_id:
                kwargs["message_thread_id"] = thread_id
            msg = await self.bot.send_message(
                target_chat, "\n".join(lines), parse_mode="HTML", reply_markup=kb, **kwargs)
            card_info = {
                "chat_id": target_chat,
                "thread_id": thread_id,
                "message_id": getattr(msg, "message_id", None),
                "label": label,
                "description": desc,
                "created_at": now,
            }
            self._pending_vault_cards[label] = card_info
            if self.memory is not None:
                try:
                    await self.memory.kv_set(f"vault_card_pending:{label}", json.dumps(card_info))
                except Exception:
                    pass
            return True
        except Exception as exc:
            logger.warning("Gửi thẻ Vault vào chat lỗi: %s", exc)
            return False

    async def on_vault_secret_captured(self, label: str, ref: str) -> None:
        """Được gọi khi bí mật được lưu vào Kho (qua Mini App hoặc form server).
        Báo lại NGAY trong chat đã gửi thẻ và tiếp tục việc đang dở (chuẩn T-10.1)."""
        import html as _html

        now = time.time()
        dedup_key = f"{label}:{ref}"
        last_time = self._recent_captured_vault.get(dedup_key, 0.0)
        if now - last_time < 30.0:
            logger.info("Bỏ qua thông báo vault trùng lặp cho %s (mã %s)", label, ref)
            return
        self._recent_captured_vault[dedup_key] = now
        if len(self._recent_captured_vault) > 200:
            self._recent_captured_vault = {
                k: v for k, v in self._recent_captured_vault.items() if now - v < 60.0
            }

        # Dọn dẹp thẻ pending trong KV store nếu có
        if self.memory is not None:
            try:
                await self.memory.kv_del(f"vault_card_pending:{label}")
            except Exception:
                pass

        if hasattr(self, "vault_broker") and self.vault_broker is not None:
            self.vault_broker.resolve(label, ref)

        pending = self._pending_vault_cards.pop(label, None) or {}
        owner = int(getattr(self.cfg, "allowed_user_id", 0) or 0)
        chat_id = pending.get("chat_id") or owner
        thread_id = pending.get("thread_id")

        if self.bot is not None and chat_id:
            msg_text = (
                f"<b>Đã nhận và lưu bí mật vào Kho an toàn</b>\n"
                f"Nhãn: <code>{_html.escape(label)}</code> · Mã tham chiếu: <code>{_html.escape(ref)}</code>\n"
                f"Giá trị bí mật được bảo vệ trong Kho trên máy, không hiển thị trong chat."
            )
            kwargs: dict = {}
            if thread_id:
                kwargs["message_thread_id"] = thread_id
            try:
                await self.bot.send_message(chat_id, msg_text, parse_mode="HTML", **kwargs)
            except Exception as exc:
                logger.warning("Gửi thông báo nhận bí mật Vault lỗi: %s", exc)

        resume = self._pending_vault_resumes.pop(label, None)
        if resume and self.agent is not None:
            resume_prompt = (
                f"Hệ thống: Người dùng đã nhập bí mật cho nhãn '{label}' vào Kho an toàn (mã ref: {ref}). "
                f"Hãy tiếp tục hoàn tất tác vụ đang dở: {resume.get('user_text', '')}"
            )
            asyncio.create_task(
                self._resume_vault_task(resume["session_key"], resume_prompt, chat_id, thread_id)
            )

    async def _resume_vault_task(self, session_key: str, prompt: str,
                                 chat_id: int, thread_id: Optional[int]) -> None:
        """Tiếp tục lượt hội thoại sau khi nhận bí mật Vault."""
        try:
            status_msg = None
            if self.bot is not None and chat_id:
                kwargs: dict = {}
                if thread_id:
                    kwargs["message_thread_id"] = thread_id
                try:
                    status_msg = await self.bot.send_message(
                        chat_id, "⏳ <i>Đang tiếp tục xử lý công việc...</i>", parse_mode="HTML", **kwargs)
                except Exception:
                    pass

            async def on_delta(piece: str):
                pass

            res = await self.agent.handle(session_key, prompt, on_delta=on_delta)
            if self.bot is not None and chat_id:
                kwargs = {}
                if thread_id:
                    kwargs["message_thread_id"] = thread_id
                if status_msg is not None:
                    try:
                        await status_msg.edit_text(res, parse_mode="HTML")
                        return
                    except Exception:
                        pass
                await self.bot.send_message(chat_id, res, parse_mode="HTML", **kwargs)
        except Exception as exc:
            logger.warning("tiếp tục tác vụ vault lỗi: %s", exc)

    async def handle_approval_callback(self, data: str,
                                       user_id: int) -> tuple[bool, str]:
        """Lõi xử lý nút inline của thẻ duyệt (tách khỏi handler
        aiogram để test được). Chỉ chủ nhân mới resolve được."""
        parts = (data or "").split(":")
        if len(parts) != 3 or parts[0] != "appr":
            return False, "Dữ liệu lạ — bỏ qua."
        if int(user_id or 0) != int(self.cfg.allowed_user_id or 0):
            return False, "Chỉ chủ nhân duyệt được."
        if self.broker is None:
            return False, "Kênh duyệt chưa được nối."
        code, approval_id = parts[1], parts[2]
        approved = code in ("1", "2")
        ok = self.broker.resolve(approval_id, approved,
                                 remember=(code == "2"))
        if not ok:
            return False, "Thẻ này đã được xử lý hoặc đã hết hạn."
        return True, "Đã duyệt." if approved else "Đã chặn."

    def format_decided_approval_card(self, record: dict) -> str:
        """Định dạng nội dung thẻ duyệt sau khi đã có quyết định hoặc hết hạn (1.7.3 T-10.1)."""
        import html as _html
        from .webapp_server import tool_action_label

        payload = record.get("payload") or {}
        outcome = record.get("outcome", "")
        remember = bool(record.get("remember"))

        tool = str(payload.get("tool") or "")
        group = str(payload.get("group") or "")
        action = tool_action_label(tool, group)

        if outcome == "approved":
            status_header = "<b>ĐÃ DUYỆT</b>" + (" (VÀ NHỚ CHO PHIÊN)" if remember else "")
            status_text = "Đã cho phép thực thi" + (" (đã nhớ cho phiên này)" if remember else " (chỉ lần này)")
        elif outcome == "denied":
            status_header = "<b>ĐÃ CHẶN</b>"
            status_text = "Đã chặn yêu cầu này"
        elif outcome == "expired":
            status_header = "<b>HẾT HẠN PHÊ DUYỆT</b>"
            status_text = "Thẻ đã hết hạn mà chưa có phản hồi — yêu cầu bị hủy an toàn"
        else:
            status_header = f"<b>KẾT QUẢ: {_html.escape(outcome.upper())}</b>"
            status_text = outcome

        lines = [
            status_header,
            f"Hành động: <b>{_html.escape(action)}</b>",
        ]
        target = str(payload.get("target") or "")
        if target:
            lines.append(f"Đích: <code>{_html.escape(target)}</code>")
        if payload.get("summary"):
            lines.append(f"Chi tiết: {_html.escape(str(payload.get('summary')))}")
        lines.append(f"Công cụ: <code>{_html.escape(tool)}</code>" + (f" · nhóm {_html.escape(group)}" if group else ""))
        reason = str(payload.get("reason") or "").strip()
        if reason:
            lines.append(f"Lý do: {_html.escape(reason)}")
        lines.append(f"Trạng thái: <b>{_html.escape(status_text)}</b>")
        return "\n".join(lines)

    async def _on_approval_decided(self, record: dict) -> None:
        """Listener của broker: quyết định xong (duyệt/chặn/HẾT
        HẠN) -> cập nhật trạng thái thẻ ngay trong chat + vô hiệu
        hoá nút bấm (chuẩn Parity T-10.1); xoá thẻ nếu cấu hình delete."""
        if self.bot is None:
            return
        card = record.get("card") or {}
        chat_id = card.get("chat_id")
        message_id = card.get("message_id")
        if chat_id and message_id:
            mode = getattr(self.cfg, "approval_card_action", "update")
            if mode == "delete":
                try:
                    await self.bot.delete_message(chat_id, message_id)
                except Exception:
                    try:
                        await self.bot.edit_message_text(
                            "Đã xử lý thẻ duyệt này.", chat_id=chat_id,
                            message_id=message_id)
                        await self.bot.edit_message_reply_markup(
                            chat_id=chat_id, message_id=message_id,
                            reply_markup=None)
                    except Exception:
                        pass
            else:
                try:
                    await self.bot.edit_message_text(
                        self.format_decided_approval_card(record),
                        chat_id=chat_id,
                        message_id=message_id,
                        parse_mode="HTML"
                    )
                except Exception as exc:
                    logger.warning("cập nhật text thẻ duyệt lỗi: %s", exc)
                try:
                    await self.bot.edit_message_reply_markup(
                        chat_id=chat_id,
                        message_id=message_id,
                        reply_markup=None
                    )
                except Exception as exc:
                    logger.warning("gỡ bàn phím thẻ duyệt lỗi: %s", exc)
        payload = record.get("payload") or {}
        outcome = record.get("outcome", "")
        approval_id = record.get("id") or str(payload.get("approval_id") or "")
        if approval_id:
            self._sent_approval_cards.discard(approval_id)
            if self.memory is not None:
                try:
                    await self.memory.kv_del(f"approval_card_sent:{approval_id}")
                except Exception:
                    pass
        label = {"approved": "Đã duyệt",
                 "denied": "Đã chặn",
                 "expired": "Thẻ duyệt hết hạn"}.get(
                     outcome, outcome)
        if payload.get("kind") == "marketplace_operation":
            mkt_title = payload.get("title") or "Thao tác MCP"
            mkt_name = payload.get("local_name") or "?"
            line = f"{label}: {mkt_title} (server {mkt_name})"
        else:
            line = (f"{label}: tool {payload.get('tool', '?')} "
                    f"(nhóm {payload.get('group') or '—'})"
                    + (" — đã nhớ cho phiên này."
                       if record.get("remember") else ""))
        if chat_id:
            await self._post_history_line(chat_id, line)

    async def _post_history_line(self, chat_id: int,
                                 line: str) -> None:
        topics = self._svc("topics")
        if topics is None or self.memory is None:
            return
        try:
            mapping = await topics.get_map(self.memory, chat_id)
            tid = topics.topic_for(mapping, "history")
            if not tid:
                return
            await self.bot.send_message(
                chat_id, line, message_thread_id=tid)
        except Exception as exc:
            logger.warning("ghi dòng lịch sử duyệt lỗi: %s", exc)

    # ---- chat phụ: mỗi topic tự do là một đoạn chat riêng ----
    @staticmethod
    def _current_thread_id(message: Message) -> int:
        if getattr(message, "is_topic_message", False):
            return int(message.message_thread_id or 0)
        return 0

    @staticmethod
    def _sidechat_id_arg(message: Message) -> Optional[int]:
        parts = (message.text or "").split()
        if len(parts) < 2:
            return None
        try:
            return int(parts[1])
        except ValueError:
            return None

    async def _chatphu_create_text(self, message: Message) -> str:
        if message.chat.type == ChatType.PRIVATE:
            return (
                "Chat phụ chỉ tạo được trong group đã bật Topics "
                "(forum), không tạo được trong DM.")
        if self.bot is None:
            return "Bot chưa sẵn sàng để tạo chat phụ."
        parts = (message.text or "").split(maxsplit=1)
        raw_title = parts[1] if len(parts) > 1 else ""
        result = await self.sidechats.create(
            self.bot, self.memory, message.chat.id, raw_title,
            is_forum=bool(getattr(message.chat, "is_forum", False)),
            timezone_name=self.cfg.default_timezone)
        if not result.get("ok"):
            return result.get("error") or "Chưa tạo được chat phụ."
        record = result["record"]
        return (
            f"Đã tạo chat phụ '{record['title']}' "
            f"(thread {record['thread_id']}). Vào topic mới để "
            "trò chuyện riêng trong đó.")

    async def _chatphu_list_text(self, message: Message) -> str:
        records = await self.sidechats.list_open(
            self.memory, message.chat.id)
        return surf.format_sidechat_list(records)

    async def _dongchat_text(self, message: Message) -> str:
        if self.bot is None:
            return "Bot chưa sẵn sàng để đóng chat phụ."
        result = await self.sidechats.close_current(
            self.bot, self.memory, self._svc("topics"),
            message.chat.id, self._current_thread_id(message))
        if not result.get("ok"):
            return result.get("error") or "Chưa đóng được chat phụ."
        record = result["record"]
        return (
            f"Đã đóng chat phụ '{record['title']}' "
            f"(thread {record['thread_id']}).")

    async def _chatphu_status_text(self, message: Message,
                                   reopen: bool) -> str:
        command = "/chatphu_mo" if reopen else "/chatphu_dong"
        thread_id = self._sidechat_id_arg(message)
        if thread_id is None:
            return f"Dùng: {command} <thread_id> (xem /chatphu_list)"
        if self.bot is None:
            return "Bot chưa sẵn sàng để đổi trạng thái chat phụ."
        if reopen:
            result = await self.sidechats.reopen_by_id(
                self.bot, self.memory, message.chat.id, thread_id)
        else:
            result = await self.sidechats.close_by_id(
                self.bot, self.memory, message.chat.id, thread_id)
        if not result.get("ok"):
            return result.get("error") or "Chưa đổi được chat phụ."
        record = result["record"]
        action = "mở lại" if reopen else "đóng"
        return (
            f"Đã {action} chat phụ '{record['title']}' "
            f"(thread {record['thread_id']}).")

    async def _handle_reaction(self, chat_id: int, message_id: int,
                               emojis: list[str]) -> bool:
        """Reaction trên bài Feed -> tín hiệu taste (mục 16.4)."""
        feed = self._svc("feed")
        if feed is None or not emojis:
            return False
        try:
            return await feed.record_reaction(chat_id, message_id,
                                              emojis)
        except Exception as exc:
            logger.warning("ghi reaction taste lỗi (bỏ qua): %s", exc)
            return False

    async def _try_forget_confirm(self, message: Message) -> bool:
        """Trả lời đúng 'quên thật' khi đang có kế hoạch quên chờ
        -> thực thi. Trả True nếu đã xử lý (đừng đưa vào agent)."""
        from .memory import fold_vi

        if fold_vi((message.text or "").strip()) != "quen that":
            return False
        key = session_key_for(message)
        kv_key = f"forget_pending:{key}"
        raw = await self.memory.kv_get(kv_key)
        if not raw:
            return False
        try:
            plan = json.loads(raw)
        except Exception:
            await self.memory.kv_set(kv_key, "")
            return False
        summary = await surf.execute_forget_plan(
            self.memory, self.cfg.dossier_dir, plan, session_key=key)
        await self.memory.kv_set(kv_key, "")
        # Nạp lại dossier vào đúng object đang dùng chung (context
        # engine giữ cùng tham chiếu) để lượt sau thấy bản đã gỡ.
        try:
            from .context import Dossier

            fresh = Dossier.load(self.cfg.dossier_dir)
            self.dossier.files.update(fresh.files)
        except Exception as exc:
            logger.warning("nạp lại dossier sau quên lỗi: %s", exc)
        await message.answer(
            f"Đã quên chủ đề '{summary['topic']}': "
            f"{summary['facts_forgotten']} fact/lesson bị vô hiệu, "
            f"{summary['dossier_lines_removed']} dòng dossier bị gỡ. "
            "Dấu vết kiểm toán vẫn còn trong sổ cái.")
        return True

    async def _try_reply_actions(self, message: Message) -> bool:
        """Reply dạng lệnh ngắn vào tin của bot: 'duyệt'/'bỏ' cho
        proactive note, 'làm luôn' cho thẻ ý tưởng."""
        replied = getattr(message, "reply_to_message", None)
        if replied is None:
            return False
        replied_text = getattr(replied, "text", None) or getattr(
            replied, "caption", None) or ""
        note = surf.parse_note_action(message.text or "", replied_text)
        if note is not None:
            status, note_id = note
            ok = await self.memory.set_proactive_note_status(
                note_id, status)
            if ok:
                await self.memory.log_trajectory(
                    session_key_for(message), "proactive_note_decided",
                    {"note_id": note_id, "status": status,
                     "via": "reply"})
                await message.answer(
                    f"Đã {'duyệt' if status == 'sent' else 'bỏ'} "
                    f"đề xuất #{note_id}.")
            else:
                await message.answer(
                    f"Không đổi được đề xuất #{note_id}.")
            return True
        ideas = self._svc("ideas")
        card_id = parse_do_reply(message.text or "", replied_text)
        if ideas is not None and card_id is not None:
            result = await ideas.do_card(
                card_id, session_key=session_key_for(message))
            if result.get("ok"):
                await message.answer(
                    f"Đã làm luôn thẻ #{card_id}: tạo goal "
                    f"#{result['goal_id']} + task {result['task_id']}.")
            else:
                await message.answer(
                    f"Thẻ #{card_id}: {result.get('error')}")
            return True
        return False

    async def _get_google_auth_url(self) -> Optional[str]:
        """Tạo fresh OAuth Authorization URL từ Google Workspace MCP."""
        target_tools = [
            "mcp_google-workspace_search_drive_files",
            "mcp_google-workspace_list_tasks",
            "mcp_google-workspace_list_calendars",
        ]
        if not self.agent or not self.agent.registry:
            return None
        tool_name = None
        for t in target_tools:
            if self.agent.registry.get(t) is not None:
                tool_name = t
                break
        if not tool_name:
            return None
        try:
            # Email lấy từ cấu hình (GOOGLE_USER_EMAIL), KHÔNG hardcode
            # email cá nhân trong code (vá audit hardcode 2026-10-26).
            user_email = str(getattr(self.cfg, "google_user_email", "") or "").strip()
            if not user_email:
                logger.warning("chưa cấu hình GOOGLE_USER_EMAIL — bỏ qua auth_probe Google")
                return None
            res = await self.agent.registry.execute(
                tool_name,
                {"user_google_email": user_email, "query": "auth_probe"}
            )
            raw = str(res.get("result", ""))
            m = re.search(r'https://accounts\.google\.com/o/oauth2/auth\?[^\s\n\)]+', raw)
            if m:
                return m.group(0)
        except Exception as e:
            logger.warning("Lỗi kích hoạt Google auth flow: %s", e)
        return None

    async def _handle_oauth_callback(self, message: Message) -> bool:
        """Tự động xử lý link OAuth callback (Google Workspace, v.v.) do người dùng paste vào chat."""
        text = (message.text or "").strip()
        if "oauth2callback" not in text or "code=" not in text:
            return False

        m = re.search(r'(?:https?://[^/:\s]+(?::(\d+))?)?/oauth2callback\?([^\s\n\)]+)', text)
        if not m:
            return False

        explicit_port = m.group(1)
        query = m.group(2)
        candidate_ports = [int(explicit_port)] if explicit_port else [8001, 8000, 8002, 8003, 8004]

        success = False
        error_detail = ""
        user_email = ""

        for port in candidate_ports:
            url = f"http://127.0.0.1:{port}/oauth2callback?{query}"
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (Mulon-Bot)"})
                with urllib.request.urlopen(req, timeout=8) as resp:
                    body = resp.read().decode("utf-8", errors="ignore")
                    if "Authentication Successful" in body or "successful" in body.lower() or resp.status == 200:
                        success = True
                        em_m = re.search(r'for user:\s*<strong>([^<]+)</strong>', body, re.IGNORECASE)
                        if em_m:
                            user_email = em_m.group(1).strip()
                        break
            except urllib.error.HTTPError as e:
                err_body = e.read().decode("utf-8", errors="ignore")
                err_m = re.search(r'<p>([^<]+)</p>', err_body)
                if err_m:
                    error_detail = err_m.group(1).strip()
                else:
                    error_detail = f"HTTP {e.code}"
            except Exception as e:
                error_detail = str(e)

        if success:
            acc_str = f" cho tài khoản <code>{html.escape(user_email)}</code>" if user_email else ""
            await message.answer(
                f"<b>Xác thực Google Workspace thành công rực rỡ{acc_str}!</b>\n\n"
                "Đã nạp và lưu trữ an toàn credentials.\n"
                "Toàn bộ 43 công cụ Google Workspace (Gmail, Google Drive, Calendar, Docs, Sheets, Tasks) đã sẵn sàng phục vụ ní ngay lập tức!",
                parse_mode="HTML"
            )
            return True
        else:
            await message.answer(
                "<b>Chưa hoàn tất xác thực Google Workspace</b>\n\n"
                f"Lý do: <code>{html.escape(error_detail or 'Không thể kết nối cổng OAuth callback trên máy Mac')}</code>\n\n"
                "• Mã (code) hoặc phiên xác thực có thể đã hết hạn. Ní vui lòng gõ <code>/google_auth</code> để lấy link đăng nhập mới tinh nha!",
                parse_mode="HTML"
            )
            return True

    async def _handle_setup_command(self, message: Message) -> None:
        """Xử lý lệnh /setup và /claim ghép nối chủ sở hữu hoặc quản lý allowlist."""
        from_user = getattr(message, "from_user", None)
        if not from_user:
            return
        user_id = from_user.id
        raw_text = (message.text or message.caption or "").strip()
        parts = raw_text.split()
        subcmd = parts[1].strip() if len(parts) > 1 else ""

        # Case 1: Bot chưa có chủ sở hữu (allowed_user_id == 0)
        if not self.cfg.allowed_user_id:
            from mulon.allowlist import claim_ownership, get_or_create_claim_token
            claim_file = getattr(self.cfg, "claim_token_path", PROJECT_ROOT / "data" / "claim_token.txt")
            allow_file = getattr(self.cfg, "allowlist_path", PROJECT_ROOT / "data" / "allowlist.json")

            if not subcmd:
                tok = get_or_create_claim_token(claim_file)
                await message.answer(
                    "<b>Bot này chưa có chủ sở hữu!</b>\n\n"
                    "Để nhận quyền chủ nhân của bot, vui lòng kiểm tra mã xác thực (Claim Token) "
                    "trong log máy chủ / terminal chạy bot, rồi gửi lệnh:\n"
                    "<code>/setup &lt;mã_token&gt;</code>",
                    parse_mode="HTML",
                )
                return

            ok, msg = claim_ownership(claim_file, allow_file, subcmd, user_id)
            if ok:
                from dataclasses import replace
                self.cfg = replace(
                    self.cfg,
                    allowed_user_id=user_id,
                    allowed_user_ids=(user_id, *[u for u in getattr(self.cfg, "allowed_user_ids", ()) if u != user_id]),
                )
                await message.answer(
                    f"<b>Ghép nối thành công!</b>\n\n"
                    f"Tài khoản Telegram của bạn (<code>{user_id}</code>) đã trở thành <b>Chủ sở hữu (Owner)</b> của MuLon.\n\n"
                    f"Từ bây giờ bot sẽ phục vụ bạn. Hãy gõ /menu hoặc gửi tin nhắn để bắt đầu!",
                    parse_mode="HTML",
                )
            else:
                await message.answer(
                    f"<b>Xác thực thất bại:</b> {msg}.\n"
                    f"Vui lòng kiểm tra lại claim token trong log máy chủ.",
                    parse_mode="HTML",
                )
            return

        # Case 2: Bot đã có chủ sở hữu -> chỉ chủ sở hữu hoặc allowlist mới được xem/quản lý
        if not self._is_allowed(message):
            return  # Chặn người lạ theo Rule 4

        # Chỉ owner mới có quyền quản trị thêm/bớt allowlist
        is_owner = (user_id == self.cfg.allowed_user_id)
        from mulon.allowlist import add_allowed_user, remove_allowed_user, load_allowlist
        allow_file = getattr(self.cfg, "allowlist_path", PROJECT_ROOT / "data" / "allowlist.json")

        if subcmd.lower() in ("add", "them"):
            if not is_owner:
                await message.answer("Chỉ chủ sở hữu (Owner) mới có quyền thêm người dùng.")
                return
            if len(parts) < 3 or not parts[2].isdigit():
                await message.answer("Cú pháp: <code>/setup add &lt;user_id&gt;</code>", parse_mode="HTML")
                return
            target_id = int(parts[2])
            ok, msg = add_allowed_user(allow_file, target_id)
            if ok:
                _, users = load_allowlist(allow_file)
                from dataclasses import replace
                self.cfg = replace(self.cfg, allowed_user_ids=tuple(users))
                await message.answer(f"Đã thêm người dùng <code>{target_id}</code> vào danh sách cho phép.", parse_mode="HTML")
            else:
                await message.answer(f"Không thể thêm: {msg}")
            return

        if subcmd.lower() in ("remove", "xoa", "del"):
            if not is_owner:
                await message.answer("Chỉ chủ sở hữu (Owner) mới có quyền xóa người dùng.")
                return
            if len(parts) < 3 or not parts[2].isdigit():
                await message.answer("Cú pháp: <code>/setup remove &lt;user_id&gt;</code>", parse_mode="HTML")
                return
            target_id = int(parts[2])
            ok, msg = remove_allowed_user(allow_file, target_id)
            if ok:
                _, users = load_allowlist(allow_file)
                from dataclasses import replace
                self.cfg = replace(self.cfg, allowed_user_ids=tuple(users))
                await message.answer(f"Đã xóa người dùng <code>{target_id}</code> khỏi danh sách.", parse_mode="HTML")
            else:
                await message.answer(f"Không thể xóa: {msg}")
            return

        if subcmd.lower() in ("api", "endpoint"):
            if not is_owner:
                await message.answer("Chỉ chủ sở hữu (Owner) mới có quyền cấu hình API.")
                return
            if len(parts) < 4:
                await message.answer(
                    "Cú pháp: <code>/setup api &lt;endpoint_url&gt; &lt;api_key&gt;</code>\n"
                    "Ví dụ: <code>/setup api http://127.0.0.1:8317/v1 my-secret-key</code>",
                    parse_mode="HTML"
                )
                return
            endpoint = parts[2].strip()
            key_val = parts[3].strip()

            from .tools import assert_url_public
            from .config import is_loopback_host
            import httpx

            parsed = urllib.parse.urlparse(endpoint)
            host = parsed.hostname or ""
            allow_remote = os.environ.get("MULON_ALLOW_REMOTE_PROXY", "0") == "1"
            if not is_loopback_host(host) and not allow_remote:
                err = await assert_url_public(endpoint)
                if err:
                    await message.answer(f"Endpoint không an toàn: {err}")
                    return

            # Kiểm tra kết nối sống
            await message.answer("⏳ Đang kiểm tra kết nối tới API endpoint...")
            try:
                headers = {"Authorization": f"Bearer {key_val}"}
                test_url = endpoint.rstrip("/") + "/models" if not endpoint.endswith("/models") else endpoint
                async with httpx.AsyncClient(timeout=6.0) as client:
                    resp = await client.get(test_url, headers=headers)
                    if resp.status_code not in (200, 201, 404):
                        await message.answer(
                            f"Endpoint từ chối xác thực (HTTP {resp.status_code}). Không lưu cấu hình để tránh bot bị lỗi.",
                            parse_mode="HTML"
                        )
                        return
            except Exception as exc:
                await message.answer(
                    f"Không thể kết nối tới endpoint ({exc}). Không lưu cấu hình.",
                    parse_mode="HTML"
                )
                return

            vstore = self._svc("vault_store")
            if vstore is not None:
                vstore.put("proxy:api_key", key_val)
            object.__setattr__(self.cfg, "proxy_base_url", endpoint)
            object.__setattr__(self.cfg, "proxy_api_key", key_val)
            if self.memory is not None:
                try:
                    await self.memory.kv_set("config:proxy_base_url", endpoint)
                except Exception:
                    pass
            try:
                from dotenv import set_key
                env_path = Path(getattr(self.cfg, "project_root", None) or PROJECT_ROOT) / ".env"
                if env_path.is_file():
                    set_key(str(env_path), "PROXY_BASE_URL", endpoint)
            except Exception:
                pass
            await message.answer(
                f"<b>Kết nối API sống!</b> Đã lưu cấu hình proxy <code>{endpoint}</code> và cất khóa vào Vault an toàn.",
                parse_mode="HTML"
            )
            return

        # Xem trạng thái cấu hình
        import platform
        owner_id, users = load_allowlist(allow_file)
        if not users and self.cfg.allowed_user_id:
            users = [self.cfg.allowed_user_id]
        user_list_str = ", ".join(f"<code>{u}</code>" for u in users) if users else "(chưa có)"

        info_lines = [
            "<b>Cấu hình bản cài MuLon</b>",
            f"• <b>Chủ sở hữu (Owner):</b> <code>{self.cfg.allowed_user_id}</code>",
            f"• <b>Allowlist ({len(users)} người):</b> {user_list_str}",
            f"• <b>Hệ điều hành:</b> {platform.system()} {platform.release()}",
            f"• <b>Model Brain:</b> <code>{self.cfg.model_brain}</code>",
            f"• <b>Proxy:</b> <code>{self.cfg.proxy_base_url}</code>",
            f"• <b>Thư mục dữ liệu:</b> <code>{self.cfg.db_path.parent}</code>",
            "",
            "<b>Lệnh quản lý cấu hình & API:</b>",
            "• <code>/setup add &lt;user_id&gt;</code>: Thêm người dùng",
            "• <code>/setup remove &lt;user_id&gt;</code>: Xóa người dùng",
            "• <code>/setup api &lt;url&gt; &lt;key&gt;</code>: Kiểm tra sống & lưu API proxy",
        ]
        await message.answer("\n".join(info_lines), parse_mode="HTML")

    # ---- handlers ----
    def _register_handlers(self) -> None:
        dp = self.dp

        @dp.message(F.text.startswith("/setup") | F.text.startswith("/claim"))
        async def cmd_setup(message: Message) -> None:
            await self._handle_setup_command(message)

        @dp.message(F.text.startswith("/start"))
        async def cmd_start(message: Message) -> None:
            if not self._is_allowed(message):
                return
            await message.answer(self.start_message_text())

        @dp.message(F.text.startswith("/menu"))
        async def cmd_menu(message: Message) -> None:
            if not self._is_allowed(message):
                return
            text, kb = self.menu_payload()
            kwargs = {}
            if kb is not None:
                kwargs["reply_markup"] = kb

            chat_id = message.chat.id
            last_msg_id = None
            if self.memory is not None:
                try:
                    raw_id = await self.memory.kv_get(f"menu_msg:{chat_id}")
                    if raw_id:
                        last_msg_id = int(raw_id)
                except Exception:
                    pass

            edited = False
            if last_msg_id and self.bot is not None:
                try:
                    await self.bot.edit_message_text(
                        text, chat_id=chat_id, message_id=last_msg_id,
                        parse_mode="HTML", **kwargs
                    )
                    edited = True
                except Exception:
                    pass

            if not edited:
                sent = await message.answer(text, parse_mode="HTML", **kwargs)
                if self.memory is not None and sent:
                    try:
                        await self.memory.kv_set(f"menu_msg:{chat_id}", str(sent.message_id))
                    except Exception:
                        pass

        @dp.message(F.text.startswith("/help"))
        async def cmd_help(message: Message) -> None:
            if not self._is_allowed(message):
                return
            parts = (message.text or "").strip().split(maxsplit=1)
            if len(parts) > 1:
                topic = parts[1].strip().lstrip("/").lower()
                help_dict = {
                    "start": "<b>/start</b>: Khởi động bot và hiển thị lời chào kèm các phím tắt chính.",
                    "help": "<b>/help [lệnh]</b>: Xem danh sách lệnh đầy đủ hoặc cách dùng một lệnh cụ thể.",
                    "menu": "<b>/menu</b>: Mở bảng điều khiển Mini App tiện lợi trên Telegram.",
                    "status": "<b>/status</b>: Xem trạng thái các dịch vụ, tiến trình, model và bộ nhớ.",
                    "model": "<b>/model [tên_model]</b>: Xem hoặc đổi model AI.\n• <code>/model session &lt;tên&gt;</code>: Đổi model riêng cho phiên này\n• <code>/model tier &lt;brain|cheap|escalated&gt; &lt;tên&gt;</code>: Cấu hình từng tầng model\n• <code>/model reset</code>: Xóa ghi đè phiên",
                    "upcoming": "<b>/upcoming</b> (alias: <code>/lich</code>, <code>/saptol</code>): Xem lịch hẹn, nhắc nhở và bài feed chủ động sắp tới.",
                    "cancel": "<b>/cancel</b> (alias: <code>/stop</code>): Dừng ngay tác vụ agent hoặc lượt xử lý đang chạy.",
                    "new": "<b>/new</b>: Chốt phiên hiện tại, xóa bộ nhớ đệm và bắt đầu ngữ cảnh hội thoại mới.",
                    "goals": "<b>/goals</b>: Xem danh sách các mục tiêu dài hạn (Goals) đang theo dõi.",
                    "vault": "<b>/vault [nhãn]</b>: Nhập API key hoặc mật khẩu bảo mật vào kho lưu trữ an toàn.",
                    "setup": "<b>/setup</b>: Xem và quản lý cấu hình bản cài đặt, allowlist người dùng, hoặc thiết lập API kết nối sống (<code>/setup api &lt;url&gt; &lt;key&gt;</code>).",
                    "restart": "<b>/restart</b>: Khởi động lại tiến trình bot an toàn.",
                    "memory": "<b>/memory</b>: Xem tóm tắt có cấu trúc về các sự kiện và ký ức dài hạn của người dùng.",
                    "quyen": "<b>/quyen</b>: Xem chi tiết các chính sách phân quyền thực thi của agent.",
                    "library": "<b>/library [từ_khóa]</b>: Tìm kiếm và xem tài liệu, hình ảnh, media trong Thư viện.",
                    "ideas": "<b>/ideas</b>: Xem và kích hoạt các thẻ ý tưởng chủ động do bot đề xuất.",
                }
                if topic in help_dict:
                    await message.answer(help_dict[topic], parse_mode="HTML")
                    return
                await message.answer(
                    f"Không có hướng dẫn chi tiết cho lệnh <code>/{topic}</code>. Gõ <code>/help</code> để xem danh sách lệnh chung.",
                    parse_mode="HTML"
                )
                return
            is_dev = getattr(self.cfg, "dev_mode", False) or getattr(self.cfg, "enable_dev_commands", False) or getattr(self.cfg, "debug", False)
            await message.answer(format_help_text(is_dev=is_dev), parse_mode="HTML")

        @dp.callback_query(F.data.startswith("appr:"))
        async def on_approval_button(query: CallbackQuery) -> None:
            user_id = query.from_user.id if query.from_user else 0
            ok, note = await self.handle_approval_callback(
                query.data or "", user_id)
            try:
                await query.answer(
                    note, show_alert=(user_id
                                      != self.cfg.allowed_user_id))
            except Exception:
                pass
            if query.message:
                try:
                    if not ok:
                        await query.message.edit_reply_markup(reply_markup=None)
                    else:
                        parts = (query.data or "").split(":")
                        code = parts[1] if len(parts) > 1 else ""
                        approved = code in ("1", "2")
                        status_str = "ĐÃ DUYỆT" if approved else "ĐÃ CHẶN"
                        if code == "2":
                            status_str += " (VÀ NHỚ CHO PHIÊN)"
                        orig_text = query.message.text or ""
                        new_text = orig_text + f"\n\n<b>[Quyết định: {status_str}]</b>"
                        await query.message.edit_text(new_text, parse_mode="HTML", reply_markup=None)
                except Exception:
                    pass

        @dp.callback_query(F.data.startswith("idea:"))
        async def on_idea_button(query: CallbackQuery) -> None:
            if not self.cfg.allowed_user_id or (query.from_user and query.from_user.id != self.cfg.allowed_user_id):
                await query.answer("Bạn không có quyền thao tác thẻ này.", show_alert=True)
                return
            parts = (query.data or "").split(":")
            if len(parts) != 3:
                await query.answer()
                return
            action, card_id_s = parts[1], parts[2]
            try:
                card_id = int(card_id_s)
            except ValueError:
                await query.answer()
                return
            ideas = self._svc("ideas")
            if ideas is None:
                await query.answer("Ideas chưa sẵn sàng.", show_alert=True)
                return
            if action == "do":
                res = await ideas.do_card(
                    card_id, session_key=f"agent:main:telegram:dm:{query.from_user.id}:topic:0"
                )
                if res.get("ok"):
                    await query.answer("Đã nhận làm luôn!")
                    try:
                        orig = query.message.text or ""
                        new_text = orig + f"\n\n<b>Đã nhận làm luôn!</b>\n• Goal #{res['goal_id']}\n• Task: <code>{res['task_id']}</code>"
                        await query.message.edit_text(new_text, parse_mode="HTML")
                    except Exception:
                        pass
                else:
                    await query.answer(res.get("error", "Lỗi"), show_alert=True)
            elif action == "bo":
                res = await ideas.dismiss(card_id)
                if res.get("ok"):
                    await query.answer("Đã bỏ qua thẻ này.")
                    try:
                        orig = query.message.text or ""
                        new_text = orig + "\n\n<i>Đã bỏ qua thẻ ý tưởng này.</i>"
                        await query.message.edit_text(new_text, parse_mode="HTML")
                    except Exception:
                        pass
                else:
                    await query.answer(res.get("error", "Lỗi"), show_alert=True)

        @dp.callback_query(F.data.startswith("feed:"))
        async def on_feed_button(query: CallbackQuery) -> None:
            if not self.cfg.allowed_user_id or (query.from_user and query.from_user.id != self.cfg.allowed_user_id):
                await query.answer()
                return
            data = query.data or ""
            msg = query.message
            if data == "feed:like":
                if self.memory is not None and msg:
                    try:
                        await self.memory.add_feed_signal(msg.chat.id, msg.message_id, "")
                    except Exception:
                        pass
                await query.answer("Đã ghi nhận quan tâm đề tài này!", show_alert=False)
            elif data == "feed:discuss":
                if not msg or not self.bot:
                    await query.answer()
                    return
                if self.memory is not None:
                    try:
                        await self.memory.add_feed_signal(msg.chat.id, msg.message_id, "")
                    except Exception:
                        pass
                chat_id = msg.chat.id
                main_tid = None
                topics = self._svc("topics")
                if topics is not None and self.memory is not None:
                    try:
                        mapping = await topics.get_map(self.memory, chat_id)
                        tid = topics.topic_for(mapping, "main")
                        # Topic General (Chung) của Forum có tid=1 nhưng Bot API không nhận thread_id=1
                        if tid and tid != 1:
                            main_tid = tid
                    except Exception:
                        pass

                try:
                    fwd_kwargs: dict[str, Any] = {
                        "chat_id": chat_id,
                        "from_chat_id": chat_id,
                        "message_id": msg.message_id,
                    }
                    if main_tid:
                        fwd_kwargs["message_thread_id"] = main_tid
                    await self.bot.forward_message(**fwd_kwargs)

                    guide_text = (
                        "<b>Thảo luận bài Feed:</b>\n"
                        "Ní muốn đào sâu góc nhìn nào, phân tích thêm số liệu, hay biến đề tài này thành kế hoạch hành động?"
                    )
                    send_kwargs: dict[str, Any] = {
                        "chat_id": chat_id,
                        "text": guide_text,
                        "parse_mode": "HTML",
                    }
                    if main_tid:
                        send_kwargs["message_thread_id"] = main_tid
                    await self.bot.send_message(**send_kwargs)

                    # ĐỒNG BỘ NGAY VÀO LỊCH SỬ CHAT CHÍNH (Context cho Agent hiểu khi thảo luận)
                    if self.memory is not None:
                        feed_content = (msg.text or msg.caption or "").strip()
                        main_session = (
                            f"agent:main:telegram:group:{chat_id}:topic:0"
                            if chat_id < 0
                            else f"agent:main:telegram:dm:{chat_id}:topic:0"
                        )
                        if main_tid and main_tid != 1:
                            main_session = f"agent:main:telegram:group:{chat_id}:topic:{main_tid}"
                        
                        await self.memory.get_or_create_session(main_session)
                        discuss_context = (
                            f"[BÀI VIẾT FEED VỪA CHUYỂN TIẾP ĐỂ THẢO LUẬN]:\n"
                            f"{feed_content}\n\n"
                            f"Thảo luận bài Feed: Ní muốn đào sâu góc nhìn nào, phân tích thêm số liệu, hay biến đề tài này thành kế hoạch hành động?"
                        )
                        await self.memory.append_message(
                            main_session,
                            "assistant",
                            discuss_context,
                            meta={"type": "feed_discuss", "feed_message_id": msg.message_id}
                        )

                    await query.answer("Đã chuyển tiếp bài sang Chat chính để thảo luận!", show_alert=False)
                except Exception as exc:
                    logger.warning("forward bài feed sang main lỗi: %s", exc)
                    await query.answer("Hãy qua Chat chính để cùng thảo luận nhé!", show_alert=True)

        @dp.message(F.web_app_data)
        async def on_web_app_data(message: Message) -> None:
            # Dự phòng: Mini App qua Direct Link KHÔNG có sendData
            # (mọi thao tác đi /api/*) — handler này chỉ phục vụ
            # nếu sau này có nút WebAppInfo ở DM gửi dữ liệu về.
            if not self._is_allowed(message):
                return
            try:
                data = json.loads(message.web_app_data.data or "{}")
            except Exception:
                data = {}
            if data.get("type") == "approve" and self.broker \
                    is not None:
                ok = self.broker.resolve(
                    str(data.get("id") or ""),
                    data.get("decision") != "deny",
                    remember=data.get("decision") == "approve_remember")
                await message.answer(
                    "Đã ghi quyết định duyệt." if ok
                    else "Thẻ duyệt đã xử lý/hết hạn.")
                return
            await message.answer("Đã nhận dữ liệu từ Mini App.")

        @dp.message(F.text.startswith("/status"))
        async def cmd_status(message: Message) -> None:
            if not self._is_allowed(message):
                return
            # CFIG-1: /status là lời thường cho người dùng —
            # không dump key cấu hình thô, không Markdown legacy.
            # Chi tiết kỹ thuật để ở --dry-run phía host.
            facts = await self.memory.active_facts(limit=1000)
            if getattr(self.memory, "vec_ready", False):
                recall_mode = "lai (vector + từ khóa)"
            else:
                recall_mode = "chỉ từ khóa (chưa có vector)"
            webapp_on = bool(self.cfg.webapp_url
                             and self.cfg.webapp_app_name)
            lines = [
                "Trạng thái Mulon",
                f"- Model đang dùng: {self.cfg.model_brain}",
                f"- Bộ nhớ: {recall_mode} · {len(facts)} fact "
                "đang hiệu lực",
                f"- Việc hẹn giờ (scheduler): "
                f"{'đang bật' if self.cfg.scheduler_enabled else 'đang tắt'}",
                f"- Chủ động (heartbeat): "
                f"{'đang bật' if await heartbeat_effective(self.memory, self.cfg) else 'đang tắt'}",
                f"- Chắt lọc ký ức nền: "
                f"{'đang bật' if self.cfg.consolidation_enabled else 'đang tắt'}",
                f"- Bảng điều khiển (Mini App): "
                f"{'đã cấu hình — mở bằng /menu' if webapp_on else 'chưa cấu hình'}",
            ]
            await message.answer("\n".join(lines))

        @dp.message(F.text.startswith("/new"))
        async def cmd_new(message: Message) -> None:
            if not self._is_allowed(message):
                return
            key = session_key_for(message)
            await self.batcher.flush_now(key)
            await self.memory.close_session(key)
            # Chốt phiên -> kích hoạt consolidation cho đúng phiên vừa
            # đóng (chạy nền, không bắt user chờ).
            if self.consolidator is not None:
                asyncio.create_task(self._consolidate_closed(key))
            current_tid = self._current_thread_id(message)
            extra_msg = ""
            if current_tid and current_tid > 1 and self.bot is not None and self.sidechats is not None:
                try:
                    res = await self.sidechats.close_current(
                        self.bot, self.memory, self._svc("topics"),
                        message.chat.id, current_tid)
                    if res.get("ok"):
                        extra_msg = f" và đóng chat phụ '{res['record']['title']}'"
                except Exception:
                    pass
            await message.answer(f"Đã chốt phiên{extra_msg}. Lượt sau bắt đầu ngữ cảnh mới.")

        @dp.message(F.text.startswith("/memory"))
        async def cmd_memory(message: Message) -> None:
            if not self._is_allowed(message):
                return
            facts = await self.memory.active_facts(limit=50)
            total_active = len(facts)
            try:
                cur = await self.memory.db.execute("SELECT COUNT(*) AS n FROM facts WHERE valid_to IS NULL")
                row = await cur.fetchone()
                if row:
                    total_active = row["n"]
            except Exception:
                pass

            subjects: dict[str, int] = {}
            for f in facts:
                subj = (f.get("subject") or "Chung").strip()
                subjects[subj] = subjects.get(subj, 0) + 1

            lines = [
                "<b>TỔNG QUAN BỘ NHỚ & TRI THỨC</b>",
                f"• Tổng số dữ kiện ghi nhớ (facts): <b>{total_active}</b>",
            ]
            if subjects:
                top_subjs = sorted(subjects.items(), key=lambda x: x[1], reverse=True)[:6]
                subj_str = ", ".join(f"{s} ({c})" for s, c in top_subjs)
                lines.append(f"• Chủ đề chính: {subj_str}")

            lines.append("\n<b>Ghi nhớ gần đây:</b>")
            if not facts:
                lines.append("<i>(Chưa có sự kiện nào được ghi nhớ)</i>")
            else:
                for f in facts[:8]:
                    prefix = f"<b>[{f['subject']}]</b> " if f.get("subject") else ""
                    lines.append(f"• #{f['id']} {prefix}{html.escape(f['fact'])}")

            if total_active > 8:
                lines.append(f"\n<i>... và còn {total_active - 8} dữ kiện khác.</i>")

            user_md = self.dossier.files.get("USER.md", "").strip() if getattr(self, "dossier", None) and hasattr(self.dossier, "files") else ""
            if user_md:
                u_lines = [l.strip() for l in user_md.splitlines() if l.strip() and not l.strip().startswith("#")][:3]
                if u_lines:
                    lines.append("\n<b>Hồ sơ cá nhân (USER.md):</b>")
                    for ul in u_lines:
                        lines.append(f"• {html.escape(ul)}")

            lines.append("\n<i>Mở Mini App (Hồ sơ → Ký ức) để tìm kiếm hoặc dùng /export_memory để xuất toàn bộ tệp.</i>")
            text = "\n".join(lines)
            for chunk in chunk_html(text):
                await message.answer(chunk, parse_mode="HTML")

        # ---------- Phase 6: bề mặt group (mục 16) ----------

        def _arg_text(message: Message) -> str:
            parts = (message.text or "").split(maxsplit=1)
            return parts[1].strip() if len(parts) > 1 else ""

        def _arg_int(message: Message) -> Optional[int]:
            parts = (message.text or "").split()
            if len(parts) >= 2:
                try:
                    return int(parts[1])
                except ValueError:
                    return None
            return None

        async def _answer_chunks(message: Message, text: str) -> None:
            # Formatter bề mặt trả TEXT THUẦN (NC-1: một quy ước
            # duy nhất) — escape rồi gửi HTML để nội dung lạ
            # (dấu <, &) không làm vỡ parse, hiển thị y như plain.
            for chunk in chunk_html(html.escape(text)):
                await message.answer(chunk, parse_mode="HTML")

        @dp.message(F.text.startswith("/setup_topics"))
        async def cmd_setup_topics(message: Message) -> None:
            if not self._is_allowed(message):
                return
            topics = self._svc("topics")
            if topics is None or self.bot is None:
                await message.answer(
                    "Bề mặt topic chưa được nối ở bản chạy này.")
                return
            is_forum = bool(getattr(message.chat, "is_forum", False))
            result = await topics.setup(
                self.bot, self.memory, message.chat.id, is_forum)
            if result.get("ok") and self.memory is not None:
                # Feed chủ động (1.4) lấy group này làm đích đăng.
                try:
                    await self.memory.kv_set(
                        "feed:group_chat_id", str(message.chat.id))
                except Exception as exc:
                    logger.warning("lưu group Feed lỗi: %s", exc)
            await _answer_chunks(
                message, surf.format_topics_result(result))

        @dp.message(F.text.startswith("/topics"))
        async def cmd_topics(message: Message) -> None:
            if not self._is_allowed(message):
                return
            topics = self._svc("topics")
            if topics is None:
                await message.answer(
                    "Bề mặt topic chưa được nối ở bản chạy này.")
                return
            mapping = await topics.get_map(self.memory, message.chat.id)
            await message.answer(surf.format_topics_map(mapping))

        # Đăng ký lệnh dài/cụ thể trước /chatphu vì filter là
        # startswith: /chatphu_list, /chatphu_dong, /chatphu_mo
        # không được rơi vào handler tạo mới.
        @dp.message(F.text.startswith("/chatphu_list"))
        async def cmd_chatphu_list(message: Message) -> None:
            if not self._is_allowed(message):
                return
            await message.answer(
                await self._chatphu_list_text(message))

        @dp.message(F.text.startswith("/chatphu_dong"))
        async def cmd_chatphu_dong(message: Message) -> None:
            if not self._is_allowed(message):
                return
            await message.answer(
                await self._chatphu_status_text(message, reopen=False))

        @dp.message(F.text.startswith("/chatphu_mo"))
        async def cmd_chatphu_mo(message: Message) -> None:
            if not self._is_allowed(message):
                return
            await message.answer(
                await self._chatphu_status_text(message, reopen=True))

        @dp.message(F.text.startswith("/dongchat"))
        async def cmd_dongchat(message: Message) -> None:
            if not self._is_allowed(message):
                return
            await message.answer(await self._dongchat_text(message))

        @dp.message(F.text.startswith("/chatphu"))
        async def cmd_chatphu(message: Message) -> None:
            if not self._is_allowed(message):
                return
            await message.answer(
                await self._chatphu_create_text(message))

        @dp.message(F.text.startswith("/feedbrief"))
        async def cmd_feedbrief(message: Message) -> None:
            if not self._is_allowed(message):
                return
            feed = self._svc("feed")
            if feed is None:
                await message.answer("Feed chưa được nối ở bản này.")
                return
            brief = _arg_text(message)
            if not brief:
                await message.answer(
                    "Brief Feed hiện tại:\n" + feed.read_brief()
                    + "\n\nSửa bằng: /feedbrief <nội dung mới>")
                return
            feed.set_brief(brief)
            await message.answer(
                "Đã cập nhật brief Feed. Bài Feed tự chạy theo "
                "lịch sẽ viết theo brief mới.")

        @dp.message(F.text.startswith("/feedsources"))
        async def cmd_feedsources(message: Message) -> None:
            if not self._is_allowed(message):
                return
            feed = self._svc("feed")
            if feed is None:
                await message.answer("Feed chưa được nối ở bản này.")
                return
            arg = _arg_text(message)
            sources = feed.read_sources()
            if not arg:
                if not sources:
                    text = ("Chưa ghim nguồn bổ sung nào. Feed vẫn "
                            "tự tìm kiếm nguồn tin cậy theo chủ đề "
                            "mỗi lượt — danh sách ghim chỉ là phụ.\n"
                            "Thêm: /feedsources add <url> | <nhãn> "
                            "| <high|normal|low>")
                else:
                    rows = []
                    for s in sources:
                        state = "" if s.get("enabled", True) \
                            else " (đang tắt)"
                        rows.append(
                            f"- {s['url']} | {s.get('label') or ''} "
                            f"| tin cậy {s.get('trust') or 'normal'}"
                            f"{state}")
                    text = ("Nguồn bổ sung đã ghim (Feed vẫn tự "
                            "tìm kiếm là chính):\n" + "\n".join(rows)
                            + "\n\nXoá: /feedsources remove <url>")
                await message.answer(text)
                return
            low_arg = arg.lower()
            if low_arg.startswith("add "):
                parts = [p.strip() for p in
                         arg[4:].split("|")]
                url = parts[0] if parts else ""
                if not url.startswith(("http://", "https://")):
                    await message.answer(
                        "URL nguồn phải bắt đầu http:// hoặc "
                        "https://.")
                    return
                if any(s["url"] == url for s in sources):
                    await message.answer("Nguồn này đã ghim rồi.")
                    return
                trust = "normal"
                if len(parts) > 2 and parts[2].lower() in (
                        "high", "normal", "low"):
                    trust = parts[2].lower()
                sources.append({
                    "url": url,
                    "label": parts[1] if len(parts) > 1 else "",
                    "trust": trust, "enabled": True})
                feed.set_sources(sources)
                await message.answer(f"Đã ghim nguồn: {url}")
                return
            if low_arg.startswith("remove "):
                url = arg[7:].strip()
                kept = [s for s in sources if s["url"] != url]
                if len(kept) == len(sources):
                    await message.answer("Không thấy nguồn đó.")
                    return
                feed.set_sources(kept)
                await message.answer(f"Đã bỏ ghim nguồn: {url}")
                return
            await message.answer(
                "Dùng: /feedsources (xem) · /feedsources add "
                "<url> | <nhãn> | <trust> · /feedsources remove "
                "<url>")

        # /feed_now: handler ẨN tương thích (1.4 rút khỏi menu
        # lệnh — Feed tự chạy theo lịch; giữ để thói quen cũ
        # không vỡ, bài qua đường này ghi origin 'manual').
        @dp.message(F.text.startswith("/feed_now"))
        async def cmd_feed_now(message: Message) -> None:
            if not self._is_allowed(message):
                return
            feed = self._svc("feed")
            if feed is None or self.bot is None:
                await message.answer("Feed chưa được nối ở bản này.")
                return
            thread = await self._topic_thread(message, "feed")
            try:
                result = await feed.publish(
                    self.bot, message.chat.id, thread)
            except Exception as exc:
                logger.warning("feed_now lỗi: %s", exc)
                await message.answer(
                    "Sinh bài Feed lỗi (model/proxy) — thử lại sau.")
                return
            if result.get("ok"):
                if thread != getattr(message, "message_thread_id",
                                     None):
                    await message.answer(
                        f"Đã đăng bài Feed mới (post "
                        f"#{result['post_id']}) vào topic Feed.")
            else:
                await message.answer(
                    f"Chưa đăng được bài Feed: {result.get('error')}")

        @dp.message(F.text.startswith("/ideas"))
        async def cmd_ideas(message: Message) -> None:
            if not self._is_allowed(message):
                return
            ideas = self._svc("ideas")
            if ideas is None or self.bot is None:
                await message.answer("Ideas chưa được nối ở bản này.")
                return
            try:
                cards = await ideas.generate()
            except Exception as exc:
                logger.warning("ideas lỗi: %s", exc)
                await message.answer(
                    "Sinh ý tưởng lỗi (model/proxy) — thử lại sau.")
                return
            thread = await self._topic_thread(message, "ideas")
            if not cards:
                await message.answer(
                    "Chưa sinh được thẻ ý tưởng nào từ dữ liệu "
                    "hiện có.")
                return
            kwargs = {}
            if thread:
                kwargs["message_thread_id"] = thread
            for card in cards:
                await self.bot.send_message(
                    message.chat.id,
                    format_idea_card(card),
                    reply_markup=idea_card_keyboard(card["id"]),
                    **kwargs,
                )
            if thread != getattr(message, "message_thread_id", None):
                await message.answer(
                    f"Đã đăng {len(cards)} thẻ ý tưởng vào topic "
                    "Ideas.")

        @dp.message(F.text.startswith("/goal"))
        async def cmd_goal_router(message: Message) -> None:
            if not self._is_allowed(message):
                return
            if self.memory is None or self.bot is None:
                return
            raw_text = (message.text or "").strip()
            parts = raw_text.split()
            cmd = parts[0].lower() if parts else "/goal"
            subcmd = parts[1].lower() if len(parts) > 1 else ""

            # Hỗ trợ /goal_close, /goal_create, /goal_update, /goal_briefing
            if cmd == "/goal_close":
                subcmd = "close"
                parts = ["/goal", "close"] + parts[1:]
            elif cmd == "/goal_create":
                subcmd = "create"
                parts = ["/goal", "create"] + parts[1:]
            elif cmd == "/goal_update":
                subcmd = "update"
                parts = ["/goal", "update"] + parts[1:]
            elif cmd == "/goal_briefing":
                subcmd = "briefing"
                parts = ["/goal", "briefing"] + parts[1:]

            thread = await self._topic_thread(message, "goals")
            kwargs = {}
            if thread:
                kwargs["message_thread_id"] = thread

            if subcmd in ("create", "new", "add"):
                args_str = raw_text[raw_text.lower().find(subcmd) + len(subcmd):].strip()
                parent_id = None
                desc = ""
                parent_match = re.search(r'(?:--parent|-p)\s+(\d+)', args_str, re.IGNORECASE)
                if parent_match:
                    parent_id = int(parent_match.group(1))
                    args_str = args_str[:parent_match.start()] + args_str[parent_match.end():]
                desc_match = re.search(r'(?:--desc|-d)\s+(?:"([^"]+)"|\'([^\']+)\'|(\S+))', args_str, re.IGNORECASE)
                if desc_match:
                    desc = desc_match.group(1) or desc_match.group(2) or desc_match.group(3) or ""
                    args_str = args_str[:desc_match.start()] + args_str[desc_match.end():]
                title = args_str.strip()
                if not title:
                    await message.answer("[Lưu ý] Cú pháp: <code>/goal create &lt;tiêu đề&gt; [--parent &lt;id&gt;] [--desc &lt;mô tả&gt;]</code>", parse_mode="HTML")
                    return
                try:
                    goal = await self.memory.create_goal(title=title, description=desc, parent_id=parent_id)
                    if parent_id:
                        parent = await self.memory.get_goal(parent_id)
                        p_title = parent['title'] if parent else str(parent_id)
                        text = (
                            f"<b>Đã tạo mục tiêu con (Subgoal) thành công!</b>\n"
                            f"• Mã: <code>#{goal['id']}</code>\n"
                            f"• Tiêu đề: <b>{html.escape(goal['title'])}</b>\n"
                            f"• Trực thuộc mục tiêu cha: <b>{html.escape(p_title)}</b> (<code>#{parent_id}</code>)\n\n"
                            f"<i>Xem toàn bộ cây mục tiêu: /goals</i>"
                        )
                    else:
                        text = (
                            f"<b>Đã tạo mục tiêu (Goal) thành công!</b>\n"
                            f"• Mã: <code>#{goal['id']}</code>\n"
                            f"• Tiêu đề: <b>{html.escape(goal['title'])}</b>\n\n"
                            f"<i>Xem toàn bộ cây mục tiêu: /goals</i>"
                        )
                    await self.bot.send_message(message.chat.id, text, parse_mode="HTML", **kwargs)
                except ValueError as exc:
                    await message.answer(f"Không tạo được mục tiêu: {exc}")
                return

            elif subcmd in ("close", "done"):
                goal_id = None
                for p in parts[2:]:
                    p_clean = p.lstrip("#")
                    if p_clean.isdigit():
                        goal_id = int(p_clean)
                        break
                if goal_id is None:
                    await message.answer("[Lưu ý] Cú pháp: <code>/goal close &lt;id&gt;</code>", parse_mode="HTML")
                    return
                target_goal = await self.memory.get_goal(goal_id)
                if not target_goal:
                    await message.answer(f"Không tìm thấy mục tiêu #{goal_id}")
                    return
                parent_id = target_goal.get("parent_id")
                closed = await self.memory.close_goal(goal_id)
                if closed is None:
                    await message.answer(f"Mục tiêu #{goal_id} đã ở trạng thái hoàn thành từ trước.")
                    return
                if parent_id:
                    parent_detail = await self.memory.get_goal_detail(parent_id)
                    prog_label = parent_detail["progress"]["progress_label"] if parent_detail else "đã cập nhật"
                    text = (
                        f"<b>Đã hoàn thành mục tiêu con (Subgoal) #{goal_id}!</b>\n"
                        f"• Tiêu đề: <b>{html.escape(target_goal['title'])}</b>\n"
                        f"• Tiến độ mục tiêu cha (#{parent_id}): <b>{html.escape(prog_label)}</b>\n\n"
                        f"<i>Xem toàn bộ cây mục tiêu: /goals</i>"
                    )
                else:
                    text = (
                        f"<b>Đã hoàn thành mục tiêu #{goal_id}!</b>\n"
                        f"• Tiêu đề: <b>{html.escape(target_goal['title'])}</b>\n\n"
                        f"<i>Xem toàn bộ cây mục tiêu: /goals</i>"
                    )
                await self.bot.send_message(message.chat.id, text, parse_mode="HTML", **kwargs)
                return

            elif subcmd in ("update", "edit"):
                goal_id = None
                for p in parts[2:]:
                    p_clean = p.lstrip("#")
                    if p_clean.isdigit():
                        goal_id = int(p_clean)
                        break
                if goal_id is None:
                    await message.answer("[Lưu ý] Cú pháp: <code>/goal update &lt;id&gt; [--title ...] [--desc ...] [--state ...]</code>", parse_mode="HTML")
                    return
                args_str = raw_text[raw_text.find(str(goal_id)) + len(str(goal_id)):].strip()
                new_title = None
                new_desc = None
                new_state = None
                t_match = re.search(r'(?:--title|-t)\s+(?:"([^"]+)"|\'([^\']+)\'|(\S+))', args_str)
                if t_match:
                    new_title = t_match.group(1) or t_match.group(2) or t_match.group(3)
                d_match = re.search(r'(?:--desc|-d)\s+(?:"([^"]+)"|\'([^\']+)\'|(\S+))', args_str)
                if d_match:
                    new_desc = d_match.group(1) or d_match.group(2) or d_match.group(3)
                s_match = re.search(r'(?:--state|-s)\s+(?:"([^"]+)"|\'([^\']+)\'|(\S+))', args_str)
                if s_match:
                    new_state = s_match.group(1) or s_match.group(2) or s_match.group(3)
                if not (new_title or new_desc or new_state):
                    new_state = args_str.strip()
                try:
                    updated = await self.memory.update_goal(
                        goal_id=goal_id, title=new_title, description=new_desc, current_state=new_state
                    )
                    if updated is None:
                        await message.answer(f"Không tìm thấy goal #{goal_id}")
                        return
                    await message.answer(f"Đã cập nhật mục tiêu #{goal_id}: <b>{html.escape(updated['title'])}</b>", parse_mode="HTML")
                except ValueError as exc:
                    await message.answer(f"Lỗi cập nhật mục tiêu: {exc}")
                return

            elif subcmd in ("briefing", "letter"):
                goal_id = None
                for p in parts[2:]:
                    p_clean = p.lstrip("#")
                    if p_clean.isdigit():
                        goal_id = int(p_clean)
                        break
                if goal_id is None:
                    await message.answer("[Lưu ý] Cú pháp: <code>/goal briefing &lt;id&gt;</code>", parse_mode="HTML")
                    return
                from .goal_briefing import GoalBriefingService
                svc = GoalBriefingService(self.cfg, self.memory, getattr(self, "gateway", None))
                try:
                    briefing = await svc.generate_briefing(goal_id)
                    text = f"<b>THƯ BRIEFING MỤC TIÊU #{goal_id}</b>\n\n{html.escape(briefing['letter_body'])}"
                    await self.bot.send_message(message.chat.id, text, parse_mode="HTML", **kwargs)
                except Exception as exc:
                    await message.answer(f"Lỗi tạo thư briefing: {exc}")
                return

            # Mặc định: Hiển thị cây Goal phân cấp kèm subgoals và tiến triển thật
            from .planning import ensure_seed_goals
            await ensure_seed_goals(self.memory)
            tree = await self.memory.get_goal_tree()
            lines = ["<b>Mục tiêu đang theo dõi (Goals)</b>\n"]
            if not tree:
                lines.append("<i>Chưa có mục tiêu nào. Tạo bằng: /goal create &lt;tiêu đề&gt;</i>")
            for g in tree:
                cat = g.get("category") or "productivity"
                kind = g.get("goal_kind") or "outcome"
                curr = g.get("current_state") or "Đang theo dõi"
                prog = g.get("progress") or {}
                prog_label = prog.get("progress_label") or "0%"
                is_done = g.get("status") == "completed"
                st_icon = "✓ Đã xong" if is_done else "Đang chạy"

                lines.append(
                    f"▫️ <b>{html.escape(g['title'])}</b> (#{g['id']} · <i>{cat} / {kind}</i>)\n"
                    f"   <b>Tiến triển:</b> <code>{html.escape(prog_label)}</code> · <i>{st_icon}</i>\n"
                    f"   <b>Trạng thái:</b> <i>{html.escape(curr)}</i>"
                )

                subgoals = g.get("subgoals") or []
                if subgoals:
                    for idx, sub in enumerate(subgoals):
                        branch = "└─" if idx == len(subgoals) - 1 else "├─"
                        sub_done = sub.get("status") == "completed"
                        sub_icon = "✓ Đã xong" if sub_done else "⏳ Đang chạy"
                        lines.append(
                            f"   {branch} ▫️ <b>{html.escape(sub['title'])}</b> (#{sub['id']} · <i>{sub_icon}</i>)"
                        )

                briefings = g.get("briefings") or []
                if briefings:
                    b = briefings[0]
                    lines.append(f"   <i>Thư briefing #{b['id']}: {html.escape(b.get('progress_summary', '')[:80])}...</i>")
                lines.append("")

            lines.append("<i>Lệnh: /goal create &lt;tiêu đề&gt; [--parent &lt;id&gt;], /goal update &lt;id&gt;, /goal close &lt;id&gt;, /goal briefing &lt;id&gt;</i>")
            text = "\n".join(lines)
            await self.bot.send_message(message.chat.id, text, parse_mode="HTML", **kwargs)
            if thread != getattr(message, "message_thread_id", None):
                await message.answer("Đã gửi danh sách mục tiêu vào topic Goals.")

        @dp.message(F.text.startswith("/idea_do"))
        async def cmd_idea_do(message: Message) -> None:
            if not self._is_allowed(message):
                return
            ideas = self._svc("ideas")
            card_id = _arg_int(message)
            if ideas is None or card_id is None:
                await message.answer("Dùng: /idea_do <id thẻ>")
                return
            result = await ideas.do_card(
                card_id, session_key=session_key_for(message))
            if result.get("ok"):
                await message.answer(
                    f"Đã làm luôn thẻ #{card_id}: tạo goal "
                    f"#{result['goal_id']} + task {result['task_id']}.")
            else:
                await message.answer(result.get("error", "Lỗi."))

        @dp.message(F.text.startswith("/idea_bo"))
        async def cmd_idea_bo(message: Message) -> None:
            if not self._is_allowed(message):
                return
            ideas = self._svc("ideas")
            card_id = _arg_int(message)
            if ideas is None or card_id is None:
                await message.answer("Dùng: /idea_bo <id thẻ>")
                return
            result = await ideas.dismiss(card_id)
            await message.answer(
                f"Đã bỏ qua thẻ #{card_id}."
                if result.get("ok")
                else result.get("error", "Lỗi."))

        @dp.message(F.text.startswith("/notes"))
        async def cmd_notes(message: Message) -> None:
            if not self._is_allowed(message):
                return
            notes = await self.memory.list_proactive_notes(
                status="pending", limit=20)
            await _answer_chunks(
                message, surf.format_notes_list(notes))

        async def _note_decide(message: Message, status: str) -> None:
            note_id = _arg_int(message)
            if note_id is None:
                await message.answer(
                    "Dùng: /note_ok <id> hoặc /note_bo <id>")
                return
            ok = await self.memory.set_proactive_note_status(
                note_id, status)
            if ok:
                await self.memory.log_trajectory(
                    session_key_for(message), "proactive_note_decided",
                    {"note_id": note_id, "status": status,
                     "via": "command"})
                await message.answer(
                    f"Đã {'duyệt' if status == 'sent' else 'bỏ'} "
                    f"đề xuất #{note_id}.")
            else:
                await message.answer(
                    f"Không đổi được đề xuất #{note_id} "
                    "(không tồn tại?).")

        @dp.message(F.text.startswith("/note_ok"))
        async def cmd_note_ok(message: Message) -> None:
            if not self._is_allowed(message):
                return
            await _note_decide(message, "sent")

        @dp.message(F.text.startswith("/note_bo"))
        async def cmd_note_bo(message: Message) -> None:
            if not self._is_allowed(message):
                return
            await _note_decide(message, "dismissed")

        @dp.message(F.text.startswith("/library"))
        async def cmd_library(message: Message) -> None:
            if not self._is_allowed(message):
                return
            library = self._svc("library")
            if library is None:
                await message.answer(
                    "Library chưa được nối ở bản chạy này.")
                return

            text = (message.text or "").strip()
            parts = text.split()
            # 1. Nếu người dùng gõ /library <id>, vd: /library 6 hoặc /library@Mulon_bot 6
            if len(parts) > 1 and parts[1].isdigit():
                target_id = int(parts[1])
                item = await library.get_item(target_id)
                if not item or item.get("status") == "trashed":
                    await message.answer(f"Không tìm thấy mục #{target_id} trong Thư viện.")
                    return
                p = Path(item["path"])
                if not p.exists():
                    await message.answer(f"Tệp của mục #{target_id} không còn tồn tại trên máy.")
                    return
                max_bytes = getattr(self.cfg, "telegram_max_file_size_bytes", 52428800)
                if p.stat().st_size > max_bytes:
                    await message.answer(
                        f"[Lưu ý] Tệp #{item['id']} ({p.stat().st_size / (1024*1024):.1f} MB) vượt quá giới hạn "
                        f"{max_bytes // (1024*1024)}MB của Telegram Bot API. "
                        f"Tệp đang nằm tại: <code>{html.escape(str(p))}</code>.",
                        parse_mode="HTML"
                    )
                    return
                ext = p.suffix.lower()
                caption = f"#{item['id']} • {item['name']}"
                try:
                    if item.get("kind") == "image" or ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
                        await message.answer_photo(photo=FSInputFile(str(p)), caption=caption)
                    elif ext in (".mp4", ".mov", ".avi", ".webm", ".mkv"):
                        await message.answer_video(video=FSInputFile(str(p)), caption=caption)
                    elif ext in (".ogg",):
                        await message.answer_voice(voice=FSInputFile(str(p)), caption=caption)
                    elif item.get("kind") == "media" or ext in (".mp3", ".wav", ".m4a", ".flac", ".aac"):
                        await message.answer_audio(audio=FSInputFile(str(p)), caption=caption)
                    else:
                        await message.answer_document(document=FSInputFile(str(p)), caption=caption)
                except Exception as e:
                    await message.answer(f"[Lưu ý] Lỗi khi gửi tệp #{target_id} qua Telegram: {e}")
                return

            # 2. Nếu người dùng gõ /library <từ khóa>, tìm kiếm bằng ngôn ngữ tự nhiên
            if len(parts) > 1 and not parts[1].isdigit():
                query = text.split(None, 1)[1].strip()
                results = await library.search(query)
                from .library import format_library_list
                if not results:
                    await message.answer(
                        f"Không tìm thấy tệp nào trong Thư viện khớp với: <i>{html.escape(query)}</i>",
                        parse_mode="HTML"
                    )
                else:
                    await message.answer(
                        format_library_list(results, title=f"<b>Kết quả tìm kiếm Thư viện cho '{html.escape(query)}' ({len(results)} mục):</b>\n"),
                        parse_mode="HTML"
                    )
                return

            # 3. Nếu người dùng gọi /library để duyệt thư viện
            await library.scan()
            items = await library.list_items(status="active")
            from .library import format_library_list
            if not items:
                await message.answer(format_library_list(items))
                return

            # Gửi xem trước các hình ảnh gần nhất thành Album ảnh trực quan
            image_items = [
                it for it in items
                if (it.get("kind") == "image" or Path(it.get("path", "")).suffix.lower() in (".jpg", ".jpeg", ".png", ".webp"))
                and Path(it.get("path", "")).exists()
            ]
            if len(image_items) > 1:
                recent = image_items[-6:]  # Tối đa 6 ảnh mới nhất
                media_group = [
                    InputMediaPhoto(
                        media=FSInputFile(it["path"]),
                        caption=(f"Thư viện ảnh Mulon ({len(image_items)} ảnh) • #{it['id']} {it['name']}"
                                 if idx == 0 else f"#{it['id']} {it['name']}")
                    )
                    for idx, it in enumerate(recent)
                ]
                try:
                    await message.answer_media_group(media=media_group)
                except Exception as e:
                    logger.warning("Gửi media group thất bại: %s", e)
            elif len(image_items) == 1:
                it = image_items[0]
                try:
                    await message.answer_photo(
                        photo=FSInputFile(it["path"]),
                        caption=f"#{it['id']} {it['name']}"
                    )
                except Exception as e:
                    logger.warning("Gửi ảnh đơn thất bại: %s", e)

            # Gửi danh sách tóm tắt có icon đẹp mắt và nút mở Mini App
            kb = None
            direct_url = webapp_direct_link(self.cfg, self._bot_username(), "panel")
            if direct_url:
                kb = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="Mở Bảng điều khiển (Mini App)", url=direct_url)
                ]])

            await message.answer(format_library_list(items), parse_mode="HTML", reply_markup=kb)

        async def _library_action(message: Message, action: str) -> None:
            library = self._svc("library")
            item_id = _arg_int(message)
            if library is None or item_id is None:
                await message.answer(
                    f"Dùng: /{action} <id item> (xem /library)")
                return
            if action == "trash_item":
                result = await library.trash_item(item_id)
                text = (f"Đã chuyển item #{item_id} vào thùng rác "
                        f"(khôi phục trong "
                        f"{self.cfg.library_trash_days} ngày bằng "
                        f"/restore_item {item_id})."
                        if result.get("ok")
                        else result.get("error", "Lỗi."))
            elif action == "restore_item":
                result = await library.restore_item(item_id)
                text = (f"Đã khôi phục item #{item_id} về "
                        f"{result.get('path')}."
                        if result.get("ok")
                        else result.get("error", "Lỗi."))
            elif action == "pin_item":
                result = await library.pin_item(item_id, pinned=True)
                text = (f"Đã ghim item #{item_id} lên đầu Thư viện."
                        if result.get("ok")
                        else result.get("error", "Lỗi."))
            elif action == "rename_item":
                parts = (message.text or "").split(None, 2)
                new_name = parts[2].strip() if len(parts) > 2 else ""
                if not new_name:
                    text = f"Dùng: /rename_item {item_id} <tên mới>"
                else:
                    result = await library.rename_item(item_id, new_name)
                    text = (f"Đã đổi tên item #{item_id} thành '{new_name}'."
                            if result.get("ok")
                            else result.get("error", "Lỗi."))
            else:  # share_item
                result = await library.share_item(item_id)
                if not result.get("ok"):
                    text = result.get("error", "Lỗi.")
                elif result.get("share_url"):
                    text = (f"Item #{item_id} ({result.get('name', '')}): "
                            f"link chia sẻ (hết hạn {result['share_expires_at']}):\n"
                            f"{result['share_url']}")
                else:
                    text = (f"Item #{item_id}: chia sẻ ở trạng thái "
                            f"'chờ host', hết hạn {result['share_expires_at']}. "
                            + result.get("note", ""))
            await message.answer(text)

        @dp.message(F.text.startswith("/trash_item"))
        async def cmd_trash_item(message: Message) -> None:
            if not self._is_allowed(message):
                return
            await _library_action(message, "trash_item")

        @dp.message(F.text.startswith("/restore_item"))
        async def cmd_restore_item(message: Message) -> None:
            if not self._is_allowed(message):
                return
            await _library_action(message, "restore_item")

        @dp.message(F.text.startswith("/share_item"))
        async def cmd_share_item(message: Message) -> None:
            if not self._is_allowed(message):
                return
            await _library_action(message, "share_item")

        @dp.message(F.text.startswith("/pin_item"))
        async def cmd_pin_item(message: Message) -> None:
            if not self._is_allowed(message):
                return
            await _library_action(message, "pin_item")

        @dp.message(F.text.startswith("/rename_item"))
        async def cmd_rename_item(message: Message) -> None:
            if not self._is_allowed(message):
                return
            await _library_action(message, "rename_item")


        @dp.message(F.text.startswith("/restart"))
        async def cmd_restart(message: Message) -> None:
            if not self._is_allowed(message):
                return
            await message.answer("<b>Đang khởi động lại bot Mulon...</b>", parse_mode="HTML")
            if self.memory is not None:
                try:
                    import json
                    await self.memory.kv_set("system:restart_notify", json.dumps({
                        "chat_id": message.chat.id,
                        "thread_id": getattr(message, "message_thread_id", None),
                        "reason": "Yêu cầu từ lệnh /restart",
                    }))
                except Exception:
                    pass
            import sys, os, threading, time
            def _reexec():
                time.sleep(1.0)
                logger.warning("cmd_restart: re-exec bot process theo yêu cầu user")
                python = sys.executable
                os.execv(python, [python, "-m", "mulon.main"])
            threading.Thread(target=_reexec, daemon=True, name="bot-restart").start()

        @dp.message(F.text.startswith("/model"))
        async def cmd_model(message: Message) -> None:
            if not self._is_allowed(message):
                return
            key = session_key_for(message)
            session_model = None
            if self.memory is not None:
                try:
                    session_model = await self.memory.kv_get(f"session_model:{key}")
                except Exception:
                    pass

            text_raw = (message.text or "").strip()
            args = text_raw.split()[1:] if len(text_raw.split()) > 1 else []

            brain = getattr(self.cfg, "model_brain", "gemini-3.8-flash")
            cheap = getattr(self.cfg, "model_cheap", "gemini-3.5-flash-lite")
            escalated = getattr(self.cfg, "model_escalated", "grok-4.20-0309-reasoning")

            if not args:
                session_line = f"• <b>Phiên này:</b> <code>{session_model}</code> (ghi đè riêng)\n" if session_model else f"• <b>Phiên này:</b> Dùng theo hệ thống (<code>{brain}</code>)\n"
                await message.answer(
                    "<b>CẤU HÌNH MODEL AI</b>\n\n"
                    "<b>Các tầng model hệ thống (3 tiers):</b>\n"
                    f"• <b>Brain (chính):</b> <code>{brain}</code>\n"
                    f"• <b>Cheap (nhẹ/tóm tắt):</b> <code>{cheap}</code>\n"
                    f"• <b>Escalated (phức tạp/bế tắc):</b> <code>{escalated}</code>\n\n"
                    "<b>Model hiệu lực:</b>\n"
                    f"{session_line}\n"
                    "• <b>Cú pháp đổi model:</b>\n"
                    "• <code>/model &lt;tên_model&gt;</code>: Đổi model Brain toàn cục\n"
                    "• <code>/model session &lt;tên_model&gt;</code>: Đổi model chỉ cho riêng phiên/topic này\n"
                    "• <code>/model tier &lt;brain|cheap|escalated&gt; &lt;tên_model&gt;</code>: Đổi tầng model cụ thể\n"
                    "• <code>/model reset</code>: Xóa ghi đè phiên, về mặc định\n\n"
                    "<b>Gợi ý model phổ biến:</b>\n"
                    "• <code>claude-3-7-sonnet-20250219</code>\n"
                    "• <code>claude-3-5-haiku-20241022</code>\n"
                    "• <code>gemini-3.8-flash</code>\n"
                    "• <code>gemini-3.5-flash-lite</code>\n"
                    "• <code>grok-4.20-0309-reasoning</code>\n"
                    "• <code>openai/muse/muse-spark</code>",
                    parse_mode="HTML"
                )
                return

            subcmd = args[0].lower()
            if subcmd == "reset":
                if self.memory is not None:
                    try:
                        await self.memory.kv_del(f"session_model:{key}")
                    except Exception:
                        pass
                await message.answer(
                    f"<b>Đã xóa ghi đè model phiên này.</b>\nPhiên quay về dùng model mặc định: <code>{brain}</code>",
                    parse_mode="HTML"
                )
                return

            if subcmd == "session":
                if len(args) < 2:
                    await message.answer("Cú pháp: <code>/model session &lt;tên_model&gt;</code>", parse_mode="HTML")
                    return
                target_model = args[1].strip()
                if self.memory is not None:
                    try:
                        await self.memory.kv_set(f"session_model:{key}", target_model)
                    except Exception as exc:
                        logger.warning("Lưu session model lỗi: %s", exc)
                await message.answer(
                    f"<b>Đã đổi model cho riêng phiên này:</b> <code>{target_model}</code>\n"
                    f"(Các phiên khác vẫn dùng cấu hình mặc định. Dùng <code>/model reset</code> để hủy)",
                    parse_mode="HTML"
                )
                return

            if subcmd == "tier":
                if len(args) < 3:
                    await message.answer(
                        "Cú pháp: <code>/model tier &lt;brain|cheap|escalated&gt; &lt;tên_model&gt;</code>",
                        parse_mode="HTML"
                    )
                    return
                tier_name = args[1].lower().strip()
                target_model = args[2].strip()
                if tier_name not in ("brain", "cheap", "escalated"):
                    await message.answer("Tầng model chỉ được chọn: <code>brain</code>, <code>cheap</code>, hoặc <code>escalated</code>.", parse_mode="HTML")
                    return
                attr_name = f"model_{tier_name}"
                old_val = getattr(self.cfg, attr_name, "")
                object.__setattr__(self.cfg, attr_name, target_model)
                if hasattr(self, "agent") and hasattr(self.agent, "cfg"):
                    object.__setattr__(self.agent.cfg, attr_name, target_model)
                if self.memory is not None:
                    try:
                        await self.memory.kv_set(f"config:{attr_name}", target_model)
                    except Exception:
                        pass
                try:
                    from dotenv import set_key
                    env_path = Path(getattr(self.cfg, "project_root", None) or PROJECT_ROOT) / ".env"
                    if env_path.is_file():
                        set_key(str(env_path), attr_name.upper(), target_model)
                except Exception:
                    pass
                await message.answer(
                    f"Đã cập nhật tầng <b>{tier_name.capitalize()}</b>: <code>{target_model}</code> (trước đó: <code>{old_val}</code>)",
                    parse_mode="HTML"
                )
                return

            target_model = args[0].strip()
            old_model = getattr(self.cfg, "model_brain", "gemini-3.8-flash")
            object.__setattr__(self.cfg, "model_brain", target_model)
            if hasattr(self, "agent") and hasattr(self.agent, "cfg"):
                object.__setattr__(self.agent.cfg, "model_brain", target_model)
            if self.memory is not None:
                try:
                    await self.memory.kv_set("config:model_brain", target_model)
                except Exception:
                    pass
            try:
                from dotenv import set_key
                env_path = Path(getattr(self.cfg, "project_root", None) or PROJECT_ROOT) / ".env"
                if env_path.is_file():
                    set_key(str(env_path), "MODEL_BRAIN", target_model)
            except Exception:
                pass
            await message.answer(
                f"Đã chuyển model Brain sang: <code>{target_model}</code> (trước đó: <code>{old_model}</code>)",
                parse_mode="HTML"
            )

        @dp.message(F.text.startswith("/the_duyet"))
        async def cmd_the_duyet(message: Message) -> None:
            if not self._is_allowed(message):
                return
            is_dev = (
                getattr(self.cfg, "dev_mode", False)
                or getattr(self.cfg, "enable_dev_commands", False)
                or getattr(self.cfg, "debug", False)
                or os.environ.get("MULON_DEV_MODE", "0") == "1"
            )
            if not is_dev:
                await message.answer(
                    "[Lưu ý] Lệnh dev thử nghiệm (<code>/the_duyet</code>) đang tắt ở bản chạy thật. "
                    "Bật ENABLE_DEV_COMMANDS=1 hoặc MULON_DEV_MODE=1 nếu muốn thử.",
                    parse_mode="HTML"
                )
                return
            thread_id = None
            if getattr(message, "is_topic_message", False):
                thread_id = message.message_thread_id
            aid = await self.send_test_approval_card(
                message.chat.id, thread_id)
            if aid is None:
                await message.answer(
                    "Kênh duyệt chưa được nối ở bản chạy này — "
                    "không gửi được thẻ thử.")

        @dp.message(F.text.startswith("/vault"))
        async def cmd_vault(message: Message) -> None:
            if not self._is_allowed(message):
                return
            server = self._svc("vault_server")
            if server is None or not server.running:
                await message.answer(
                    "Vault form server chưa chạy trên bản này "
                    "(kiểm tra VAULT_PORT).")
                return
            label = _arg_text(message) or "secret"
            link = server.link_for(label)
            # Đường CHÍNH từ 1.3.0: nhập NGAY trong Mini App
            # (màn Kho lưu trữ an toàn) — link 127.0.0.1 chỉ mở
            # được trên chính máy chạy bot, chết trên điện thoại,
            # nên hạ xuống đường phụ cho desktop.
            app_link = webapp_direct_link(
                self.cfg, self._bot_username(), "vault")
            lines = [
                f"Nhập bí mật '{label}' ngay trong Mini App: mở "
                "Cài đặt → Kho lưu trữ an toàn, điền nhãn + giá "
                "trị rồi bấm Lưu — giá trị đi thẳng vào kho, "
                "không qua chat, lưu xong chỉ còn ref dạng "
                "vault:<uuid>.",
            ]
            kb = None
            if app_link:
                kb = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(
                        text="Mở Kho trong Mini App", url=app_link)]])
            lines.append(
                f"Đường phụ (chỉ mở được trên máy tính đang chạy "
                f"bot): form một lần {link} — hết hạn sau "
                f"{self.cfg.vault_token_ttl_s // 60} phút.")
            note = "\n".join(lines)
            if message.chat.type == ChatType.PRIVATE:
                await message.answer(note, reply_markup=kb)
            elif self.bot is not None:
                # Trong group: link là capability — chỉ gửi DM.
                await self.bot.send_message(
                    self.cfg.allowed_user_id, note, reply_markup=kb)
                await message.answer(
                    "Đã gửi hướng dẫn nhập vault vào DM của bạn "
                    "(không đăng link ở group).")

        @dp.message(F.text.startswith("/google_auth"))
        async def cmd_google_auth(message: Message) -> None:
            if not self._is_allowed(message):
                return
            await message.answer("⏳ <i>Đang tạo link xác thực Google Workspace mới...</i>", parse_mode="HTML")
            auth_url = await self._get_google_auth_url()
            if not auth_url:
                await message.answer(
                    "[Lưu ý] Không thể tạo link xác thực Google lúc này. Ní hãy kiểm tra xem server <code>google-workspace</code> trong MCP đã bật chưa nhé.",
                    parse_mode="HTML"
                )
                return
            await message.answer(
                "<b>XÁC THỰC GOOGLE WORKSPACE CHO MULON</b>\n\n"
                "• <b>Bấm vào link đăng nhập Google dưới đây:</b>\n"
                f"<a href=\"{auth_url}\"><b>BẤM VÀO ĐÂY ĐỂ ĐĂNG NHẬP GOOGLE</b></a>\n\n"
                "<b>Cách thức hoạt động:</b>\n"
                "• Đăng nhập tài khoản Google và bấm <b>Cho phép (Allow)</b>.\n"
                "• Trình duyệt (trên điện thoại hay máy Mac) sẽ tự động chuyển hướng qua Cloudflare và hoàn tất kích hoạt 100% tự động.\n"
                "• <i>(Dự phòng):</i> Nếu trình duyệt không tự chuyển hướng, ní chỉ cần copy toàn bộ link trên thanh địa chỉ rồi dán gửi vào đây nha!",
                parse_mode="HTML",
                disable_web_page_preview=True,
            )

        @dp.message(F.text.startswith("/zalo"))
        async def cmd_zalo(message: Message) -> None:
            if not self._is_allowed(message):
                return
            arg = _arg_text(message).strip().lower()
            connectors = self.surfaces.get("connectors") if self.surfaces else None
            conn = await connectors.get("zalo_personal") if connectors else None
            if not conn:
                await message.answer("[Lưu ý] Connector Zalo cá nhân chưa sẵn sàng hoặc chưa nạp.")
                return

            if arg == "disconnect":
                res = await conn.call("disconnect", {})
                await message.answer("Đã ngắt kết nối và xoá phiên Zalo cá nhân khỏi Kho an toàn.")
                return

            if arg == "qr":
                res = await conn.call("qr_login", {"step": "start"})
                if not res.get("ok"):
                    await message.answer(f"[Lưu ý] Không thể khởi tạo đăng nhập QR Zalo: {res.get('error')}")
                    return
                qr_path = res.get("qr_path")
                msg_out = (
                    "<b>ĐĂNG NHẬP ZALO CÁ NHÂN (QR CODE)</b>\n\n"
                    "• Ní hãy dùng app Zalo trên điện thoại quét mã QR để đăng nhập.\n"
                    f"<i>{res.get('limitations', '')}</i>"
                )
                if qr_path and os.path.exists(qr_path):
                    from aiogram.types import FSInputFile
                    await message.answer_photo(FSInputFile(qr_path), caption=msg_out, parse_mode="HTML")
                else:
                    await message.answer(msg_out, parse_mode="HTML")
                return

            # Mặc định: status
            health = await conn.health_check()
            if health.get("connected"):
                user = health.get("user") or {}
                uid = user.get("id") or "chưa rõ"
                await message.answer(
                    f"<b>ZALO CÁ NHÂN ĐÃ KẾT NỐI</b>\n"
                    f"• User ID: <code>{uid}</code>\n"
                    f"• Trạng thái: Sẵn sàng gửi/nhận tin nhắn và tệp.\n\n"
                    f"<i>{health.get('limitations', '')}</i>\n"
                    f"• Để ngắt kết nối: <code>/zalo disconnect</code>",
                    parse_mode="HTML"
                )
            else:
                await message.answer(
                    "<b>ZALO CÁ NHÂN CHƯA KẾT NỐI</b>\n\n"
                    f"• Chi tiết: {health.get('detail', 'Chưa đăng nhập')}\n"
                    f"<i>{health.get('limitations', '')}</i>\n\n"
                    "• Gõ <code>/zalo qr</code> để bắt đầu quét mã QR đăng nhập.",
                    parse_mode="HTML"
                )

        @dp.message(F.text.startswith("/telethon") | F.text.startswith("/telegram_user"))
        async def cmd_telethon(message: Message) -> None:
            if not self._is_allowed(message):
                return
            arg = _arg_text(message).strip().lower()
            connectors = self.surfaces.get("connectors") if self.surfaces else None
            conn = await connectors.get("telegram_personal") if connectors else None
            if not conn:
                await message.answer("[Lưu ý] Connector Telegram cá nhân chưa sẵn sàng hoặc chưa nạp.")
                return

            if arg == "disconnect":
                res = await conn.call("disconnect", {})
                await message.answer("Đã ngắt kết nối và xoá phiên Telegram cá nhân khỏi Kho an toàn.")
                return

            if arg == "qr":
                res = await conn.call("qr_login", {"step": "start"})
                if not res.get("ok"):
                    await message.answer(f"[Lưu ý] Không thể khởi tạo đăng nhập QR Telegram: {res.get('error')}")
                    return
                qr_url = res.get("qr_url", "")
                await message.answer(
                    "<b>ĐĂNG NHẬP TELEGRAM CÁ NHÂN (MTProto)</b>\n\n"
                    f"• Link đăng nhập thiết bị: <code>{qr_url}</code>\n\n"
                    "<b>Cách quét mã trên điện thoại:</b>\n"
                    "1. Mở app Telegram -> Cài đặt (Settings)\n"
                    "2. Thiết bị (Devices) -> Quét mã QR (Link Desktop Device)\n\n"
                    f"<i>{res.get('warning', '')}</i>\n"
                    "• Sau khi quét xong, gõ <code>/telethon status</code> để kiểm tra.",
                    parse_mode="HTML"
                )
                return

            # Mặc định: status
            health = await conn.health_check()
            if health.get("connected"):
                user = health.get("user") or {}
                uname = f"@{user.get('username')}" if user.get('username') else str(user.get('id', ''))
                await message.answer(
                    f"<b>TELEGRAM CÁ NHÂN ĐÃ KẾT NỐI</b>\n"
                    f"• Tài khoản: <b>{uname}</b>\n"
                    f"• Trạng thái: Sẵn sàng đọc/gửi tin nhắn qua kênh MTProto độc lập.\n\n"
                    f"<i>{health.get('warning', '')}</i>\n"
                    f"• Để ngắt kết nối: <code>/telethon disconnect</code>",
                    parse_mode="HTML"
                )
            else:
                await message.answer(
                    "<b>TELEGRAM CÁ NHÂN CHƯA KẾT NỐI</b>\n\n"
                    f"• Chi tiết: {health.get('detail', 'Chưa đăng nhập')}\n"
                    f"<i>{health.get('warning', '')}</i>\n\n"
                    "• Gõ <code>/telethon qr</code> để lấy link/mã QR kết nối.",
                    parse_mode="HTML"
                )

        @dp.message(F.text.startswith("/facebook"))
        async def cmd_facebook(message: Message) -> None:
            if not self._is_allowed(message):
                return
            full_arg = _arg_text(message).strip()
            parts = full_arg.split(maxsplit=1)
            subcmd = parts[0].lower() if parts else "status"
            subarg = parts[1].strip() if len(parts) > 1 else ""

            connectors = self.surfaces.get("connectors") if self.surfaces else None
            conn = await connectors.get("facebook_personal") if connectors else None
            if not conn:
                await message.answer("[Lưu ý] Connector Facebook cá nhân chưa sẵn sàng hoặc chưa nạp.")
                return

            if subcmd == "disconnect":
                await conn.call("disconnect", {})
                await message.answer("Đã ngắt kết nối và xoá phiên cookie Facebook cá nhân khỏi Kho an toàn.")
                return

            if subcmd == "connect":
                if not subarg:
                    await message.answer(
                        "<b>HƯỚNG DẪN KẾT NỐI FACEBOOK CÁ NHÂN</b>\n\n"
                        "Cú pháp: <code>/facebook connect c_user=...; xs=...;</code>\n\n"
                        "<b>LƯU Ý BẢO MẬT & RỦI RO CAO:</b>\n"
                        "• Meta không hỗ trợ API chính thức cho tài khoản cá nhân.\n"
                        "• Phiên web cookies chỉ nên trích xuất từ chính trình duyệt đang dùng trên máy này (cùng IP mạng).\n"
                        "• Khuyến nghị chỉ dùng tài khoản thử nghiệm / phụ.\n"
                        "• Nếu Facebook yêu cầu xác minh danh tính, hệ thống Checkpoint Guard sẽ tự ngắt để bảo vệ tài khoản.",
                        parse_mode="HTML"
                    )
                    return
                res = await conn.call("configure", {"cookies": subarg})
                if not res.get("ok"):
                    await message.answer(f"[Lưu ý] Kết nối Facebook thất bại: {res.get('error')}")
                    return
                uid = res.get("user", {}).get("id") or "Đã ghi nhận"
                await message.answer(
                    f"<b>ĐÃ CẤU HÌNH PHIÊN FACEBOOK CÁ NHÂN</b>\n"
                    f"• UID: <code>{uid}</code>\n"
                    f"• Session cookies đã lưu an toàn trong Kho bảo mật (Vault).\n\n"
                    f"<i>{res.get('warning', '')}</i>\n"
                    f"• Để kiểm tra: <code>/facebook status</code>\n"
                    f"• Để ngắt kết nối: <code>/facebook disconnect</code>",
                    parse_mode="HTML"
                )
                return

            if subcmd in ("groups", "list_groups"):
                res = await conn.call("list_groups", {"all": True})
                if not res.get("ok"):
                    await message.answer(f"[Lưu ý] Không đọc được danh sách nhóm: {res.get('error')}")
                    return
                groups = res.get("groups") or []
                if not groups:
                    await message.answer("Chưa có nhóm Facebook nào trong danh sách.")
                    return
                lines = [f"<b>DANH SÁCH NHÓM FACEBOOK ĐÃ THAM GIA ({len(groups)} nhóm):</b>\n"]
                for g in groups[:10]:
                    gid = g.get("id", "")
                    gname = g.get("name", gid)
                    privacy = g.get("privacy", "closed")
                    lines.append(f"• <b>{gname}</b> (<code>{gid}</code>) - <i>{privacy}</i>")
                await message.answer("\n".join(lines), parse_mode="HTML")
                return

            if subcmd in ("feed", "read_feed"):
                res = await conn.call("read_feed", {})
                if not res.get("ok"):
                    await message.answer(f"[Lưu ý] Không đọc được Bảng tin: {res.get('error')}")
                    return
                posts = res.get("posts") or []
                if not posts:
                    await message.answer("Bảng tin Facebook hiện đang trống.")
                    return
                lines = [f"<b>BẢNG TIN FACEBOOK ({len(posts)} bài viết):</b>\n"]
                for p in posts[:5]:
                    author = p.get("author", "Facebook User")
                    content = p.get("raw_text") or p.get("content") or ""
                    snippet = (content[:80] + "...") if len(content) > 80 else content
                    lines.append(f"• <b>{author}</b>: {html.escape(snippet)}")
                await message.answer("\n".join(lines), parse_mode="HTML")
                return

            # Mặc định: status
            health = await conn.health_check()
            warning_txt = health.get("warning", "")
            if health.get("checkpoint_detected"):
                await message.answer(
                    "[Cảnh báo] <b>PHÁT HIỆN CHECKPOINT FACEBOOK</b>\n\n"
                    f"• Chi tiết: {health.get('detail')}\n"
                    "• Checkpoint Guard đã tự động ngắt kết nối để bảo vệ tài khoản khỏi bị spam request.\n"
                    "• Hãy mở trình duyệt và đăng nhập Facebook để hoàn tất xác minh nếu cần, sau đó cập nhật lại cookie hoặc gõ <code>/facebook disconnect</code>.",
                    parse_mode="HTML"
                )
            elif health.get("connected"):
                user = health.get("user") or {}
                uname = user.get("name") or str(user.get("id", ""))
                await message.answer(
                    f"<b>FACEBOOK CÁ NHÂN ĐÃ KẾT NỐI</b>\n"
                    f"• Tài khoản: <b>{uname}</b>\n"
                    f"• Trạng thái: Sẵn sàng đọc trang cá nhân, bảng tin, bạn bè và Messenger.\n\n"
                    f"<i>{warning_txt}</i>\n\n"
                    f"• Để ngắt kết nối: <code>/facebook disconnect</code>",
                    parse_mode="HTML"
                )
            else:
                await message.answer(
                    "<b>FACEBOOK CÁ NHÂN CHƯA KẾT NỐI</b>\n\n"
                    f"• Chi tiết: {health.get('detail', 'Chưa có cookie')}\n\n"
                    f"<b>CẢNH BÁO:</b> <i>{warning_txt}</i>\n\n"
                    "• Gõ <code>/facebook connect &lt;cookies&gt;</code> để kết nối.",
                    parse_mode="HTML"
                )

        @dp.message(F.text.startswith("/instagram") | F.text.startswith("/ig"))
        async def cmd_instagram(message: Message) -> None:
            if not self._is_allowed(message):
                return
            full_arg = _arg_text(message).strip()
            parts = full_arg.split(maxsplit=1)
            subcmd = parts[0].lower() if parts else "status"
            subarg = parts[1].strip() if len(parts) > 1 else ""

            connectors = self.surfaces.get("connectors") if self.surfaces else None
            conn = await connectors.get("instagram_messages") if connectors else None
            if not conn:
                await message.answer("[Lưu ý] Connector Tin nhắn Instagram chưa sẵn sàng hoặc chưa nạp.")
                return

            if subcmd == "disconnect":
                await conn.call("disconnect", {})
                await message.answer("Đã ngắt kết nối và xoá phiên Tin nhắn Instagram khỏi Kho an toàn.")
                return

            if subcmd == "connect":
                if not subarg:
                    await message.answer(
                        "<b>HƯỚNG DẪN KẾT NỐI TIN NHẮN INSTAGRAM</b>\n\n"
                        "Cú pháp: <code>/instagram connect sessionid=...; ds_user_id=...;</code>\n\n"
                        "<b>LƯU Ý BẢO MẬT:</b>\n"
                        "• Phiên cookie/token được lưu an toàn qua Kho bảo mật (Vault).\n"
                        "• Giữ tần suất gửi tin nhắn ở mức bình thường để tránh bị Meta hạn chế tài khoản.",
                        parse_mode="HTML"
                    )
                    return
                res = await conn.call("configure", {"cookies": subarg})
                if not res.get("ok"):
                    await message.answer(f"[Lưu ý] Kết nối thất bại: {res.get('error')}")
                    return
                user_name = res.get("user", {}).get("username") or "Đã ghi nhận"
                await message.answer(
                    f"<b>ĐÃ CẤU HÌNH TIN NHẮN INSTAGRAM</b>\n"
                    f"• Người dùng: <code>{user_name}</code>\n"
                    f"• Phiên đã được lưu an toàn trong Kho bảo mật (Vault).\n\n"
                    f"• Để kiểm tra: <code>/instagram status</code>\n"
                    f"• Xem hộp thư: <code>/instagram inbox</code>\n"
                    f"• Ngắt kết nối: <code>/instagram disconnect</code>",
                    parse_mode="HTML"
                )
                return

            if subcmd == "inbox":
                folder = subarg.lower() if subarg in ("pending", "spam") else "inbox"
                res = await conn.call("read_inbox", {"folder": folder})
                if not res.get("ok"):
                    await message.answer(f"[Lưu ý] Không đọc được hộp thư: {res.get('error')}")
                    return
                threads = res.get("threads") or []
                if not threads:
                    await message.answer(f"Hộp thư Instagram ({folder}) hiện đang trống.")
                    return
                lines = [f"<b>HỘP THƯ INSTAGRAM ({folder.upper()})</b> ({len(threads)} hội thoại):\n"]
                for t in threads[:5]:
                    tid = t.get("thread_id", "")
                    title = t.get("title") or t.get("participant") or tid
                    snippet = t.get("snippet", "")
                    lines.append(f"• <b>{title}</b> (<code>{tid}</code>): {snippet}")
                await message.answer("\n".join(lines), parse_mode="HTML")
                return

            # Mặc định: status
            health = await conn.health_check()
            if health.get("checkpoint_detected"):
                await message.answer(
                    "[Cảnh báo] <b>PHÁT HIỆN CHECKPOINT INSTAGRAM</b>\n\n"
                    f"• Chi tiết: {health.get('detail')}\n"
                    "• Checkpoint Guard đã tự ngắt kết nối an toàn để bảo vệ tài khoản.\n"
                    "• Hãy đăng nhập Instagram trên trình duyệt để xác minh, sau đó kết nối lại.",
                    parse_mode="HTML"
                )
            elif health.get("connected"):
                user = health.get("user") or {}
                uname = user.get("username") or str(user.get("id", ""))
                await message.answer(
                    f"<b>TIN NHẮN INSTAGRAM ĐÃ KẾT NỐI</b>\n"
                    f"• Tài khoản: <b>{uname}</b>\n"
                    f"• Trạng thái: Sẵn sàng đọc hộp thư, tìm kiếm tin nhắn, gửi tin và thả reaction.\n\n"
                    f"• Xem hộp thư: <code>/instagram inbox</code>\n"
                    f"• Ngắt kết nối: <code>/instagram disconnect</code>",
                    parse_mode="HTML"
                )
            else:
                await message.answer(
                    "<b>TIN NHẮN INSTAGRAM CHƯA KẾT NỐI</b>\n\n"
                    f"• Chi tiết: {health.get('detail', 'Chưa có phiên')}\n\n"
                    "• Gõ <code>/instagram connect &lt;cookies&gt;</code> để kết nối.",
                    parse_mode="HTML"
                )

        @dp.message(F.text.startswith("/threads_dm") | F.text.startswith("/threads"))
        async def cmd_threads(message: Message) -> None:
            if not self._is_allowed(message):
                return
            full_arg = _arg_text(message).strip()
            parts = full_arg.split(maxsplit=1)
            subcmd = parts[0].lower() if parts else "status"
            subarg = parts[1].strip() if len(parts) > 1 else ""

            connectors = self.surfaces.get("connectors") if self.surfaces else None
            conn = await connectors.get("threads_messages") if connectors else None
            if not conn:
                await message.answer("[Lưu ý] Connector Tin nhắn Threads chưa sẵn sàng hoặc chưa nạp.")
                return

            if subcmd == "disconnect":
                await conn.call("disconnect", {})
                await message.answer("Đã ngắt kết nối và xoá phiên Tin nhắn Threads khỏi Kho an toàn.")
                return

            if subcmd == "connect":
                if not subarg:
                    await message.answer(
                        "<b>HƯỚNG DẪN KẾT NỐI TIN NHẮN THREADS</b>\n\n"
                        "Cú pháp: <code>/threads connect sessionid=...; ds_user_id=...;</code>\n\n"
                        "<b>GIỚI HẠN CỨNG BẮT BUỘC:</b>\n"
                        "• Threads chỉ cho phép gửi tin nhắn tới người ĐÃ có hội thoại từ trước.\n"
                        "• Tuyệt đối KHÔNG mở DM mới tới người lạ chỉ bằng @handle.\n"
                        "• Phiên cookie được lưu an toàn trong Kho bảo mật (Vault).",
                        parse_mode="HTML"
                    )
                    return
                res = await conn.call("configure", {"cookies": subarg})
                if not res.get("ok"):
                    await message.answer(f"[Lưu ý] Kết nối thất bại: {res.get('error')}")
                    return
                user_name = res.get("user", {}).get("username") or "Đã ghi nhận"
                await message.answer(
                    f"<b>ĐÃ CẤU HÌNH TIN NHẮN THREADS</b>\n"
                    f"• Người dùng: <code>{user_name}</code>\n"
                    f"• Phiên đã được lưu an toàn trong Kho bảo mật (Vault).\n\n"
                    f"<i>Lưu ý: Chỉ nhắn được người đã có hội thoại từ trước.</i>\n\n"
                    f"• Để kiểm tra: <code>/threads status</code>\n"
                    f"• Xem hộp thư: <code>/threads inbox</code>\n"
                    f"• Ngắt kết nối: <code>/threads disconnect</code>",
                    parse_mode="HTML"
                )
                return

            if subcmd == "inbox":
                folder = subarg.lower() if subarg == "pending" else "inbox"
                res = await conn.call("read_inbox", {"folder": folder})
                if not res.get("ok"):
                    await message.answer(f"[Lưu ý] Không đọc được hộp thư: {res.get('error')}")
                    return
                threads = res.get("threads") or []
                if not threads:
                    await message.answer(f"Hộp thư Threads ({folder}) hiện đang trống.")
                    return
                lines = [f"<b>HỘP THƯ THREADS ({folder.upper()})</b> ({len(threads)} hội thoại):\n"]
                for t in threads[:5]:
                    tid = t.get("thread_id", "")
                    title = t.get("title") or t.get("participant") or tid
                    snippet = t.get("snippet", "")
                    lines.append(f"• <b>{title}</b> (<code>{tid}</code>): {snippet}")
                await message.answer("\n".join(lines), parse_mode="HTML")
                return

            if subcmd in ("posts", "list_posts"):
                p_conn = await connectors.get("threads_personal") if connectors else None
                if not p_conn:
                    await message.answer("[Lưu ý] Connector Threads cá nhân (nội dung) chưa sẵn sàng.")
                    return
                res = await p_conn.call("list_posts", {})
                if not res.get("ok"):
                    await message.answer(f"[Lưu ý] Không đọc được bài viết: {res.get('error')}")
                    return
                posts = res.get("posts") or []
                if not posts:
                    await message.answer("Chưa có bài viết Threads nào.")
                    return
                lines = [f"<b>BÀI ĐĂNG THREADS ({len(posts)} bài):</b>\n"]
                for p in posts[:5]:
                    pid = p.get("id", "")
                    content = p.get("raw_text") or p.get("text") or ""
                    snippet = (content[:80] + "...") if len(content) > 80 else content
                    lines.append(f"• (<code>{pid}</code>): {html.escape(snippet)}")
                await message.answer("\n".join(lines), parse_mode="HTML")
                return

            # Mặc định: status
            health = await conn.health_check()
            limitations_txt = health.get("limitations", "")
            if health.get("checkpoint_detected"):
                await message.answer(
                    "[Cảnh báo] <b>PHÁT HIỆN CHECKPOINT THREADS</b>\n\n"
                    f"• Chi tiết: {health.get('detail')}\n"
                    "• Checkpoint Guard đã tự ngắt kết nối an toàn để bảo vệ tài khoản.\n"
                    "• Hãy đăng nhập Threads trên trình duyệt để xác minh, sau đó kết nối lại.",
                    parse_mode="HTML"
                )
            elif health.get("connected"):
                user = health.get("user") or {}
                uname = user.get("username") or str(user.get("id", ""))
                await message.answer(
                    f"<b>TIN NHẮN THREADS ĐÃ KẾT NỐI</b>\n"
                    f"• Tài khoản: <b>{uname}</b>\n"
                    f"• Trạng thái: Sẵn sàng đọc hộp thư, đọc tin nhắn và gửi tin (hội thoại có sẵn).\n\n"
                    f"<b>GIỚI HẠN:</b> <i>{limitations_txt}</i>\n\n"
                    f"• Xem hộp thư: <code>/threads inbox</code>\n"
                    f"• Ngắt kết nối: <code>/threads disconnect</code>",
                    parse_mode="HTML"
                )
            else:
                await message.answer(
                    "<b>TIN NHẮN THREADS CHƯA KẾT NỐI</b>\n\n"
                    f"• Chi tiết: {health.get('detail', 'Chưa có phiên')}\n\n"
                    f"<b>LƯU Ý:</b> <i>{limitations_txt}</i>\n\n"
                    "• Gõ <code>/threads connect &lt;cookies&gt;</code> để kết nối.",
                    parse_mode="HTML"
                )

        @dp.message(F.text.startswith("/google") & ~F.text.startswith("/google_auth"))
        async def cmd_google(message: Message) -> None:
            if not self._is_allowed(message):
                return
            arg = _arg_text(message).strip().lower()
            connectors = self.surfaces.get("connectors") if self.surfaces else None
            gdrive = await connectors.get("gdrive") if connectors else None
            gmail = await connectors.get("gmail") if connectors else None
            gcal = await connectors.get("gcalendar") if connectors else None

            if arg in ("drive", "files") and gdrive:
                res = await gdrive.call("list_files", {"page_size": 5})
                if not res.get("ok"):
                    await message.answer(f"[Lưu ý] Không đọc được Google Drive: {res.get('error')}")
                    return
                files = res.get("files") or []
                if not files:
                    await message.answer("Google Drive của ní chưa có tập tin nào.")
                    return
                lines = [f"<b>TẬP TIN GOOGLE DRIVE ({len(files)} tệp gần nhất):</b>\n"]
                for f in files:
                    fid = f.get("id", "")
                    name = f.get("raw_name") or f.get("name") or fid
                    mime = f.get("mime_type", "")
                    lines.append(f"• <b>{html.escape(name)}</b> (<code>{fid}</code>) <i>[{mime.split('.')[-1]}]</i>")
                await message.answer("\n".join(lines), parse_mode="HTML")
                return

            # Default status
            health_drive = await gdrive.health_check() if gdrive else {"ok": False, "detail": "Chưa nạp"}
            health_mail = await gmail.health_check() if gmail else {"ok": False, "detail": "Chưa nạp"}
            health_cal = await gcal.health_check() if gcal else {"ok": False, "detail": "Chưa nạp"}
            email = health_drive.get("email") or health_mail.get("email") or "Chưa kết nối"
            await message.answer(
                f"<b>TRẠNG THÁI GOOGLE WORKSPACE</b>\n\n"
                f"• Tài khoản: <b>{email}</b>\n"
                f"• Gmail: {'Sẵn sàng' if health_mail.get('ok') else '[Lưu ý] ' + health_mail.get('detail', '')}\n"
                f"• Google Calendar: {'Sẵn sàng' if health_cal.get('ok') else '[Lưu ý] ' + health_cal.get('detail', '')}\n"
                f"• Google Drive: {'Sẵn sàng' if health_drive.get('ok') else '[Lưu ý] ' + health_drive.get('detail', '')}\n"
                f"• Google Docs & Sheets: {'Sẵn sàng' if health_drive.get('ok') else 'Chưa kết nối'}\n\n"
                f"• Để xác thực/kết nối lại: <code>/google_auth</code>\n"
                f"• Xem file Drive: <code>/google drive</code>",
                parse_mode="HTML"
            )

        @dp.message(F.text.startswith("/fbpage"))
        async def cmd_fbpage(message: Message) -> None:
            if not self._is_allowed(message):
                return
            arg = _arg_text(message).strip().lower()
            connectors = self.surfaces.get("connectors") if self.surfaces else None
            conn = await connectors.get("facebook_page") if connectors else None
            if not conn:
                await message.answer("[Lưu ý] Connector Facebook Page chưa sẵn sàng.")
                return

            if arg in ("feed", "posts"):
                res = await conn.call("read_page_feed", {"limit": 5})
                if not res.get("ok"):
                    await message.answer(f"[Lưu ý] Không đọc được Bảng tin Fanpage: {res.get('error')}")
                    return
                posts = res.get("posts") or []
                if not posts:
                    await message.answer("Fanpage chưa có bài đăng nào gần đây.")
                    return
                lines = [f"<b>BÀI ĐĂNG GẦN NHẤT TRÊN FANPAGE:</b>\n"]
                for p in posts[:5]:
                    pid = p.get("id", "")
                    msg = p.get("raw_message") or p.get("message") or "(Bài đăng kèm ảnh/video)"
                    snippet = (msg[:120] + "...") if len(msg) > 120 else msg
                    lines.append(f"• <code>{pid}</code>: {html.escape(snippet)}")
                await message.answer("\n".join(lines), parse_mode="HTML")
                return

            health = await conn.health_check()
            if health.get("connected"):
                await message.answer(
                    f"<b>FACEBOOK FANPAGE ĐÃ KẾT NỐI</b>\n\n"
                    f"• Fanpage: <b>{health.get('page_name', '')}</b> (<code>{health.get('page_id', '')}</code>)\n"
                    f"• Trạng thái: Sẵn sàng đọc bảng tin, insights và đăng bài/trả lời bình luận.\n\n"
                    f"• Xem bài đăng: <code>/fbpage feed</code>",
                    parse_mode="HTML"
                )
            else:
                await message.answer(
                    f"<b>FACEBOOK FANPAGE CHƯA CẤU HÌNH</b>\n\n"
                    f"• Chi tiết: {health.get('detail')}\n\n"
                    f"• Nhập Page Token & Page ID vào Mini App hoặc Vault để kích hoạt.",
                    parse_mode="HTML"
                )

        @dp.message(F.text.startswith("/tiktok"))
        async def cmd_tiktok(message: Message) -> None:
            if not self._is_allowed(message):
                return
            arg = _arg_text(message).strip().lower()
            connectors = self.surfaces.get("connectors") if self.surfaces else None
            conn = await connectors.get("tiktok") if connectors else None
            if not conn:
                await message.answer("[Lưu ý] Connector TikTok chưa sẵn sàng.")
                return

            if arg in ("videos", "list"):
                res = await conn.call("list_videos", {"max_count": 5})
                if not res.get("ok"):
                    await message.answer(f"[Lưu ý] Không đọc được danh sách video TikTok: {res.get('error')}")
                    return
                videos = res.get("videos") or []
                if not videos:
                    await message.answer("Tài khoản TikTok chưa có video nào.")
                    return
                lines = [f"<b>DANH SÁCH VIDEO TIKTOK ({len(videos)} video gần nhất):</b>\n"]
                for v in videos:
                    vid = v.get("id", "")
                    title = v.get("raw_title") or v.get("title") or "Video TikTok"
                    views = v.get("view_count", 0)
                    likes = v.get("like_count", 0)
                    lines.append(f"• <b>{html.escape(title)}</b> (<code>{vid}</code>) - <i>Lượt xem: {views} | {likes}</i>")
                await message.answer("\n".join(lines), parse_mode="HTML")
                return

            health = await conn.health_check()
            if health.get("connected"):
                await message.answer(
                    f"<b>TIKTOK ĐÃ KẾT NỐI</b>\n\n"
                    f"• Nhà sáng tạo: <b>{health.get('display_name', '')}</b> (<code>{health.get('open_id', '')}</code>)\n"
                    f"• Trạng thái: Sẵn sàng xem thông tin, video và xuất bản nội dung.\n\n"
                    f"<i>Lưu ý: {health.get('limitations', '')}</i>\n\n"
                    f"• Xem video: <code>/tiktok videos</code>",
                    parse_mode="HTML"
                )
            else:
                await message.answer(
                    f"<b>TIKTOK CHƯA CẤU HÌNH</b>\n\n"
                    f"• Chi tiết: {health.get('detail')}\n\n"
                    f"• Nhập Access Token & Open ID vào Mini App hoặc Vault để kích hoạt.",
                    parse_mode="HTML"
                )

        @dp.message(F.text.startswith("/forget"))
        async def cmd_forget(message: Message) -> None:
            if not self._is_allowed(message):
                return
            topic = _arg_text(message)
            if not topic:
                await message.answer(
                    "Dùng: /forget <chủ đề> — mình sẽ liệt kê kế "
                    "hoạch quên trước, chưa xóa gì ngay.")
                return
            plan = await surf.build_forget_plan(
                self.memory, self.cfg.dossier_dir, topic)
            key = session_key_for(message)
            await self.memory.kv_set(
                f"forget_pending:{key}",
                json.dumps(plan, ensure_ascii=False))
            await _answer_chunks(
                message, surf.format_forget_plan(plan))

        @dp.message(F.text.startswith("/export_memory"))
        async def cmd_export_memory(message: Message) -> None:
            if not self._is_allowed(message):
                return
            text = await surf.export_memory_text(
                self.memory, self.dossier.files)
            out_dir = Path(self.cfg.workspace_dir) / "exports"
            out_dir.mkdir(parents=True, exist_ok=True)
            stamp = re.sub(r"[^0-9]", "", surf.now_iso())[:14]
            path = out_dir / f"memory-export-{stamp}.md"
            path.write_text(text, encoding="utf-8")
            await message.answer_document(
                FSInputFile(str(path)),
                caption="Bản xuất ký ức (dossier + facts kèm nguồn).")

        @dp.message(F.document)
        async def on_document(message: Message) -> None:
            if not self._is_allowed(message):
                return
            if self._is_duplicate_message(message):
                return
            if not self._should_respond(message):
                return
            doc = message.document
            name = (doc.file_name or "").lower()
            upload_dir = Path(self.cfg.workspace_dir) / "uploads"
            upload_dir.mkdir(parents=True, exist_ok=True)
            local = upload_dir / f"doc_{message.message_id}_{doc.file_name or 'file'}"
            if self.bot:
                try:
                    tg_file = await self.bot.get_file(doc.file_id)
                    if tg_file.file_path:
                        await self.bot.download_file(tg_file.file_path, destination=str(local))
                except Exception as exc:
                    logger.warning("tải tài liệu từ telegram lỗi: %s", exc)

            caption = (message.caption or "").strip()
            library = self._svc("library")
            item = None
            if library is not None and local.is_file():
                try:
                    item = await library.index_file(local, source="user_upload", caption=caption)
                except Exception as exc:
                    logger.warning("lập chỉ mục tài liệu vào thư viện lỗi: %s", exc)

            is_img = any(name.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"))
            if is_img:
                await self._post_media_to_library("photo", FSInputFile(str(local)), f"[Thư viện] {doc.file_name or 'Ảnh tải lên'}", chat_id=message.chat.id)
                item_str = f" • Thư viện #{item['id']}" if item else ""
                text = f"[Người dùng gửi kèm ảnh: {local}{item_str}]\n{caption}".strip() if caption else f"[Người dùng gửi kèm ảnh: {local}{item_str}]"
            else:
                # Kiểm tra nếu user chủ đích import ký ức (có lệnh /import hoặc caption chứa import)
                if (name.endswith(".md") or name.endswith(".json") or name.endswith(".txt")) and ("import" in caption.lower() or caption.startswith("/import")):
                    try:
                        ftext = local.read_text(encoding="utf-8", errors="replace")
                        items = surf.parse_import_content(ftext, doc.file_name or "")
                        added = 0
                        for it in items:
                            await self.memory.add_fact(it["fact"], subject=it["subject"], source="import")
                            added += 1
                        await self.memory.log_trajectory(session_key_for(message), "memory_import", {"file": doc.file_name, "facts_added": added})
                        await message.answer(f"Đã import {added} fact từ file {doc.file_name} (nguồn: import).")
                        return
                    except Exception as exc:
                        logger.warning("import ký ức từ file lỗi: %s", exc)

                await self._post_media_to_library("document", FSInputFile(str(local)), f"[Thư viện] {doc.file_name or 'Tài liệu'}", chat_id=message.chat.id)
                from .library import kind_of
                kind = kind_of(local)
                item_str = f" • Thư viện #{item['id']}" if item else ""
                text = f"[Người dùng gửi tài liệu: {doc.file_name or local.name} (loại: {kind}{item_str}, đường dẫn: {local})]\n{caption}".strip()

            text = format_reply_context(message, text)
            key = session_key_for(message)
            self._sessions_meta[key] = message
            if self.batcher.is_busy(key):
                await self._notify_queued(key, message)
            await self.batcher.add(key, text)

        @dp.message(F.text.startswith("/quyen"))
        async def cmd_quyen(message: Message) -> None:
            if not self._is_allowed(message):
                return
            if self.policy is None:
                await message.answer(
                    "Policy chưa được nối ở bản chạy này.")
                return
            self.policy.reload_host()
            await message.answer(surf.summarize_policy(self.policy))

        @dp.message(F.text.startswith("/approvals"))
        async def cmd_approvals(message: Message) -> None:
            if not self._is_allowed(message):
                return
            rows = await self.memory.recent_trajectory(
                kind="policy_decision", limit=10)
            # 1.2.0: gộp cả quyết định qua thẻ duyệt (nấc ask) —
            # đổi về cùng khuôn payload để format chung.
            ask_rows = await self.memory.recent_trajectory(
                kind="approval_decision", limit=10)
            for r in ask_rows:
                p = dict(r.get("payload") or {})
                p.setdefault("layer", "ask")
                p["allowed"] = bool(p.get("approved"))
                rows.append({**r, "payload": p})
            rows.sort(key=lambda r: r.get("id", 0), reverse=True)
            await message.answer(surf.format_approvals(rows[:10]))

        @dp.message_reaction()
        async def on_reaction(event) -> None:
            user = getattr(event, "user", None)
            if user is not None and self.cfg.allowed_user_id \
                    and user.id != self.cfg.allowed_user_id:
                return  # taste chỉ học từ user trong allowlist
            emojis = []
            for r in getattr(event, "new_reaction", []) or []:
                emoji = getattr(r, "emoji", None)
                if emoji:
                    emojis.append(emoji)
            await self._handle_reaction(
                event.chat.id, event.message_id, emojis)

        @dp.message(F.text.startswith("/voiceon"))
        async def cmd_voiceon(message: Message) -> None:
            if not self._is_allowed(message):
                return
            if self.voice is None:
                await message.answer(
                    "Voice chưa được nối ở bản chạy này.")
                return
            self.set_voice_reply(session_key_for(message), True)
            await message.answer(
                "Đã bật trả lời bằng giọng cho phiên này. "
                "Tắt bằng /voiceoff.")

        @dp.message(F.text.startswith("/voiceoff"))
        async def cmd_voiceoff(message: Message) -> None:
            if not self._is_allowed(message):
                return
            self.set_voice_reply(session_key_for(message), False)
            await message.answer("Đã tắt trả lời bằng giọng.")

        @dp.message(F.voice)
        async def on_voice(message: Message) -> None:
            if not self._is_allowed(message):
                return
            if self._is_duplicate_message(message):
                return
            if not self._should_respond_voice(message):
                return
            await self._send_typing(message)
            await self._process_voice_message(message)

        @dp.message(F.text.startswith("/upcoming") | F.text.startswith("/saptol") | F.text.startswith("/lich"))
        async def cmd_upcoming(message: Message) -> None:
            if not self._is_allowed(message):
                return
            if self.memory is None:
                await message.answer("Chưa khởi tạo bộ nhớ.")
                return
            from .planning import internal_kind
            lines = ["<b>Danh sách Sắp tới (Upcoming)</b>\n"]
            # Schedules
            try:
                scheds = await self.memory.list_schedules()
                active_scheds = [s for s in scheds if s.get("enabled", 1) and internal_kind(s.get("payload") or "") is None]
                if active_scheds:
                    lines.append("⏰ <b>Job theo lịch hẹn:</b>")
                    for s in active_scheds:
                        nxt = s.get("next_run_at") or "theo cron"
                        lines.append(f"  • <b>{s.get('payload', '')[:50]}</b> ({s.get('cron', '')})")
                        lines.append(f"    <i>Tới hạn:</i> {nxt} · <i>Sửa/huỷ:</i> dùng chat 'huỷ lịch {s['id']}'")
            except Exception:
                pass

            # Heartbeat
            lines.append("<b>Heartbeat:</b> 30 phút một lần (quét chủ động) · <i>Chỉ xem</i>")
            # Feed
            try:
                from .feed_auto import cron_times_label, DEFAULT_CRON
                feed_svc = self._svc("feed_auto")
                feed_cron = DEFAULT_CRON
                if feed_svc is not None and hasattr(feed_svc, "settings"):
                    st = await feed_svc.settings()
                    feed_cron = st.get("cron") or DEFAULT_CRON
                elif hasattr(self.cfg, "feed_auto_cron") and self.cfg.feed_auto_cron:
                    feed_cron = self.cfg.feed_auto_cron
                feed_lbl = cron_times_label(feed_cron) or feed_cron
                lines.append(f"<b>Feed chủ động:</b> {feed_lbl} (2 bài/ngày) · <i>Chỉ xem</i>")
            except Exception:
                from .feed_auto import cron_times_label, DEFAULT_CRON
                feed_lbl = cron_times_label(DEFAULT_CRON) or DEFAULT_CRON
                lines.append(f"<b>Feed chủ động:</b> {feed_lbl} (2 bài/ngày) · <i>Chỉ xem</i>")

            # Tracked items
            try:
                tracked = await self.memory.list_tracked_items(status="open")
                if tracked:
                    lines.append("\n<b>Cam kết đang theo dõi:</b>")
                    for t in tracked:
                        due = t.get("due_at") or "Đang theo dõi"
                        lines.append(f"  • <b>{t['title']}</b> (Hạn: {due})")
                        lines.append(f"    <i>Cập nhật/đóng:</i> nói trong chat 'đóng cam kết #{t['id']}'")
            except Exception:
                pass

            lines.append("\n<i>Mục có nhãn 'Sửa/huỷ qua chat' bạn có thể ra lệnh trực tiếp trong hội thoại để điều chỉnh.</i>")
            await message.answer("\n".join(lines), parse_mode="HTML")

        @dp.message(F.text.startswith("/cancel") | F.text.startswith("/stop"))
        async def cmd_cancel(message: Message) -> None:
            if not self._is_allowed(message):
                return
            parts = (message.text or "").strip().split()
            target_id = parts[1] if len(parts) > 1 else ""
            if target_id:
                stopped = False
                if self.activity:
                    stopped = self.activity.stop_task(target_id)
                if self.memory:
                    try:
                        t_row = await self.memory.get_task(target_id)
                        if t_row and t_row.get("status") == "running":
                            await self.memory.cancel_task(target_id, error="Đã dừng theo lệnh chat /stop")
                            stopped = True
                    except Exception:
                        pass
                if stopped:
                    await message.answer(f"Đã dừng tác vụ '{target_id}' thành công.")
                else:
                    await message.answer(f"Không tìm thấy tác vụ đang chạy với mã '{target_id}'.")
                return

            key = session_key_for(message)
            qp = self._queued_placeholders.pop(key, None)
            if qp:
                try:
                    await qp.delete()
                except Exception:
                    pass
            if self.batcher.is_busy(key):
                running_task = self._active_tasks.get(key)
                had_running_task = bool(running_task and not running_task.done())
                if had_running_task:
                    running_task.cancel()
                self.batcher.drain(key)
                try:
                    await self.memory.cancel_turn(key, reason="user_cancelled")
                except Exception:
                    pass
                if self.activity:
                    self.activity.stop_session_tasks(key)
                # Sửa T-24.4: Nếu có running_task, _on_batch đã bắt CancelledError và tự sửa placeholder.
                # Chỉ gửi tin mới khi không có running_task để tránh vừa sửa tin cũ vừa gửi tin mới cùng nội dung.
                if not had_running_task:
                    await message.answer("Đã dừng tác vụ đang chạy theo yêu cầu.")
            else:
                self.batcher.drain(key)
                try:
                    await self.memory.cancel_turn(key, reason="user_cancelled")
                except Exception:
                    pass
                if self.activity:
                    self.activity.stop_session_tasks(key)
                await message.answer("Đã dừng tác vụ theo yêu cầu.")

        @dp.message(F.text)
        async def on_text(message: Message) -> None:
            if not self._is_allowed(message):
                return
            if self._is_duplicate_message(message):
                return
            raw_text = (message.text or "").strip()

            # Chặn lệnh lạ không có handler, trả lời ngay không vào vòng agent (T-26)
            if raw_text.startswith("/"):
                first_token = raw_text.split()[0]
                if re.match(r"^/[a-zA-Z0-9_]+(@[a-zA-Z0-9_]+)?$", first_token):
                    cmd_name = first_token[1:].split("@")[0].lower()
                    if cmd_name not in ALL_HANDLED_COMMANDS:
                        await message.answer("Không có lệnh này — xem /help")
                        return

            clean_txt = raw_text.lower()
            if clean_txt in ("restart", "restart bot", "restart bot lại đi", "khởi động lại", "khởi động lại bot", "/restart"):
                await cmd_restart(message)
                return
            # Tự động bắt OAuth callback (Google Workspace, v.v.) khi user dán URL vào
            if message.text and ("oauth2callback" in message.text and "code=" in message.text):
                if await self._handle_oauth_callback(message):
                    return
            # Phase 6: các phản hồi dạng lệnh ngắn được xử lý ngay,
            # không vào agent: xác nhận 'quên thật', reply
            # 'duyệt'/'bỏ' vào note, 'làm luôn' vào thẻ ý tưởng.
            if await self._try_forget_confirm(message):
                return
            if getattr(message, "reply_to_message", None) is not None and \
                    await self._try_reply_actions(message):
                return
            if not self._should_respond(message):
                return
            await self._send_typing(message)
            key = session_key_for(message)
            self._sessions_meta[key] = message

            # Cơ chế ngắt khi người dùng đổi ý rõ ràng trong lúc bot đang bận (T-09)
            if self.batcher.is_busy(key):
                is_cancel, redirect = is_cancellation_intent(message.text or "")
                if is_cancel:
                    qp = self._queued_placeholders.pop(key, None)
                    if qp:
                        try:
                            await qp.delete()
                        except Exception:
                            pass
                    running_task = self._active_tasks.get(key)
                    had_running_task = bool(running_task and not running_task.done())
                    if had_running_task:
                        running_task.cancel()
                    self.batcher.drain(key)
                    try:
                        await self.memory.cancel_turn(key, reason="user_cancelled")
                    except Exception:
                        pass
                    if self.activity:
                        self.activity.stop_session_tasks(key)
                    if redirect:
                        await message.answer(f"Đã dừng việc trước, chuyển sang: {redirect}")
                        await self.batcher.add(key, redirect)
                    else:
                        # Sửa T-24.4: _on_batch đã sửa placeholder thành thông báo dừng, chỉ gửi tin mới khi không có running_task
                        if not had_running_task:
                            await message.answer("Đã dừng tác vụ theo yêu cầu.")
                    return
                # Gửi tin lúc bot đang bận: xác nhận xếp hàng ngay trong vài giây (T-24.7, X-06)
                await self._notify_queued(key, message)

            text = format_reply_context(message, message.text or "")
            await self.batcher.add(key, text)

        @dp.message(F.photo)
        async def on_photo(message: Message) -> None:
            if not self._is_allowed(message):
                return
            if self._is_duplicate_message(message):
                return
            if not self._should_respond(message):
                return
            await self._send_typing(message)
            key = session_key_for(message)
            self._sessions_meta[key] = message

            local_path: Optional[Path] = None
            if self.bot and message.photo:
                try:
                    largest = message.photo[-1]
                    tg_file = await self.bot.get_file(largest.file_id)
                    upload_dir = Path(self.cfg.workspace_dir) / "images" / "uploads"
                    upload_dir.mkdir(parents=True, exist_ok=True)
                    local_path = upload_dir / f"photo_{message.message_id}_{largest.file_unique_id}.jpg"
                    if tg_file.file_path:
                        await self.bot.download_file(tg_file.file_path, destination=str(local_path))
                except Exception as exc:
                    logger.warning("tải ảnh từ telegram thất bại: %s", exc)

            caption = (message.caption or "").strip()
            library = self._svc("library")
            item = None
            if local_path and local_path.is_file():
                if library is not None:
                    try:
                        item = await library.index_file(local_path, source="user_upload", caption=caption)
                    except Exception as exc:
                        logger.warning("lập chỉ mục ảnh vào thư viện lỗi: %s", exc)
                item_str = f" #{item['id']}" if item else ""
                clean_lbl = caption if caption else f"[Thư viện] Ảnh tải lên{item_str}"
                await self._post_media_to_library(
                    "photo",
                    FSInputFile(str(local_path)),
                    clean_lbl,
                    chat_id=message.chat.id,
                )
                item_str = f" • Thư viện #{item['id']}" if item else ""
                if caption:
                    text = f"[Người dùng gửi kèm ảnh: {local_path}{item_str}]\n{caption}"
                else:
                    text = f"[Người dùng gửi kèm ảnh: {local_path}{item_str}]"
            else:
                text = caption or "[Người dùng gửi một hình ảnh]"

            text = format_reply_context(message, text)
            if self.batcher.is_busy(key):
                await self._notify_queued(key, message)
            await self.batcher.add(key, text)

        @dp.message(F.video)
        async def on_video(message: Message) -> None:
            if not self._is_allowed(message):
                return
            if self._is_duplicate_message(message):
                return
            if not self._should_respond(message):
                return
            await self._send_typing(message)
            key = session_key_for(message)
            self._sessions_meta[key] = message
            vid = message.video
            local_path: Optional[Path] = None
            if self.bot and vid:
                try:
                    tg_file = await self.bot.get_file(vid.file_id)
                    upload_dir = Path(self.cfg.workspace_dir) / "uploads"
                    upload_dir.mkdir(parents=True, exist_ok=True)
                    vname = vid.file_name or f"video_{message.message_id}_{vid.file_unique_id}.mp4"
                    local_path = upload_dir / vname
                    if tg_file.file_path:
                        await self.bot.download_file(tg_file.file_path, destination=str(local_path))
                except Exception as exc:
                    logger.warning("tải video từ telegram thất bại: %s", exc)

            caption = (message.caption or "").strip()
            library = self._svc("library")
            item = None
            if local_path and local_path.is_file():
                if library is not None:
                    try:
                        item = await library.index_file(local_path, source="user_upload", caption=caption)
                    except Exception as exc:
                        logger.warning("lập chỉ mục video vào thư viện lỗi: %s", exc)
                item_str = f" #{item['id']}" if item else ""
                clean_lbl = caption if caption else f"[Thư viện] {vid.file_name or f'Video tải lên{item_str}'}"
                await self._post_media_to_library(
                    "video",
                    FSInputFile(str(local_path)),
                    clean_lbl,
                    chat_id=message.chat.id,
                )
                item_str = f" • Thư viện #{item['id']}" if item else ""
                dur_str = f", thời lượng: {vid.duration}s" if vid and vid.duration else ""
                text = f"[Người dùng gửi video: {local_path.name} (đường dẫn: {local_path}{dur_str}{item_str})]\n{caption}".strip()
            else:
                text = caption or f"[Người dùng gửi một video]"

            text = format_reply_context(message, text)
            if self.batcher.is_busy(key):
                await self._notify_queued(key, message)
            await self.batcher.add(key, text)

        @dp.message(F.audio)
        async def on_audio(message: Message) -> None:
            if not self._is_allowed(message):
                return
            if self._is_duplicate_message(message):
                return
            if not self._should_respond(message):
                return
            await self._send_typing(message)
            key = session_key_for(message)
            self._sessions_meta[key] = message
            aud = message.audio
            local_path: Optional[Path] = None
            if self.bot and aud:
                try:
                    tg_file = await self.bot.get_file(aud.file_id)
                    upload_dir = Path(self.cfg.workspace_dir) / "uploads"
                    upload_dir.mkdir(parents=True, exist_ok=True)
                    aname = aud.file_name or f"audio_{message.message_id}_{aud.file_unique_id}.mp3"
                    local_path = upload_dir / aname
                    if tg_file.file_path:
                        await self.bot.download_file(tg_file.file_path, destination=str(local_path))
                except Exception as exc:
                    logger.warning("tải audio từ telegram thất bại: %s", exc)

            caption = (message.caption or "").strip()
            library = self._svc("library")
            item = None
            if local_path and local_path.is_file():
                if library is not None:
                    try:
                        item = await library.index_file(local_path, source="user_upload", caption=caption)
                    except Exception as exc:
                        logger.warning("lập chỉ mục audio vào thư viện lỗi: %s", exc)
                item_str = f" #{item['id']}" if item else ""
                clean_lbl = caption if caption else f"[Thư viện] {aud.file_name or f'Âm thanh tải lên{item_str}'}"
                await self._post_media_to_library(
                    "audio",
                    FSInputFile(str(local_path)),
                    clean_lbl,
                    chat_id=message.chat.id,
                )
                item_str = f" • Thư viện #{item['id']}" if item else ""
                dur_str = f", thời lượng: {aud.duration}s" if aud and aud.duration else ""
                text = f"[Người dùng gửi tệp âm thanh: {local_path.name} (đường dẫn: {local_path}{dur_str}{item_str})]\n{caption}".strip()
            else:
                text = caption or f"[Người dùng gửi một tệp âm thanh]"

            text = format_reply_context(message, text)
            if self.batcher.is_busy(key):
                await self._notify_queued(key, message)
            await self.batcher.add(key, text)

        # --- Telegram Business Handlers (T-29) ---
        @dp.business_connection()
        async def on_business_connection(conn: BusinessConnection) -> None:
            await self.business_service.handle_business_connection(conn)

        @dp.business_message()
        async def on_business_message(message: Message) -> None:
            await self.business_service.process_business_message(message)

        @dp.edited_business_message()
        async def on_edited_business_message(message: Message) -> None:
            logger.debug("Khách sửa business_message: %s", getattr(message, "message_id", None))

        @dp.message(F.text.startswith("/business") | F.text.startswith("/biz"))
        async def cmd_business(message: Message) -> None:
            if not self._is_allowed(message):
                return
            report = await self.business_service.get_status_report()
            cfg_on = "Bật (1)" if report["config_enabled"] else "Tắt (0) — đặt TELEGRAM_BUSINESS_ENABLED=1 để bật"
            conn_info = report.get("connection_info")
            if conn_info and conn_info.get("is_enabled"):
                conn_status = f"Đang kết nối (ID: <code>{conn_info.get('connection_id')}</code>)"
                reply_perm = "Có quyền gửi thay nick chủ" if conn_info.get("can_reply") else "[Lưu ý] Thiếu quyền can_reply"
            else:
                conn_status = "Chưa kết nối (hoặc đã ngắt)"
                reply_perm = "Vào Cài đặt Telegram → Telegram Business → Chatbots để kết nối"

            stats = report.get("stats", {})
            lines = [
                "<b>BÁO CÁO TELEGRAM BUSINESS CHATBOT (T-29)</b>",
                f"• Cấu hình hệ thống: <b>{cfg_on}</b>",
                f"• Trạng thái kết nối: {conn_status}",
                f"• Quyền trả lời: <i>{reply_perm}</i>",
                "",
                "<b>Thống kê hoạt động:</b>",
                f"• Tự động trả lời (Auto-reply): <b>{stats.get('auto_replies', 0)}</b>",
                f"• Bản nháp cần duyệt (Drafts): <b>{stats.get('drafts_created', 0)}</b> (Đã duyệt: {stats.get('drafts_approved', 0)} · Từ chối: {stats.get('drafts_denied', 0)})",
                f"• Sản phẩm trong catalog: <b>{report.get('products_count', 0)}</b> món (cấm bịa giá)",
                f"• FAQ giải đáp sẵn: <b>{report.get('faq_count', 0)}</b> chủ đề",
                "",
                "<i>Nguyên tắc an toàn: STK ngân hàng & giảm giá luôn soạn nháp chờ chủ duyệt, tuyệt đối không tự gửi.</i>",
            ]
            await message.answer("\n".join(lines), parse_mode="HTML")

        # Gắn tham chiếu các lệnh cốt lõi cho test & tái sử dụng
        self._handle_help_command = cmd_help
        self._handle_model_command = cmd_model
        self._handle_the_duyet_command = cmd_the_duyet
        self._handle_memory_command = cmd_memory
        self._handle_upcoming_command = cmd_upcoming
        self._handle_text_message = on_text

    async def _consolidate_closed(self, key: str) -> None:
        try:
            await self.consolidator.run_once(session_key=key)
        except Exception as exc:
            logger.warning("consolidation sau /new lỗi (bỏ qua): %s", exc)

    async def run(self) -> None:
        if not self.cfg.telegram_bot_token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN chưa được cấu hình")
        self.bot = Bot(token=self.cfg.telegram_bot_token)
        if hasattr(self, "business_service") and self.business_service is not None:
            self.business_service.bot = self.bot
        me = await self.bot.get_me()
        self.bot._me_username = me.username  # type: ignore[attr-defined]
        logger.info("bot @%s bắt đầu polling", me.username)
        # Marketplace 1.3.0: bot đã sẵn sàng -> gắn trình thẻ +
        # notifier rồi quyết toán boot (thông báo đối chiếu sau
        # restart + restart lần 2 nếu vừa tự rollback). Chạy nền
        # để không chặn polling.
        if self.marketplace is not None:
            self.marketplace.bind_card_presenter(
                self.send_marketplace_card_to_owner)

            async def _notify(text: str) -> None:
                if self.bot is not None and \
                        self.cfg.allowed_user_id:
                    await self.bot.send_message(
                        self.cfg.allowed_user_id, text)

            self.marketplace.bind_notifier(_notify)
            import asyncio as _asyncio
            _asyncio.create_task(self.marketplace.settle_boot())
        # Feed chủ động 1.4.0: gắn sender cho runner — runner
        # đăng bài + báo tạm dừng qua bot thật (trả message_id).
        feed_auto = self._svc("feed_auto")
        if feed_auto is not None and self.bot is not None:
            async def _feed_send(chat_id: int, text: str,
                                 thread_id=None,
                                 reply_markup=None,
                                 message_thread_id=None,
                                 **extra) -> int:
                kwargs = dict(extra)
                tid = thread_id if thread_id is not None else message_thread_id
                if tid:
                    kwargs["message_thread_id"] = tid
                if reply_markup is not None:
                    kwargs["reply_markup"] = reply_markup
                msg = await self.bot.send_message(
                    chat_id, text, **kwargs)
                return int(getattr(msg, "message_id", 0) or 0)

            feed_auto.bind_sender(_feed_send)
        # Vault 1.6.0: gắn notifier gửi thẻ Vault cho agent tool
        reg = getattr(self.agent, "registry", None)
        if reg is not None:
            from .vault import register_vault_tools
            register_vault_tools(
                reg, self.cfg,
                notifier=self.send_vault_card_to_owner,
                vault_broker=self.vault_broker)
        # Menu lệnh "/" cho user thấy ngay (Khối 1, 1.2.0). Lỗi
        # đăng ký chỉ log warning — không được làm sập bot.
        try:
            await self.bot.set_my_commands([
                BotCommand(command=c, description=d)
                for c, d in MENU_COMMANDS
            ])
        except Exception as exc:
            logger.warning("đăng ký set_my_commands lỗi (bỏ qua): %s",
                           exc)
        # Seed goals nếu DB chưa có
        try:
            from .planning import ensure_seed_goals
            await ensure_seed_goals(self.memory)
        except Exception as exc:
            logger.warning("ensure_seed_goals lỗi (bỏ qua): %s", exc)

        # Khôi phục model_brain đã lưu trước đó nếu có
        try:
            saved_model = await self.memory.kv_get("config:model_brain")
            if saved_model:
                object.__setattr__(self.cfg, "model_brain", saved_model)
                if hasattr(self, "agent") and hasattr(self.agent, "cfg"):
                    object.__setattr__(self.agent.cfg, "model_brain", saved_model)
        except Exception:
            pass

        # Báo khởi động lại thành công nếu vừa restart
        try:
            raw_notify = await self.memory.kv_get("system:restart_notify")
            if raw_notify and self.bot is not None:
                await self.memory.kv_del("system:restart_notify")
                import json
                info = json.loads(raw_notify)
                cid = info.get("chat_id") or self.cfg.allowed_user_id
                tid = info.get("thread_id")
                reason = info.get("reason") or "Khởi động lại theo yêu cầu"
                if cid:
                    kws = {
                        "chat_id": cid,
                        "text": f"<b>Bot Mulon đã khởi động lại thành công và sẵn sàng phục vụ!</b>\n<i>({reason})</i>",
                        "parse_mode": "HTML",
                    }
                    if tid:
                        kws["message_thread_id"] = tid
                    await self.bot.send_message(**kws)
        except Exception as exc:
            logger.warning("Lỗi gửi thông báo restart: %s", exc)

        if not self.cfg.allowed_user_id and not getattr(self.cfg, "allowed_user_ids", ()):
            from mulon.allowlist import get_or_create_claim_token
            claim_file = getattr(self.cfg, "claim_token_path", PROJECT_ROOT / "data" / "claim_token.txt")
            tok = get_or_create_claim_token(claim_file)
            logger.warning(
                "\n================================================================================\n"
                " [MULON SETUP] BOT CHƯA CÓ CHỦ SỞ HỮU (ALLOWED_USER_ID = 0)!\n"
                " Mã Claim Token: %s\n"
                " Để nhận quyền sở hữu bot, hãy nhắn cho bot trên Telegram:\n"
                "     /setup %s\n"
                "================================================================================",
                tok, tok
            )

        used_updates = self.dp.resolve_used_update_types()
        business_updates = {
            "business_connection",
            "business_message",
            "edited_business_message",
            "deleted_business_messages",
        }
        all_allowed = list(set(used_updates) | business_updates)
        await self.dp.start_polling(self.bot, allowed_updates=all_allowed)
