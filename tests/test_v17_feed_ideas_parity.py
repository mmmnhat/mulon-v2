"""Kiểm thử Parity Feed + Ideas chủ động (T-10.3 / Parity đợt 1.7.5).

Checklist: C1 + C2 + C3/C7 (MỘT PHẦN) + R11.
- Feed: Nguồn ngoài web/social/dịch vụ đã kết nối + taste học từ reaction VÀ thảo luận.
- R11: Bộ phận viết Feed không đọc transcript thô, chỉ đọc bản tóm tắt gu (taste summary).
- Ideas: Thẻ ý tưởng sinh nền từ ngữ cảnh thật (goals, cam kết, bài học, fact),
  mỗi thẻ có rationale + nguồn + chấm feasibility/fit/novelty; người dùng xử lý
  được trên thẻ (chạy thử/bỏ qua) như Muse.
"""

from __future__ import annotations

import json
from pathlib import Path
import pytest

from mulon.config import Config
from mulon.memory import Memory
from mulon.feed import FeedEngine, assess_trust, taste_summary
from mulon.ideas import IdeaEngine, format_idea_card, _parse_ideas
from mulon.connectors import ConnectorRegistry, SystemConnector
from mulon.webapp_server import WebAppServer
from tests.conftest import open_memory


class DummyGateway:
    def __init__(self, response_text: str = ""):
        self.response_text = response_text
        self.last_messages: list[dict] = []

    async def complete(self, messages, **kwargs):
        self.last_messages = list(messages)
        class _Comp:
            def __init__(self, text):
                self.text = text
        return _Comp(self.response_text)


@pytest.fixture
async def mem(cfg):
    m = await open_memory(cfg)
    yield m
    await m.close()


@pytest.mark.asyncio
async def test_feed_external_sources_web_social_and_connectors(cfg, mem):
    """C1: Nguồn ngoài bao gồm web, social domains và connector feed_snapshot."""
    # 1. Kiểm tra assess_trust nhận diện social domains từ config/feed_sources.json
    assert assess_trust("https://github.com/torvalds/linux") == "normal"
    assert assess_trust("https://x.com/openai/status/123") == "normal"
    assert assess_trust("https://threads.net/@zuck/post/456") == "normal"
    assert assess_trust("https://substack.com/post/789") == "normal"
    assert assess_trust("https://huggingface.co/models") == "normal"
    assert assess_trust("https://vnexpress.net/thoi-su") == "high"

    # 2. Connector hỗ trợ feed_snapshot
    reg = ConnectorRegistry()
    reg.register(SystemConnector())

    # Tạo goal để hot_topics có chủ đề tìm kiếm
    await mem.create_goal("Nghiên cứu AI", "Phát triển agent")

    gw = DummyGateway("Chủ đề: Công nghệ\n\nBài viết test feed.")
    engine = FeedEngine(cfg, mem, gw, connectors=reg, collect_external=True)

    # Mock searcher & fetcher hermetic
    async def fake_search(query, limit=5):
        return [{"url": "https://github.com/mulon/ai", "title": "MuLon Repo"}]

    async def fake_fetch(url):
        return {
            "ok": True,
            "url": url,
            "raw": "<html><title>MuLon Agent</title><body>Chi tiết nền tảng agent AI.</body></html>",
            "content": "Chi tiết nền tảng agent AI.",
            "content_type": "text/html",
        }

    engine._searcher = fake_search
    engine._fetcher = fake_fetch

    got = await engine.collect_external_material()
    items = got["items"]
    assert len(items) >= 1
    # Có tư liệu từ web/social hoặc connector
    kinds = {it.get("kind") for it in items}
    assert "web" in kinds or "connector" in kinds


