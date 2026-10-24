"""Library (thiết kế mục 16.7): catalog file agent tạo/lưu cho user.

- Lập chỉ mục bằng quét workspace (bỏ qua thùng rác + file ẩn)
  hoặc index từng file khi agent tạo ra.
- Xóa = chuyển vào workspace/trash/, khôi phục được trong
  LIBRARY_TRASH_DAYS ngày (mặc định 30) — không xóa cứng.
- Chia sẻ: /share_item đặt hạn <= 48h và trạng thái
  share_status='pending_host'. Bản này KHÔNG có host công khai nên
  KHÔNG bịa link — trạng thái "chờ host" là sự thật vận hành.
"""

from __future__ import annotations

import logging
import shutil
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("mulon.library")

KIND_BY_EXT = {
    ".md": "document", ".txt": "document", ".pdf": "document",
    ".docx": "document", ".odt": "document", ".csv": "document",
    ".png": "image", ".jpg": "image", ".jpeg": "image",
    ".webp": "image", ".gif": "image",
    ".mp3": "media", ".mp4": "media", ".ogg": "media",
    ".wav": "media", ".mov": "media", ".webm": "media",
    ".py": "code", ".json": "code", ".html": "code", ".css": "code",
    ".js": "code", ".zip": "archive",
}


def kind_of(path: Path) -> str:
    return KIND_BY_EXT.get(path.suffix.lower(), "other")


def _now() -> datetime:
    return datetime.now(timezone.utc)


class LibraryService:
    def __init__(self, cfg, memory):
        self.cfg = cfg
        self.memory = memory

    @property
    def trash_dir(self) -> Path:
        return Path(self.cfg.workspace_dir) / "trash"

    # ---------- lập chỉ mục ----------
    async def index_file(self, path: str | Path,
                         source: str = "agent") -> Optional[dict]:
        p = Path(path)
        if not p.is_file():
            return None
        existing = await self.memory.get_library_item_by_path(str(p))
        if existing is not None:
            return existing
        return await self.memory.add_library_item(
            p.name, kind_of(p), str(p), source=source)

    async def scan(self) -> dict:
        """Quét workspace, lập chỉ mục file chưa có trong catalog.
        Bỏ qua: thư mục trash, thành phần ẩn (bắt đầu bằng '.')."""
        base = Path(self.cfg.workspace_dir)
        indexed = 0
        seen = 0
        if base.exists():
            for p in sorted(base.rglob("*")):
                if not p.is_file():
                    continue
                rel = p.relative_to(base)
                if any(part.startswith(".") for part in rel.parts):
                    continue
                if rel.parts and rel.parts[0] == "trash":
                    continue
                seen += 1
                before = await self.memory.get_library_item_by_path(
                    str(p))
                if before is None:
                    await self.memory.add_library_item(
                        p.name, kind_of(p), str(p), source="scan")
                    indexed += 1
        return {"ok": True, "files_seen": seen, "indexed": indexed}

    async def list_items(self, status: Optional[str] = "active",
                         limit: int = 100) -> list[dict]:
        return await self.memory.list_library_items(
            status=status, limit=limit)

    # ---------- thùng rác 30 ngày ----------
    async def trash_item(self, item_id: int) -> dict:
        item = await self.memory.get_library_item(item_id)
        if item is None:
            return {"ok": False, "error": f"không thấy item #{item_id}"}
        if item["status"] != "active":
            return {"ok": False,
                    "error": f"item #{item_id} đang ở trạng thái "
                             f"{item['status']}"}
        src = Path(item["path"])
        trash_path = ""
        if src.is_file():
            self.trash_dir.mkdir(parents=True, exist_ok=True)
            dest = self.trash_dir / f"{item_id}_{src.name}"
            n = 1
            while dest.exists():
                n += 1
                dest = self.trash_dir / f"{item_id}_{n}_{src.name}"
            shutil.move(str(src), str(dest))
            trash_path = str(dest)
        await self.memory.update_library_item(
            item_id, status="trashed", trash_path=trash_path,
            trashed_at=_now().isoformat(timespec="seconds"))
        await self.memory.log_trajectory(
            "", "library_trashed",
            {"item_id": item_id, "trash_path": trash_path})
        return {"ok": True, "item_id": item_id, "trash_path": trash_path}

    async def restore_item(self, item_id: int) -> dict:
        item = await self.memory.get_library_item(item_id)
        if item is None:
            return {"ok": False, "error": f"không thấy item #{item_id}"}
        if item["status"] != "trashed":
            return {"ok": False,
                    "error": f"item #{item_id} không nằm trong thùng rác"}
        trashed_at = item.get("trashed_at") or ""
        try:
            age = _now() - datetime.fromisoformat(trashed_at)
        except Exception:
            age = timedelta(0)
        if age > timedelta(days=self.cfg.library_trash_days):
            return {"ok": False,
                    "error": f"đã quá {self.cfg.library_trash_days} "
                             "ngày trong thùng rác — không khôi phục "
                             "được nữa"}
        dest = Path(item["path"])
        trash_path = item.get("trash_path") or ""
        if trash_path and Path(trash_path).is_file():
            dest.parent.mkdir(parents=True, exist_ok=True)
            if dest.exists():
                dest = dest.with_name(
                    dest.stem + ".restored" + dest.suffix)
            shutil.move(trash_path, str(dest))
        await self.memory.update_library_item(
            item_id, status="active", path=str(dest), trash_path="",
            trashed_at="")
        await self.memory.log_trajectory(
            "", "library_restored",
            {"item_id": item_id, "path": str(dest)})
        return {"ok": True, "item_id": item_id, "path": str(dest)}

    # ---------- chia sẻ <= 48h (chờ host, không bịa link) ----------
    async def share_item(self, item_id: int, hours: float = 48) -> dict:
        item = await self.memory.get_library_item(item_id)
        if item is None:
            return {"ok": False, "error": f"không thấy item #{item_id}"}
        if item["status"] != "active":
            return {"ok": False,
                    "error": f"item #{item_id} không ở trạng thái active"}
        hours = max(0.1, min(float(hours), 48.0))
        expires = (_now() + timedelta(hours=hours)).isoformat(
            timespec="seconds")
        await self.memory.update_library_item(
            item_id, share_status="pending_host",
            share_expires_at=expires)
        await self.memory.log_trajectory(
            "", "library_share_requested",
            {"item_id": item_id, "share_expires_at": expires})
        return {
            "ok": True,
            "item_id": item_id,
            "share_status": "pending_host",
            "share_expires_at": expires,
            "note": "Bản này chưa có host công khai — yêu cầu chia sẻ "
                    "đã ghi với hạn <=48h ở trạng thái chờ host, "
                    "chưa có link để gửi.",
        }


def format_library_list(items: list[dict]) -> str:
    if not items:
        return "Library trống."
    lines = ["Library:"]
    for it in items:
        extra = ""
        if it.get("share_status") == "pending_host":
            extra = f" · chia sẻ chờ host tới {it['share_expires_at']}"
        lines.append(
            f"- #{it['id']} [{it['kind']}] {it['name']} ({it['path']})"
            + extra)
    return "\n".join(lines)
