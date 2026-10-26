import asyncio
import json
import pytest
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock
from aiohttp import ClientSession

from mulon.approvals import ApprovalBroker
from mulon.config import Config
from mulon.connectors import build_default_connectors
from mulon.context import Dossier
from mulon.memory import Memory
from mulon.policy import PolicyEngine
from mulon.tools import build_default_registry
from mulon.vault import VaultStore
from mulon.webapp_server import ActivityTracker, WebAppServer
from mulon.subagents import SubagentRunner
from tests.test_v12_webapp_auth import TOKEN, OWNER, make_init_data


async def _create_server(cfg, memory, activity=None):
    cfg2 = replace(cfg, telegram_bot_token=TOKEN,
                   allowed_user_id=OWNER, webapp_port=0,
                   proactivity_enabled=True)
    policy = PolicyEngine(cfg2.policy_path, memory=memory)
    broker = ApprovalBroker(policy=policy, timeout_s=30)
    vault = VaultStore(cfg2.vault_path)
    server = WebAppServer(
        cfg2, memory=memory, policy=policy, broker=broker,
        connectors=build_default_connectors(cfg2), mcp_manager=None,
        vault_store=vault,
        registry=build_default_registry(cfg2, memory),
        dossier=Dossier.load(cfg2.dossier_dir), skills=None,
        activity=activity or ActivityTracker()
    )
    assert await server.start()
    return server


@pytest.mark.asyncio
async def test_activity_tracker_multi_task_and_stop():
    tracker = ActivityTracker()
    assert not tracker.snapshot()["busy"]

    stop_event_main = asyncio.Event()
    stop_event_sub = asyncio.Event()

    async def long_running_coro(event):
        try:
            await event.wait()
        except asyncio.CancelledError:
            raise

    loop = asyncio.get_running_loop()
    main_task = loop.create_task(long_running_coro(stop_event_main))
    sub_task = loop.create_task(long_running_coro(stop_event_sub))

    tracker.register_task("task_main_1", main_task, title="Tác vụ chính", session_key="sess:1", current_step="Bước 1", kind="main")
    tracker.register_task("sub_2", sub_task, title="Sub-agent research", session_key="sess:sub:2", current_step="Đang đọc tài liệu", kind="subagent")

    snap = tracker.snapshot()
    assert snap["busy"] is True
    assert len(snap["running_tasks"]) == 2

    # Cập nhật bước
    tracker.update_task_step("sub_2", "Đang tổng hợp thông tin")
    info = tracker.get_running_task_info("sub_2")
    assert info["current_step"] == "Đang tổng hợp thông tin"

    # Dừng sub-agent thật sự
    stopped = tracker.stop_task("sub_2")
    assert stopped is True
    assert sub_task.cancelled() or sub_task.cancelling()

    # Dừng task không tồn tại
    assert tracker.stop_task("non_existent") is False

    main_task.cancel()
    try:
        await main_task
    except asyncio.CancelledError:
        pass
    try:
        await sub_task
    except asyncio.CancelledError:
        pass


@pytest.mark.asyncio
async def test_memory_tasks_current_step_and_cancel(tmp_path):
    db_file = tmp_path / "test_tasks.db"
    mem = await Memory.open(db_file)

    task_id = "test_task_123"
    steps = ["Lập kế hoạch", "Thu thập dữ liệu", "Phân tích"]
    await mem.create_task(task_id, "sess:test", "Phân tích thị trường", steps)

    # Ban đầu bước 0 là doing
    await mem.update_step(task_id, 0, "doing")
    tasks = await mem.list_tasks(limit=10)
    assert len(tasks) == 1
    assert tasks[0]["id"] == task_id
    assert tasks[0]["status"] == "running"
    assert tasks[0]["current_step"] == "Lập kế hoạch"

    # Bước 0 xong, bước 1 doing
    await mem.update_step(task_id, 0, "done")
    await mem.update_step(task_id, 1, "doing")
    t_row = await mem.get_task(task_id)
    assert t_row["current_step"] == "Thu thập dữ liệu"

    # Huỷ task
    await mem.cancel_task(task_id, error="Người dùng bấm dừng")
    t_after = await mem.get_task(task_id)
    assert t_after["status"] == "cancelled"
    assert t_after["error"] == "Người dùng bấm dừng"

    await mem.close()