@pytest.mark.asyncio
async def test_feed_taste_learns_from_reactions_and_discussions(cfg, mem):
    """C1: Taste học từ cả reaction (thích/ghét) VÀ thảo luận của người dùng."""
    gw = DummyGateway()
    engine = FeedEngine(cfg, mem, gw)

    post_id = await mem.add_feed_post(100, 200, "Bài viết về AI Agents", origin="auto", topic="AI Agents")
    await mem.add_feed_post_sources(post_id, [{"url": "https://example.com/ai", "source": "search:example.com", "content_hash": "h1"}])

    # 1. Ghi nhận reaction thích
    await mem.add_feed_signal(100, 200, "❤️")
    # 2. Ghi nhận thảo luận của người dùng
    await engine.record_discussion(100, 200, comment="Cần phân tích sâu hơn về multi-agent coordination.")

    summary = await engine.update_taste()
    assert "Tín hiệu taste đã ghi" in summary
    assert "thảo luận" in summary.lower()
    assert "AI Agents" in summary or "multi-agent" in summary or "phản hồi" in summary

    # Profile gu thích chủ đề được thảo luận
    profile = await engine.taste_profile()
    assert "AI Agents" in profile["liked_topics"]


@pytest.mark.asyncio
async def test_feed_r11_strict_separation_no_raw_transcripts(cfg, mem):
    """R11: Feed writer TUYỆT ĐỐI không đọc transcript thô, chỉ đọc bản tóm tắt gu (taste summary)."""
    # Ghi một số tin nhắn chat nhạy cảm vào DB
    await mem.append_message("agent:main:telegram:dm:100:topic:0", "user", "Tin nhắn riêng tư bí mật 12345")
    await mem.append_message("agent:main:telegram:dm:100:topic:0", "assistant", "Tôi đã ghi nhớ bí mật của bạn.")

    gw = DummyGateway("Chủ đề: Tổng quan\n\nNội dung bài viết chuẩn.")
    engine = FeedEngine(cfg, mem, gw)

    # Thiết lập taste summary
    engine.set_brief("Tập trung vào xu hướng AI thế hệ mới.")
    await mem.add_feed_post(100, 300, "Bài cũ", origin="auto", topic="Tech")
    await mem.add_feed_signal(100, 300, "👍")
    await engine.update_taste()

    # Thực hiện lượt sinh bài
    material = await engine.collect_material()
    await engine.compose(material, external=[], recent=[], purpose="feed")

    # Kiểm tra ngữ cảnh gửi vào gateway writer
    messages = gw.last_messages
    full_prompt_text = " ".join(m.get("content", "") for m in messages)

    # Phải có taste summary & brief
    assert "## Brief" in full_prompt_text
    assert "## Taste của user" in full_prompt_text
    # Tuyệt đối KHÔNG chứa transcript thô
    assert "Tin nhắn riêng tư bí mật 12345" not in full_prompt_text
    assert "Tôi đã ghi nhớ bí mật của bạn." not in full_prompt_text


@pytest.mark.asyncio
async def test_ideas_generation_with_rationale_source_and_scores(cfg, mem):
    """C2: Thẻ ý tưởng sinh từ ngữ cảnh thật, có đủ rationale, nguồn và chấm điểm feasibility/fit/novelty."""
    # Tạo ngữ cảnh thật trong DB
    g = await mem.create_goal("Tối ưu hóa hiệu năng hệ thống", "Giảm tải 30% bộ nhớ")
    await mem.create_tracked_item("Hoàn thành báo cáo kỹ thuật", due_at="2026-10-30T10:00:00Z")
    await mem.add_fact("User đang tập trung phát triển AI bot MuLon", subject="user")

    ideas_json = json.dumps({
        "ideas": [
            {
                "title": "Profiling bộ nhớ SQLite WAL",
                "description": "Chạy benchmark và đo kích thước cache để giảm phân mảnh WAL.",
                "rationale": "Bạn đang có mục tiêu tối ưu hóa hiệu năng và giảm tải 30% bộ nhớ.",
                "source": f"Goal #{g['id']} Tối ưu hóa hiệu năng",
                "feasibility": 4.5,
                "fit": 5.0,
                "novelty": 4.0
            }
        ]
    })
    gw = DummyGateway(ideas_json)
    engine = IdeaEngine(cfg, mem, gw)

    cards = await engine.generate()
    assert len(cards) == 1
    card = cards[0]

    assert card["title"] == "Profiling bộ nhớ SQLite WAL"
    assert "tối ưu hóa hiệu năng" in card["rationale"].lower()
    assert f"Goal #{g['id']}" in card["source"]
    assert card["feasibility"] == 4.5
    assert card["fit"] == 5.0
    assert card["novelty"] == 4.0

    # Kiểm tra format_idea_card
    formatted = format_idea_card(card)
    assert f"#{card['id']}" in formatted
    assert "Profiling bộ nhớ SQLite WAL" in formatted
    assert "Lý do:" in formatted
    assert "Nguồn:" in formatted
    assert "Khả thi: 4.5/5" in formatted
    assert "Phù hợp: 5.0/5" in formatted
    assert "Mới: 4.0/5" in formatted


