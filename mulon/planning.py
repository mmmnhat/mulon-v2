"""Scheduler + goals/tracking (thiết kế mục 7) — Phase 3.

Scheduler: vòng lặp nền DUY NHẤT khi được bật đích danh
(SCHEDULER_ENABLED=1, mặc định TẮT — bài học vụ user phải xóa toàn
bộ job tự động 2026-10-22). Khi tới hạn: tính lần kế tiếp và ghi
TRƯỚC (chống bắn trùng — bài học heartbeat Mulon cũ), rồi tạo task
cho agent trong session hệ thống và ghi trajectory.

Goals: 2 trạng thái (active/completed), activity log, tracked items
ở tầng DB. Goal không bao giờ tự đóng.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

from .cron import next_run_iso
from .tools import ToolSpec

logger = logging.getLogger("mulon.planning")

SYSTEM_SESSION = "agent:main:system:scheduler"
_UTC = timezone.utc  # tránh bị tham số tool tên 'timezone' che

AgentProvider = Callable[[], Awaitable[object]]


class SchedulerService:
    """Quét schedules tới hạn và giao việc cho agent."""

    def __init__(self, cfg, memory, agent_provider: AgentProvider):
        self.cfg = cfg
        self.memory = memory
        self._agent_provider = agent_provider
        self._lock = asyncio.Lock()

    async def run_due_once(self, now: Optional[datetime] = None) -> list[str]:
        """Chạy mọi schedule đã tới hạn. Trả danh sách id đã bắn.

        Lỗi của từng schedule bị nuốt (ghi trajectory) — 1 job hỏng
        không chặn các job khác và không sập vòng lặp.
        """
        now = now or datetime.now(timezone.utc)
        fired: list[str] = []
        async with self._lock:
            due = await self.memory.due_schedules(
                now.astimezone(timezone.utc).isoformat(timespec="seconds")
            )
            agent = None
            for sched in due:
                try:
                    # Tính + ghi lần kế tiếp TRƯỚC khi chạy: tiến trình
                    # có chết giữa chừng cũng không bắn trùng job này.
                    nxt = next_run_iso(sched["cron"], now,
                                       sched["timezone"])
                except Exception as exc:
                    logger.warning("schedule %s cron lỗi, tắt: %s",
                                   sched["id"], exc)
                    await self.memory.cancel_schedule(sched["id"])
                    continue
                await self.memory.mark_schedule_run(
                    sched["id"],
                    now.astimezone(timezone.utc).isoformat(timespec="seconds"),
                    nxt,
                )
                try:
                    if agent is None:
                        agent = await self._agent_provider()
                    session_key = sched["session_key"] or SYSTEM_SESSION
                    await self.memory.log_trajectory(
                        session_key, "schedule_fired",
                        {"schedule_id": sched["id"],
                         "cron": sched["cron"]},
                    )
                    await agent.handle(session_key, sched["payload"])
                    fired.append(sched["id"])
                except Exception as exc:
                    logger.warning("schedule %s chạy lỗi: %s",
                                   sched["id"], exc)
                    await self.memory.log_trajectory(
                        sched["session_key"] or SYSTEM_SESSION,
                        "schedule_error",
                        {"schedule_id": sched["id"], "error": str(exc)},
                    )
        return fired

    async def run_forever(self) -> None:
        """Vòng lặp nền — chỉ được tạo task khi SCHEDULER_ENABLED=1."""
        logger.info("scheduler nền BẬT (tick %ss)",
                    self.cfg.scheduler_tick_s)
        while True:
            await asyncio.sleep(self.cfg.scheduler_tick_s)
            try:
                fired = await self.run_due_once()
                if fired:
                    logger.info("scheduler đã bắn: %s", fired)
            except Exception as exc:
                logger.warning("scheduler tick lỗi (bỏ qua): %s", exc)


# ---------------------------------------------------------------------------
# Tools
# ---------------------------------------------------------------------------

def register_planning_tools(registry, cfg, memory) -> None:
    def spec(name, desc, params, group, timeout):
        def deco(fn):
            registry.register(ToolSpec(name, desc, params, group, timeout, fn))
            return fn

        return deco

    @spec(
        "schedule_task",
        "Hẹn giờ 1 việc lặp lại theo cron 5 trường (phút giờ ngày tháng "
        "thứ), múi giờ tường minh. Việc chỉ CHẠY khi scheduler được bật "
        "(SCHEDULER_ENABLED=1). Trả về lịch đã tạo kèm lần chạy kế tiếp.",
        {
            "type": "object",
            "properties": {
                "cron": {"type": "string"},
                "payload": {"type": "string"},
                "timezone": {
                    "type": "string",
                    "default": "Asia/Ho_Chi_Minh",
                },
                "session_key": {"type": "string", "default": ""},
            },
            "required": ["cron", "payload"],
        },
        "schedule", 10,
    )
    async def schedule_task(cron: str, payload: str,
                            timezone: str = "Asia/Ho_Chi_Minh",
                            session_key: str = ""):
        tz_name = timezone or cfg.default_timezone
        try:
            nxt = next_run_iso(cron, datetime.now(_UTC), tz_name)
        except Exception as exc:
            return {"ok": False, "error": f"cron không hợp lệ: {exc}"}
        schedule_id = uuid.uuid4().hex[:12]
        sched = await memory.create_schedule(
            schedule_id, cron, tz_name, payload, session_key, nxt,
        )
        return {"ok": True, "schedule": sched}

    @spec(
        "list_schedules",
        "Liệt kê mọi lịch hẹn giờ đã tạo (kể cả đã tắt).",
        {"type": "object", "properties": {}, "required": []},
        "schedule", 10,
    )
    async def list_schedules():
        items = await memory.list_schedules()
        return {"ok": True, "schedules": items}

    @spec(
        "cancel_schedule",
        "Tắt 1 lịch hẹn giờ theo id (không xóa dữ liệu).",
        {
            "type": "object",
            "properties": {"schedule_id": {"type": "string"}},
            "required": ["schedule_id"],
        },
        "schedule", 10,
    )
    async def cancel_schedule(schedule_id: str):
        ok = await memory.cancel_schedule(schedule_id)
        if not ok:
            return {"ok": False,
                    "error": f"không thấy schedule: {schedule_id}"}
        return {"ok": True, "schedule_id": schedule_id, "enabled": 0}

    @spec(
        "create_goal",
        "Tạo mục tiêu dài hạn (goal). Goal có activity log riêng và "
        "không bao giờ tự đóng.",
        {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "description": {"type": "string", "default": ""},
            },
            "required": ["title"],
        },
        "goals", 10,
    )
    async def create_goal(title: str, description: str = ""):
        goal = await memory.create_goal(title, description)
        return {"ok": True, "goal": goal}

    @spec(
        "list_goals",
        "Liệt kê goals. status rỗng = mọi trạng thái; 'active' hoặc "
        "'completed' để lọc. Kèm tracked items đang mở của từng goal.",
        {
            "type": "object",
            "properties": {
                "status": {"type": "string", "default": ""},
            },
            "required": [],
        },
        "goals", 10,
    )
    async def list_goals(status: str = ""):
        goals = await memory.list_goals(status=status or None)
        for goal in goals:
            goal["open_items"] = await memory.list_tracked_items(
                goal_id=goal["id"], status="open"
            )
        return {"ok": True, "goals": goals}

    @spec(
        "log_goal_activity",
        "Ghi 1 dòng tiến độ vào activity log của goal.",
        {
            "type": "object",
            "properties": {
                "goal_id": {"type": "integer"},
                "note": {"type": "string"},
            },
            "required": ["goal_id", "note"],
        },
        "goals", 10,
    )
    async def log_goal_activity(goal_id: int, note: str):
        goal = await memory.get_goal(int(goal_id))
        if goal is None:
            return {"ok": False, "error": f"không thấy goal: {goal_id}"}
        entry = await memory.log_goal_activity(int(goal_id), note)
        return {"ok": True, "activity": entry}

    @spec(
        "close_goal",
        "Đóng goal (chuyển sang completed) — chỉ khi việc đã thật sự xong.",
        {
            "type": "object",
            "properties": {"goal_id": {"type": "integer"}},
            "required": ["goal_id"],
        },
        "goals", 10,
    )
    async def close_goal(goal_id: int):
        goal = await memory.close_goal(int(goal_id))
        if goal is None:
            return {"ok": False,
                    "error": f"goal {goal_id} không tồn tại hoặc đã đóng"}
        return {"ok": True, "goal": goal}
