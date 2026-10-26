"""Scheduler + goals/tracking (thiết kế mục 7) — Phase 3.

Scheduler: vòng lặp nền DUY NHẤT khi được bật đích danh
(SCHEDULER_ENABLED=1, mặc định TẮT — bài học vụ user phải xóa toàn
bộ job tự động 2026-10-22). Khi tới hạn: tính lần kế tiếp và ghi
TRƯỚC (chống bắn trùng — bài học heartbeat Mulon cũ), rồi tạo task
cho agent trong session hệ thống và ghi trajectory.

Từ 1.4 (Feed chủ động): scheduler biết thêm JOB HỆ THỐNG NỘI BỘ
(payload JSON {"kind": "<tên>", "v": 1}) — do mã hệ thống đăng
ký handler riêng, KHÔNG qua agent loop. Quy tắc CÔ LẬP TICK
(spec feed 1.4 mục 4.3): vòng tick có thể chạy chỉ để phục vụ
job nội bộ (run_due_once(include_regular=False)) — khi đó các
schedule THƯỜNG (do agent tạo, mặc định tắt theo chính sách
cứng) KHÔNG được bắn và KHÔNG bị tiêu thụ next_run.

Goals: 2 trạng thái (active/completed), activity log, tracked items
ở tầng DB. Goal không bao giờ tự đóng.
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from datetime import datetime, timezone
from typing import Awaitable, Callable, Optional

from .cron import next_run_iso
from .tools import ToolSpec
from .config import DEFAULT_TIMEZONE

logger = logging.getLogger("mulon.planning")

SYSTEM_SESSION = "agent:main:system:scheduler"
_UTC = timezone.utc  # tránh bị tham số tool tên 'timezone' che

AgentProvider = Callable[[], Awaitable[object]]
InternalHandler = Callable[[dict], Awaitable[object]]


def internal_payload(kind: str) -> str:
    """Payload chuẩn của 1 job hệ thống nội bộ."""
    return json.dumps({"kind": kind, "v": 1})


def internal_kind(payload: str) -> Optional[str]:
    """Tên job nội bộ nếu payload là marker nội bộ, else None.
    Payload thường là text tự do của user/agent — không parse
    được JSON dict có 'kind' + 'v' thì coi là lịch thường."""
    try:
        data = json.loads(payload or "")
    except Exception:
        return None
    if isinstance(data, dict) and data.get("v") == 1 \
            and isinstance(data.get("kind"), str):
        return data["kind"]
    return None


class SchedulerService:
    """Quét schedules tới hạn và giao việc cho agent."""

    def __init__(self, cfg, memory, agent_provider: AgentProvider):
        self.cfg = cfg
        self.memory = memory
        self._agent_provider = agent_provider
        self._lock = asyncio.Lock()
        self.internal_handlers: dict[str, InternalHandler] = {}

    def register_internal_handler(self, kind: str,
                                  fn: InternalHandler) -> None:
        """Đăng ký handler cho job hệ thống nội bộ (vd feed_auto).
        Handler nhận dict schedule, tự ghi vết của nó."""
        self.internal_handlers[kind] = fn

    def has_internal_handlers(self) -> bool:
        return bool(self.internal_handlers)

    async def run_due_once(self, now: Optional[datetime] = None,
                           include_regular: bool = True) -> list[str]:
        """Chạy các schedule đã tới hạn. Trả danh sách id đã bắn.

        include_regular=False = CHẾ ĐỘ CÔ LẬP (spec 1.4 mục 4.3):
        chỉ job nội bộ được bắn; schedule thường tới hạn bị GIỮ
        NGUYÊN (không advance next_run, không ghi trajectory) để
        khi scheduler thường được bật thật, chúng vẫn còn hạn.

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
                kind = internal_kind(sched["payload"])
                if kind is None and not include_regular:
                    continue  # giữ nguyên lịch thường — xem docstring
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
                    if kind is not None:
                        handler = self.internal_handlers.get(kind)
                        if handler is None:
                            logger.warning(
                                "job nội bộ %s chưa có handler — bỏ "
                                "qua lượt này", kind)
                            continue
                        await handler(sched)
                        fired.append(sched["id"])
                        continue
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
        """Vòng lặp nền. Bắn lịch thường CHỈ khi SCHEDULER_ENABLED=1;
        job nội bộ luôn được phục vụ khi vòng lặp chạy (main.py chỉ
        khởi động vòng lặp khi có handler nội bộ hoặc scheduler
        thường bật — xem quy tắc cô lập tick ở docstring module).
        """
        include_regular = bool(self.cfg.scheduler_enabled)
        logger.info("scheduler nền BẬT (tick %ss, lịch thường: %s)",
                    self.cfg.scheduler_tick_s,
                    "bật" if include_regular else "TẮT — chỉ job "
                    "hệ thống nội bộ")
        while True:
            await asyncio.sleep(self.cfg.scheduler_tick_s)
            try:
                fired = await self.run_due_once(
                    include_regular=include_regular)
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
        "thứ), múi giờ tường minh. Phải gắn với goal_id hoặc tracked_item_id "
        "nếu là việc theo dõi mục tiêu. Trả về lịch đã tạo kèm lần chạy kế tiếp. "
        "Lưu ý: Thư briefing cho goal do hệ thống nền tạo tự động, không thể đặt lịch thủ công.",
        {
            "type": "object",
            "properties": {
                "cron": {"type": "string"},
                "payload": {"type": "string"},
                "title": {"type": "string", "default": ""},
                "goal_id": {"type": "integer"},
                "tracked_item_id": {"type": "integer"},
                "timezone": {
                    "type": "string",
                    "default": DEFAULT_TIMEZONE,
                },
                "session_key": {"type": "string", "default": ""},
            },
            "required": ["cron", "payload"],
        },
        "schedule", 10,
    )
    async def schedule_task(cron: str, payload: str,
                            title: str = "",
                            goal_id: Optional[int] = None,
                            tracked_item_id: Optional[int] = None,
                            timezone: str = DEFAULT_TIMEZONE,
                            session_key: str = ""):
        # Checklist C8: Goal briefings user không đặt lịch được
        lower_payload = (payload or "").lower()
        lower_title = (title or "").lower()
        if "briefing" in lower_payload or "briefing" in lower_title or "goal_briefing" in lower_payload:
            return {
                "ok": False,
                "error": "Goal briefings do tiến trình nền của hệ thống tự động sinh và đính kèm vào mục tiêu, người dùng không thể đặt lịch thủ công (chuẩn Muse C8)."
            }
        tz_name = timezone or cfg.default_timezone
        try:
            nxt = next_run_iso(cron, datetime.now(_UTC), tz_name)
        except Exception as exc:
            return {"ok": False, "error": f"cron không hợp lệ: {exc}"}
        schedule_id = uuid.uuid4().hex[:12]
        sched = await memory.create_schedule(
            schedule_id, cron, tz_name, payload, session_key, nxt,
            title=title, goal_id=goal_id, tracked_item_id=tracked_item_id,
        )
        return {"ok": True, "schedule": sched}

    @spec(
        "list_schedules",
        "Liệt kê các lịch hẹn giờ ĐÃ TẠO QUA AGENT (kể cả đã tắt). "
        "Job hệ thống nội bộ (vd Feed chủ động) không nằm trong "
        "danh sách này và không tắt được bằng tool thường.",
        {"type": "object", "properties": {}, "required": []},
        "schedule", 10,
    )
    async def list_schedules():
        items = [s for s in await memory.list_schedules()
                 if internal_kind(s.get("payload") or "") is None]
        return {"ok": True, "schedules": items}

    @spec(
        "cancel_schedule",
        "Tắt 1 lịch hẹn giờ theo id (không xóa dữ liệu). Job hệ "
        "thống nội bộ không tắt được bằng tool này.",
        {
            "type": "object",
            "properties": {"schedule_id": {"type": "string"}},
            "required": ["schedule_id"],
        },
        "schedule", 10,
    )
    async def cancel_schedule(schedule_id: str):
        row = await memory.get_schedule(schedule_id)
        if row is not None and internal_kind(
                row.get("payload") or "") is not None:
            return {"ok": False,
                    "error": "đây là job hệ thống nội bộ — không "
                             "tắt được bằng tool thường"}
        ok = await memory.cancel_schedule(schedule_id)
        if not ok:
            return {"ok": False,
                    "error": f"không thấy schedule: {schedule_id}"}
        return {"ok": True, "schedule_id": schedule_id, "enabled": 0}

    @spec(
        "create_goal",
        "Tạo mục tiêu (goal) mới. Có thể tạo subgoal (mục tiêu con lồng 1 cấp) bằng cách truyền parent_id.",
        {
            "type": "object",
            "properties": {
                "title": {"type": "string"},
                "description": {"type": "string", "default": ""},
                "parent_id": {"type": "integer", "description": "ID của goal cha nếu là subgoal (chỉ lồng 1 cấp)"},
                "category": {"type": "string", "default": "productivity"},
                "goal_kind": {"type": "string", "default": "outcome"},
            },
            "required": ["title"],
        },
        "goals", 10,
    )
    async def create_goal(title: str, description: str = "",
                          parent_id: Optional[int] = None,
                          category: str = "productivity",
                          goal_kind: str = "outcome"):
        try:
            goal = await memory.create_goal(
                title=title, description=description,
                parent_id=parent_id, category=category, goal_kind=goal_kind
            )
            return {"ok": True, "goal": goal}
        except ValueError as err:
            return {"ok": False, "error": str(err)}

    @spec(
        "update_goal",
        "Cập nhật thông tin của goal (tiêu đề, mô tả, trạng thái tiến độ hiện tại, nhóm, hoặc gán parent_id lồng 1 cấp).",
        {
            "type": "object",
            "properties": {
                "goal_id": {"type": "integer"},
                "title": {"type": "string"},
                "description": {"type": "string"},
                "current_state": {"type": "string"},
                "category": {"type": "string"},
                "goal_kind": {"type": "string"},
                "parent_id": {"type": "integer"},
            },
            "required": ["goal_id"],
        },
        "goals", 10,
    )
    async def update_goal(goal_id: int, title: Optional[str] = None,
                          description: Optional[str] = None,
                          current_state: Optional[str] = None,
                          category: Optional[str] = None,
                          goal_kind: Optional[str] = None,
                          parent_id: Optional[int] = None):
        try:
            goal = await memory.update_goal(
                goal_id=int(goal_id), title=title, description=description,
                current_state=current_state, category=category,
                goal_kind=goal_kind, parent_id=parent_id
            )
            if goal is None:
                return {"ok": False, "error": f"Không tìm thấy goal #{goal_id}"}
            return {"ok": True, "goal": goal}
        except ValueError as err:
            return {"ok": False, "error": str(err)}

    @spec(
        "list_goals",
        "Liệt kê goals theo cây phân cấp. status rỗng = mọi trạng thái; 'active' hoặc "
        "'completed' để lọc. Kèm subgoals, tracked items và tiến triển thật của từng goal.",
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
        tree = await memory.get_goal_tree(status=status or None)
        # Giữ open_items cho tương thích ngược
        for goal in tree:
            goal["open_items"] = await memory.list_tracked_items(
                goal_id=goal["id"], status="open"
            )
        return {"ok": True, "goals": tree}

    @spec(
        "get_goal_detail",
        "Xem chi tiết đầy đủ của 1 goal kèm subgoals, tiến triển thật, cam kết, nhật ký và thư briefings.",
        {
            "type": "object",
            "properties": {"goal_id": {"type": "integer"}},
            "required": ["goal_id"],
        },
        "goals", 10,
    )
    async def get_goal_detail(goal_id: int):
        detail = await memory.get_goal_detail(int(goal_id))
        if detail is None:
            return {"ok": False, "error": f"Không tìm thấy goal #{goal_id}"}
        return {"ok": True, "goal": detail}

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
        "Đóng goal hoặc subgoal (chuyển sang completed) — chỉ khi việc đã thật sự xong. Đóng subgoal sẽ tự động cập nhật tiến độ thật của goal cha.",
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

    @spec(
        "generate_goal_briefing",
        "Tiến trình nền tự nghiên cứu và tạo thư briefing (Letter) đính kèm vào goal. Thư gồm: Tiến triển thật, Việc tiếp theo, và Điểm nghẽn.",
        {
            "type": "object",
            "properties": {"goal_id": {"type": "integer"}},
            "required": ["goal_id"],
        },
        "goals", 10,
    )
    async def generate_goal_briefing(goal_id: int):
        from .goal_briefing import GoalBriefingService
        svc = GoalBriefingService(cfg, memory, gateway=None)
        try:
            briefing = await svc.generate_briefing(int(goal_id))
            return {"ok": True, "briefing": briefing}
        except ValueError as err:
            return {"ok": False, "error": str(err)}

    @spec(
        "list_goal_briefings",
        "Liệt kê các thư briefing đã phát cho goal.",
        {
            "type": "object",
            "properties": {
                "goal_id": {"type": "integer"},
                "limit": {"type": "integer", "default": 10},
            },
            "required": ["goal_id"],
        },
        "goals", 10,
    )
    async def list_goal_briefings(goal_id: int, limit: int = 10):
        items = await memory.list_goal_briefings(int(goal_id), limit=limit)
        return {"ok": True, "briefings": items}


async def ensure_seed_goals(memory) -> list[dict]:
    """Khởi tạo 5 mục tiêu nền tảng từ ngữ cảnh thật của người dùng nếu DB đang trống."""
    existing = await memory.list_goals(status="active")
    if existing:
        return existing
    seeds = [
        (
            "MuLon AI & Mini App",
            "Phát triển và hoàn thiện trợ lý AI Mulon, Mini App và đồng bộ đầy đủ trải nghiệm với Muse AI.",
            "career",
            "outcome",
            "Đang hoàn thiện tính năng Feed, Thẻ ý tưởng và kho ảnh visual Library",
        ),
        (
            "Chiến dịch Affiliate Marketing (Shopee & Lazada)",
            "Khai thác API Accesstrade và đăng ký tiếp thị liên kết đa sàn, tạo link và tối ưu hoa hồng.",
            "money",
            "outcome",
            "Đã kết nối API Accesstrade, sẵn sàng tạo link affiliate tự động",
        ),
        (
            "Sản xuất nội dung đa kênh (TikTok, Threads, Instagram)",
            "Xây dựng kịch bản video ngắn cho @vesomlamgi, bài viết Threads cho @supbomacket và Reels/Page Mmmnhat.",
            "career",
            "behavior",
            "Lên lịch và kịch bản thử nghiệm theo định hướng viral",
        ),
        (
            "Sáng tạo hình ảnh & Avatar AI (Agnes AI)",
            "Thử nghiệm tạo ảnh, thiết kế concept nhân vật, hình đại diện và poster bán hàng bằng Agnes AI.",
            "interests",
            "learning",
            "Đã cất API key vào Vault, sẵn sàng gọi sinh ảnh và đồng bộ vào Library",
        ),
        (
            "Hệ sinh thái Multi-agent Telegram",
            "Nghiên cứu kiến trúc đa bot chạy song song, phân công vai trò chuyên biệt cho từng bot phụ.",
            "productivity",
            "exploratory",
            "Đang thử nghiệm kiến trúc Subagent và kết nối BotFather",
        ),
    ]
    created = []
    for title, desc, cat, kind, note in seeds:
        g = await memory.create_goal(title, desc, current_state=note, category=cat, goal_kind=kind)
        if note:
            await memory.log_goal_activity(g["id"], note)
        created.append(g)
    return created
