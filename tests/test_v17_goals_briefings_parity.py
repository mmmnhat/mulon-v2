"""Test parity Goals & Goal Briefings (T-10.4).

Theo spec T-10.4:
- Goals: tạo/sửa/đóng goal qua chat, goal có subgoal lồng 1 cấp.
- Mini App thấy cây goal + tiến triển thật (không phần trăm tự bịa — suy từ subgoal/cam kết đã đóng).
- Goal briefings: tiến trình nền viết thư briefing gắn vào goal (tiến triển, việc tiếp theo, điểm nghẽn)
  — người dùng KHÔNG đặt lịch được (đúng chuẩn Muse, checklist C8).
- Nghiệm thu: test sống: tạo goal + 2 subgoal qua chat -> app hiện đúng cây; đóng 1 subgoal -> tiến triển cập nhật;
  briefing sinh ra và gắn đúng goal.
"""
from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock
import pytest

from mulon.config import Config
from mulon.connectors import ConnectorRegistry
from mulon.goal_briefing import GoalBriefingService
from mulon.memory import Memory
from mulon.planning import register_planning_tools
from mulon.telegram_bot import TelegramSurface
from mulon.tools import ToolRegistry
from mulon.webapp_server import WebAppServer
from tests.conftest import open_memory


@pytest.fixture
async def mem(cfg):
    m = await open_memory(cfg)
    yield m
    await m.close()


@pytest.mark.asyncio
async def test_goal_and_subgoal_nesting_1_level(mem):
    """Goal có subgoal lồng đúng 1 cấp; chặn lồng cấp 2."""
    root = await mem.create_goal(title="Ra mắt sản phẩm", description="Dự án Q4")
    assert root["id"] is not None
    assert root["parent_id"] is None

    # Tạo 2 subgoal lồng 1 cấp
    sub1 = await mem.create_goal(title="Thiết kế UI", parent_id=root["id"])
    sub2 = await mem.create_goal(title="Viết Backend API", parent_id=root["id"])
    assert sub1["parent_id"] == root["id"]
    assert sub2["parent_id"] == root["id"]

    subgoals = await mem.list_subgoals(root["id"])
    assert len(subgoals) == 2

    # Chặn tạo subgoal con của subgoal (cấp 2)
    with pytest.raises(ValueError, match="Chỉ hỗ trợ subgoal lồng 1 cấp"):
        await mem.create_goal(title="Vẽ icon button", parent_id=sub1["id"])

    # Chặn cập nhật thành cha của chính nó
    with pytest.raises(ValueError, match="không thể làm cha của chính nó"):
        await mem.update_goal(goal_id=root["id"], parent_id=root["id"])

    # Cập nhật thông tin goal
    updated = await mem.update_goal(
        goal_id=sub1["id"],
        title="Thiết kế UI v2",
        current_state="Đã xong wireframe",
    )
    assert updated["title"] == "Thiết kế UI v2"
    assert updated["current_state"] == "Đã xong wireframe"


