"""Phase 7 — chat phụ bằng topic tự do trong group forum.

Mỗi topic phụ có session/lịch sử riêng theo thread, nhưng registry
của nó phải tách hẳn khỏi map 6 topic-tab cố định. Test bằng Bot
API giả, không gọi Telegram thật.
"""

import re
from types import SimpleNamespace

from aiogram.enums import ChatType

from mulon import surfaces as surf
from mulon.context import Dossier
from mulon.telegram_bot import TelegramSurface
from tests.conftest import open_memory

CHAT_ID = -100123


class FakeBot:
    def __init__(self, member_status="administrator",
                 fail_create=False, fail_opening=False):
        self.id = 999
        self.member_status = member_status
        self.fail_create = fail_create
        self.fail_opening = fail_opening
        self.created = []       # [(chat_id, name)]
        self.sent = []          # [(chat_id, text, thread_id)]
        self.closed = []        # [(chat_id, thread_id)]
        self.reopened = []      # [(chat_id, thread_id)]
        self._next_thread = 200
        self._next_msg = 7000

    async def get_chat_member(self, chat_id, user_id):
        return SimpleNamespace(status=self.member_status)

    async def create_forum_topic(self, chat_id, name=None):
        if self.fail_create:
            raise RuntimeError("telegram create failed")
        self._next_thread += 1
        self.created.append((chat_id, name))
        return SimpleNamespace(message_thread_id=self._next_thread)

    async def send_message(self, chat_id, text, message_thread_id=None):
        if self.fail_opening:
            raise RuntimeError("telegram send failed")
        self._next_msg += 1
        self.sent.append((chat_id, text, message_thread_id))
        return SimpleNamespace(message_id=self._next_msg)

    async def close_forum_topic(self, chat_id, message_thread_id=None):
        self.closed.append((chat_id, message_thread_id))
        return True

    async def reopen_forum_topic(self, chat_id, message_thread_id=None):
        self.reopened.append((chat_id, message_thread_id))
        return True


def _fake_message(text, *, chat_type=ChatType.SUPERGROUP,
                  is_forum=True, thread_id=None, chat_id=CHAT_ID):
    chat = SimpleNamespace(id=chat_id, type=chat_type,
                           is_forum=is_forum)
    msg = SimpleNamespace(
        chat=chat,
        text=text,
        from_user=SimpleNamespace(id=42),
        is_topic_message=thread_id is not None,
        message_thread_id=thread_id,
        reply_to_message=None,
        answers=[],
    )

    async def answer(t, **kw):
        msg.answers.append(t)

    msg.answer = answer
    return msg


async def _surface(cfg, memory, bot):
    surface = TelegramSurface(
        cfg, agent=None, memory=memory,
        dossier=Dossier.load(cfg.dossier_dir),
        surfaces={"topics": surf.TopicManager()})
    surface.bot = bot
    return surface


async def test_create_sidechat_success_and_registry_is_separate(cfg):
    memory = await open_memory(cfg)
    bot = FakeBot()
    surface = await _surface(cfg, memory, bot)

    text = await surface._chatphu_create_text(
        _fake_message("/chatphu  Kế hoạch\n  tuần này  "))

    records = await surface.sidechats.list_all(memory, CHAT_ID)
    assert len(records) == 1
    record = records[0]
    assert record["title"] == "Kế hoạch tuần này"
    assert record["status"] == "open"
    assert record["created_at"]
    assert bot.created == [(CHAT_ID, "Kế hoạch tuần này")]
    assert len(bot.sent) == 1
    sent_chat, opening, sent_thread = bot.sent[0]
    assert sent_chat == CHAT_ID
    assert sent_thread == record["thread_id"]
    assert "đoạn chat phụ" in opening
    assert "lịch sử hội thoại" in opening
    assert "ký ức dài hạn" in opening
    assert "/dongchat" in opening
    assert "Kế hoạch tuần này" in text
    assert str(record["thread_id"]) in text
    # Registry chat phụ không được ghi vào map topic cố định.
    assert await surf.TopicManager().get_map(memory, CHAT_ID) == {}
    await memory.close()


async def test_create_sidechat_default_and_truncated_title(cfg):
    memory = await open_memory(cfg)
    bot = FakeBot()
    surface = await _surface(cfg, memory, bot)

    await surface._chatphu_create_text(_fake_message("/chatphu"))
    await surface._chatphu_create_text(
        _fake_message("/chatphu " + "a" * 200))

    titles = [name for _, name in bot.created]
    assert re.fullmatch(r"Chat phụ \d{2}:\d{2} \d{2}/\d{2}", titles[0])
    assert len(titles[1]) == surf.SIDECHAT_MAX_TITLE_CHARS
    await memory.close()


async def test_create_sidechat_rejected_in_dm_and_non_forum(cfg):
    memory = await open_memory(cfg)
    bot = FakeBot()
    surface = await _surface(cfg, memory, bot)

    dm_text = await surface._chatphu_create_text(_fake_message(
        "/chatphu Riêng", chat_type=ChatType.PRIVATE,
        is_forum=False, chat_id=42))
    assert "không tạo được trong DM" in dm_text

    group_text = await surface._chatphu_create_text(_fake_message(
        "/chatphu Nhóm thường", is_forum=False))
    assert "chưa bật Topics" in group_text
    assert bot.created == []
    assert await surface.sidechats.list_all(memory, CHAT_ID) == []
    await memory.close()


