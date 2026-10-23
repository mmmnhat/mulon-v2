"""Phase 2 — background review fork (mục 4.3) + session_search:
fork chạy nền sau lượt, ghi digest + fact, nuốt lỗi gateway;
session_search trả tin gốc nguyên văn kèm session + thời gian."""

import asyncio
import json

from mulon.agent import Agent
from mulon.context import ContextEngine, Dossier
from mulon.gateway import Completion
from mulon.policy import PolicyEngine
from mulon.tools import build_default_registry
from tests.conftest import open_memory

S_OLD = "agent:main:telegram:dm:1:topic:0"
S_NEW = "agent:main:telegram:dm:2:topic:0"


async def _wait_digests(memory, session_key, count=1, timeout_s=5.0):
    waited = 0.0
    while waited < timeout_s:
        digests = await memory.list_digests(session_key=session_key)
        if len(digests) >= count:
            return digests
        await asyncio.sleep(0.05)
        waited += 0.05
    return await memory.list_digests(session_key=session_key)


class ForkGateway:
    async def complete(self, messages, model=None, tools=None, purpose="",
                       temperature=None):
        if purpose == "review_fork":
            return Completion(text=json.dumps({
                "digest": "User chào buổi sáng.",
                "facts": ["User thường chào buổi sáng lúc rảnh"],
            }))
        return Completion(text="{}")

    async def stream(self, messages, model=None, purpose="", on_delta=None):
        if on_delta:
            await on_delta("chào ní")
        return Completion(text="chào ní")


class ForkBoomGateway(ForkGateway):
    async def complete(self, messages, model=None, tools=None, purpose="",
                       temperature=None):
        if purpose == "review_fork":
            raise RuntimeError("gateway sập theo kịch bản test")
        return Completion(text="{}")


async def _make_agent(cfg, gateway):
    memory = await open_memory(cfg)
    dossier = Dossier.load(cfg.dossier_dir)
    ctx = ContextEngine(cfg, dossier, memory, gateway)
    registry = build_default_registry(cfg, memory)
    policy = PolicyEngine(cfg.policy_path, memory=memory)
    return Agent(cfg, gateway, memory, ctx, registry, policy), memory


async def test_review_fork_writes_digest_and_fact(cfg):
    agent, memory = await _make_agent(cfg, ForkGateway())
    result = await agent.handle(S_OLD, "chào buổi sáng")
    assert result.text == "chào ní"  # lượt chính không chờ fork
    digests = await _wait_digests(memory, S_OLD)
    assert digests, "fork phải ghi digest sau lượt"
    assert digests[0]["digest"] == "User chào buổi sáng."
    assert digests[0]["facts_saved"] == 1
    facts = [f for f in await memory.active_facts()
             if f["source"] == "review_fork"]
    assert len(facts) == 1
    await memory.close()


async def test_review_fork_swallows_gateway_error(cfg):
    agent, memory = await _make_agent(cfg, ForkBoomGateway())
    result = await agent.handle(S_OLD, "chào buổi sáng")
    assert result.text == "chào ní"  # gateway fork sập, lượt chính nguyên
    digests = await _wait_digests(memory, S_OLD)
    assert digests, "fork lỗi vẫn ghi digest (rỗng) để truy vết"
    assert digests[0]["facts_saved"] == 0
    await memory.close()


async def test_session_search_returns_verbatim(cfg):
    memory = await open_memory(cfg)
    await memory.get_or_create_session(S_OLD)
    original = "Mã đặt phòng khách sạn là ABC123XYZ, nhớ kỹ giúp tui nha"
    await memory.append_message(S_OLD, "user", original)
    await memory.get_or_create_session(S_NEW)
    await memory.append_message(S_NEW, "user", "chuyện không liên quan")

    results = await memory.session_search("mã đặt phòng")
    assert results
    top = results[0]
    assert top["content"] == original  # nguyên văn, không tóm tắt
    assert top["session_key"] == S_OLD
    assert top["created_at"]

    # Loại trừ phiên chỉ định -> không còn kết quả của phiên đó.
    filtered = await memory.session_search(
        "mã đặt phòng", exclude_session=S_OLD
    )
    assert filtered == []

    # Qua tool registry: cùng kết quả, bọc cấu trúc ok.
    reg = build_default_registry(cfg, memory)
    out = await reg.execute("session_search", {"query": "đặt phòng"})
    assert out["ok"] is True
    assert out["results"][0]["content"] == original
    await memory.close()
