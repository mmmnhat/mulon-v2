"""Ideas (thiết kế mục 16.5): thẻ ý tưởng có hạn sống.

- Sinh từ goals + khoảng trống ký ức bằng model rẻ (lệnh /ideas —
  không có tiến trình nền tự sinh ở bản này; hook để sẵn).
- Mỗi thẻ: tiêu đề, mô tả, nguồn, hết hạn mặc định 14 ngày
  (IDEA_TTL_DAYS). Hết hạn -> trạng thái expired và agent trả lời
  được lý do thẻ biến mất.
- "Làm luôn" (/idea_do hoặc reply vào thẻ) -> thẻ thành goal +
  task thật; /idea_bo -> dismissed. User bỏ qua là thao tác của
  user — hệ thống không tự dismissed thay.
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Optional

logger = logging.getLogger("mulon.ideas")


def _expiry(ttl_days: int) -> str:
    return (datetime.now(timezone.utc)
            + timedelta(days=ttl_days)).isoformat(timespec="seconds")


def _parse_ideas(text: str) -> list[dict]:
    """Parse JSON phòng thủ từ output model rẻ: chấp nhận cả mảng
    trần lẫn object {"ideas": [...]} lẫn JSON nằm giữa văn xuôi."""
    candidates = [text]
    m = re.search(r"(\{.*\}|\[.*\])", text or "", re.DOTALL)
    if m:
        candidates.append(m.group(1))
    for raw in candidates:
        try:
            data = json.loads(raw)
        except Exception:
            continue
        items = data.get("ideas") if isinstance(data, dict) else data
        if not isinstance(items, list):
            continue
        out = []
        for it in items:
            if not isinstance(it, dict):
                continue
            title = str(it.get("title") or "").strip()
            if title:
                out.append({
                    "title": title[:200],
                    "description": str(it.get("description") or "")[:1000],
                })
        if out:
            return out
    return []


class IdeaEngine:
    def __init__(self, cfg, memory, gateway):
        self.cfg = cfg
        self.memory = memory
        self.gateway = gateway

    async def cleanup_expired(self) -> list[dict]:
        expired = await self.memory.expire_idea_cards()
        if expired:
            await self.memory.log_trajectory(
                "", "ideas_expired",
                {"ids": [c["id"] for c in expired],
                 "reason": "hết hạn (quá IDEA_TTL_DAYS ngày)"},
            )
        return expired

    async def _material(self) -> str:
        goals = await self.memory.list_goals(status="active")
        lines = []
        for g in goals[:6]:
            acts = await self.memory.list_goal_activity(g["id"], limit=2)
            recent = "; ".join(a["note"] for a in acts) or "chưa có"
            lines.append(
                f"- Goal #{g['id']}: {g['title']} — {g['description']}"
                f" | tiến độ gần nhất: {recent}")
        tracked = await self.memory.list_tracked_items(status="open")
        for t in tracked[:5]:
            lines.append(f"- Cam kết đang mở: {t['title']}")
        facts = await self.memory.active_facts(limit=12)
        for f in facts[:6]:
            lines.append(f"- Fact: {f['fact']}")
        return "\n".join(lines) or "(chưa có dữ liệu nền)"

    async def generate(self) -> list[dict]:
        """Dọn thẻ hết hạn rồi sinh 3-5 thẻ mới, lưu DB (status open)."""
        await self.cleanup_expired()
        material = await self._material()
        comp = await self.gateway.complete(
            [
                {"role": "system", "content": (
                    "Bạn đề xuất các việc cụ thể agent có thể làm cho "
                    "user, suy từ goals và ký ức được cấp. Trả JSON "
                    "thuần dạng {\"ideas\": [{\"title\": \"...\", "
                    "\"description\": \"...\"}]} với 3-5 ý tưởng, mỗi "
                    "ý tưởng làm được trong một phiên làm việc, không "
                    "lặp việc đã có sẵn trong dữ liệu.")},
                {"role": "user", "content": material},
            ],
            model=self.cfg.model_cheap,
            purpose="ideas",
            temperature=0.7,
        )
        cards = []
        for idea in _parse_ideas(comp.text or ""):
            card = await self.memory.add_idea_card(
                idea["title"], idea["description"],
                source="goals+memory",
                expires_at=_expiry(self.cfg.idea_ttl_days),
            )
            cards.append(card)
        if cards:
            await self.memory.log_trajectory(
                "", "ideas_generated",
                {"ids": [c["id"] for c in cards]})
        return cards

    async def do_card(self, card_id: int,
                      session_key: str = "") -> dict:
        """'Làm luôn': thẻ -> goal + task thật, thẻ -> done."""
        card = await self.memory.get_idea_card(card_id)
        if card is None:
            return {"ok": False, "error": f"không thấy thẻ #{card_id}"}
        if card["status"] == "expired":
            return {"ok": False,
                    "error": f"thẻ #{card_id} đã hết hạn nên biến mất"}
        if card["status"] != "open":
            return {"ok": False,
                    "error": f"thẻ #{card_id} đang ở trạng thái "
                             f"{card['status']}"}
        goal = await self.memory.create_goal(
            card["title"], card["description"])
        task_id = f"idea-{card_id}-{uuid.uuid4().hex[:8]}"
        steps = [card["description"] or card["title"],
                 "Kiểm chứng kết quả trước khi báo xong"]
        await self.memory.create_task(
            task_id, session_key, card["title"], steps)
        await self.memory.log_goal_activity(
            goal["id"], f"Tạo từ thẻ ý tưởng #{card_id}")
        await self.memory.set_idea_card_status(
            card_id, "done", goal_id=goal["id"])
        await self.memory.log_trajectory(
            session_key, "idea_done",
            {"card_id": card_id, "goal_id": goal["id"],
             "task_id": task_id},
        )
        return {"ok": True, "card_id": card_id,
                "goal_id": goal["id"], "task_id": task_id}

    async def dismiss(self, card_id: int) -> dict:
        card = await self.memory.get_idea_card(card_id)
        if card is None:
            return {"ok": False, "error": f"không thấy thẻ #{card_id}"}
        ok = await self.memory.set_idea_card_status(card_id, "dismissed")
        if ok:
            await self.memory.log_trajectory(
                "", "idea_dismissed", {"card_id": card_id})
        return {"ok": ok, "card_id": card_id}


def format_idea_card(card: dict) -> str:
    """Text 1 thẻ để đăng trong topic Ideas. Dòng đầu mang #id để
    reply 'làm luôn' map về đúng thẻ."""
    expires = str(card.get("expires_at") or "")[:10]
    lines = [f"💡 Thẻ ý tưởng #{card['id']}: {card['title']}"]
    if card.get("description"):
        lines.append(card["description"])
    if expires:
        lines.append(f"(hết hạn {expires} — trả lời 'làm luôn' vào thẻ "
                     f"này hoặc /idea_do {card['id']}; bỏ qua: "
                     f"/idea_bo {card['id']})")
    return "\n".join(lines)


def parse_do_reply(text: str, replied_text: Optional[str]) -> Optional[int]:
    """Reply 'làm luôn' vào 1 thẻ -> id thẻ từ text thẻ được trích."""
    folded = (text or "").strip().lower()
    if not (folded.startswith("làm luôn") or folded.startswith("lam luon")
            or folded.startswith("làm đi") or folded.startswith("lam di")):
        return None
    m = re.search(r"#(\d+)", replied_text or "")
    return int(m.group(1)) if m else None
