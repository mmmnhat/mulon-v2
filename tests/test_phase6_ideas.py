"""Phase 6 — Ideas (mục 16.5): sinh thẻ từ goals/ký ức, hết hạn
14 ngày, 'làm luôn' -> goal + task, bỏ qua -> dismissed."""

import json
from datetime import datetime, timedelta, timezone

from mulon.gateway import Completion
from mulon.ideas import IdeaEngine, format_idea_card, parse_do_reply
from mulon.memory import now_iso
from tests.conftest import open_memory

IDEAS_JSON = json.dumps({"ideas": [
    {"title": "Viết bản tin tuần", "description": "Tổng hợp tiến độ goals"},
    {"title": "Dọn kho file cũ", "description": "Rà soát workspace"},
    {"title": "Thử lịch nhắc mới", "description": ""},
]}, ensure_ascii=False)


class IdeaGateway:
    def __init__(self, text=IDEAS_JSON):
        self._text = text

    async def complete(self, messages, model=None, tools=None, **kw):
        assert kw.get("purpose") == "ideas"
        return Completion(text=self._text)


async def test_generate_creates_cards_with_14d_expiry(cfg):
    memory = await open_memory(cfg)
    await memory.create_goal("Goal nền", "để có tư liệu")
    engine = IdeaEngine(cfg, memory, IdeaGateway())
    cards = await engine.generate()
    assert len(cards) == 3
    for card in cards:
        assert card["status"] == "open"
        created = datetime.fromisoformat(card["created_at"])
        expires = datetime.fromisoformat(card["expires_at"])
        delta = expires - created
        assert timedelta(days=13, hours=23) < delta < timedelta(days=14,
                                                                hours=1)
    open_cards = await memory.list_idea_cards(status="open")
    assert len(open_cards) == 3
    await memory.close()


async def test_generate_garbage_output_no_cards_no_crash(cfg):
    memory = await open_memory(cfg)
    engine = IdeaEngine(cfg, memory, IdeaGateway(text="không phải json"))
    assert await engine.generate() == []
    await memory.close()


async def test_expired_card_vanishes_and_do_explains(cfg):
    memory = await open_memory(cfg)
    past = (datetime.now(timezone.utc)
            - timedelta(days=1)).isoformat(timespec="seconds")
    card = await memory.add_idea_card("Thẻ cũ", "đã quá hạn",
                                      expires_at=past)
    engine = IdeaEngine(cfg, memory, IdeaGateway())
    expired = await engine.cleanup_expired()
    assert [c["id"] for c in expired] == [card["id"]]
    fresh = await memory.get_idea_card(card["id"])
    assert fresh["status"] == "expired"
    result = await engine.do_card(card["id"])
    assert result["ok"] is False
    assert "hết hạn" in result["error"]
    await memory.close()


async def test_do_card_creates_goal_and_task(cfg):
    memory = await open_memory(cfg)
    card = await memory.add_idea_card(
        "Làm bản tin", "tổng hợp tuần", expires_at=now_iso())
    engine = IdeaEngine(cfg, memory, IdeaGateway())
    result = await engine.do_card(card["id"], session_key="sk-1")
    assert result["ok"] is True
    goal = await memory.get_goal(result["goal_id"])
    assert goal["title"] == "Làm bản tin"
    assert goal["status"] == "active"
    task = await memory.get_task(result["task_id"])
    assert task is not None and task["title"] == "Làm bản tin"
    done = await memory.get_idea_card(card["id"])
    assert done["status"] == "done" and done["goal_id"] == goal["id"]
    # Làm lại lần nữa -> từ chối vì không còn open.
    again = await engine.do_card(card["id"])
    assert again["ok"] is False
    await memory.close()


async def test_dismiss_card(cfg):
    memory = await open_memory(cfg)
    card = await memory.add_idea_card("Thẻ bỏ", "", expires_at=now_iso())
    engine = IdeaEngine(cfg, memory, IdeaGateway())
    result = await engine.dismiss(card["id"])
    assert result["ok"] is True
    assert (await memory.get_idea_card(card["id"]))["status"] == "dismissed"
    assert (await engine.dismiss(999999))["ok"] is False
    await memory.close()


def test_format_and_parse_do_reply():
    card = {"id": 7, "title": "Ý tưởng A", "description": "mô tả",
            "expires_at": "2026-11-06T10:00:00+00:00"}
    text = format_idea_card(card)
    assert text.startswith("💡 Thẻ ý tưởng #7")
    assert parse_do_reply("làm luôn", text) == 7
    assert parse_do_reply("LÀM LUÔN nhé", text) == 7
    assert parse_do_reply("hay đấy", text) is None
    assert parse_do_reply("làm luôn", "không có id ở đây") is None