@pytest.mark.asyncio
async def test_webapp_upcoming_state_aggregation(tmp_path, cfg):
    db_file = tmp_path / "test_upcoming.db"
    mem = await Memory.open(db_file)

    # Thêm schedule cá nhân
    await mem.create_schedule(
        schedule_id=1,
        cron="0 9 * * *",
        timezone_name="Asia/Ho_Chi_Minh",
        payload="Nhắc nhở họp giao ban hàng ngày",
        session_key="sess:main",
        next_run_at="2026-10-27T09:00:00+07:00",
        enabled=1,
    )
    # Thêm tracked item
    await mem.create_tracked_item("Hoàn thành báo cáo quý", detail="Gửi cho ban giám đốc", due_at="2026-10-30")

    server = await _create_server(cfg, mem)

    try:
        upcoming = await server._upcoming_state()
        # Phải có: 1 schedule, 1 heartbeat, 1 tracked_item
        kinds = [u["kind"] for u in upcoming]
        assert "schedule" in kinds
        assert "heartbeat" in kinds
        assert "tracked_item" in kinds

        # Kiểm tra cờ can_modify_via_chat
        for u in upcoming:
            if u["kind"] in ("schedule", "tracked_item"):
                assert u["can_modify_via_chat"] is True
                assert u["read_only"] is False
                assert "chat" in u["chat_instruction"].lower()
            elif u["kind"] == "heartbeat":
                assert u["can_modify_via_chat"] is False
                assert u["read_only"] is True

        init_data = make_init_data(user_id=OWNER, token=TOKEN)
        headers = {"X-Telegram-Init-Data": init_data}
        url = f"http://127.0.0.1:{server.port}/api/upcoming"
        async with ClientSession() as session:
            async with session.get(url, headers=headers) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data["ok"] is True
                assert len(data["upcoming"]) >= 3
    finally:
        await server.stop()
        await mem.close()


@pytest.mark.asyncio
async def test_webapp_stop_task_endpoint(tmp_path, cfg):
    db_file = tmp_path / "test_api_stop.db"
    mem = await Memory.open(db_file)

    activity = ActivityTracker()
    server = await _create_server(cfg, mem, activity=activity)

    task_id = "task_running_abc"
    await mem.create_task(task_id, "sess:test", "Tác vụ chạy lâu", ["Bước 1", "Bước 2"])
    
    stop_event = asyncio.Event()
    async def dummy_run():
        await stop_event.wait()

    loop = asyncio.get_running_loop()
    live_task = loop.create_task(dummy_run())
    activity.register_task(task_id, live_task, title="Tác vụ chạy lâu", session_key="sess:test")

    init_data = make_init_data(user_id=OWNER, token=TOKEN)
    headers = {"X-Telegram-Init-Data": init_data}
    stop_url = f"http://127.0.0.1:{server.port}/api/task/stop"
    state_url = f"http://127.0.0.1:{server.port}/api/state"

    try:
        async with ClientSession() as session:
            # Kiểm tra /api/state có current_step và upcoming
            async with session.get(state_url, headers=headers) as resp:
                assert resp.status == 200
                st_data = await resp.json()
                assert "upcoming" in st_data
                running_tasks = [t for t in st_data["tasks"] if t["id"] == task_id]
                assert len(running_tasks) == 1
                assert running_tasks[0]["status"] == "running"

            # Huỷ task bằng API /api/task/stop
            async with session.post(stop_url, json={"id": task_id}, headers=headers) as resp:
                assert resp.status == 200
                body = await resp.json()
                assert body["ok"] is True
                assert body["stopped_live"] is True

            # Kiểm tra live_task đã bị huỷ thật
            assert live_task.cancelled() or live_task.cancelling()

            # Kiểm tra DB đã cập nhật sang cancelled
            db_task = await mem.get_task(task_id)
            assert db_task["status"] == "cancelled"

            # Sau khi huỷ, /api/state phản ánh trạng thái cancelled
            async with session.get(state_url, headers=headers) as resp:
                st_data = await resp.json()
                cancelled_tasks = [t for t in st_data["tasks"] if t["id"] == task_id]
                assert cancelled_tasks[0]["status"] == "cancelled"

    finally:
        await server.stop()
        try:
            live_task.cancel()
            await live_task
        except asyncio.CancelledError:
            pass
        await mem.close()


