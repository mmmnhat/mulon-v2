"""Bề mặt Telegram (aiogram 3) — kênh duy nhất (thiết kế mục 16).

- Allowlist cứng theo ALLOWED_USER_ID: người khác ra lệnh không chạy.
- Gom tin liên tiếp (mục 16.1): debounce ~2.5s, cả chùm thành 1 lượt.
- Ack bằng reaction thay tin trạng thái rác; streaming bằng edit tại chỗ.
- Session key theo (chat, topic): `agent:main:telegram:<loại>:<chat>:topic:<id>`.
- Group có người khác: chỉ đáp khi được mention/reply (GROUP_MENTION_ONLY).
- Lệnh tối thiểu: /start /status /new /memory. Mọi tính năng khác đi
  bằng ngôn ngữ tự nhiên.
- Voice (Phase 4, mục 8.1): tin nhắn thoại -> STT (voice.py) ->
  bản đã hiểu ngữ đi tiếp vào agent như tin chữ. /voiceon /
  /voiceoff bật/tắt trả lời bằng giọng theo từng session.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Awaitable, Callable, Optional

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ChatType
from aiogram.types import FSInputFile, Message, ReactionTypeEmoji

logger = logging.getLogger("mulon.telegram")

FlushFn = Callable[[str, str, list[str]], Awaitable[None]]


class MessageBatcher:
    """Gom các tin liên tiếp của cùng 1 session thành 1 lượt xử lý."""

    def __init__(self, debounce_s: float, on_flush: FlushFn):
        self.debounce_s = debounce_s
        self.on_flush = on_flush
        self._buffers: dict[str, list[str]] = {}
        self._timers: dict[str, asyncio.Task] = {}

    async def add(self, key: str, text: str) -> None:
        self._buffers.setdefault(key, []).append(text)
        old = self._timers.get(key)
        if old is not None:
            old.cancel()
        self._timers[key] = asyncio.create_task(self._delayed_flush(key))

    async def _delayed_flush(self, key: str) -> None:
        try:
            await asyncio.sleep(self.debounce_s)
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


# ------------------------------- bot -------------------------------

class TelegramSurface:
    def __init__(self, cfg, agent, memory, dossier, consolidator=None,
                 voice=None):
        self.cfg = cfg
        self.agent = agent
        self.memory = memory
        self.dossier = dossier
        self.consolidator = consolidator
        # VoiceService (mulon.voice) — None thì tính năng voice tắt
        # sạch: tin thoại được báo chưa sẵn sàng, /voiceon vô hiệu.
        self.voice = voice
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

    # ---- điều kiện đáp trong group ----
    def _should_respond(self, message: Message) -> bool:
        if message.chat.type == ChatType.PRIVATE:
            return True
        if (message.text or "").startswith("/"):
            return True
        if not self.cfg.group_mention_only:
            return True
        if message.reply_to_message and message.reply_to_message.from_user \
                and self.bot is not None and message.reply_to_message.from_user.id == self.bot.id:
            return True
        username = getattr(self.bot, "_me_username", None) if self.bot else None
        if username and f"@{username}" in (message.text or ""):
            return True
        return False

    def _is_allowed(self, message: Message) -> bool:
        if not self.cfg.allowed_user_id:
            return False  # chưa cấu hình allowlist -> không phục vụ ai
        return bool(message.from_user and message.from_user.id == self.cfg.allowed_user_id)

    # ---- luồng xử lý 1 lượt ----
    async def _on_batch(self, key: str, joined: str, parts: list[str]) -> None:
        anchor = self._sessions_meta.get(key)
        if anchor is None:
            return
        lock = self._locks.setdefault(key, asyncio.Lock())
        async with lock:  # mỗi session tối đa 1 lượt active (mục 3.3)
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
            result = await self.agent.handle(
                key, joined, on_delta=on_delta
            )
            final = result.text or "(không có nội dung)"
            chunks = chunk_html(final)
            try:
                if placeholder is not None:
                    await placeholder.edit_text(chunks[0], parse_mode="HTML")
                    for extra in chunks[1:]:
                        await anchor.answer(extra, parse_mode="HTML")
                else:
                    for chunk in chunks:
                        await anchor.answer(chunk, parse_mode="HTML")
            except Exception:
                # HTML lỗi ở đâu đó -> gửi lại dạng text thuần, không nuốt kết quả.
                for chunk in chunk_html(final):
                    plain = re.sub(r"<[^>]+>", "", chunk)
                    await anchor.answer(plain)
            await self._maybe_send_voice(key, anchor, final)

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
        return bool(
            message.reply_to_message
            and message.reply_to_message.from_user
            and self.bot is not None
            and message.reply_to_message.from_user.id == self.bot.id
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
        await self.batcher.add(key, text)

    # ---- handlers ----
    def _register_handlers(self) -> None:
        dp = self.dp

        @dp.message(F.text.startswith("/start"))
        async def cmd_start(message: Message) -> None:
            if not self._is_allowed(message):
                return
            if self.dossier.bootstrap_pending():
                boot = self.dossier.files.get("BOOTSTRAP.md", "")
                await message.answer(
                    "Chào bạn, đây là lần chạy đầu tiên. Mình hỏi nhanh vài "
                    "câu để dựng hồ sơ rồi làm việc luôn nhé.\n\n" + boot[:3000]
                )
            else:
                identity = self.dossier.files.get("IDENTITY.md", "")
                await message.answer(
                    "Mình đang chạy. Cứ nhắn việc bằng lời thường.\n\n"
                    + identity[:1000]
                )

        @dp.message(F.text.startswith("/status"))
        async def cmd_status(message: Message) -> None:
            if not self._is_allowed(message):
                return
            summary = self.cfg.masked_summary()
            facts = await self.memory.active_facts(limit=1000)
            lines = ["**Trạng thái Mulon**"]
            for k, v in summary.items():
                lines.append(f"- {k}: `{v}`")
            lines.append(f"- fact đang hiệu lực: {len(facts)}")
            embedder = getattr(self.memory, "embedder", None)
            if getattr(self.memory, "vec_ready", False):
                recall_mode = f"hybrid (vector 70% + BM25 30%, {embedder.name})"
            else:
                recall_mode = "BM25-only (chưa có embedder)"
            lines.append(f"- recall: {recall_mode}")
            await message.answer("\n".join(lines), parse_mode="Markdown")

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
            lines = ["**Fact đang hiệu lực:**"]
            if not facts:
                lines.append("(chưa có)")
            for f in facts:
                prefix = f"[{f['subject']}] " if f["subject"] else ""
                lines.append(f"- #{f['id']} {prefix}{f['fact']}")
            mem_md = self.dossier.files.get("MEMORY.md", "").strip()
            if mem_md:
                lines.append("\n**MEMORY.md:**\n" + mem_md[:2500])
            for chunk in chunk_html("\n".join(lines)):
                await message.answer(chunk, parse_mode="HTML")

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
            await self._process_voice_message(message)

        @dp.message(F.text)
        async def on_text(message: Message) -> None:
            if not self._is_allowed(message):
                return
            if not self._should_respond(message):
                return
            key = session_key_for(message)
            self._sessions_meta[key] = message
            await self.batcher.add(key, message.text or "")

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
        await self.dp.start_polling(self.bot)
