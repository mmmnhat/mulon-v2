"""1.3.0 Gói D: đối soát "hai Chat chính" — map cũ (1.0/1.1)
ghi main -> topic tự tạo thì hợp nhất về General (thread 1),
đóng topic cũ sau 1 tin chỉ đường; bằng chứng mâu thuẫn thì
chỉ ghi nhận, không đóng; không đường nào tạo topic tên
"Chat chính" nữa."""

import json

from mulon.surfaces import SideChatRegistry, TopicManager
from tests.conftest import open_memory
from tests.test_phase6_topics import FakeBot

CHAT = -1001


class ClosableBot(FakeBot):
    def __init__(self, *a, **kw):
        super().__init__(*a, **kw)
        self.closed = []        # [(chat_id, thread_id)]

    async def close_forum_topic(self, chat_id, message_thread_id=None):
        self.closed.append((chat_id, message_thread_id))
        return True

    async def reopen_forum_topic(self, chat_id,
                                 message_thread_id=None):
        return True


async def _seed_map(memory, mapping):
    await memory.kv_set(f"topics:{CHAT}", json.dumps(mapping))


async def _seed_sidechats(memory, records):
    await memory.kv_set(
        f"sidechats:{CHAT}", json.dumps(records, ensure_ascii=False))


async def test_reconcile_merges_legacy_main_and_closes_topic(cfg):
    memory = await open_memory(cfg)
    await _seed_map(memory, {"main": 137, "feed": 138})
    bot = ClosableBot()
    tm = TopicManager()
    result = await tm.setup(bot, memory, CHAT, is_forum=True)
    recon = result["reconcile"]
    assert recon["action"] == "merged"
    assert recon["legacy_thread_id"] == 137
    # Map: main duy nhất là General; feed giữ nguyên.
    assert result["map"]["main"] == 1
    assert result["map"]["feed"] == 138
    mapping = await tm.get_map(memory, CHAT)
    assert mapping["main"] == 1
    # Đúng 1 tin chỉ đường vào topic cũ, nói rõ chuyển về General.
    redirects = [t for _, t, tid in bot.sent if tid == 137]
    assert len(redirects) == 1
    assert "General" in redirects[0]
    # Topic cũ bị ĐÓNG (không xoá), đúng 1 lần.
    assert bot.closed == [(CHAT, 137)]
    # Record legacy/superseded đã ghi.
    records = await tm._legacy_records(memory, CHAT)
    assert len(records) == 1
    rec = records[0]
    assert rec["thread_id"] == 137 and rec["superseded_by"] == 1
    assert rec["notified"] is True and rec["closed"] is True
    # Chạy lại: không gửi lại, không đóng lại, không đổi nữa.
    bot2 = ClosableBot()
    result2 = await tm.setup(bot2, memory, CHAT, is_forum=True)
    assert result2["reconcile"]["action"] == "none"
    assert bot2.closed == []
    assert [1 for _, _, tid in bot2.sent if tid == 137] == []
    await memory.close()


async def test_reconcile_uncertain_when_registry_conflicts(cfg):
    memory = await open_memory(cfg)
    await _seed_map(memory, {"main": 137})
    await _seed_sidechats(memory, [{
        "thread_id": 137, "title": "Việc riêng", "status": "open",
        "created_at": "2026-10-20T00:00:00+00:00"}])
    bot = ClosableBot()
    tm = TopicManager()
    recon = await tm.reconcile_main_topic(bot, memory, CHAT)
    assert recon["action"] == "uncertain"
    assert recon["notes"]
    # Không đóng, không gửi chỉ đường, không đổi map.
    assert bot.closed == []
    assert [1 for _, _, tid in bot.sent if tid == 137] == []
    mapping = await tm.get_map(memory, CHAT)
    assert mapping["main"] == 137
    await memory.close()


async def test_reconcile_uncertain_registry_title_only(cfg):
    memory = await open_memory(cfg)
    await _seed_map(memory, {"main": 1, "feed": 5})
    await _seed_sidechats(memory, [{
        "thread_id": 222, "title": "Chat chính", "status": "open",
        "created_at": "2026-10-20T00:00:00+00:00"}])
    bot = ClosableBot()
    recon = await TopicManager().reconcile_main_topic(
        bot, memory, CHAT)
    assert recon["action"] == "uncertain"
    assert bot.closed == []
    mapping = await TopicManager().get_map(memory, CHAT)
    assert mapping == {"main": 1, "feed": 5}
    await memory.close()


async def test_no_code_path_creates_chat_chinh_topic(cfg):
    memory = await open_memory(cfg)
    bot = ClosableBot()
    result = await TopicManager().setup(bot, memory, CHAT,
                                        is_forum=True)
    assert result["ok"] is True
    assert "Chat chính" not in {name for _, name in bot.created}
    # Chat phụ cũng bị chặn đặt đúng tên này.
    created_before = len(bot.created)
    res = await SideChatRegistry().create(
        bot, memory, CHAT, "Chat chính", is_forum=True)
    assert res["ok"] is False
    assert "General" in res["error"]
    assert len(bot.created) == created_before
    await memory.close()