@pytest.mark.asyncio
async def test_subagent_task_registration_and_cancellation(tmp_path, cfg):
    db_file = tmp_path / "test_subagent.db"
    mem = await Memory.open(db_file)
    activity = ActivityTracker()

    from mulon.gateway import Completion
    class HangGateway:
        async def complete(self, *args, **kwargs):
            await asyncio.sleep(100)
            return Completion(text="")
        async def stream(self, *args, **kwargs):
            await asyncio.sleep(100)
            return Completion(text="")

    gateway = HangGateway()
    from mulon.context import ContextEngine
    ctx = ContextEngine(cfg, Dossier.load(cfg.dossier_dir), mem, gateway)

    policy = MagicMock()
    from mulon.policy import PolicyDecision
    policy.check = AsyncMock(return_value=PolicyDecision(True, "default"))
    registry_factory = lambda: build_default_registry(cfg, mem)

    runner = SubagentRunner(cfg, gateway, mem, ctx, policy, registry_factory, activity=activity)

    loop = asyncio.get_running_loop()
    sub_task = loop.create_task(runner.run("Nghiên cứu về quantum computing", profile="researcher"))

    # Đợi subagent khởi động và đăng ký vào activity
    await asyncio.sleep(0.05)
    running_list = activity.list_running_tasks()
    assert len(running_list) == 1
    sub_meta = running_list[0]
    assert sub_meta["kind"] == "subagent"
    sub_id = sub_meta["task_id"]

    # Dừng subagent qua activity.stop_task
    stopped = activity.stop_task(sub_id)
    assert stopped is True

    try:
        await sub_task
    except asyncio.CancelledError:
        pass

    # Kiểm tra DB: task subagent đã cập nhật thành cancelled
    task_row = await mem.get_task(sub_id)
    assert task_row is not None
    assert task_row["status"] == "cancelled"

    # ActivityTracker đã gỡ task
    assert len(activity.list_running_tasks()) == 0

    await mem.close()


@pytest.mark.asyncio
async def test_telegram_surface_upcoming_and_stop_commands(tmp_path, cfg):
    from mulon.telegram_bot import TelegramSurface

    db_file = tmp_path / "test_tg_surface.db"
    mem = await Memory.open(db_file)
    activity = ActivityTracker()

    await mem.create_schedule(
        schedule_id=5,
        cron="0 10 * * *",
        timezone_name="Asia/Ho_Chi_Minh",
        payload="Gửi báo cáo hiệu năng tuần",
        session_key="sess:tg",
        next_run_at="2026-10-27T10:00:00+07:00",
        enabled=1,
    )
    await mem.create_tracked_item("Chốt danh sách tính năng v1.8", detail="Hạn trước thứ 6", due_at="2026-10-31")

    surface = TelegramSurface(cfg=cfg, agent=None, memory=mem, dossier=None, activity=activity)
    surface._is_allowed = MagicMock(return_value=True)

    # Đăng ký handlers bằng cách gọi setup dp
    dp = surface.dp
    
    # Giả lập tin nhắn /upcoming
    msg_upcoming = MagicMock()
    msg_upcoming.text = "/upcoming"
    msg_upcoming.answer = AsyncMock()

    # Tìm handler /upcoming trong dp
    # Hoặc gọi trực tiếp logic qua event
    for handler in dp.message.handlers:
        call_fn = handler.callback
        if getattr(call_fn, "__name__", "") == "cmd_upcoming":
            await call_fn(msg_upcoming)
            break

    msg_upcoming.answer.assert_called_once()
    answer_text = msg_upcoming.answer.call_args[0][0]
    assert "Danh sách Sắp tới (Upcoming)" in answer_text
    assert "Gửi báo cáo hiệu năng tuần" in answer_text
    assert "Chốt danh sách tính năng v1.8" in answer_text
    assert "Sửa/huỷ qua chat" in answer_text

    # Giả lập lệnh /stop <task_id>
    task_id = "task_long_running_xyz"
    await mem.create_task(task_id, "sess:tg", "Tác vụ render video", ["Bước 1"])
    stop_event = asyncio.Event()
    async def dummy():
        await stop_event.wait()
    loop = asyncio.get_running_loop()
    dummy_task = loop.create_task(dummy())
    activity.register_task(task_id, dummy_task, title="Tác vụ render video")

    msg_stop = MagicMock()
    msg_stop.text = f"/stop {task_id}"
    msg_stop.answer = AsyncMock()

    for handler in dp.message.handlers:
        call_fn = handler.callback
        if getattr(call_fn, "__name__", "") == "cmd_cancel":
            await call_fn(msg_stop)
            break

    msg_stop.answer.assert_called_once()
    stop_reply = msg_stop.answer.call_args[0][0]
    assert f"Đã dừng tác vụ '{task_id}' thành công." in stop_reply
    assert dummy_task.cancelled() or dummy_task.cancelling()
    t_row = await mem.get_task(task_id)
    assert t_row["status"] == "cancelled"

    try:
        dummy_task.cancel()
        await dummy_task
    except asyncio.CancelledError:
        pass
    await mem.close()
