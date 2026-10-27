"""Test cho T-24.1: Chạy song song sub-agent cho việc nhiều phần độc lập (chuẩn Muse)."""

from __future__ import annotations

import asyncio
from dataclasses import replace
import json
import pytest

from mulon.agent import Agent, Intent, should_plan_multi_task
from mulon.approvals import ApprovalBroker, register_approval_tools
from mulon.context import ContextEngine, Dossier
from mulon.gateway import Completion
from tests.conftest import open_memory
from mulon.policy import PolicyEngine
from mulon.subagents import PROFILES, SubagentRunner, register_subagent_tool
from mulon.tools import ToolRegistry, ToolSpec


def test_should_plan_multi_task():
    """Kiểm tra heuristic nhận diện câu lệnh nhiều việc độc lập."""
    # Các câu đơn lẻ -> False
    assert not should_plan_multi_task("Xem lịch hôm nay")
    assert not should_plan_multi_task("Tìm tài liệu về Python 3.12")
    assert not should_plan_multi_task("làm thơ về mùa thu")
    assert not should_plan_multi_task("Chào bạn, bạn có khỏe không?")

    # Các câu nhiều phần việc độc lập -> True
    assert should_plan_multi_task(
        "Tìm 2 tin AI kèm nguồn / liệt kê việc chờ duyệt / lịch hôm nay"
    )
    assert should_plan_multi_task(
        "Tìm 2 tin AI kèm nguồn, liệt kê việc chờ duyệt, và xem lịch hôm nay"
    )
    assert should_plan_multi_task(
        "1. Tra cứu thời tiết hôm nay\n2. Đọc file README.md"
    )
    assert should_plan_multi_task(
        "Vừa kiểm tra việc chờ duyệt vừa tra cứu tin tức AI"
    )
    assert should_plan_multi_task(
        "Liệt kê các mục tiêu đồng thời kiểm tra lịch trình"
    )


@pytest.mark.asyncio
async def test_list_approvals_tool(cfg, tmp_path):
    """Kiểm tra tool list_approvals trả đúng danh sách pending và history."""
    policy = PolicyEngine(cfg.policy_path, memory=await open_memory(cfg))
    broker = ApprovalBroker(policy=policy, timeout_s=60.0)
    registry = ToolRegistry()
    register_approval_tools(registry, broker)

    tool_spec = registry.get("list_approvals")
    assert tool_spec is not None

    # Mở 1 approval
    broker.open("appr_001", {"tool": "run_command", "args": {"command": "ls"}})
    res = await registry.execute("list_approvals", {"status": "pending"})
    assert res["ok"] is True
    assert len(res["pending"]) == 1
    assert res["pending"][0]["id"] == "appr_001"

    # Chờ và giải quyết approval
    waiter = asyncio.create_task(broker.wait("appr_001"))
    broker.resolve("appr_001", approved=True)
    await waiter

    res_after = await registry.execute("list_approvals", {"status": "pending"})
    assert len(res_after["pending"]) == 0

    res_hist = await registry.execute("list_approvals", {"status": "history"})
    assert len(res_hist["history"]) == 1
    assert res_hist["history"][0]["id"] == "appr_001"
    assert res_hist["history"][0]["outcome"] == "approved"

    await policy.memory.close()


def test_subagent_profiles_loading_and_toolsets():
    """Kiểm tra PROFILES nạp từ config/subagent_profiles.json có đầy đủ read-only tools."""
    assert "researcher" in PROFILES
    assert "default" in PROFILES
    assert "coder" in PROFILES

    researcher_tools = PROFILES["researcher"]["tools"]
    # researcher phải có web_search, list_approvals, list_schedules, list_goals
    assert "web_search" in researcher_tools
    assert "web_fetch" in researcher_tools
    assert "list_approvals" in researcher_tools
    assert "list_schedules" in researcher_tools
    assert "list_goals" in researcher_tools

    default_tools = PROFILES["default"]["tools"]
    assert "web_search" in default_tools
    assert "list_approvals" in default_tools
    assert "list_schedules" in default_tools


@pytest.mark.asyncio
async def test_plan_decomposition_returns_parallel_subtasks(cfg):
    """Agent._plan trả về plan có parallel=True và danh sách subtasks."""
    class PlanGateway:
        async def complete(self, messages, model=None, tools=None, purpose="", temperature=None):
            if purpose == "plan":
                return Completion(text=json.dumps({
                    "steps": [
                        "Sub-agent 1: Tìm 2 tin AI",
                        "Sub-agent 2: Liệt kê việc chờ duyệt",
                        "Sub-agent 3: Lịch hôm nay",
                        "Tổng hợp kết quả",
                    ],
                    "parallel": True,
                    "subtasks": [
                        {"task": "Tìm 2 tin AI kèm nguồn", "profile": "researcher"},
                        {"task": "Liệt kê việc chờ duyệt", "profile": "default"},
                        {"task": "Xem lịch hôm nay", "profile": "default"},
                    ],
                }))
            return Completion(text="ok")

    cfg = replace(cfg, review_fork_enabled=False)
    memory = await open_memory(cfg)
    dossier = Dossier.load(cfg.dossier_dir)
    gateway = PlanGateway()
    ctx = ContextEngine(cfg, dossier, memory, gateway)
    registry = ToolRegistry()
    policy = PolicyEngine(cfg.policy_path, memory=memory)
    agent = Agent(cfg, gateway, memory, ctx, registry, policy)

    plan = await agent._plan("Tìm 2 tin AI kèm nguồn / liệt kê việc chờ duyệt / lịch hôm nay", Intent.TOOL)
    assert plan["parallel"] is True
    assert len(plan["subtasks"]) == 3
    assert plan["subtasks"][0]["task"] == "Tìm 2 tin AI kèm nguồn"
    assert plan["subtasks"][0]["profile"] == "researcher"
    assert len(plan["steps"]) == 4

    await memory.close()