@pytest.mark.asyncio
async def test_factual_progress_calculation(mem):
    """Tiến triển thật: suy từ subgoal và cam kết đã đóng, tuyệt đối không bịa phần trăm."""
    root = await mem.create_goal(title="Xây dựng hệ thống thanh toán")

    # Khi chưa có subgoal hay cam kết: 0% khi active, 100% khi completed
    detail = await mem.get_goal_detail(root["id"])
    assert detail["progress"]["total_units"] == 0
    assert detail["progress"]["progress_pct"] == 0
    assert "0%" in detail["progress"]["progress_label"]

    # Thêm 2 subgoal và 1 cam kết tracked item
    sub1 = await mem.create_goal(title="Tích hợp Stripe", parent_id=root["id"])
    sub2 = await mem.create_goal(title="Tích hợp Momo", parent_id=root["id"])
    track1 = await mem.create_tracked_item(
        title="Đăng ký tài khoản doanh nghiệp", goal_id=root["id"]
    )

    # 3 đơn vị tổng cộng, chưa xong đơn vị nào -> 0%
    detail = await mem.get_goal_detail(root["id"])
    assert detail["progress"]["total_units"] == 3
    assert detail["progress"]["completed_units"] == 0
    assert detail["progress"]["progress_pct"] == 0
    assert "0/2 subgoal" in detail["progress"]["progress_label"]
    assert "0/1 cam kết" in detail["progress"]["progress_label"]

    # Đóng 1 subgoal -> tiến triển cập nhật thành 1/3 (33%)
    closed_sub1 = await mem.close_goal(sub1["id"])
    assert closed_sub1["status"] == "completed"

    detail = await mem.get_goal_detail(root["id"])
    assert detail["progress"]["completed_subgoals"] == 1
    assert detail["progress"]["completed_units"] == 1
    assert detail["progress"]["progress_pct"] == 33
    assert "1/2 subgoal" in detail["progress"]["progress_label"]

    # Đóng cam kết tracked item -> tiến triển cập nhật thành 2/3 (67%)
    await mem.update_tracked_item(track1["id"], status="completed")

    detail = await mem.get_goal_detail(root["id"])
    assert detail["progress"]["completed_units"] == 2
    assert detail["progress"]["progress_pct"] == 67
    assert "1/1 cam kết" in detail["progress"]["progress_label"]

    # Đóng subgoal còn lại -> tiến triển đạt 3/3 (100%)
    await mem.close_goal(sub2["id"])
    detail = await mem.get_goal_detail(root["id"])
    assert detail["progress"]["completed_units"] == 3
    assert detail["progress"]["progress_pct"] == 100


@pytest.mark.asyncio
async def test_goal_briefings_service(cfg, mem):
    """Goal briefings: tiến trình nền viết thư briefing dạng Letter gắn đúng vào goal."""
    root = await mem.create_goal(
        title="Mở rộng thị trường Đông Nam Á",
        description="Mục tiêu kinh doanh 2026",
    )
    sub1 = await mem.create_goal(title="Nghiên cứu thị trường Singapore", parent_id=root["id"])
    await mem.create_goal(title="Thiết lập pháp nhân Thái Lan", parent_id=root["id"])
    await mem.close_goal(sub1["id"])

    svc = GoalBriefingService(cfg, mem)
    briefing = await svc.generate_briefing(root["id"])

    assert briefing["goal_id"] == root["id"]
    assert "Mở rộng thị trường" in briefing["title"]
    assert "1/2" in briefing["progress_summary"]
    assert "Thái Lan" in briefing["next_steps"]
    assert "Chào ní" in briefing["letter_body"]
    assert "### 1. Tiến triển" in briefing["letter_body"]
    assert "### 2. Việc tiếp theo" in briefing["letter_body"]
    assert "### 3. Điểm nghẽn & Rủi ro" in briefing["letter_body"]

    # Kiểm tra lưu vào database và activity log
    saved = await mem.get_latest_goal_briefing(root["id"])
    assert saved is not None
    assert saved["id"] == briefing["id"]

    acts = await mem.list_goal_activity(root["id"])
    assert any("briefing" in a["note"].lower() for a in acts)


@pytest.mark.asyncio
async def test_user_cannot_schedule_briefings(cfg, mem):
    """Checklist C8: người dùng KHÔNG đặt lịch được cho Goal Briefings bằng schedule."""
    reg = ToolRegistry()
    register_planning_tools(reg, cfg, mem)

    # Thử đặt lịch briefing -> bị từ chối
    res = await reg.execute("schedule_task", {
        "cron": "0 9 * * *",
        "payload": "Tạo goal_briefing cho goal 1",
        "title": "Briefing hàng ngày",
    })
    assert res["ok"] is False
    assert "Goal briefings do tiến trình nền" in res["error"]
    assert "không thể đặt lịch thủ công" in res["error"]


