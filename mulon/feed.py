"""Feed (thiết kế mục 16.4): bài do agent TỰ VIẾT từ tư liệu nội bộ.

- Brief nằm trong dossier/FEED.md (user sửa bằng /feedbrief hoặc sửa
  tay); writer đọc brief + bản tóm tắt taste, KHÔNG đọc transcript
  thô, KHÔNG lấy tin từ nguồn ngoài (tuyệt đối không aggregator).
- Nguồn bài: goals đang chạy, tracked item sắp tới, bài học mới,
  fact đáng nhớ — toàn bộ đã có sẵn trong DB của chính user.
- Đăng bằng /feed_now (hoặc hook scheduler sau này — mặc định không
  tự chạy). Reaction trên bài được ghi thành tín hiệu taste
  (feed_signals) và taste summary trong FEED.md được cập nhật.
"""

from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("mulon.feed")

BRIEF_BEGIN = "<!-- BRIEF:BEGIN -->"
BRIEF_END = "<!-- BRIEF:END -->"
TASTE_BEGIN = "<!-- TASTE:BEGIN -->"
TASTE_END = "<!-- TASTE:END -->"

DEFAULT_BRIEF = (
    "Mỗi bài Feed: một đoạn ngắn về điều đáng chú ý nhất trong việc "
    "của user hôm nay, kết bằng một việc nhỏ làm được ngay."
)

_FEED_TEMPLATE = """# FEED — brief cho bài Feed

<!-- BRIEF:BEGIN -->
{brief}
<!-- BRIEF:END -->

## Taste (tự động — đừng sửa tay)

<!-- TASTE:BEGIN -->
Chưa có tín hiệu taste nào.
<!-- TASTE:END -->
"""

_POSITIVE = {"👍", "❤️", "🔥", "😍", "🎉"}
_NEGATIVE = {"👎", "💩", "😡", "🖕"}


def _section(text: str, begin: str, end: str) -> str:
    m = re.search(
        re.escape(begin) + r"(.*?)" + re.escape(end), text, re.DOTALL)
    return m.group(1).strip() if m else ""


def _replace_section(text: str, begin: str, end: str, new: str) -> str:
    pattern = re.compile(
        re.escape(begin) + r".*?" + re.escape(end), re.DOTALL)
    block = f"{begin}\n{new.strip()}\n{end}"
    if pattern.search(text):
        return pattern.sub(lambda _: block, text, count=1)
    return text.rstrip() + "\n\n" + block + "\n"


def taste_summary(counts: list[dict], total_posts: int = 0) -> str:
    """Bản tóm tắt gu từ tín hiệu reaction — tất định, không qua LLM,
    writer đọc bản này chứ không đọc transcript thô (mục 16.4)."""
    if not counts:
        return "Chưa có tín hiệu taste nào."
    pos = sum(c["n"] for c in counts if c["reaction"] in _POSITIVE)
    neg = sum(c["n"] for c in counts if c["reaction"] in _NEGATIVE)
    total = sum(c["n"] for c in counts)
    detail = ", ".join(f"{c['reaction']} ×{c['n']}" for c in counts)
    lines = [
        f"Tín hiệu taste đã ghi: {detail} (tổng {total}"
        + (f" trên {total_posts} bài" if total_posts else "") + ").",
        f"Tích cực {pos} · tiêu cực {neg}.",
    ]
    if pos > neg:
        lines.append(
            "Writer: tiếp tục ưu tiên dạng bài/nội dung được reaction "
            "tích cực; né dạng từng bị reaction tiêu cực.")
    elif neg > pos:
        lines.append(
            "Writer: user đang không hưởng ứng dạng bài gần đây — đổi "
            "góc tiếp cận, ngắn hơn, sát việc đang chạy hơn.")
    else:
        lines.append("Writer: chưa đủ tín hiệu để kết luận gu.")
    lines.append(
        "Cập nhật: "
        + datetime.now(timezone.utc).isoformat(timespec="seconds"))
    return "\n".join(lines)


