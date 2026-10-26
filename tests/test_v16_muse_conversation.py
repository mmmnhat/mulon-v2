"""Test T-09: Cơ chế hội thoại ngang Muse.

Bao gồm:
1. Gộp tin & phát hiện huỷ / chuyển hướng khi người dùng đổi ý (cancellation / redirect).
2. Trả lời trong lúc đang làm: phản hồi tiến trình trực quan trên placeholder Telegram.
3. Sub-agents: ghi nhận task hiển thị ở tab Việc, công cụ chạy song song spawn_subagents_parallel.
4. Cách reply: tự nhận thức nạp chỉ dẫn phong cách hội thoại Muse từ prompt.
"""

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from mulon.context import ContextEngine, Dossier
from mulon.gateway import Completion, ToolCall
from mulon.policy import PolicyEngine
from mulon.subagents import SubagentRunner, register_subagent_tool
from mulon.telegram_bot import (
    MessageBatcher, TelegramSurface, is_cancellation_intent,
)
from mulon.tools import ToolRegistry, build_default_registry
from tests.conftest import open_memory


class _FakeAnchor:
    def __init__(self):
        self.answers = []
        self.placeholders = []
        self.chat = SimpleNamespace(id=123)

    async def react(self, reactions):
        pass

    async def answer(self, text, **kw):
        self.answers.append(text)
        ph = SimpleNamespace(text=text, edits=[])

        async def edit_text(t, **kw2):
            ph.text = t
            ph.edits.append(t)

        ph.edit_text = edit_text
        self.placeholders.append(ph)
        return ph


class _LongRunningAgent:
    """Agent giả lập tác vụ dài, phát đầy đủ sự kiện tiến trình hoặc có thể bị hủy."""

    def __init__(self, delay_s: float = 0.5):
        self.delay_s = delay_s
        self.started = asyncio.Event()
        self.was_cancelled = False

    async def handle(self, session_key, user_text, on_delta=None, on_event=None):
        self.started.set()
        if on_event:
            await on_event("task_start", {"title": "Tra cứu thông tin", "steps": ["B1", "B2"]})
            await on_event("tool_start", {"tool": "web_search"})
        try:
            await asyncio.sleep(self.delay_s)
            if on_event:
                await on_event("tool_done", {"tool": "web_search", "step_title": "Đã tìm kiếm 5 trang web"})
                await on_event("verify", {})
            return SimpleNamespace(text="Kết quả hoàn chỉnh.")
        except asyncio.CancelledError:
            self.was_cancelled = True
            raise


def test_is_cancellation_intent_detection():
    # 1. Các từ dừng rõ ràng
    assert is_cancellation_intent("thôi")[0] is True
    assert is_cancellation_intent("dừng lại")[0] is True
    assert is_cancellation_intent("/cancel")[0] is True
    assert is_cancellation_intent("/stop")[0] is True
    assert is_cancellation_intent("hủy đi ní")[0] is True
    assert is_cancellation_intent("bỏ qua đi")[0] is True
    assert is_cancellation_intent("đổi ý rồi")[0] is True

    # 2. Chuyển hướng yêu cầu
    is_c, rest = is_cancellation_intent("thôi đừng tìm cái đó nữa, tính 2 + 2 đi")
    assert is_c is True
    assert "tính 2 + 2 đi" in rest

    is_c2, rest2 = is_cancellation_intent("thay vì vậy làm bài thơ đi")
    assert is_c2 is True
    assert "làm bài thơ đi" in rest2

    # 3. Tin nhắn bình thường không bị nhận nhầm
    assert is_cancellation_intent("xin chào ní")[0] is False
    assert is_cancellation_intent("tìm thông tin về Python")[0] is False
    assert is_cancellation_intent("đọc file report.txt")[0] is False


async def test_active_turn_cancellation(cfg):
    """Khi bot đang bận, tin nhắn dừng sẽ ngắt ngay lượt đang chạy."""
    agent = _LongRunningAgent(delay_s=2.0)
    memory = await open_memory(cfg)
    dossier = Dossier.load(cfg.dossier_dir)
    surface = TelegramSurface(cfg, agent, memory, dossier)
    key = "agent:main:telegram:dm:42:topic:0"

    anchor = _FakeAnchor()
    surface._sessions_meta[key] = anchor

    # Bắt đầu lượt dài trong background task
    turn_task = asyncio.create_task(surface._on_batch(key, "Tìm kiếm tài liệu phức tạp", ["Tìm kiếm tài liệu phức tạp"]))
    await asyncio.wait_for(agent.started.wait(), timeout=1.0)
    assert surface.batcher.is_busy(key)

    # Người dùng gửi tin nhắn dừng
    running_task = surface._active_tasks.get(key)
    assert running_task is not None

    # Giả lập logic trong on_text khi nhận tin dừng
    is_cancel, _ = is_cancellation_intent("thôi dừng lại đi")
    assert is_cancel is True
    running_task.cancel()
    surface.batcher.drain(key)

    # Chờ lượt kết thúc sau khi bị cancel
    with pytest.raises(asyncio.CancelledError):
        await turn_task

    assert agent.was_cancelled is True
    assert not surface.batcher.is_busy(key)
    # Placeholder phản hồi xác nhận đã dừng
    assert len(anchor.placeholders) > 0
    assert "Đã dừng tác vụ" in anchor.placeholders[0].text

    await memory.close()