@pytest.mark.asyncio
async def test_planning_goal_tools_tree_and_close(cfg, mem):
    """Kiểm tra bộ tools planning: create_goal, update_goal, close_goal, list_goals, generate_goal_briefing."""
    reg = ToolRegistry()
    register_planning_tools(reg, cfg, mem)

    # Tạo goal + 2 subgoal qua tools
    r1 = await reg.execute("create_goal", {"title": "Xây dựng website bán hàng"})
    assert r1["ok"] is True
    root_id = r1["goal"]["id"]

    s1 = await reg.execute("create_goal", {"title": "Làm giỏ hàng", "parent_id": root_id})
    s2 = await reg.execute("create_goal", {"title": "Tích hợp cổng VNPay", "parent_id": root_id})
    assert s1["ok"] is True and s2["ok"] is True
    sub1_id = s1["goal"]["id"]

    # list_goals trả về cây
    tree_res = await reg.execute("list_goals", {})
    assert tree_res["ok"] is True
    tree = tree_res["goals"]
    found = [g for g in tree if g["id"] == root_id]
    assert len(found) == 1
    assert len(found[0]["subgoals"]) == 2
    assert found[0]["progress"]["progress_pct"] == 0

    # Đóng 1 subgoal qua close_goal
    c_res = await reg.execute("close_goal", {"goal_id": sub1_id})
    assert c_res["ok"] is True

    # Cây cập nhật tiến độ
    tree_res2 = await reg.execute("list_goals", {})
    found2 = [g for g in tree_res2["goals"] if g["id"] == root_id][0]
    assert found2["progress"]["completed_subgoals"] == 1
    assert found2["progress"]["progress_pct"] == 50

    # Sinh briefing qua tool
    b_res = await reg.execute("generate_goal_briefing", {"goal_id": root_id})
    assert b_res["ok"] is True
    assert "Chào ní" in b_res["briefing"]["letter_body"]


@pytest.mark.asyncio
async def test_miniapp_goals_api_endpoints(cfg, mem):
    """Mini App: API /api/state và /api/goals thấy đúng cây goal + tiến triển thật + thư briefing."""
    class DummyPolicy:
        def can_use_sync(self, *a, **k): return True
        def state(self): return {}

    class DummyBroker:
        def pending(self): return []

    server = WebAppServer(
        cfg=cfg,
        memory=mem,
        policy=DummyPolicy(),
        broker=DummyBroker(),
        connectors=ConnectorRegistry(),
        mcp_manager=None,
        vault_store=None,
        registry=None,
    )

    # 1. Tạo goal + subgoal qua API create
    class DummyReq1:
        async def json(self):
            return {"title": "Học Machine Learning", "category": "education"}

    res1 = await server._handle_goal_create(DummyReq1())
    assert res1.status == 200
    data1 = json.loads(res1.text)
    assert data1["ok"] is True
    root_id = data1["goal"]["id"]

    class DummyReq2:
        async def json(self):
            return {"title": "Học Linear Algebra", "parent_id": root_id}

    res2 = await server._handle_goal_create(DummyReq2())
    assert res2.status == 200
    data2 = json.loads(res2.text)
    assert data2["ok"] is True
    sub_id = data2["goal"]["id"]

    # 2. Kiểm tra /api/goals endpoint
    class DummyReqList:
        query = {}

    res_list = await server._handle_goals_list(DummyReqList())
    assert res_list.status == 200
    data_list = json.loads(res_list.text)
    assert data_list["ok"] is True
    assert len(data_list["goals"]) == 1
    assert len(data_list["goals"][0]["subgoals"]) == 1

    # 3. Kiểm tra _goals_state nạp vào /api/state
    st = await server._goals_state()
    assert st["count"] == 1
    assert len(st["tree"]) == 1
    assert len(st["tree"][0]["subgoals"]) == 1
    assert st["tree"][0]["progress"]["progress_pct"] == 0

    # 4. Đóng subgoal qua API close
    class DummyReqClose:
        async def json(self):
            return {"goal_id": sub_id}

    res_close = await server._handle_goal_close(DummyReqClose())
    assert res_close.status == 200

    # 5. Tiến độ cập nhật lên 100%
    st_after = await server._goals_state()
    assert st_after["tree"][0]["progress"]["progress_pct"] == 100
    assert "1/1 subgoal" in st_after["tree"][0]["progress"]["progress_label"]

    # 6. Sinh briefing qua API
    class DummyReqBrief:
        match_info = {"id": str(root_id)}

    res_brief = await server._handle_goal_briefing(DummyReqBrief())
    assert res_brief.status == 200
    data_brief = json.loads(res_brief.text)
    assert data_brief["ok"] is True
    assert "Chào ní" in data_brief["briefing"]["letter_body"]


