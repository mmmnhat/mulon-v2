"""Vòng plan-act-verify với gateway giả lập: tool chạy thật (in-memory
DB), verify độc lập, history chỉ chứa câu trả lời sạch, trace ở trajectory."""

import json
import pytest

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


async def test_classify_intent_user_addressing_and_file_updates():
    from mulon.agent import Intent, classify_intent, clean_task_title

    assert classify_intent("Kêu tôi là ní, không cần kêu tên") is Intent.TOOL
    assert classify_intent("Ủa không cập nhật vô file hả") is Intent.TOOL
    assert classify_intent("cập nhật dossier giúp tui") is Intent.TOOL
    assert classify_intent("Đọc docs này trước") is Intent.TOOL
    assert classify_intent("https://www.agnes-ai.com/en/docs/overview") is Intent.TOOL
    assert classify_intent("sk-R248ZIPdKKMatMYeiCAc6bfajseaktrbMiHV11") is Intent.TOOL
    assert classify_intent("Dùng agnes tạo ảnh thử") is Intent.TOOL
    assert classify_intent("Cất rồi", [{"role": "assistant", "content": "Ní đã bấm thẻ Vault lưu key chưa?"}]) is Intent.TOOL
    assert clean_task_title('[Đang trả lời tin của Minh Nhật: "https://docs"]\nĐọc docs này') == "Đọc docs này"
    assert clean_task_title("Việc thông thường") == "Việc thông thường"


async def test_tools_reload_dossier_on_write(cfg):
    from pathlib import Path
    memory = await open_memory(cfg)
    dossier = Dossier.load(cfg.dossier_dir)
    registry = build_default_registry(cfg, memory, dossier=dossier)
    user_md = Path(cfg.dossier_dir) / "USER.md"
    content = "# USER\n- **Gọi là:** ní\n"
    res = await registry.execute("write_file", {"path": str(user_md), "content": content})
    assert res["ok"] is True
    assert dossier.files.get("USER.md") == content.strip()
    await memory.close()


async def _noop():
    return None


@pytest.mark.asyncio
async def test_unlimited_budget_and_synthesis_fallback(cfg):
    from dataclasses import replace
    from mulon.gateway import Completion, ToolCall
    from mulon.policy import PolicyEngine
    from mulon.context import ContextEngine, Dossier
    from mulon.agent import Agent

    cfg2 = replace(cfg, max_llm_calls_per_task=0, verify_max_retries=0)
    memory = await open_memory(cfg2)
    policy = PolicyEngine(cfg2.policy_path, memory=memory)

    call_count = 0

    class LoopingGateway:
        async def complete(self, messages, model=None, tools=None, purpose="", temperature=None):
            nonlocal call_count
            call_count += 1
            if purpose == "verify":
                return Completion(text=json.dumps({"ok": True, "diagnosis": ""}))
            if purpose == "plan":
                return Completion(text=json.dumps({"steps": ["Chạy"]}))
            if purpose == "synthesize":
                return Completion(text="Đã hoàn tất tổng hợp báo cáo.")
            if call_count < 35:
                # Gọi tool 34 lần (vượt trần cũ 30)
                return Completion(
                    text="",
                    tool_calls=[ToolCall(id=f"c_{call_count}", name="now", arguments="{}")],
                )
            return Completion(text="Hoàn thành sau 35 lượt gọi.")

        async def stream(self, messages, model=None, purpose="", on_delta=None):
            return await self.complete(messages, model=model, purpose=purpose)

    gateway = LoopingGateway()
    dossier = Dossier.load(cfg2.dossier_dir)
    ctx = ContextEngine(cfg2, dossier, memory, gateway)
    reg = build_default_registry(cfg2, memory)
    agent = Agent(cfg2, gateway, memory, ctx, reg, policy)

    res = await agent.handle("sess:test_unlimited", "chạy lệnh kiểm tra giờ hệ thống")
    assert "chạm trần ngân sách" not in res.text
    assert call_count >= 35
    assert "Hoàn thành sau 35 lượt gọi." in res.text
    await memory.close()