async def test_progress_reporting_on_placeholder(cfg):
    """Tiến trình hiển thị trực quan các bước đã xong (✓) và đang chạy (⏳) trên placeholder."""
    agent = _LongRunningAgent(delay_s=0.05)
    memory = await open_memory(cfg)
    dossier = Dossier.load(cfg.dossier_dir)
    surface = TelegramSurface(cfg, agent, memory, dossier)
    key = "agent:main:telegram:dm:42:topic:0"

    anchor = _FakeAnchor()
    surface._sessions_meta[key] = anchor

    await surface._on_batch(key, "Tra cứu và tổng hợp", ["Tra cứu và tổng hợp"])
    assert len(anchor.placeholders) > 0
    ph = anchor.placeholders[0]
    # Kiểm tra các lần edit tiến trình có chứa icon trực quan
    all_edits = " ".join(ph.edits)
    assert "⏳" in all_edits or "✓" in all_edits
    # Kết quả cuối cùng được cập nhật vào placeholder
    assert ph.text == "Kết quả hoàn chỉnh."

    await memory.close()


async def test_subagent_task_visible_in_memory_and_tab_viec(cfg):
    """Sub-agent khi chạy tạo bản ghi task trong memory (tab Việc)."""
    class SimpleChildGateway:
        async def complete(self, messages, model=None, tools=None, purpose="", temperature=None):
            return Completion(text="Subagent đã hoàn thành công việc nghiên cứu.")

        async def stream(self, messages, model=None, purpose="", on_delta=None):
            return Completion(text="Chào")

    memory = await open_memory(cfg)
    dossier = Dossier.load(cfg.dossier_dir)
    gateway = SimpleChildGateway()
    ctx = ContextEngine(cfg, dossier, memory, gateway)
    registry = build_default_registry(cfg, memory)
    policy = PolicyEngine(cfg.policy_path, memory=memory)

    runner = SubagentRunner(
        cfg, gateway, memory, ctx, policy,
        registry_factory=lambda: registry,
    )

    digest = await runner.run(
        "Khảo sát thị trường AI năm 2026", profile="researcher",
        parent_session="agent:main:telegram:dm:42:topic:0",
    )
    assert digest["ok"] is True
    assert digest["status"] == "done"

    # Kiểm tra task đã xuất hiện trong danh sách tasks của memory (tab Việc)
    tasks = await memory.list_tasks(limit=10)
    sub_tasks = [t for t in tasks if "Sub-agent [researcher]" in t.get("title", "")]
    assert len(sub_tasks) >= 1
    st = sub_tasks[0]
    assert st["status"] == "done"
    assert "Khảo sát thị trường" in st["title"]

    await memory.close()


async def test_subagents_parallel_execution(cfg):
    """spawn_subagents_parallel chạy song song nhiều subagent và gom kết quả."""
    calls = []

    class MultiChildGateway:
        async def complete(self, messages, model=None, tools=None, purpose="", temperature=None):
            if purpose == "verify":
                return Completion(text=json.dumps({"ok": True, "diagnosis": ""}))
            if purpose == "plan":
                return Completion(text=json.dumps({"steps": ["Việc con"]}))
            content = " ".join(m.get("content", "") for m in messages)
            calls.append(content)
            await asyncio.sleep(0.05)
            return Completion(text=f"Xong việc: {len(calls)}")

        async def stream(self, messages, model=None, purpose="", on_delta=None):
            return Completion(text="Chào")

    memory = await open_memory(cfg)
    dossier = Dossier.load(cfg.dossier_dir)
    gateway = MultiChildGateway()
    ctx = ContextEngine(cfg, dossier, memory, gateway)
    registry = ToolRegistry()
    policy = PolicyEngine(cfg.policy_path, memory=memory)

    runner = SubagentRunner(
        cfg, gateway, memory, ctx, policy,
        registry_factory=lambda: registry,
    )
    register_subagent_tool(registry, runner, parent_session="parent_sess")

    tool_spec = registry.get("spawn_subagents_parallel")
    assert tool_spec is not None

    tasks_input = [
        {"task": "Phần việc A: tra cứu Shopee", "profile": "default"},
        {"task": "Phần việc B: tra cứu Tiki", "profile": "default"},
        {"task": "Phần việc C: tra cứu Lazada", "profile": "default"},
    ]

    res = await tool_spec.handler(tasks=tasks_input)
    assert res["ok"] is True
    assert res["count"] == 3
    assert len(res["results"]) == 3
    for r in res["results"]:
        assert r["ok"] is True
        assert r["status"] == "done"

    await memory.close()


def test_muse_reply_style_included_in_self_knowledge(cfg):
    """Khối tự nhận thức chứa chỉ dẫn phong cách hội thoại chuẩn Muse."""
    registry = ToolRegistry()
    from mulon.agent import build_self_knowledge
    knowledge = build_self_knowledge(cfg, registry)
    assert "CHUẨN MUSE" in knowledge
    assert "Ngắn gọn, đúng ý" in knowledge