@pytest.mark.asyncio
async def test_task_path_executes_parallel_subagents_end_to_end(cfg):
    """Yêu cầu nhiều việc độc lập tự động chạy qua spawn_subagents_parallel song song."""
    calls = []
    parallel_executed = False

    class ParallelSubagentMockGateway:
        async def complete(self, messages, model=None, tools=None, purpose="", temperature=None):
            nonlocal parallel_executed
            content = " ".join(m.get("content") or "" for m in messages)

            if purpose == "plan":
                return Completion(text=json.dumps({
                    "steps": [
                        "Sub-agent 1: Tìm 2 tin AI",
                        "Sub-agent 2: Liệt kê việc chờ duyệt",
                        "Sub-agent 3: Lịch hôm nay",
                        "Tổng hợp kết quả",
                    ],
                    "parallel": True,
                    "subtasks": [
                        {"task": "Tìm 2 tin tức AI kèm nguồn", "profile": "researcher"},
                        {"task": "Liệt kê việc chờ duyệt", "profile": "default"},
                        {"task": "Lịch hôm nay", "profile": "default"},
                    ],
                }))

            if purpose == "verify":
                return Completion(text=json.dumps({"ok": True, "diagnosis": ""}))

            # Sub-agent hoặc agent chính gọi model
            calls.append({"purpose": purpose, "content": content})

            # Lời gọi tổng hợp của agent chính sau khi nhận kết quả subagent
            if any(m.get("role") == "tool" for m in messages) or "spawn_subagents_parallel" in content:
                parallel_executed = True
                return Completion(text=(
                    "Dưới đây là kết quả hoàn thành:\n"
                    "1. Tin AI: DeepMind ra mắt model mới (techcrunch.com) và Meta cập nhật Llama (theverge.com)\n"
                    "2. Việc chờ duyệt: Có 1 việc chờ duyệt xóa file\n"
                    "3. Lịch hôm nay: 14:00 Họp kỹ thuật, 17:00 Điểm tin Feed"
                ))

            # Nếu subagent xử lý tác vụ con
            if "Tìm 2 tin tức AI" in content:
                await asyncio.sleep(0.02)
                return Completion(text="[Tin tức AI: 1. DeepMind ra mắt model mới (Nguồn: techcrunch.com); 2. Meta cập nhật Llama (Nguồn: theverge.com)]")
            if "Liệt kê việc chờ duyệt" in content:
                await asyncio.sleep(0.02)
                return Completion(text="[Việc chờ duyệt: Hiện có 1 việc chờ duyệt xóa file]")
            if "Lịch hôm nay" in content:
                await asyncio.sleep(0.02)
                return Completion(text="[Lịch hôm nay: 14:00 Họp kỹ thuật; 17:00 Điểm tin Feed]")

            return Completion(text="Đã xử lý xong.")

        async def stream(self, messages, model=None, purpose="", on_delta=None):
            return Completion(text="Chào")

    cfg = replace(cfg, review_fork_enabled=False)
    memory = await open_memory(cfg)
    dossier = Dossier.load(cfg.dossier_dir)
    gateway = ParallelSubagentMockGateway()
    ctx = ContextEngine(cfg, dossier, memory, gateway)
    registry = ToolRegistry()
    policy = PolicyEngine(cfg.policy_path, memory=memory)
    broker = ApprovalBroker(policy=policy, timeout_s=60.0)

    runner = SubagentRunner(
        cfg, gateway, memory, ctx, policy,
        registry_factory=lambda: registry,
    )
    register_subagent_tool(registry, runner, parent_session="parent_sess_01")
    register_approval_tools(registry, broker)

    agent = Agent(cfg, gateway, memory, ctx, registry, policy, broker=broker)

    user_prompt = "Tìm 2 tin AI kèm nguồn / liệt kê việc chờ duyệt / lịch hôm nay"
    turn_res = await agent.handle("parent_sess_01", user_prompt)

    # 1. Kiểm tra kết quả tổng hợp đầy đủ nội dung từ cả 3 subagent
    assert turn_res.text is not None
    assert "techcrunch.com" in turn_res.text
    assert "việc chờ duyệt" in turn_res.text.lower()
    assert "14:00" in turn_res.text
    assert parallel_executed is True

    # 2. Kiểm tra subagent đã tạo các task con trong memory
    tasks = await memory.list_tasks(limit=20)
    subagent_tasks = [t for t in tasks if str(t.get("id") or "").startswith("sub_")]
    assert len(subagent_tasks) == 3, f"Phải có 3 sub-agent tasks trong memory, thực tế: {len(subagent_tasks)}"

    # 3. Kiểm tra trajectory đã ghi nhận tool_call spawn_subagents_parallel
    trajectories = await memory.recent_trajectory(kind="tool_call", limit=20)
    parallel_calls = [tr for tr in trajectories if tr["payload"].get("tool") == "spawn_subagents_parallel"]
    assert len(parallel_calls) == 1
    assert len(parallel_calls[0]["payload"]["args"]["tasks"]) == 3

    await memory.close()
