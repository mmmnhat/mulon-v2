"""Vòng plan-act-verify với gateway giả lập: tool chạy thật (in-memory
DB), verify độc lập, history chỉ chứa câu trả lời sạch, trace ở trajectory."""

import json

from mulon.agent import Agent
from mulon.context import ContextEngine, Dossier
from mulon.gateway import Completion, ToolCall
from mulon.policy import PolicyEngine
from mulon.tools import build_default_registry
from tests.conftest import open_memory

SESSION = "agent:main:telegram:dm:1:topic:0"


class FakeGateway:
    """Act: lượt 1 gọi tool `now`, lượt 2 trả text. Verify: JSON ok."""

    def __init__(self):
        self.act_calls = 0

    async def complete(self, messages, model=None, tools=None, purpose="",
                       temperature=None):
        if purpose == "verify":
            return Completion(text=json.dumps({"ok": True, "diagnosis": ""}))
        if purpose == "plan":
            return Completion(text=json.dumps({"steps": ["Làm việc", "Trình kết quả"]}))
        self.act_calls += 1
        if self.act_calls == 1:
            return Completion(
                text="",
                tool_calls=[ToolCall(id="c1", name="now", arguments="{}")],
            )
        return Completion(text="Đã xem giờ xong rồi ní.")

    async def stream(self, messages, model=None, purpose="", on_delta=None):
        if on_delta:
            await on_delta("chào ní")
        return Completion(text="chào ní")


async def _make_agent(cfg):
    memory = await open_memory(cfg)
    dossier = Dossier.load(cfg.dossier_dir)
    gateway = FakeGateway()
    ctx = ContextEngine(cfg, dossier, memory, gateway)
    registry = build_default_registry(cfg, memory)
    policy = PolicyEngine(cfg.policy_path, memory=memory)
    return Agent(cfg, gateway, memory, ctx, registry, policy), memory


async def test_task_path_verifies_and_keeps_history_clean(cfg):
    agent, memory = await _make_agent(cfg)
    result = await agent.handle(SESSION, "chạy lệnh xem giờ hệ thống giúp tui")
    assert result.verified is True
    assert result.task_id
    assert "Đã xem giờ" in result.text

    task = await memory.get_task(result.task_id)
    assert task["status"] == "done"

    history = await memory.recent_messages(SESSION, limit=10)
    roles = [m["role"] for m in history]
    assert roles == ["user", "assistant"]
    # Không có trace/tool trong history
    assert all("tool" not in m["content"] for m in history)
    await memory.close()


async def test_chat_fast_path_streams(cfg):
    agent, memory = await _make_agent(cfg)
    pieces = []
    result = await agent.handle(
        SESSION, "chào buổi sáng", on_delta=lambda p: pieces.append(p) or _noop()
    )
    assert result.text == "chào ní"
    assert pieces == ["chào ní"]
    await memory.close()


async def _noop():
    return None
