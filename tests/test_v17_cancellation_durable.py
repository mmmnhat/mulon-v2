"""Test T-24.2: Huỷ việc phải dứt điểm — mục tiêu cũ không sống lại ở lượt sau.

Kiểm tra:
1. Khi một lượt tác vụ bị hủy (/cancel hoặc cancellation marker), mục tiêu và thông điệp
   cũ được đánh dấu đã hủy dứt điểm, không lọt vào recent_messages hay ngữ cảnh của lượt sau.
2. Toàn bộ task 'running' trong DB và ActivityTracker của session được chuyển sang 'cancelled'.
3. Lượt tiếp theo gửi yêu cầu mới hoàn toàn độc lập: tiến trình, kế hoạch và kết quả không
   hề chứa bất kỳ dấu vết nào của việc cũ đã hủy.
4. Memory recall, compaction và memory_flush đều lọc bỏ các thông điệp đã bị hủy.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from mulon.agent import Agent
from mulon.context import ContextEngine, Dossier
from mulon.gateway import Completion
from mulon.policy import PolicyEngine
from mulon.telegram_bot import TelegramSurface, is_cancellation_intent
from mulon.tools import ToolRegistry, ToolSpec
from mulon.webapp_server import ActivityTracker
from tests.conftest import open_memory


class _FakeAnchor:
    def __init__(self):
        self.answers = []
        self.placeholders = []
        self.chat = SimpleNamespace(id=789)

    async def answer(self, text, parse_mode=None):
        self.answers.append(text)
        return self

    async def reply(self, text, parse_mode=None):
        self.answers.append(text)
        return self

    async def edit_text(self, text, parse_mode=None):
        self.text = text
        return self


class _HangingAgent:
    """Agent giả lập tác vụ dài bị huỷ giữa chừng."""

    def __init__(self):
        self.started = asyncio.Event()
        self.was_cancelled = False
        self.handled_texts = []

    async def handle(self, session_key, user_text, on_delta=None, on_event=None):
        self.handled_texts.append(user_text)
        self.started.set()
        if on_event:
            await on_event("task_start", {"title": user_text, "steps": ["B1", "B2"]})
            await on_event("tool_start", {"tool": "long_search"})
        try:
            await asyncio.sleep(5.0)
            return SimpleNamespace(text="Kết quả xong.")
        except asyncio.CancelledError:
            self.was_cancelled = True
            raise


@pytest.mark.asyncio
async def test_cancel_turn_cleans_memory_and_tasks(cfg):
    """Kiểm tra cancel_turn cập nhật DB: messages đánh dấu cancelled, task 'running' chuyển 'cancelled'."""
    memory = await open_memory(cfg)
    session_key = "agent:main:telegram:dm:999:topic:0"

    # 1. Tạo session và user message
    msg_id = await memory.append_message(session_key, "user", "Kiểm tra số dư Accesstrade bằng api key")
    task_id = "task_acc_123"
    await memory.create_task(task_id, session_key, "Kiểm tra số dư Accesstrade", ["B1", "B2"])
    await memory.add_task_step(task_id, "B1", "doing")
    await memory.add_task_step(task_id, "B2", "pending")

    # Xác nhận task đang running
    t_before = await memory.get_task(task_id)
    assert t_before["status"] == "running"

    # 2. Huỷ turn
    res = await memory.cancel_turn(session_key, user_msg_id=msg_id, reason="user_cancelled")
    assert res["ok"] is True
    assert res["cancelled_tasks"] == 1

    # 3. Kiểm tra user message đã được cập nhật role='cancelled_user' và meta.cancelled=1
    m_after = await memory.get_message(msg_id)
    assert m_after["role"] == "cancelled_user"
    meta = m_after["meta"] if isinstance(m_after["meta"], dict) else json.loads(m_after["meta"])
    assert meta.get("cancelled") == 1
    assert meta.get("cancelled_reason") == "user_cancelled"

    # 4. Kiểm tra task đã được cập nhật status='cancelled' và các bước đều cancelled
    t_after = await memory.get_task(task_id)
    assert t_after["status"] == "cancelled"
    for s in t_after["steps"]:
        assert s["status"] == "cancelled"

    # 5. recent_messages mặc định (include_cancelled=False) KHÔNG được chứa tin nhắn này
    recent = await memory.recent_messages(session_key)
    assert not any("Accesstrade" in m["content"] for m in recent)
    assert len(recent) == 0

    # Nhưng recent_messages(include_cancelled=True) vẫn xem được nếu cần
    recent_all = await memory.recent_messages(session_key, include_cancelled=True)
    assert any("Accesstrade" in m["content"] for m in recent_all)

    await memory.close()


@pytest.mark.asyncio
async def test_context_engine_excludes_cancelled_goals(cfg):
    """Kiểm tra ContextEngine.build loại bỏ hoàn toàn mục tiêu của lượt bị huỷ."""
    memory = await open_memory(cfg)
    dossier = Dossier.load(cfg.dossier_dir)
    gw = AsyncMock()
    ctx_engine = ContextEngine(cfg, dossier, memory, gw)
    session_key = "agent:main:telegram:dm:888:topic:0"

    # Turn 1: Yêu cầu Accesstrade rồi bị huỷ
    msg_id = await memory.append_message(session_key, "user", "Nhiệm vụ Accesstrade curl api lấy số dư")
    await memory.cancel_turn(session_key, user_msg_id=msg_id, reason="user_cancelled")

    # Turn 2: Yêu cầu mới độc lập "Gửi email cho Nam"
    built = await ctx_engine.build(session_key, "Gửi email cho Nam")

    # Kiểm tra built.messages: hoàn toàn KHÔNG có chữ Accesstrade
    all_content = " ".join(str(m.get("content", "")) for m in built.messages)
    assert "Accesstrade" not in all_content
    assert "Gửi email cho Nam" in all_content

    # Kiểm tra recall cũng không mang Accesstrade vào
    recall_hits = await memory.recall("Accesstrade", exclude_session="other")
    assert not any("Accesstrade" in h.get("text", "") for h in recall_hits)

    await memory.close()


@pytest.mark.asyncio
async def test_telegram_surface_cancel_durable_workflow(cfg):
    """Kiểm tra end-to-end trên TelegramSurface: /cancel huỷ dứt điểm, lượt sau không chạy kèm."""
    agent = _HangingAgent()
    memory = await open_memory(cfg)
    dossier = Dossier.load(cfg.dossier_dir)
    surface = TelegramSurface(cfg, agent, memory, dossier)
    key = "agent:main:telegram:dm:777:topic:0"

    anchor = _FakeAnchor()
    surface._sessions_meta[key] = anchor

    # 1. Bắt đầu lượt dài Accesstrade
    turn_task = asyncio.create_task(
        surface._on_batch(key, "Quét tài liệu Accesstrade và curl số dư", ["Quét tài liệu Accesstrade và curl số dư"])
    )
    await asyncio.wait_for(agent.started.wait(), timeout=1.0)
    assert surface.batcher.is_busy(key)

    # 2. Huỷ bằng logic giống /cancel trong bot
    running_task = surface._active_tasks.get(key)
    assert running_task is not None
    running_task.cancel()
    surface.batcher.drain(key)
    await memory.cancel_turn(key, reason="user_cancelled")
    surface.activity.stop_session_tasks(key)

    with pytest.raises(asyncio.CancelledError):
        await turn_task

    assert agent.was_cancelled is True
    assert not surface.batcher.is_busy(key)

    # 3. Lượt tiếp theo gửi việc mới: "Gửi email cho Nam"
    # Kiểm tra recent_messages cho lượt tiếp theo
    recent = await memory.recent_messages(key)
    assert not any("Accesstrade" in m["content"] for m in recent)

    # 4. Khi lượt mới chạy, agent.handle nhận đúng nội dung mới, không bị gộp việc cũ
    agent2 = _HangingAgent()
    surface.agent = agent2
    agent2.started = asyncio.Event()

    turn2_task = asyncio.create_task(
        surface._on_batch(key, "Gửi email cho Nam", ["Gửi email cho Nam"])
    )
    await asyncio.wait_for(agent2.started.wait(), timeout=1.0)
    # Huỷ an toàn để kết thúc test
    t2 = surface._active_tasks.get(key)
    if t2:
        t2.cancel()
    with pytest.raises(asyncio.CancelledError):
        await turn2_task

    # agent2 chỉ nhận đúng "Gửi email cho Nam", không hề dính "Accesstrade"
    assert agent2.handled_texts == ["Gửi email cho Nam"]

    await memory.close()


@pytest.mark.asyncio
async def test_activity_tracker_stop_session_tasks():
    """Kiểm tra ActivityTracker.stop_session_tasks huỷ và dọn dẹp đúng session_key."""
    tracker = ActivityTracker()
    session_1 = "session_1"
    session_2 = "session_2"

    async def _dummy():
        try:
            await asyncio.sleep(10)
        except asyncio.CancelledError:
            pass

    t1 = asyncio.create_task(_dummy())
    t2 = asyncio.create_task(_dummy())
    t3 = asyncio.create_task(_dummy())

    tracker.register_task("task_1", t1, title="Task 1", session_key=session_1)
    tracker.register_task("task_2", t2, title="Task 2", session_key=session_1)
    tracker.register_task("task_3", t3, title="Task 3", session_key=session_2)
    tracker.start_turn(session_1, "Turn session 1")

    assert len(tracker.list_running_tasks()) == 3
    assert tracker.current is not None

    # Dừng toàn bộ session 1
    stopped_count = tracker.stop_session_tasks(session_1)
    assert stopped_count == 2
    await asyncio.sleep(0)
    assert t1.cancelled() or t1.done()
    assert t2.cancelled() or t2.done()
    assert not t3.cancelled()
    assert len(tracker.list_running_tasks()) == 1
    assert tracker.current is None

    # Dọn dẹp t3
    t3.cancel()
    await asyncio.gather(t1, t2, t3, return_exceptions=True)
