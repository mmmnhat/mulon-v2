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
import re
from pathlib import Path
from types import SimpleNamespace
from typing import Awaitable, Callable, Optional

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ChatType
from aiogram.types import (BotCommand, CallbackQuery, FSInputFile,
                           InlineKeyboardButton, InlineKeyboardMarkup,
                           InputMediaPhoto, Message, ReactionTypeEmoji)

from . import surfaces as surf
from .agent import clean_task_title
from .ideas import format_idea_card, parse_do_reply
from .proactivity import effective_enabled as heartbeat_effective
from .webapp_server import ActivityTracker, plain_step_label, \
    tool_action_label

logger = logging.getLogger("mulon.telegram")

# Danh sách lệnh đăng ký lên Telegram lúc khởi động (set_my_commands)
# để user gõ "/" là thấy menu — mô tả tiếng Việt ngắn.
BOT_COMMANDS: list[tuple[str, str]] = [
    ("start", "Bắt đầu / nghi lễ lần đầu"),
    ("menu", "Mở bảng điều khiển (Mini App)"),
    ("status", "Trạng thái hệ thống"),
    ("new", "Chốt phiên, bắt đầu ngữ cảnh mới"),
    ("memory", "Xem bộ nhớ + fact kèm nguồn"),
    ("setup_topics", "Tạo các topic-tab trong group"),
    ("topics", "Xem map topic"),
    ("chatphu", "Tạo chat phụ (topic tự do)"),
    ("chatphu_list", "Liệt kê chat phụ đang mở"),
    ("dongchat", "Đóng chat phụ hiện tại"),
    ("chatphu_dong", "Đóng chat phụ theo id"),
    ("chatphu_mo", "Mở lại chat phụ theo id"),
    ("feedbrief", "Xem/sửa brief của Feed"),
    ("feedsources", "Nguồn bổ sung của Feed"),
    ("ideas", "Sinh thẻ ý tưởng"),
    ("idea_do", "Làm luôn thẻ ý tưởng"),
    ("idea_bo", "Bỏ qua thẻ ý tưởng"),
    ("notes", "Đề xuất chủ động đang chờ"),
    ("note_ok", "Duyệt đề xuất"),
    ("note_bo", "Bỏ đề xuất"),
    ("library", "Xem Library"),
    ("trash_item", "Cho item vào thùng rác"),
    ("restore_item", "Khôi phục item"),
    ("share_item", "Chia sẻ item (chờ host duyệt)"),
    ("vault", "Nhận link form nhập bí mật"),
    ("forget", "Quên một chủ đề (có kế hoạch trước)"),
    ("export_memory", "Xuất bản sao ký ức"),
    ("quyen", "Quyền của agent bằng lời thường"),
    ("approvals", "Lịch sử quyết định quyền"),
    ("the_duyet", "Gửi thẻ phê duyệt thử (thật, vô hại)"),
    ("voiceon", "Bật trả lời bằng giọng"),
    ("voiceoff", "Tắt trả lời bằng giọng"),
    # Sửa UI: 3 lệnh này đã có handler nhưng trước đây không có
    # trong menu lệnh nên người dùng không biết để gọi.
    ("feed_now", "Chạy Feed ngay một lượt"),
    ("pin_item", "Ghim item Library theo id"),
    ("rename_item", "Đổi tên item Library theo id"),
]


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
            self._schedule(key)

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
        is_burst = (
            _is_short_opener(text)
            or (text or "").strip().lower().startswith("[người dùng gửi")
            or len(self._buffers.get(key, [])) > 1
        )
        delay = (self.debounce_s * 1.5) if is_burst else self.debounce_s
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
    out = html.escape(out, quote=False)
    out = _BOLD_RE.sub(r"<b>\1</b>", out)
    out = _HEADING_RE.sub(r"<b>\1</b>", out)
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
        self.batcher = MessageBatcher(cfg.debounce_seconds, self._on_batch)
        self._register_handlers()

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
        rep = getattr(message, "reply_to_message", None)
        rep_user = getattr(rep, "from_user", None) if rep else None
        if rep_user and self.bot is not None and getattr(rep_user, "id", None) == self.bot.id:
            return True
        username = getattr(self.bot, "_me_username", None) if self.bot else None
        if username and f"@{username}" in content:
            return True
        return False

    def _is_allowed(self, message: Message) -> bool:
        if not self.cfg.allowed_user_id:
            return False  # chưa cấu hình allowlist -> không phục vụ ai
        return bool(message.from_user and message.from_user.id == self.cfg.allowed_user_id)

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
            async with lock:  # mỗi session tối đa 1 lượt active (mục 3.3)
                # Drain: tin tới trong lúc lượt này chờ lock
                # thuộc về chính lượt này — gộp vào input theo
                # đúng thứ tự, không sinh lượt thừa.
                extra = self.batcher.drain(key)
                if extra:
                    parts = parts + extra
                    joined = "\n".join(parts)
                try:
                    await anchor.react([ReactionTypeEmoji(emoji="👀")])
                except Exception:
                    pass
                placeholder = None
                state = {"shown": "", "last_edit": 0.0}

                async def on_delta(piece: str) -> None:
                    state["shown"] += piece
                    now = asyncio.get_event_loop().time()
                    if placeholder is not None and now - state["last_edit"] > 1.0:
                        state["last_edit"] = now
                        try:
                            await placeholder.edit_text(state["shown"][:4000])
                        except Exception:
                            pass

                if True:
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
                # 1.2.0: tiến trình MỘT DÒNG trên placeholder (chi
                # tiết đầy đủ ở Mini App) + thẻ duyệt khi policy
                # nấc "ask". Chống flood: tối đa 1 edit/1,2s và
                # không đè lên text đang stream của fast path.
                status_state = {"last": 0.0}

                async def _edit_status(label: str) -> None:
                    if placeholder is None or state["shown"]:
                        return
                    now = asyncio.get_event_loop().time()
                    if now - status_state["last"] < 1.2:
                        return
                    status_state["last"] = now
                    try:
                        await placeholder.edit_text(label)
                    except Exception:
                        pass

                async def on_event(kind: str, payload: dict) -> None:
                    # Nhãn lời thường DÙNG CHUNG cho chat + Mini
                    # App (plain_step_label) — mặt chat không lộ
                    # tên tool thô.
                    label = plain_step_label(kind, payload)
                    if label:
                        self.activity.set_step(label)
                    if kind == "approval_requested":
                        thread_id = None
                        if getattr(anchor, "is_topic_message", False):
                            thread_id = anchor.message_thread_id
                        await self.send_approval_card(
                            anchor.chat.id, thread_id, payload)
                    elif label:
                        await _edit_status(label + "…")

                self.activity.start_turn(key, clean_task_title(joined))
                try:
                    result = await self.agent.handle(
                        key, joined, on_delta=on_delta,
                        on_event=on_event)
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
                final = result.text or "(không có nội dung)"
                chunks = chunk_html(md_to_html(final))
                try:
                    if placeholder is not None:
                        await placeholder.edit_text(chunks[0], parse_mode="HTML")
                        for extra in chunks[1:]:
                            await anchor.answer(extra, parse_mode="HTML")
                    else:
                        for chunk in chunks:
                            await anchor.answer(chunk, parse_mode="HTML")
                except Exception:
                    # HTML lỗi ở đâu đó -> gửi lại bản ESCAPE (NC-1:
                    # không strip-tag nữa — strip ăn mất cả code
                    # chứa <div>, "a < b" trong câu trả lời).
                    for chunk in chunk_html(html.escape(final)):
                        await anchor.answer(chunk, parse_mode="HTML")
                await self._maybe_send_photo(anchor, final)
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
            typing_stop.set()
            if typing_task is not None:
                typing_task.cancel()
            # Luôn nhả bận + kick nhịp debounce cho phần tin bị
            # giữ (nếu còn) — chạy cả khi lượt xử lý ném lỗi.
            self.activity.end_turn()
            self.batcher.release(key)

    # ---- media / photo output ----
    async def _maybe_send_photo(self, anchor: Message, final_text: str) -> None:
        """Tự động phát hiện nếu trong câu trả lời có file ảnh local hoặc link ảnh
        trực tiếp (từ tool sinh ảnh Agnes AI / media) để gửi ảnh thật vào chat."""
        if not final_text:
            return
        # 1. Tìm đường dẫn file ảnh local
        img_paths = re.findall(
            r"(?:[\w\-\./]+)?images/[\w\-]+\.(?:png|jpg|jpeg|webp)",
            final_text, re.IGNORECASE,
        )
        sent = False
        for p in img_paths:
            candidates = [
                Path(p),
                Path(self.cfg.workspace_dir) / "images" / Path(p).name,
                Path(self.cfg.workspace_dir) / p,
            ]
            for cand in candidates:
                if cand.is_file() and cand.stat().st_size > 0:
                    try:
                        await anchor.answer_photo(FSInputFile(str(cand)))
                        sent = True
                        break
                    except Exception as exc:
                        logger.warning("gửi ảnh local qua telegram lỗi: %s", exc)
            if sent:
                break

        if not sent:
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
                        await anchor.answer_photo(clean_u)
                        sent = True
                        break
                    except Exception as exc:
                        logger.warning("gửi ảnh url qua telegram lỗi: %s", exc)

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
                "🧭 <b>Bảng điều khiển Mulon</b>\n"
                "Tiến trình, phê duyệt, lịch, hồ sơ, kết nối, vault "
                "và quyền — tất cả ở trong app. Chạm nút để mở.",
                kb)
        return (
            "🧭 Bảng điều khiển (Mini App) chưa mở được vì thiếu "
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
                text="✅ Duyệt",
                callback_data=f"appr:1:{approval_id}"),
            InlineKeyboardButton(
                text="❌ Chặn",
                callback_data=f"appr:0:{approval_id}"),
        ]
        if rememberable:
            buttons.append(InlineKeyboardButton(
                text="📌 Duyệt và nhớ",
                callback_data=f"appr:2:{approval_id}"))
        rows: list[list[InlineKeyboardButton]] = [buttons]
        link = webapp_direct_link(self.cfg, self._bot_username(),
                                  f"approve_{approval_id}")
        if link:
            rows.append([InlineKeyboardButton(
                text="Xem chi tiết", url=link)])
        return InlineKeyboardMarkup(inline_keyboard=rows)

    async def send_approval_card(self, chat_id: int,
                                 thread_id: Optional[int],
                                 payload: dict) -> Optional[int]:
        """Gửi tin thẻ duyệt vào đúng topic đang chạy + attach
        định tuyến vào broker để gỡ đúng thẻ khi có quyết định."""
        if self.bot is None or self.broker is None:
            return None
        import html as _html

        from .approvals import approval_scope

        approval_id = str(payload.get("approval_id") or "")
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
            f"🔐 <b>{_html.escape(action)}</b>",
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
            "approved": "✅ Đã ghi nhận: anh vừa DUYỆT thẻ thử.",
            "denied": "❌ Đã ghi nhận: anh vừa CHẶN thẻ thử.",
            "expired": "⌛ Thẻ duyệt thử hết hạn — chưa có quyết "
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
            f"🧩 <b>{_html.escape(str(payload.get('title') or 'Thao tác MCP'))}</b>",
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
        """Gửi thẻ yêu cầu bí mật vào DM của owner (1.6.0)."""
        owner = int(getattr(self.cfg, "allowed_user_id", 0) or 0)
        if not owner or self.bot is None:
            return False
        label = info.get("label", "")
        desc = info.get("description", "")
        safe_param = info.get("startapp_param") or f"vault_{label.replace(':', '__')}"
        direct_url = webapp_direct_link(self.cfg, self._bot_username(), safe_param)
        lines = [
            f"🔐 Yêu cầu bí mật vào Kho",
            f"Agent cần thông tin: {label}",
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
            await self.bot.send_message(
                owner, "\n".join(lines), reply_markup=kb)
            return True
        except Exception as exc:
            logger.warning("Gửi thẻ Vault vào chat lỗi: %s", exc)
            return False

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

    async def _on_approval_decided(self, record: dict) -> None:
        """Listener của broker: quyết định xong (duyệt/chặn/HẾT
        HẠN) -> XÓA tin thẻ khỏi chat + ghi 1 dòng vào topic
        Lịch sử & Hệ thống nếu topic đó tồn tại."""
        if self.bot is None:
            return
        card = record.get("card") or {}
        chat_id = card.get("chat_id")
        message_id = card.get("message_id")
        if chat_id and message_id:
            try:
                await self.bot.delete_message(chat_id, message_id)
            except Exception:
                # Không xóa được (quá cũ/thiếu quyền): sửa thành
                # đã xử lý + gỡ bàn phím để không bấm lại được.
                try:
                    await self.bot.edit_message_text(
                        "Đã xử lý thẻ duyệt này.", chat_id=chat_id,
                        message_id=message_id)
                    await self.bot.edit_message_reply_markup(
                        chat_id=chat_id, message_id=message_id,
                        reply_markup=None)
                except Exception:
                    pass
        payload = record.get("payload") or {}
        outcome = record.get("outcome", "")
        label = {"approved": "✅ Đã duyệt",
                 "denied": "❌ Đã chặn",
                 "expired": "⌛ Thẻ duyệt hết hạn"}.get(
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

    # ---- handlers ----
    def _register_handlers(self) -> None:
        dp = self.dp

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
            await message.answer(text, parse_mode="HTML", **kwargs)

        @dp.callback_query(F.data.startswith("appr:"))
        async def on_approval_button(query: CallbackQuery) -> None:
            user_id = query.from_user.id if query.from_user else 0
            _, note = await self.handle_approval_callback(
                query.data or "", user_id)
            try:
                await query.answer(
                    note, show_alert=(user_id
                                      != self.cfg.allowed_user_id))
            except Exception:
                pass

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
            await message.answer("Đã chốt phiên. Lượt sau bắt đầu ngữ cảnh mới.")

        @dp.message(F.text.startswith("/memory"))
        async def cmd_memory(message: Message) -> None:
            if not self._is_allowed(message):
                return
            facts = await self.memory.active_facts(limit=50)
            lines = ["Fact đang hiệu lực (kèm nguồn — hỏi 'sao mày "
                     "biết' là truy được tới đây):"]
            if not facts:
                lines.append("(chưa có)")
            for f in facts:
                prefix = f"[{f['subject']}] " if f["subject"] else ""
                lines.append(f"- #{f['id']} {prefix}{f['fact']}")
                prov = []
                if f.get("source"):
                    prov.append(f"nguồn: {f['source']}")
                if f.get("created_at"):
                    prov.append(f"ghi lúc {f['created_at']}")
                if prov:
                    lines.append("  · " + " · ".join(prov))
                if f.get("source_msg_id"):
                    src = await self.memory.get_message(
                        int(f["source_msg_id"]))
                    if src:
                        excerpt = str(src["content"])[:120]
                        lines.append(
                            f"  · từ tin #{src['id']} "
                            f"({src['role']}): {excerpt}")
            mem_md = self.dossier.files.get("MEMORY.md", "").strip()
            if mem_md:
                lines.append("\nMEMORY.md:\n" + mem_md[:2500])
            # Text thuần (NC-1): không chèn **, không parse HTML —
            # nội dung fact/MEMORY.md chứa gì cũng hiển thị nguyên.
            text = "\n".join(lines)
            for chunk in chunk_html(html.escape(text)):
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
                    message.chat.id, format_idea_card(card), **kwargs)
            if thread != getattr(message, "message_thread_id", None):
                await message.answer(
                    f"Đã đăng {len(cards)} thẻ ý tưởng vào topic "
                    "Ideas.")

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
                ext = p.suffix.lower()
                caption = f"#{item['id']} • {item['name']}"
                try:
                    if item.get("kind") == "image" or ext in (".jpg", ".jpeg", ".png", ".webp", ".gif"):
                        await message.answer_photo(photo=FSInputFile(str(p)), caption=caption)
                    elif item.get("kind") == "media" or ext in (".ogg", ".mp3", ".wav", ".m4a"):
                        await message.answer_voice(voice=FSInputFile(str(p)), caption=caption)
                    else:
                        await message.answer_document(document=FSInputFile(str(p)), caption=caption)
                except Exception as e:
                    await message.answer(f"Lỗi khi gửi tệp #{target_id}: {e}")
                return

            # 2. Nếu người dùng gọi /library để duyệt thư viện
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
                        caption=(f"🖼️ Thư viện ảnh Mulon ({len(image_items)} ảnh) • #{it['id']} {it['name']}"
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
                        caption=f"🖼️ #{it['id']} {it['name']}"
                    )
                except Exception as e:
                    logger.warning("Gửi ảnh đơn thất bại: %s", e)

            # Gửi danh sách tóm tắt có icon đẹp mắt và nút mở Mini App
            kb = None
            direct_url = webapp_direct_link(self.cfg, self._bot_username(), "panel")
            if direct_url:
                kb = InlineKeyboardMarkup(inline_keyboard=[[
                    InlineKeyboardButton(text="🖼️ Mở Bảng điều khiển (Mini App)", url=direct_url)
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

        @dp.message(F.text.startswith("/the_duyet"))
        async def cmd_the_duyet(message: Message) -> None:
            if not self._is_allowed(message):
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
            doc = message.document
            name = (doc.file_name or "").lower()
            if any(name.endswith(ext) for ext in (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif")):
                if not self._should_respond(message):
                    return
                upload_dir = Path(self.cfg.workspace_dir) / "images" / "uploads"
                upload_dir.mkdir(parents=True, exist_ok=True)
                local = upload_dir / f"doc_{message.message_id}_{doc.file_name or 'image.jpg'}"
                if self.bot:
                    try:
                        tg_file = await self.bot.get_file(doc.file_id)
                        if tg_file.file_path:
                            await self.bot.download_file(tg_file.file_path, destination=str(local))
                    except Exception as exc:
                        logger.warning("tải ảnh tài liệu lỗi: %s", exc)
                caption = (message.caption or "").strip()
                if local.is_file():
                    text = f"[Người dùng gửi kèm ảnh: {local}]\n{caption}" if caption else f"[Người dùng gửi kèm ảnh: {local}]"
                else:
                    text = caption or "[Người dùng gửi một file hình ảnh]"
                text = format_reply_context(message, text)
                key = session_key_for(message)
                self._sessions_meta[key] = message
                await self.batcher.add(key, text)
                return

            # Hiện chỉ nhận file để import ký ức (mục 16.11); file
            # khác được báo rõ thay vì nuốt im lặng.
            if not (name.endswith(".md") or name.endswith(".json")
                    or name.endswith(".txt")):
                await message.answer(
                    "Hiện mình chỉ nhận file .md/.json/.txt để "
                    "import ký ức hoặc file ảnh. File này chưa được xử lý.")
                return
            if self.bot is None:
                await message.answer(
                    "Chưa tải được file ở bản chạy này.")
                return
            try:
                tg_file = await self.bot.get_file(doc.file_id)
                in_dir = Path(self.cfg.workspace_dir) / "imports"
                in_dir.mkdir(parents=True, exist_ok=True)
                local = in_dir / (doc.file_name or "import.md")
                await self.bot.download_file(
                    tg_file.file_path, destination=str(local))
                text = local.read_text(encoding="utf-8",
                                       errors="replace")
            except Exception as exc:
                logger.warning("tải file import lỗi: %s", exc)
                await message.answer("Mình không tải/đọc được file này.")
                return
            items = surf.parse_import_content(text, doc.file_name or "")
            added = 0
            for item in items:
                await self.memory.add_fact(
                    item["fact"], subject=item["subject"],
                    source="import")
                added += 1
            await self.memory.log_trajectory(
                session_key_for(message), "memory_import",
                {"file": doc.file_name, "facts_added": added})
            await message.answer(
                f"Đã import {added} fact từ file "
                f"{doc.file_name} (nguồn: import).")

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
            if not self._should_respond_voice(message):
                return
            await self._send_typing(message)
            await self._process_voice_message(message)

        @dp.message(F.text)
        async def on_text(message: Message) -> None:
            if not self._is_allowed(message):
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

            text = format_reply_context(message, message.text or "")
            await self.batcher.add(key, text)

        @dp.message(F.photo)
        async def on_photo(message: Message) -> None:
            if not self._is_allowed(message):
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
            if local_path and local_path.is_file():
                if caption:
                    text = f"[Người dùng gửi kèm ảnh: {local_path}]\n{caption}"
                else:
                    text = f"[Người dùng gửi kèm ảnh: {local_path}]"
            else:
                text = caption or "[Người dùng gửi một hình ảnh]"

            text = format_reply_context(message, text)
            await self.batcher.add(key, text)

    async def _consolidate_closed(self, key: str) -> None:
        try:
            await self.consolidator.run_once(session_key=key)
        except Exception as exc:
            logger.warning("consolidation sau /new lỗi (bỏ qua): %s", exc)

    async def run(self) -> None:
        if not self.cfg.telegram_bot_token:
            raise RuntimeError("TELEGRAM_BOT_TOKEN chưa được cấu hình")
        self.bot = Bot(token=self.cfg.telegram_bot_token)
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
                                 thread_id=None) -> int:
                kwargs = {}
                if thread_id:
                    kwargs["message_thread_id"] = thread_id
                msg = await self.bot.send_message(
                    chat_id, text, **kwargs)
                return int(getattr(msg, "message_id", 0) or 0)

            feed_auto.bind_sender(_feed_send)
        # Vault 1.6.0: gắn notifier gửi thẻ Vault cho agent tool
        reg = getattr(self.agent, "registry", None)
        if reg is not None:
            from .vault import register_vault_tools
            register_vault_tools(
                reg, self.cfg, notifier=self.send_vault_card_to_owner)
        # Menu lệnh "/" cho user thấy ngay (Khối 1, 1.2.0). Lỗi
        # đăng ký chỉ log warning — không được làm sập bot.
        try:
            await self.bot.set_my_commands([
                BotCommand(command=c, description=d)
                for c, d in BOT_COMMANDS
            ])
        except Exception as exc:
            logger.warning("đăng ký set_my_commands lỗi (bỏ qua): %s",
                           exc)
        await self.dp.start_polling(self.bot)
