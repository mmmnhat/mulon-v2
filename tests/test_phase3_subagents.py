"""Phase 3 — subagents: agent loop đầy đủ với toolset thu hẹp theo
profile, trần riêng, digest nén (không phải transcript)."""

import json
from dataclasses import replace

from mulon.context import ContextEngine, Dossier
from mulon.gateway import Completion, ToolCall
from mulon.policy import PolicyEngine
from mulon.subagents import PROFILES, SubagentRunner
from mulon.tools import build_default_registry
from tests.conftest import open_memory


class ChildGateway:
    """Act: lượt đầu gọi tool `now`, sau đó trả text. Verify: ok."""

    def __init__(self):
        self.act_calls = 0
        self.seen_tool_names: list[str] = []

    async def complete(self, messages, model=None, tools=None, purpose="",
                       temperature=None):
        if purpose == "verify":
            return Completion(text=json.dumps({"ok": True, "diagnosis": ""}))
        if purpose == "plan":
            return Completion(text=json.dumps({"steps": ["Việc con"]}))
        if tools is not None:
            self.seen_tool_names = [t["function"]["name"] for t in tools]
        self.act_calls += 1
        if self.act_calls == 1:
            return Completion(
                text="",
                tool_calls=[ToolCall(id="c1", name="now", arguments="{}")],
                prompt_tokens=120, completion_tokens=30,
            )
        return Completion(
            text="Việc con đã xong: đã xem giờ hệ thống.",
            prompt_tokens=100, completion_tokens=25,
        )

    async def stream(self, messages, model=None, purpose="", on_delta=None):
        return Completion(text="chào")


class LoopGateway:
    """Luôn đòi gọi tool — dùng để kiểm trần vòng lặp."""

    async def complete(self, messages, model=None, tools=None, purpose="",
                       temperature=None):
        if purpose == "verify":
            return Completion(text=json.dumps(
                {"ok": False, "diagnosis": "chưa xong"}))
        if purpose == "plan":
            return Completion(text=json.dumps({"steps": ["Lặp"]}))
        return Completion(
            text="",
            tool_calls=[ToolCall(id="x", name="now", arguments="{}")],
            prompt_tokens=10, completion_tokens=5,
        )

    async def stream(self, messages, model=None, purpose="", on_delta=None):
        return Completion(text="chào")


async def _make_runner(cfg, gateway):
    memory = await open_memory(cfg)
    dossier = Dossier.load(cfg.dossier_dir)
    ctx = ContextEngine(cfg, dossier, memory, gateway)
    registry = build_default_registry(cfg, memory)
    policy = PolicyEngine(cfg.policy_path, memory=memory)
    runner = SubagentRunner(
        cfg, gateway, memory, ctx, policy,
        registry_factory=lambda: registry,
    )
    return runner, memory, registry


async def test_subagent_completes_and_returns_digest(cfg):
    gateway = ChildGateway()
    runner, memory, _ = await _make_runner(cfg, gateway)
    digest = await runner.run(
        "chạy lệnh xem giờ hệ thống giúp", profile="researcher",
        parent_session="agent:main:telegram:dm:1:topic:0",
    )
    assert digest["ok"] is True
    assert digest["status"] == "done"
    assert digest["profile"] == "researcher"
    assert digest["verified"] is True
    assert digest["llm_calls"] > 0
    assert digest["tokens_used"] > 0
    assert "Việc con đã xong" in digest["summary"]
    # Digest là bản nén: có trần ký tự, không kèm transcript/tool thô
    assert len(digest["summary"]) <= cfg.subagent_digest_max_chars
    # Toolset của researcher: có now, KHÔNG có tool ghi file / spawn
    assert "now" in gateway.seen_tool_names
    assert "write_file" not in gateway.seen_tool_names
    assert "spawn_subagent" not in gateway.seen_tool_names
    await memory.close()


async def test_subagent_coder_profile_has_file_tools(cfg):
    gateway = ChildGateway()
    runner, memory, _ = await _make_runner(cfg, gateway)
    digest = await runner.run("chạy lệnh xem giờ", profile="coder")
    assert digest["ok"] is True
    assert "write_file" in gateway.seen_tool_names
    assert "run_command" in gateway.seen_tool_names
    assert "spawn_subagent" not in gateway.seen_tool_names
    await memory.close()


async def test_subagent_hits_llm_call_cap_safely(cfg):
    cfg2 = replace(cfg, subagent_max_llm_calls=5, verify_max_retries=0)
    runner, memory, _ = await _make_runner(cfg2, LoopGateway())
    runner.cfg = cfg2
    digest = await runner.run("chạy lệnh lặp mãi không xong",
                              profile="default")
    # Dừng an toàn ở trần: có digest trả về, không treo, không exception
    assert digest["profile"] == "default"
    assert digest["llm_calls"] <= 5 + 2  # + verify/plan phụ trợ
    assert digest["status"] in ("failed", "unverified")
    assert digest["summary"]
    await memory.close()


async def test_subagent_unknown_profile(cfg):
    runner, memory, _ = await _make_runner(cfg, ChildGateway())
    digest = await runner.run("gì đó", profile="không_có")
    assert digest["ok"] is False
    assert "profile" in digest["error"]
    await memory.close()


def test_profiles_never_include_spawn():
    for name, prof in PROFILES.items():
        assert "spawn_subagent" not in prof["tools"], name