async def test_create_sidechat_rejected_without_admin(cfg):
    memory = await open_memory(cfg)
    bot = FakeBot(member_status="member")
    surface = await _surface(cfg, memory, bot)

    text = await surface._chatphu_create_text(
        _fake_message("/chatphu Không quyền"))

    assert "chưa có quyền admin" in text
    assert bot.created == []
    assert await surface.sidechats.list_all(memory, CHAT_ID) == []
    await memory.close()


async def test_create_sidechat_api_error_writes_no_registry(cfg):
    memory = await open_memory(cfg)
    bot = FakeBot(fail_create=True)
    surface = await _surface(cfg, memory, bot)

    text = await surface._chatphu_create_text(
        _fake_message("/chatphu Lỗi API"))

    assert "Không tạo được chat phụ" in text
    assert await surface.sidechats.list_all(memory, CHAT_ID) == []
    await memory.close()


async def test_create_sidechat_opening_error_rolls_back_topic(cfg):
    memory = await open_memory(cfg)
    bot = FakeBot(fail_opening=True)
    surface = await _surface(cfg, memory, bot)

    text = await surface._chatphu_create_text(
        _fake_message("/chatphu Lỗi tin mở đầu"))

    assert "không gửi được tin mở đầu" in text
    assert len(bot.created) == 1
    assert len(bot.closed) == 1  # topic mồ côi được đóng lại
    assert await surface.sidechats.list_all(memory, CHAT_ID) == []
    await memory.close()


async def test_sidechat_list_empty_then_open_items(cfg):
    memory = await open_memory(cfg)
    bot = FakeBot()
    surface = await _surface(cfg, memory, bot)
    msg = _fake_message("/chatphu_list")

    empty = await surface._chatphu_list_text(msg)
    assert "Chưa có chat phụ nào" in empty

    await surface._chatphu_create_text(
        _fake_message("/chatphu Việc A"))
    text = await surface._chatphu_list_text(msg)
    record = (await surface.sidechats.list_open(memory, CHAT_ID))[0]
    assert "Việc A" in text
    assert str(record["thread_id"]) in text
    await memory.close()


async def test_dongchat_inside_sidechat_closes_it(cfg):
    memory = await open_memory(cfg)
    bot = FakeBot()
    surface = await _surface(cfg, memory, bot)
    await surface._chatphu_create_text(
        _fake_message("/chatphu Đang làm"))
    record = (await surface.sidechats.list_all(memory, CHAT_ID))[0]

    text = await surface._dongchat_text(_fake_message(
        "/dongchat", thread_id=record["thread_id"]))

    assert "Đã đóng chat phụ" in text
    assert bot.closed == [(CHAT_ID, record["thread_id"])]
    closed = await surface.sidechats.get(
        memory, CHAT_ID, record["thread_id"])
    assert closed["status"] == "closed"
    assert await surface.sidechats.list_open(memory, CHAT_ID) == []
    await memory.close()


async def test_dongchat_rejects_general_and_fixed_topics(cfg):
    memory = await open_memory(cfg)
    bot = FakeBot()
    surface = await _surface(cfg, memory, bot)
    topics = surf.TopicManager()
    setup = await topics.setup(bot, memory, CHAT_ID, is_forum=True)
    assert setup["ok"] is True

    general = await surface._dongchat_text(
        _fake_message("/dongchat", thread_id=1))
    assert "Chat chính (General)" in general

    fixed = await surface._dongchat_text(_fake_message(
        "/dongchat", thread_id=setup["map"]["feed"]))
    assert "topic cố định" in fixed
    assert bot.closed == []
    await memory.close()


async def test_sidechat_remote_close_and_reopen_by_id(cfg):
    memory = await open_memory(cfg)
    bot = FakeBot()
    surface = await _surface(cfg, memory, bot)
    await surface._chatphu_create_text(
        _fake_message("/chatphu Điều khiển xa"))
    record = (await surface.sidechats.list_all(memory, CHAT_ID))[0]
    tid = record["thread_id"]

    close_text = await surface._chatphu_status_text(
        _fake_message(f"/chatphu_dong {tid}"), reopen=False)
    assert "Đã đóng chat phụ" in close_text
    assert bot.closed == [(CHAT_ID, tid)]
    assert (await surface.sidechats.get(memory, CHAT_ID, tid))[
        "status"] == "closed"

    reopen_text = await surface._chatphu_status_text(
        _fake_message(f"/chatphu_mo {tid}"), reopen=True)
    assert "Đã mở lại chat phụ" in reopen_text
    assert bot.reopened == [(CHAT_ID, tid)]
    assert (await surface.sidechats.get(memory, CHAT_ID, tid))[
        "status"] == "open"
    await memory.close()


async def test_sidechat_remote_unknown_id_is_reported(cfg):
    memory = await open_memory(cfg)
    bot = FakeBot()
    surface = await _surface(cfg, memory, bot)

    close_text = await surface._chatphu_status_text(
        _fake_message("/chatphu_dong 9999"), reopen=False)
    reopen_text = await surface._chatphu_status_text(
        _fake_message("/chatphu_mo 9999"), reopen=True)

    assert "Không thấy chat phụ" in close_text
    assert "Không thấy chat phụ" in reopen_text
    assert bot.closed == []
    assert bot.reopened == []
    await memory.close()
