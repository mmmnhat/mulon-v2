"""Proactivity engine — heartbeat gom việc (thiết kế mục 7) — Phase 4.

Pattern đã chốt (tham chiếu heartbeat OpenClaw, giữ khác biệt theo
lệnh user: opt-in đích danh, mặc định TẮT):

- Một lượt quét đọc checklist `dossier/HEARTBEAT.md`, gom mọi mục
  vào 1 lượt chạy bằng MODEL RẺ với ngữ cảnh NHẸ (lightContext:
  chỉ fact gần + cam kết đang mở + lịch đang bật — không nạp cả
  dossier, không dùng history đầy đủ).
- Chỉ chạy trong khung giờ hoạt động `PROACTIVITY_ACTIVE_HOURS`
  (mặc định 07:00-23:00 theo DEFAULT_TIMEZONE). Ngoài giờ: bỏ qua.
- Không có gì đáng nói -> ghi trajectory kind='heartbeat' với
  HEARTBEAT_OK và IM LẶNG. Im lặng là trạng thái đúng mặc định.
- Có việc đáng nói -> tạo "đề xuất" trong bảng proactive_notes
  (status='pending'). Phase 4 CHƯA gửi gì cho user cả — bề mặt
  Phase 6 mới trình các đề xuất này.
- `dossier/PROACTIVE_PREFERENCES.md` dạy hệ thống nên/cấm chủ động
  về chủ đề nào: mục nào user liệt kê ở phần chặn mà khớp nội dung
  đề xuất thì đề xuất bị dập (suppressed) và ghi trajectory.

Chạy tay:  python -m mulon.proactivity --once
Trong bot: main.py bật vòng lặp nền khi PROACTIVITY_ENABLED=1.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import re
import sys
from datetime import datetime, time as dtime
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo

from .memory import fold_vi

logger = logging.getLogger("mulon.proactivity")

HEARTBEAT_OK = "HEARTBEAT_OK"

_CHECK_SYSTEM = (
    "Bạn là lượt quét chủ động (heartbeat) của một trợ lý cá nhân. "
    "Dưới đây là CHECKLIST cần kiểm tra và NGỮ CẢNH NHẸ (fact gần "
    "đây, cam kết đang mở, lịch đang bật). Chỉ nêu những việc THẬT "
    "SỰ đáng để ý: sắp tới hạn, bị kẹt/lỗi, thay đổi quan trọng, cơ "
    "hội rõ ràng. Thà im lặng còn hơn làm phiền: không có gì đáng "
    "nói thì trả mảng rỗng. Chỉ trả JSON đúng dạng: {\"notes\": "
    "[{\"content\": \"việc đáng nói, gọn 1-2 câu\", \"reason\": "
    "\"vì sao đáng nói\", \"topic\": \"chủ đề ngắn\"}]}. Không thêm "
    "chữ nào ngoài JSON."
)


# ---------------------------------------------------------------------------
# Hàm thuần (test không cần model/DB)
# ---------------------------------------------------------------------------

def parse_active_hours(spec: str) -> tuple[dtime, dtime]:
    """'07:00-23:00' -> (time(7,0), time(23,0)). Sai dạng -> mặc định."""
    try:
        start_s, end_s = str(spec).split("-", 1)

        def _p(part: str) -> dtime:
            h, m = part.strip().split(":", 1)
            return dtime(hour=int(h) % 24, minute=int(m) % 60)

        return _p(start_s), _p(end_s)
    except Exception:
        return dtime(7, 0), dtime(23, 0)


def in_active_hours(now_local: datetime, spec: str) -> bool:
    """now_local phải đã ở múi giờ địa phương. Hỗ trợ khung qua đêm
    (vd 22:00-06:00)."""
    start, end = parse_active_hours(spec)
    t = now_local.time()
    if start <= end:
        return start <= t < end
    return t >= start or t < end


def _strip_comments(text: str) -> str:
    return re.sub(r"<!--[\s\S]*?-->", " ", text or "")


def parse_checklist(text: str) -> list[str]:
    """Trích các mục việc từ HEARTBEAT.md.

    Nhận cả dòng '- [ ] ...', '- [x] ...' (đã tick vẫn tính là mục
    cần quét lại định kỳ) và bullet '- ...' thường. Bỏ comment HTML,
    tiêu đề và dòng trống.
    """
    items: list[str] = []
    for line in _strip_comments(text).splitlines():
        s = line.strip()
        m = re.match(r"^[-*]\s+(?:\[[ xX]\]\s*)?(.+)$", s)
        if m:
            item = m.group(1).strip()
            if item:
                items.append(item)
    return items


def parse_blocked_topics(text: str) -> list[str]:
    """Trích chủ đề bị chặn từ PROACTIVE_PREFERENCES.md.

    Quy ước của file mẫu: bullet nằm dưới tiêu đề có chữ 'không'
    (vd '## Không chủ động về') là chủ đề bị chặn. Bullet ở các
    phần khác (khung giờ, ghi chú...) không tính.
    """
    blocked: list[str] = []
    in_block_section = False
    for line in _strip_comments(text).splitlines():
        s = line.strip()
        if s.startswith("#"):
            heading = fold_vi(s.lstrip("#").strip().lower())
            in_block_section = "khong" in heading
            continue
        if in_block_section:
            m = re.match(r"^[-*]\s+(?:\[[ xX]\]\s*)?(.+)$", s)
            if m:
                topic = m.group(1).strip()
                if topic:
                    blocked.append(topic)
    return blocked


def topic_blocked(note: dict, blocked_topics: list[str]) -> Optional[str]:
    """Trả chủ đề chặn khớp đầu tiên, không khớp -> None.

    Khớp theo dạng gấp dấu trên cả topic/content/reason của đề
    xuất: chủ đề chặn là chuỗi con của nội dung, hoặc ngược lại.
    """
    hay = fold_vi(
        f"{note.get('topic', '')} {note.get('content', '')} "
        f"{note.get('reason', '')}".lower()
    )
    for topic in blocked_topics:
        needle = fold_vi(topic.lower()).strip()
        if needle and needle in hay:
            return topic
    return None


def parse_notes_json(text: str) -> list[dict]:
    """Bóc JSON notes từ câu trả lời model — parse phòng thủ."""
    if not text:
        return []
    m = re.search(r"\{[\s\S]*\}", text)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except Exception:
        return []
    raw = data.get("notes") if isinstance(data, dict) else None
    notes: list[dict] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        content = str(item.get("content") or "").strip()
        if not content:
            continue
        notes.append({
            "content": content,
            "reason": str(item.get("reason") or "").strip(),
            "topic": str(item.get("topic") or "").strip(),
        })
    return notes


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

class ProactivityEngine:
    """Một lượt heartbeat: checklist + ngữ cảnh nhẹ -> notes xếp hàng."""

    def __init__(self, cfg, memory, gateway):
        self.cfg = cfg
        self.memory = memory
        self.gateway = gateway

    # ---------- đọc file dossier (tươi, không qua snapshot) ----------
    def _read_dossier_file(self, name: str) -> str:
        path = Path(self.cfg.dossier_dir) / name
        try:
            return path.read_text(encoding="utf-8")
        except Exception:
            return ""

    async def _light_context(self) -> str:
        """Ngữ cảnh NHẸ cho heartbeat: fact gần + cam kết mở + lịch.

        Không nạp dossier đầy đủ, không lịch sử chat — đây là kỷ
        luật lightContext để lượt quét rẻ và nhanh.
        """
        parts: list[str] = []
        try:
            facts = await self.memory.active_facts(limit=20)
            if facts:
                lines = [f"- [{f['subject']}] {f['fact']}" if f["subject"]
                         else f"- {f['fact']}" for f in facts]
                parts.append("FACT GẦN ĐÂY:\n" + "\n".join(lines))
        except Exception as exc:
            logger.warning("heartbeat đọc facts lỗi: %s", exc)
        try:
            items = await self.memory.list_tracked_items(status="open")
            if items:
                lines = [
                    f"- {it['title']}"
                    + (f" (hạn: {it['due_at']})" if it.get("due_at") else "")
                    + (f" — {it['detail']}" if it.get("detail") else "")
                    for it in items[:20]
                ]
                parts.append("CAM KẾT ĐANG MỞ:\n" + "\n".join(lines))
        except Exception as exc:
            logger.warning("heartbeat đọc tracked items lỗi: %s", exc)
        try:
            schedules = await self.memory.list_schedules(enabled_only=True)
            if schedules:
                lines = [
                    f"- [{s['id']}] {s['cron']} ({s['timezone']}): "
                    f"{s['payload']}"[:200]
                    for s in schedules[:10]
                ]
                parts.append("LỊCH ĐANG BẬT:\n" + "\n".join(lines))
        except Exception as exc:
            logger.warning("heartbeat đọc schedules lỗi: %s", exc)
        return "\n\n".join(parts) if parts else "(ngữ cảnh trống)"

    # ---------- điểm vào ----------
    async def run_once(self, now: Optional[datetime] = None) -> dict:
        """Chạy 1 lượt heartbeat. Trả stats; KHÔNG BAO GIỜ gửi tin.

        stats: {skipped: str|None, items: int, candidates: int,
                notes: int, suppressed: int, heartbeat_ok: bool}
        """
        stats = {"skipped": None, "items": 0, "candidates": 0,
                 "notes": 0, "suppressed": 0, "heartbeat_ok": False}
        tz = ZoneInfo(self.cfg.default_timezone)
        now_local = (now or datetime.now(tz)).astimezone(tz)

        if not in_active_hours(now_local, self.cfg.proactivity_active_hours):
            stats["skipped"] = "out_of_hours"
            await self.memory.log_trajectory(
                "", "heartbeat",
                {"result": "skipped_out_of_hours",
                 "at": now_local.isoformat(timespec="seconds")})
            return stats

        checklist = parse_checklist(self._read_dossier_file("HEARTBEAT.md"))
        stats["items"] = len(checklist)
        if not checklist:
            stats["heartbeat_ok"] = True
            await self.memory.log_trajectory(
                "", "heartbeat", {"result": HEARTBEAT_OK,
                                  "reason": "checklist_empty"})
            return stats

        context = await self._light_context()
        checklist_text = "\n".join(f"- {item}" for item in checklist)
        try:
            comp = await self.gateway.complete(
                [
                    {"role": "system", "content": _CHECK_SYSTEM},
                    {"role": "user",
                     "content": f"CHECKLIST:\n{checklist_text}\n\n"
                                f"NGỮ CẢNH NHẸ:\n{context}"},
                ],
                model=self.cfg.model_cheap,
                temperature=0.2,
                purpose="heartbeat",
            )
            candidates = parse_notes_json(comp.text)
        except Exception as exc:
            # Model sập thì lượt này coi như không có gì đáng nói —
            # im lặng vẫn đúng hơn là báo động giả.
            logger.warning("heartbeat gọi model lỗi (im lặng): %s", exc)
            candidates = []
        stats["candidates"] = len(candidates)

        blocked = parse_blocked_topics(
            self._read_dossier_file("PROACTIVE_PREFERENCES.md"))
        for note in candidates:
            hit = topic_blocked(note, blocked)
            if hit:
                stats["suppressed"] += 1
                await self.memory.log_trajectory(
                    "", "heartbeat_note_suppressed",
                    {"topic": note.get("topic", ""), "blocked_by": hit})
                continue
            await self.memory.add_proactive_note(
                note["content"], note.get("reason", ""),
                note.get("topic", ""))
            stats["notes"] += 1

        if stats["notes"] == 0:
            stats["heartbeat_ok"] = True
            await self.memory.log_trajectory(
                "", "heartbeat",
                {"result": HEARTBEAT_OK,
                 "candidates": stats["candidates"],
                 "suppressed": stats["suppressed"]})
        else:
            await self.memory.log_trajectory(
                "", "heartbeat",
                {"result": "notes_queued", "notes": stats["notes"],
                 "suppressed": stats["suppressed"]})
        return stats


# ---------------------------------------------------------------------------
# CLI: python -m mulon.proactivity --once
# ---------------------------------------------------------------------------

async def _amain(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="mulon.proactivity")
    parser.add_argument("--once", action="store_true",
                        help="chạy 1 lượt heartbeat rồi thoát")
    parser.add_argument("--env-file", default=None)
    args = parser.parse_args(argv)
    if not args.once:
        parser.print_help()
        return 2
    # Import trễ để --help không phải dựng hệ thống.
    from .config import Config
    from .embeddings import build_embedder
    from .gateway import ModelGateway
    from .memory import Memory

    cfg = Config.load(env_file=args.env_file)
    cfg.db_path.parent.mkdir(parents=True, exist_ok=True)
    memory = await Memory.open(cfg.db_path)
    embedder = build_embedder(cfg)
    if embedder is not None:
        memory.embed_timeout_s = cfg.embed_timeout_s
        await memory.set_embedder(embedder)
    try:
        engine = ProactivityEngine(cfg, memory, ModelGateway(cfg, memory))
        stats = await engine.run_once()
        print(json.dumps(stats, ensure_ascii=False))
        return 0
    finally:
        await memory.close()


def main(argv: list[str] | None = None) -> int:
    return asyncio.run(_amain(list(argv if argv is not None else sys.argv[1:])))


if __name__ == "__main__":
    raise SystemExit(main())