@pytest.mark.asyncio
async def test_ideas_actions_do_and_dismiss(cfg, mem):
    """C2: Người dùng xử lý được trên thẻ (chạy thử / bỏ qua)."""
    gw = DummyGateway()
    engine = IdeaEngine(cfg, mem, gw)

    card = await mem.add_idea_card(
        "Viết test hồi quy cho Feed",
        description="Bổ sung kiểm thử tự động cho feed_snapshot.",
        source="Goal #1",
        rationale="Cần đảm bảo tính ổn định của hệ thống",
        feasibility=4.8,
        fit=5.0,
        novelty=3.5,
    )
    card_id = card["id"]

    # 1. Thao tác 'Làm luôn' (do_card)
    res = await engine.do_card(card_id, session_key="test_session")
    assert res["ok"] is True
    assert "goal_id" in res
    assert "task_id" in res

    # Thẻ chuyển trạng thái sang done
    updated = await mem.get_idea_card(card_id)
    assert updated["status"] == "done"
    assert updated["goal_id"] == res["goal_id"]

    # Task và Goal thật được tạo
    goal = await mem.get_goal(res["goal_id"])
    assert goal["title"] == "Viết test hồi quy cho Feed"
    task = await mem.get_task(res["task_id"])
    assert task["title"] == "Viết test hồi quy cho Feed"

    # 2. Thao tác 'Bỏ qua' (dismiss)
    card2 = await mem.add_idea_card("Ý tưởng thử nghiệm", "Sẽ bị bỏ qua")
    dis_res = await engine.dismiss(card2["id"])
    assert dis_res["ok"] is True
    card2_db = await mem.get_idea_card(card2["id"])
    assert card2_db["status"] == "dismissed"


@pytest.mark.asyncio
async def test_ideas_webapp_api_endpoints(cfg, mem):
    """API Mini App cho Ideas: /api/ideas, /api/ideas/generate, /api/ideas/do, /api/ideas/dismiss."""
    gw = DummyGateway(json.dumps({
        "ideas": [{
            "title": "Tự động hóa báo cáo tuần",
            "description": "Gửi briefing qua Telegram mỗi thứ Sáu",
            "rationale": "Tiết kiệm 2 giờ làm việc thủ công",
            "source": "Fact: thói quen làm việc",
            "feasibility": 4.2,
            "fit": 4.8,
            "novelty": 4.0
        }]
    }))
    ideas_engine = IdeaEngine(cfg, mem, gw)

    class DummyPolicy:
        def can_use_sync(self, *a, **k): return True
        def state(self): return {}

    class DummyBroker:
        def pending(self): return []

    server = WebAppServer(
        cfg, memory=mem, policy=DummyPolicy(), broker=DummyBroker(),
        connectors=ConnectorRegistry(), mcp_manager=None,
        vault_store=None, registry=None, ideas=ideas_engine
    )

    # 1. Generate via API
    gen_req = None
    gen_res = await server._handle_ideas_generate(gen_req)
    assert gen_res.status == 200
    gen_data = json.loads(gen_res.text)
    assert gen_data["ok"] is True
    assert len(gen_data["ideas"]) == 1
    card_id = gen_data["ideas"][0]["id"]

    # 2. List via API
    class DummyReq:
        query = {"status": "open"}
    list_res = await server._handle_ideas_list(DummyReq())
    assert list_res.status == 200
    list_data = json.loads(list_res.text)
    assert len(list_data["ideas"]) == 1

    # 3. Do card via API
    class DummyDoReq:
        async def json(self): return {"card_id": card_id}
    do_res = await server._handle_ideas_do(DummyDoReq())
    assert do_res.status == 200
    do_data = json.loads(do_res.text)
    assert do_data["ok"] is True
    assert "goal_id" in do_data