@pytest.mark.asyncio
async def test_telegram_chat_goal_commands(cfg, mem):
    """Test lệnh chat /goal và /goals: tạo goal, tạo 2 subgoal, đóng 1 subgoal -> tiến độ cập nhật, sinh briefing."""
    bot = AsyncMock()
    surface = TelegramSurface(cfg=cfg, agent=None, memory=mem, dossier=None)
    surface.bot = bot
    surface._is_allowed = MagicMock(return_value=True)
    surface._topic_thread = AsyncMock(return_value=None)

    dp = surface.dp

    # Tìm callback cmd_goal_router
    router_fn = None
    for handler in dp.message.handlers:
        fn = handler.callback
        if getattr(fn, "__name__", "") == "cmd_goal_router":
            router_fn = fn
            break
    assert router_fn is not None, "Phải đăng ký cmd_goal_router"

    def make_msg(text: str):
        msg = AsyncMock()
        msg.text = text
        msg.chat.id = 12345678
        msg.message_thread_id = None
        msg.from_user.id = 12345678
        msg.answer = AsyncMock()
        return msg

    # 1. /goal create Kế hoạch Q4
    msg1 = make_msg("/goal create Kế hoạch Q4 --desc 'Mục tiêu trọng tâm'")
    await router_fn(msg1)
    bot.send_message.assert_called()
    call_text1 = bot.send_message.call_args[0][1]
    assert "Đã tạo mục tiêu (Goal) thành công" in call_text1
    assert "Kế hoạch Q4" in call_text1

    tree1 = await mem.get_goal_tree()
    root_id = tree1[0]["id"]

    # 2. Tạo 2 subgoal: /goal create Làm Landing Page --parent <root_id>
    msg2 = make_msg(f"/goal create Làm Landing Page --parent {root_id}")
    await router_fn(msg2)
    call_text2 = bot.send_message.call_args[0][1]
    assert "Đã tạo mục tiêu con (Subgoal) thành công" in call_text2
    assert "Làm Landing Page" in call_text2

    msg3 = make_msg(f"/goal create Chạy Facebook Ads --parent {root_id}")
    await router_fn(msg3)

    tree2 = await mem.get_goal_tree()
    subgoals = tree2[0]["subgoals"]
    assert len(subgoals) == 2
    sub1_id = subgoals[0]["id"]

    # 3. Xem /goals
    msg_list = make_msg("/goals")
    await router_fn(msg_list)
    list_text = bot.send_message.call_args[0][1]
    assert "Kế hoạch Q4" in list_text
    assert "Làm Landing Page" in list_text
    assert "Chạy Facebook Ads" in list_text
    assert "0/2 subgoal" in list_text

    # 4. Đóng 1 subgoal: /goal close <sub1_id>
    msg_close = make_msg(f"/goal close {sub1_id}")
    await router_fn(msg_close)
    close_text = bot.send_message.call_args[0][1]
    assert "Đã hoàn thành mục tiêu con (Subgoal)" in close_text
    assert "1/2 subgoal" in close_text

    # 5. Sinh briefing: /goal briefing <root_id>
    msg_brief = make_msg(f"/goal briefing {root_id}")
    await router_fn(msg_brief)
    brief_text = bot.send_message.call_args[0][1]
    assert "THƯ BRIEFING MỤC TIÊU" in brief_text
    assert "Tiến triển" in brief_text
    assert "Việc tiếp theo" in brief_text
