"""Phase 6 — quản lý topic (mục 16.0): topic = tab trong group
forum. Test bằng Bot API giả (duck-type), không gọi Telegram thật:
chưa bật forum -> báo rõ; bot thiếu admin -> báo rõ; đủ điều kiện
-> tạo topic còn thiếu, lưu map vào kv_state, ghim mục lục."""

from types import SimpleNamespace

import pytest

from mulon.surfaces import SURFACES, TopicManager
from tests.conftest import open_memory


class FakeBot:
    """Duck-type của aiogram Bot cho các method bề mặt topic."""

    def __init__(self, member_status="administrator"):
        self.id = 999
        self.member_status = member_status
        self.created = []       # [(chat_id, name)]
        self.sent = []          # [(chat_id, text, thread_id)]
        self.pinned = []        # [(chat_id, message_id)]
        self._next_thread = 100
        self._next_msg = 5000

    async def get_chat_member(self, chat_id, user_id):
        return SimpleNamespace(status=self.member_status)

    async def create_forum_topic(self, chat_id, name=None):
        self._next_thread += 1
        self.created.append((chat_id, name))
        return SimpleNamespace(message_thread_id=self._next_thread)

    async def send_message(self, chat_id, text, message_thread_id=None):
        self._next_msg += 1
        self.sent.append((chat_id, text, message_thread_id))
        return SimpleNamespace(message_id=self._next_msg)

    async def pin_chat_message(self, chat_id, message_id):
        self.pinned.append((chat_id, message_id))
        return True


async def test_setup_requires_forum(cfg):
    memory = await open_memory(cfg)
    bot = FakeBot()
    result = await TopicManager().setup(bot, memory, -1001,
                                        is_forum=False)
    assert result["ok"] is False
    assert any("Topics" in e for e in result["errors"])
    assert bot.created == []
    await memory.close()


async def test_setup_requires_admin(cfg):
    memory = await open_memory(cfg)
    bot = FakeBot(member_status="member")
    result = await TopicManager().setup(bot, memory, -1001,
                                        is_forum=True)
    assert result["ok"] is False
    assert any("admin" in e for e in result["errors"])
    assert bot.created == []
    await memory.close()


async def test_setup_creates_topics_pins_index_and_persists(cfg):
    memory = await open_memory(cfg)
    bot = FakeBot()
    tm = TopicManager()
    result = await tm.setup(bot, memory, -1001, is_forum=True)
    assert result["ok"] is True
    # main = General (thread 1, không tạo bằng API); còn lại tạo hết.
    assert result["map"]["main"] == 1
    created_titles = {name for _, name in bot.created}
    assert created_titles == {s["title"] for s in SURFACES
                              if s["key"] != "main"}
    # Mục lục được gửi vào đúng thread và ghim.
    assert len(bot.pinned) == len(result["created"])
    feed_texts = [t for _, t, tid in bot.sent
                  if tid == result["map"]["feed"]]
    assert feed_texts and "Feed" in feed_texts[0]
    # Map bền trong kv_state: manager mới vẫn đọc được.
    mapping = await TopicManager().get_map(memory, -1001)
    assert mapping == result["map"]
    assert tm.topic_for(mapping, "library") == mapping["library"]
    await memory.close()


async def test_setup_second_run_creates_nothing(cfg):
    memory = await open_memory(cfg)
    bot = FakeBot()
    tm = TopicManager()
    first = await tm.setup(bot, memory, -1001, is_forum=True)
    n_created = len(bot.created)
    second = await tm.setup(bot, memory, -1001, is_forum=True)
    assert len(bot.created) == n_created  # không tạo trùng
    assert second["created"] == {}
    assert second["map"] == first["map"]
    await memory.close()


async def test_setup_partial_failure_keeps_successes(cfg):
    memory = await open_memory(cfg)

    class FlakyBot(FakeBot):
        async def create_forum_topic(self, chat_id, name=None):
            if name == "Ideas":
                raise RuntimeError("not enough rights")
            return await super().create_forum_topic(chat_id, name=name)

    bot = FlakyBot()
    result = await TopicManager().setup(bot, memory, -1001,
                                        is_forum=True)
    assert "ideas" not in result["map"]
    assert "feed" in result["map"]
    assert any("Ideas" in e for e in result["errors"])
    await memory.close()


async def test_feed_signals_and_forward_discuss(cfg):
    memory = await open_memory(cfg)
    chat_id = -1001
    post_msg_id = 42

    # Thử ghi feed signal like và discuss
    sig_like = await memory.add_feed_signal(chat_id, post_msg_id, "❤️")
    assert sig_like > 0
    sig_disc = await memory.add_feed_signal(chat_id, post_msg_id, "💬")
    assert sig_disc > 0

    counts = await memory.feed_signal_counts()
    rx_map = {c["reaction"]: c["n"] for c in counts}
    assert rx_map.get("❤️") == 1
    assert rx_map.get("💬") == 1
    await memory.close()

