"""Bề mặt Telegram (aiogram 3) — kênh duy nhất (thiết kế mục 16).

- Allowlist cứng theo ALLOWED_USER_ID: người khác ra lệnh không chạy.
- Gom tin liên tiếp (mục 16.1): debounce ~2.5s, cả chùm thành 1 lượt.
- Ack bằng reaction thay tin trạng thái rác; streaming bằng edit tại chỗ.
- Session key theo (chat, topic): `agent:main:telegram:<loại>:<chat>:topic:<id>`.
- Group có người khác: chỉ đáp khi được mention/reply (GROUP_MENTION_ONLY).
- Lệnh lõi: /start /status /new /memory. Phase 6 thêm bề mặt group
  (mục 16): /setup_topics /topics, Feed (/feedbrief /feed_now +
  reaction -> taste), Ideas (/ideas /idea_do /idea_bo + reply
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
from contextlib import nullcontext
import json
import logging
import re
from pathlib import Path
from typing import Awaitable, Callable, Optional

from aiogram import Bot, Dispatcher, F
from aiogram.enums import ChatType
from aiogram.types import FSInputFile, Message, ReactionTypeEmoji
from aiogram.utils.chat_action import ChatActionSender

from . import surfaces as surf
from .ideas import format_idea_card, parse_do_reply

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
                 voice=None, policy=None, surfaces=None):
        self.cfg = cfg
        self.agent = agent
        self.memory = memory
        self.dossier = dossier
        self.consolidator = consolidator
        # VoiceService (mulon.voice) — None thì tính năng voice tắt
        # sạch: tin thoại được báo chưa sẵn sàng, /voiceon vô hiệu.
        self.voice = voice
        # Phase 6: PolicyEngine (cho /quyen) + bó dịch vụ bề mặt
        # {topics, feed, ideas, library, vault_server}. Thiếu dịch vụ
        # nào thì lệnh của bề mặt đó báo "chưa nối" sạch, không sập.
        self.policy = policy
        self.surfaces = surfaces or {}
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

            chat = getattr(anchor, "chat", None)
            chat_id = getattr(chat, "id", None)
            thread_id = getattr(anchor, "message_thread_id", None)
            typing_ctx = (
                ChatActionSender.typing(
                    bot=self.bot,
                    chat_id=chat_id,
                    message_thread_id=thread_id,
                )
                if self.bot is not None and chat_id is not None
                else nullcontext()
            )

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
            async with typing_ctx:
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
            thread_id = getattr(message, "message_thread_id", None)
            await self.bot.send_chat_action(
                chat_id=message.chat.id,
                action="typing",
                message_thread_id=thread_id,
            )
        except Exception:
            pass
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
        replied = message.reply_to_message
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
            lines = ["**Fact đang hiệu lực (kèm nguồn — hỏi 'sao mày "
                     "biết' là truy được tới đây):**"]
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
                lines.append("\n**MEMORY.md:**\n" + mem_md[:2500])
            for chunk in chunk_html("\n".join(lines)):
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
            for chunk in chunk_html(text):
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
                    "**Brief Feed hiện tại:**\n" + feed.read_brief()
                    + "\n\nSửa bằng: /feedbrief <nội dung mới>")
                return
            feed.set_brief(brief)
            await message.answer(
                "Đã cập nhật brief Feed. Bài sau (/feed_now) sẽ "
                "viết theo brief mới.")

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
            await library.scan()
            items = await library.list_items(status="active")
            from .library import format_library_list

            await _answer_chunks(message, format_library_list(items))

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
            else:  # share_item
                result = await library.share_item(item_id)
                text = (f"Item #{item_id}: chia sẻ ở trạng thái "
                        f"'chờ host', hết hạn {result['share_expires_at']}. "
                        + result["note"]
                        if result.get("ok")
                        else result.get("error", "Lỗi."))
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
            note = (f"Form nhập bí mật '{label}': {link}\n"
                    "Link dùng đúng 1 lần, hết hạn sau "
                    f"{self.cfg.vault_token_ttl_s // 60} phút. "
                    "Giá trị không đi qua chat — nhập xong form sẽ "
                    "cho một ref dạng vault:<uuid>.")
            if message.chat.type == ChatType.PRIVATE:
                await message.answer(note)
            elif self.bot is not None:
                # Trong group: link là capability — chỉ gửi DM.
                await self.bot.send_message(
                    self.cfg.allowed_user_id, note)
                await message.answer(
                    "Đã gửi link form vault vào DM của bạn "
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
            # Hiện chỉ nhận file để import ký ức (mục 16.11); file
            # khác được báo rõ thay vì nuốt im lặng.
            doc = message.document
            name = (doc.file_name or "").lower()
            if not (name.endswith(".md") or name.endswith(".json")
                    or name.endswith(".txt")):
                await message.answer(
                    "Hiện mình chỉ nhận file .md/.json/.txt để "
                    "import ký ức. File này chưa được xử lý.")
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
            await message.answer(surf.format_approvals(rows))

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
            if message.reply_to_message is not None and \
                    await self._try_reply_actions(message):
                return
            if not self._should_respond(message):
                return
            key = session_key_for(message)
            self._sessions_meta[key] = message
            try:
                thread_id = getattr(message, "message_thread_id", None)
                if message.bot:
                    await message.bot.send_chat_action(
                        chat_id=message.chat.id,
                        action="typing",
                        message_thread_id=thread_id,
                    )
            except Exception:
                pass
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
