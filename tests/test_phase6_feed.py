"""Phase 6 — Feed (mục 16.4): bài tự viết từ tư liệu NỘI BỘ theo
brief trong FEED.md; reaction -> feed_signals -> taste summary
cập nhật vào đúng mục tự động của FEED.md."""

import re
from types import SimpleNamespace

from mulon.feed import FeedEngine, taste_summary
from mulon.gateway import Completion
from tests.conftest import open_memory

POST_TEXT = "Hôm nay goal chính đang chờ một bước nhỏ: chốt bản nháp."


class FeedGateway:
    def __init__(self, text=POST_TEXT):
        self._text = text
        self.prompts = []

    async def complete(self, messages, model=None, tools=None, **kw):
        self.prompts.append(messages)
        assert kw.get("purpose") == "feed"
        return Completion(text=self._text)


class FakeBot:
    def __init__(self):
        self.sent = []
        self._next = 700

    async def send_message(self, chat_id, text, message_thread_id=None):
        self._next += 1
        self.sent.append((chat_id, text, message_thread_id))
        return SimpleNamespace(message_id=self._next)


async def _seed(memory):
    goal = await memory.create_goal("Ra mắt bản 1.0", "chốt bề mặt")
    await memory.log_goal_activity(goal["id"], "đã xong khung topic")
    await memory.create_tracked_item(
        "Gia hạn tên miền", goal_id=goal["id"], due_at="2026-10-30")
    await memory.add_fact("User thích báo cáo ngắn gọn.",
                          subject="user", source="test")
    return goal


async def test_publish_uses_internal_material_and_brief(cfg):
    memory = await open_memory(cfg)
    await _seed(memory)
    engine = FeedEngine(cfg, memory, FeedGateway())
    engine.set_brief("Viết kiểu tin nhanh buổi sáng, tối đa 3 câu.")
    bot = FakeBot()
    result = await engine.publish(bot, chat_id=-1001, thread_id=101)
    assert result["ok"] is True
    chat_id, text, thread = bot.sent[0]
    assert (chat_id, thread) == (-1001, 101)
    assert text == POST_TEXT
    # Prompt phải chứa brief + tư liệu nội bộ (goal), không nguồn ngoài.
    prompt = engine.gateway.prompts[0][1]["content"]
    assert "tin nhanh buổi sáng" in prompt
    assert "Ra mắt bản 1.0" in prompt
    assert "Gia hạn tên miền" in prompt
    # Bài được ghi để reaction map về đúng post.
    post = await memory.get_feed_post(-1001, result["message_id"])
    assert post is not None and post["content"] == POST_TEXT
    await memory.close()


async def test_brief_roundtrip_preserves_taste_section(cfg):
    memory = await open_memory(cfg)
    engine = FeedEngine(cfg, memory, FeedGateway())
    engine.set_brief("Brief số một.")
    assert engine.read_brief() == "Brief số một."
    await memory.add_feed_signal(-1, 1, "👍")
    await engine.update_taste()
    engine.set_brief("Brief số hai.")
    assert engine.read_brief() == "Brief số hai."
    assert "👍 ×1" in engine.read_taste()  # taste không bị brief đè
    await memory.close()


async def test_reaction_becomes_taste_signal(cfg):
    memory = await open_memory(cfg)
    engine = FeedEngine(cfg, memory, FeedGateway())
    bot = FakeBot()
    result = await engine.publish(bot, chat_id=-1001, thread_id=None)
    mid = result["message_id"]
    # Reaction trên tin KHÔNG phải bài Feed -> không thành taste.
    assert await engine.record_reaction(-1001, 424242, ["👍"]) is False
    assert await memory.feed_signal_counts() == []
    # Reaction trên đúng bài Feed -> ghi + cập nhật FEED.md.
    assert await engine.record_reaction(-1001, mid, ["👍", "❤️"]) is True
    counts = {c["reaction"]: c["n"]
              for c in await memory.feed_signal_counts()}
    assert counts == {"👍": 1, "❤️": 1}
    taste = engine.read_taste()
    assert "👍 ×1" in taste and "tích cực" in taste.lower()
    await memory.close()


def test_taste_summary_empty_and_negative():
    assert "Chưa có" in taste_summary([])
    neg = taste_summary([{"reaction": "👎", "n": 2}])
    assert "tiêu cực 2" in neg and "đổi" in neg


async def test_generate_empty_model_output_is_clean_error(cfg):
    memory = await open_memory(cfg)
    engine = FeedEngine(cfg, memory, FeedGateway(text="  "))
    result = await engine.publish(FakeBot(), chat_id=1)
    assert result["ok"] is False
    await memory.close()
