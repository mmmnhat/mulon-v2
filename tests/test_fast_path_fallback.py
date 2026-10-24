"""Tests for streaming fallback and tool hint expansion."""

import pytest
from mulon.agent import classify_intent, Intent, Agent
from mulon.gateway import Completion, ModelGateway
from mulon.context import ContextEngine, Dossier
from mulon.tools import ToolRegistry
from mulon.policy import PolicyEngine
from tests.conftest import open_memory

SESSION = "agent:main:telegram:dm:1:topic:0"


def test_classify_intent_expanded_hints():
    assert classify_intent("Test vault thử") == Intent.TOOL
    assert classify_intent("Check folder dự án này đc không") == Intent.TOOL
    assert classify_intent("xem thư mục code") == Intent.TOOL
    assert classify_intent("kiểm tra gmail") == Intent.TOOL
    assert classify_intent("ghim vào kho thư viện") == Intent.TOOL
    assert classify_intent("Cc gì v") == Intent.CHAT
    assert classify_intent("chào buổi sáng") == Intent.CHAT


class EmptyStreamThenCompleteGateway:
    """Stream trả về chuỗi rỗng; complete trả về câu trả lời thật."""

    def __init__(self):
        self.stream_called = 0
        self.complete_called = 0

    async def stream(self, messages, model=None, purpose="", on_delta=None):
        self.stream_called += 1
        return Completion(text="")

    async def complete(self, messages, model=None, purpose="", temperature=None, tools=None):
        self.complete_called += 1
        return Completion(text="Đây là câu trả lời cứu hộ từ fallback complete.")


@pytest.mark.asyncio
async def test_fast_path_fallbacks_when_stream_is_empty(cfg):
    memory = await open_memory(cfg)
    dossier = Dossier.load(cfg.dossier_dir)
    gw = EmptyStreamThenCompleteGateway()
    ctx = ContextEngine(cfg, dossier, memory, gw)
    reg = ToolRegistry()
    policy = PolicyEngine(cfg.policy_path, memory=memory)
    agent = Agent(cfg, gw, memory, ctx, reg, policy)

    res = await agent.handle(SESSION, "chào bạn")
    assert gw.stream_called == 1
    assert gw.complete_called >= 1
    assert "cứu hộ" in res.text
    await memory.close()
