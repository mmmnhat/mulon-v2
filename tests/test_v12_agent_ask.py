"""1.2.0 Khối 2: agent gặp policy "ask" — broker chặn thì tool
KHÔNG chạy và model nhận lỗi từ chối; duyệt thì chạy như thường;
không có broker thì chặn an toàn."""

import asyncio
import json

from mulon.agent import Agent
from mulon.approvals import ApprovalBroker
from mulon.context import ContextEngine, Dossier
from mulon.gateway import Completion, ToolCall
from mulon.policy import PolicyEngine
from mulon.tools import build_default_registry
from tests.conftest import open_memory

SESSION = "agent:main:telegram:dm:1:topic:0"


class Gateway:
    """Act 1: gọi tool `now`. Act 2: trả text. Ghi lại messages
    của act 2 để soi nội dung tool result model nhận được."""

    def __init__(self):
        self.act_calls = 0
        self.act_messages = None

    async def complete(self, messages, model=None, tools=None,
                       purpose="", temperature=None):
        if purpose == "verify":
            return Completion(text=json.dumps(
                {"ok": True, "diagnosis": ""}))
        if purpose == "plan":
            return Completion(text=json.dumps({"steps": ["Việc"]}))
        if tools is None:
            # Review fork và các lời gọi phụ: trả JSON trống, KHÔNG
            # đụng vào bộ đếm act (trước đây fork ghi đè messages
            # đã ghi của act — lỗi ở test, không phải product).
            return Completion(text="{}")
        self.act_calls += 1
        self.act_messages = messages
        if self.act_calls == 1:
            return Completion(text="", tool_calls=[
                ToolCall(id="c1", name="now", arguments="{}")])
        return Completion(text="Xong.")

    async def stream(self, messages, model=None, purpose="",
                     on_delta=None):
        return Completion(text="chào")


async def _make(cfg, decision):
    cfg.policy_path.write_text(json.dumps(
        {"tools": {"now": "ask"}}), encoding="utf-8")
    memory = await open_memory(cfg)
    dossier = Dossier.load(cfg.dossier_dir)
    gateway = Gateway()
    ctx = ContextEngine(cfg, dossier, memory, gateway)
    registry = build_default_registry(cfg, memory)
    policy = PolicyEngine(cfg.policy_path, memory=memory)
    broker = ApprovalBroker(policy=policy, timeout_s=10)

    async def on_event(kind, payload):
        if kind == "approval_requested":
            async def _decide():
                await asyncio.sleep(0.05)
                broker.resolve(payload["approval_id"], decision)

            asyncio.create_task(_decide())

    agent = Agent(cfg, gateway, memory, ctx, registry, policy,
                  broker=broker)
    return agent, memory, gateway, on_event


async def test_ask_denied_tool_not_executed(cfg):
    agent, memory, gateway, on_event = await _make(cfg, False)
    result = await agent.handle(
        SESSION, "chạy lệnh xem giờ giúp tui", on_event=on_event)
    assert result.text == "Xong."
    # Tool KHÔNG hề chạy: không có trajectory tool_call.
    calls = await memory.recent_trajectory(kind="tool_call", limit=5)
    assert calls == []
    # Model nhận được lỗi từ chối rõ ràng trong tool result.
    tool_msgs = [m for m in (gateway.act_messages or [])
                 if m.get("role") == "tool"]
    assert tool_msgs and "TỪ CHỐI" in tool_msgs[0]["content"]
    decisions = await memory.recent_trajectory(
        kind="approval_decision", limit=5)
    assert decisions and decisions[0]["payload"]["outcome"] == "denied"
    await memory.close()


async def test_ask_approved_tool_executes(cfg):
    agent, memory, gateway, on_event = await _make(cfg, True)
    result = await agent.handle(
        SESSION, "chạy lệnh xem giờ giúp tui", on_event=on_event)
    assert result.text == "Xong."
    calls = await memory.recent_trajectory(kind="tool_call", limit=5)
    assert len(calls) == 1 and calls[0]["payload"]["tool"] == "now"
    await memory.close()


async def test_fast_path_gateway_error_is_plain_language(cfg):
    """LOI-1: lỗi gateway ở fast path -> user chỉ thấy lời
    thường, chi tiết kỹ thuật vào trajectory turn_error."""
    from mulon.gateway import GatewayError

    class BrokenGateway(Gateway):
        async def stream(self, messages, model=None, purpose="",
                         on_delta=None):
            raise GatewayError(
                "gọi model thất bại sau 3 lần: http://127.0.0.1:8317 "
                "chi tiết nhà cung cấp xyz")

    memory = await open_memory(cfg)
    dossier = Dossier.load(cfg.dossier_dir)
    gateway = BrokenGateway()
    ctx = ContextEngine(cfg, dossier, memory, gateway)
    registry = build_default_registry(cfg, memory)
    policy = PolicyEngine(cfg.policy_path, memory=memory)
    agent = Agent(cfg, gateway, memory, ctx, registry, policy)
    result = await agent.handle(SESSION, "chào buổi sáng nhé")
    assert "thử lại sau ít phút" in result.text
    assert "127.0.0.1" not in result.text
    assert "xyz" not in result.text
    rows = await memory.recent_trajectory(kind="turn_error", limit=3)
    assert rows and "fast_path" in str(rows[0]["payload"])
    await memory.close()


async def test_ask_without_broker_blocks_safely(cfg):
    cfg.policy_path.write_text(json.dumps(
        {"tools": {"now": "ask"}}), encoding="utf-8")
    memory = await open_memory(cfg)
    dossier = Dossier.load(cfg.dossier_dir)
    gateway = Gateway()
    ctx = ContextEngine(cfg, dossier, memory, gateway)
    registry = build_default_registry(cfg, memory)
    policy = PolicyEngine(cfg.policy_path, memory=memory)
    agent = Agent(cfg, gateway, memory, ctx, registry, policy)  # no broker
    result = await agent.handle(SESSION, "chạy lệnh xem giờ giúp tui")
    assert result.text == "Xong."
    calls = await memory.recent_trajectory(kind="tool_call", limit=5)
    assert calls == []
    tool_msgs = [m for m in (gateway.act_messages or [])
                 if m.get("role") == "tool"]
    assert tool_msgs and "chưa được nối" in tool_msgs[0]["content"]
    await memory.close()
