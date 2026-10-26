"""Goal Briefings — tiến trình nền viết thư briefing gắn vào goal (chuẩn Muse C8 + D2).

Theo spec T-10.4 + checklist C8 / D2:
- Thư briefing dạng Letter đính kèm vào goal:
  1. Tiến triển (Progress summary)
  2. Việc tiếp theo (Next steps)
  3. Điểm nghẽn & Rủi ro (Bottlenecks)
- Người dùng KHÔNG đặt lịch được bằng schedule (chuẩn C8).
- Gắn đúng vào goal_id, lưu trong goal_briefings, ghi activity log.
"""
from __future__ import annotations

import logging
from typing import Optional

from .datafiles import load_prompt
from .memory import Memory, now_iso

logger = logging.getLogger("mulon.goal_briefing")


class GoalBriefingService:
    """Tiến trình nền tự nghiên cứu cho từng goal, viết thư briefing đính vào goal."""

    def __init__(self, cfg, memory: Memory, gateway=None):
        self.cfg = cfg
        self.memory = memory
        self.gateway = gateway
        self.prompt = load_prompt("goal_briefing_system")

    async def generate_briefing(self, goal_id: int) -> dict:
        """Tạo thư briefing mới cho goal_id."""
        goal = await self.memory.get_goal(goal_id)
        if goal is None:
            raise ValueError(f"Không tìm thấy goal #{goal_id}")

        subgoals = await self.memory.list_subgoals(goal_id)
        tracked_items = await self.memory.list_tracked_items(goal_id=goal_id)
        activities = await self.memory.list_goal_activity(goal_id, limit=10)
        progress = self.memory.calculate_goal_progress(goal, subgoals, tracked_items)

        # 1. Tổng hợp tiến triển thật (không bịa phần trăm)
        prog_parts = []
        if progress["total_subgoals"] > 0:
            prog_parts.append(
                f"Đã hoàn thành {progress['completed_subgoals']}/{progress['total_subgoals']} mục tiêu con ({progress['progress_pct']}%)"
            )
        if progress["total_tracked_items"] > 0:
            prog_parts.append(
                f"Đã giải quyết {progress['completed_tracked_items']}/{progress['total_tracked_items']} cam kết"
            )
        curr = goal.get("current_state", "").strip()
        if curr:
            prog_parts.append(f"Ghi nhận gần nhất: {curr}")
        if not prog_parts:
            prog_parts.append("Mục tiêu đang trong giai đoạn khởi động, chưa phát sinh mục con.")
        progress_summary = ". ".join(prog_parts) + "."

        # 2. Tổng hợp việc tiếp theo (Next steps)
        next_parts = []
        open_subgoals = [s for s in subgoals if s.get("status") == "active"]
        if open_subgoals:
            sub_titles = [f"'{s['title']}' (#{s['id']})" for s in open_subgoals]
            next_parts.append(f"Tập trung hoàn thành các mục tiêu con đang chạy: {', '.join(sub_titles)}")
        open_items = [t for t in tracked_items if t.get("status") == "open"]
        if open_items:
            item_titles = [f"'{t['title']}'" for t in open_items[:3]]
            next_parts.append(f"Xử lý các cam kết đang mở: {', '.join(item_titles)}")
        if not open_subgoals and not open_items:
            if progress["total_subgoals"] > 0 and progress["completed_subgoals"] == progress["total_subgoals"]:
                next_parts.append("Tất cả mục tiêu con đã hoàn tất. Có thể tiến hành nghiệm thu và đóng mục tiêu chính.")
            else:
                next_parts.append("Xác định thêm các mục tiêu con cụ thể và mốc thời gian hoàn thành.")
        next_steps = ". ".join(next_parts) + "."

        # 3. Tổng hợp điểm nghẽn & rủi ro (Bottlenecks)
        bn_parts = []
        if open_subgoals and len(open_subgoals) == len(subgoals) and progress["total_subgoals"] > 1:
            bn_parts.append("Chưa có mục tiêu con nào được hoàn thành, tiến độ có dấu hiệu dàn trải")
        overdue_items = [t for t in open_items if t.get("due_at")]
        if overdue_items:
            bn_parts.append(f"Có {len(overdue_items)} cam kết có hạn chót cần bám sát")
        if not bn_parts:
            bn_parts.append("Hiện chưa ghi nhận điểm nghẽn lớn nào")
        bottlenecks = ". ".join(bn_parts) + "."

        # 4. Thư briefing dạng Letter chuẩn Muse
        title = f"Briefing: {goal['title']}"
        letter_body = (
            f"Chào ní,\n\n"
            f"Dưới đây là thư briefing cập nhật cho mục tiêu: **{goal['title']}**\n\n"
            f"### 1. Tiến triển\n{progress_summary}\n\n"
            f"### 2. Việc tiếp theo\n{next_steps}\n\n"
            f"### 3. Điểm nghẽn & Rủi ro\n{bottlenecks}\n\n"
            f"---\n"
            f"*Thư briefing do hệ thống nền tạo tự động.*"
        )

        # Lưu vào database
        briefing = await self.memory.create_goal_briefing(
            goal_id=goal_id,
            title=title,
            progress_summary=progress_summary,
            next_steps=next_steps,
            bottlenecks=bottlenecks,
            letter_body=letter_body,
        )

        # Ghi activity log
        await self.memory.log_goal_activity(
            goal_id,
            f"Đã phát thư briefing #{briefing['id']}",
            update_state=False,
        )

        return briefing

    async def run_periodic_briefings(self) -> list[dict]:
        """Tiến trình nền quét các goal đang chạy và tạo briefing."""
        roots = await self.memory.get_goal_tree(status="active")
        generated = []
        for g in roots:
            try:
                b = await self.generate_briefing(g["id"])
                generated.append(b)
            except Exception as exc:
                logger.warning("Không tạo được briefing cho goal #%s: %s", g.get("id"), exc)
        return generated