class FeedEngine:
    def __init__(self, cfg, memory, gateway):
        self.cfg = cfg
        self.memory = memory
        self.gateway = gateway

    @property
    def feed_path(self) -> Path:
        return Path(self.cfg.dossier_dir) / "FEED.md"

    # ---------- brief & taste (file FEED.md) ----------
    def _read_file(self) -> str:
        path = self.feed_path
        if path.exists():
            return path.read_text(encoding="utf-8")
        return _FEED_TEMPLATE.format(brief=DEFAULT_BRIEF)

    def _write_file(self, text: str) -> None:
        self.feed_path.parent.mkdir(parents=True, exist_ok=True)
        self.feed_path.write_text(text, encoding="utf-8")

    def read_brief(self) -> str:
        return _section(self._read_file(), BRIEF_BEGIN, BRIEF_END) \
            or DEFAULT_BRIEF

    def read_taste(self) -> str:
        return _section(self._read_file(), TASTE_BEGIN, TASTE_END)

    def set_brief(self, brief: str) -> None:
        """Sửa brief bằng lời thường (/feedbrief). Taste giữ nguyên."""
        text = self._read_file()
        self._write_file(
            _replace_section(text, BRIEF_BEGIN, BRIEF_END, brief))

    async def update_taste(self) -> str:
        counts = await self.memory.feed_signal_counts()
        cur = await self.memory.db.execute(
            "SELECT COUNT(*) AS n FROM feed_posts")
        posts = int((await cur.fetchone())["n"])
        summary = taste_summary(counts, posts)
        text = self._read_file()
        self._write_file(
            _replace_section(text, TASTE_BEGIN, TASTE_END, summary))
        return summary

    # ---------- tư liệu nội bộ ----------
    async def collect_material(self) -> dict:
        goals = await self.memory.list_goals(status="active")
        goal_lines = []
        for g in goals[:5]:
            acts = await self.memory.list_goal_activity(g["id"], limit=1)
            last = acts[0]["note"] if acts else "(chưa có tiến độ)"
            goal_lines.append(f"- Goal #{g['id']} {g['title']}: {last}")
        tracked = await self.memory.list_tracked_items(status="open")
        tracked.sort(key=lambda t: t.get("due_at") or "9999")
        tracked_lines = [
            f"- {t['title']}"
            + (f" (hạn {t['due_at']})" if t.get("due_at") else "")
            for t in tracked[:5]
        ]
        facts = await self.memory.active_facts(limit=100)
        lessons = [f for f in facts
                   if str(f.get("subject") or "").startswith("lesson:")]
        notable = [
            f for f in facts
            if not str(f.get("subject") or "").startswith("lesson:")
        ]
        return {
            "goals": goal_lines,
            "tracked": tracked_lines,
            "lessons": [f"- {f['fact']}" for f in lessons[:3]],
            "facts": [f"- {f['fact']}" for f in notable[:5]],
        }

    # ---------- sinh + đăng ----------
    async def generate(self) -> str:
        """Một bài Feed từ brief + taste + tư liệu nội bộ (model rẻ)."""
        material = await self.collect_material()
        blocks = [f"## Brief\n{self.read_brief()}"]
        taste = self.read_taste()
        if taste:
            blocks.append(f"## Taste của user\n{taste}")
        for title, key in (("Goals đang chạy", "goals"),
                           ("Cam kết/hạn sắp tới", "tracked"),
                           ("Bài học mới", "lessons"),
                           ("Fact đáng nhớ", "facts")):
            if material[key]:
                blocks.append(f"## {title}\n" + "\n".join(material[key]))
        comp = await self.gateway.complete(
            [
                {"role": "system", "content": (
                    "Bạn là writer của Feed cá nhân. Viết ĐÚNG một bài "
                    "Feed ngắn bằng tiếng Việt theo brief. CHỈ dùng tư "
                    "liệu nội bộ được cấp — không bịa tin tức, số liệu "
                    "hay nguồn ngoài, không trích đoạn hội thoại. "
                    "Không tiêu đề markdown, không mở đầu kiểu thông "
                    "báo hệ thống.")},
                {"role": "user", "content": "\n\n".join(blocks)},
            ],
            model=self.cfg.model_cheap,
            purpose="feed",
            temperature=0.7,
        )
        return (comp.text or "").strip()

    async def publish(self, bot, chat_id: int,
                      thread_id: Optional[int] = None) -> dict:
        """Sinh bài và đăng vào topic Feed. bot là duck-type có
        send_message(chat_id, text, message_thread_id=...)."""
        text = await self.generate()
        if not text:
            return {"ok": False, "error": "model trả bài trống"}
        kwargs = {}
        if thread_id:
            kwargs["message_thread_id"] = thread_id
        msg = await bot.send_message(chat_id, text, **kwargs)
        message_id = int(getattr(msg, "message_id", 0) or 0)
        post_id = await self.memory.add_feed_post(
            chat_id, message_id, text)
        await self.memory.log_trajectory(
            f"agent:main:telegram:group:{chat_id}:topic:{thread_id or 0}",
            "feed_posted",
            {"post_id": post_id, "message_id": message_id,
             "chars": len(text)},
        )
        return {"ok": True, "post_id": post_id,
                "message_id": message_id, "text": text}

    # ---------- reaction -> taste ----------
    async def record_reaction(self, chat_id: int, message_id: int,
                              reactions: list[str]) -> bool:
        """Ghi reaction thành tín hiệu taste. Chỉ tính khi tin đó
        đúng là bài Feed đã đăng — reaction bừa không thành taste."""
        post = await self.memory.get_feed_post(chat_id, message_id)
        if post is None:
            return False
        for emoji in reactions:
            if emoji:
                await self.memory.add_feed_signal(
                    chat_id, message_id, emoji)
        if reactions:
            await self.update_taste()
        return True
