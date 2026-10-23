"""Phase 3 — scheduler (cron theo múi giờ, chống bắn trùng, mặc
định tắt) + goals/tracked items CRUD qua tool."""

import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest

from mulon.cron import next_run, parse_cron
from mulon.planning import SchedulerService, register_planning_tools
from mulon.tools import ToolRegistry
from tests.conftest import open_memory

HCM = ZoneInfo("Asia/Ho_Chi_Minh")


# ---------- cron ----------

def test_cron_daily_next_run_hcm():
    after = datetime(2026, 10, 23, 1, 0, tzinfo=timezone.utc)  # 08:00 HCM
    nxt = next_run("30 8 * * *", after, "Asia/Ho_Chi_Minh")
    assert nxt.hour == 8 and nxt.minute == 30
    assert nxt.utcoffset().total_seconds() == 7 * 3600
    # 08:30 HCM hôm nay = 01:30 UTC, vẫn sau mốc 01:00 UTC
    assert nxt.astimezone(timezone.utc) == datetime(
        2026, 10, 23, 1, 30, tzinfo=timezone.utc)


def test_cron_rolls_to_next_day():
    after = datetime(2026, 10, 23, 3, 0, tzinfo=timezone.utc)  # 10:00 HCM
    nxt = next_run("30 8 * * *", after, "Asia/Ho_Chi_Minh")
    assert nxt.day == 24 and nxt.hour == 8 and nxt.minute == 30


def test_cron_step_and_weekday():
    # Mỗi 15 phút
    after = datetime(2026, 10, 23, 0, 7, tzinfo=timezone.utc)
    nxt = next_run("*/15 * * * *", after, "Asia/Ho_Chi_Minh")
    assert nxt.minute == 15
    # 09:00 thứ Hai (dow=1). 2026-10-23 là thứ Sáu -> kế tiếp 26/10.
    after2 = datetime(2026, 10, 23, 0, 0, tzinfo=timezone.utc)
    nxt2 = next_run("0 9 * * 1", after2, "Asia/Ho_Chi_Minh")
    assert nxt2.weekday() == 0  # Monday
    assert (nxt2.year, nxt2.month, nxt2.day) == (2026, 10, 26)
    assert nxt2.hour == 9


def test_cron_invalid_expressions():
    for bad in ("* * * *", "99 * * * *", "a b c d e", "0 9 32 * *", ""):
        with pytest.raises(ValueError):
            parse_cron(bad)


# ---------- scheduler service ----------

class FakeAgent:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    async def handle(self, session_key, user_text, **kwargs):
        self.calls.append((session_key, user_text))
        return None


async def test_scheduler_fires_due_once_and_advances(cfg):
    memory = await open_memory(cfg)
    past = "2020-01-01T00:00:00+00:00"
    await memory.create_schedule(
        "s1", "0 9 * * *", "Asia/Ho_Chi_Minh", "nhắc uống nước",
        "", past,
    )
    agent = FakeAgent()

    async def provider():
        return agent

    svc = SchedulerService(cfg, memory, provider)
    fired = await svc.run_due_once(datetime(2026, 10, 23, tzinfo=timezone.utc))
    assert fired == ["s1"]
    assert agent.calls and agent.calls[0][1] == "nhắc uống nước"

    sched = await memory.get_schedule("s1")
    assert sched["last_run_at"]
    assert sched["next_run_at"] > "2026-10-23T00:00:00+00:00"

    # Chạy lại ngay: chưa tới hạn mới -> không bắn trùng
    fired2 = await svc.run_due_once(
        datetime(2026, 10, 23, tzinfo=timezone.utc))
    assert fired2 == []
    assert len(agent.calls) == 1
    await memory.close()


# ---------- tools: schedules + goals ----------

async def test_schedule_and_goal_tools(cfg):
    memory = await open_memory(cfg)
    reg = ToolRegistry()
    register_planning_tools(reg, cfg, memory)

    bad = await reg.execute("schedule_task",
                            {"cron": "không hợp lệ", "payload": "x"})
    assert bad["ok"] is False

    made = await reg.execute("schedule_task", {
        "cron": "0 9 * * *", "payload": "báo cáo sáng",
    })
    assert made["ok"] is True
    sched_id = made["schedule"]["id"]
    assert made["schedule"]["next_run_at"]

    listed = await reg.execute("list_schedules", {})
    assert listed["ok"] is True and len(listed["schedules"]) == 1

    cancelled = await reg.execute("cancel_schedule",
                                  {"schedule_id": sched_id})
    assert cancelled["ok"] is True
    gone = await reg.execute("cancel_schedule",
                             {"schedule_id": "không-có"})
    assert gone["ok"] is False

    goal = await reg.execute("create_goal", {
        "title": "Ra mắt shop", "description": "mục tiêu quý 4",
    })
    assert goal["ok"] is True
    goal_id = goal["goal"]["id"]
    assert goal["goal"]["status"] == "active"

    act = await reg.execute("log_goal_activity", {
        "goal_id": goal_id, "note": "đã xong bước 1",
    })
    assert act["ok"] is True
    miss = await reg.execute("log_goal_activity", {
        "goal_id": 99999, "note": "x",
    })
    assert miss["ok"] is False

    # Tracked item ở tầng DB, list_goals kèm item đang mở
    await memory.create_tracked_item(
        "Đặt phòng họp", goal_id=goal_id, due_at="2026-11-01")
    goals = await reg.execute("list_goals", {"status": "active"})
    assert goals["ok"] is True and len(goals["goals"]) == 1
    assert len(goals["goals"][0]["open_items"]) == 1
    assert goals["goals"][0]["open_items"][0]["title"] == "Đặt phòng họp"

    closed = await reg.execute("close_goal", {"goal_id": goal_id})
    assert closed["ok"] is True
    assert closed["goal"]["status"] == "completed"
    again = await reg.execute("close_goal", {"goal_id": goal_id})
    assert again["ok"] is False

    activity = await memory.list_goal_activity(goal_id)
    assert activity and activity[0]["note"] == "đã xong bước 1"
    await memory.close()
