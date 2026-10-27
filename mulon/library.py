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

import hashlib
import html
import logging
import secrets
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


# ---------- chặn scan/share file nhạy cảm (sửa 1.6.3) ----------
def _share_token_hash(token: str) -> str:
    """Hash SHA-256 của share token để lưu DB, thay vì token gốc.

    Trước 1.6.3 DB lưu token plaintext nên ai đọc được DB là có
    ngay link chia sẻ. Token gốc vẫn trả về cho caller đúng 1 lần
    để dựng URL; DB chỉ giữ hash, tra cứu bằng hash(token đầu vào).
    """
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _denied_reason(path: Path) -> str:
    """Lý do từ chối scan/share, "" nếu được phép.

    Denylist theo tên: chứa .env, hậu tố .pem, chứa "secret",
    hậu tố .db, đúng tên vault.json. Đây là lớp phòng vệ cho file
    nhạy cảm, không thay thế việc user tự không đưa secret vào
    workspace.
    """
    name = path.name.lower()
    if name == "vault.json":
        return "file vault.json"
    if ".env" in name:
        return "tên chứa .env"
    if name.endswith(".pem"):
        return "tên có hậu tố .pem"
    if "secret" in name:
        return "tên chứa secret"
    if name.endswith(".db"):
        return "tên có hậu tố .db"
    return ""


def _share_blocked_reason(path: Path, workspace: Path) -> str:
    """Kiểm tra lại path lúc share (không chỉ lúc scan): symlink,
    resolve ra ngoài workspace, hoặc thuộc denylist đều bị chặn.
    Item cũ đã index trước 1.6.3 vẫn bị chặn ở đây.
    """
    try:
        if path.is_symlink():
            return "đường dẫn là symlink"
    except Exception:
        pass
    reason = _denied_reason(path)
    if reason:
        return reason
    try:
        resolved = path.resolve()
        base = workspace.resolve()
        if not resolved.is_relative_to(base):
            return "file nằm ngoài workspace"
    except Exception:
        return "không resolve được đường dẫn"
    return ""


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
                         source: str = "agent",
                         caption: str = "") -> Optional[dict]:
        p = Path(path)
        if not p.is_file():
            return None
        existing = await self.memory.get_library_item_by_path(str(p))
        if existing is not None:
            if caption and not existing.get("caption"):
                await self.memory.update_library_item(existing["id"], caption=caption)
                existing["caption"] = caption
            return existing
        return await self.memory.add_library_item(
            p.name, kind_of(p), str(p), source=source, caption=caption)

    async def get_item(self, item_id: int) -> Optional[dict]:
        return await self.memory.get_library_item(item_id)

    async def search(self, query: str, kind: Optional[str] = None,
                     status: str = "active", limit: int = 50) -> list[dict]:
        return await self.memory.search_library_items(
            query=query, kind=kind, status=status, limit=limit)

    async def scan(self) -> dict:
        """Quét workspace, lập chỉ mục file chưa có trong catalog.
        Bỏ qua: thư mục trash, thành phần ẩn (bắt đầu bằng '.').
        Sửa 1.6.3: bỏ qua symlink, file resolve ra ngoài workspace,
        và file thuộc denylist nhạy cảm (.env/.pem/*secret*/.db/
        vault.json) — trước đây scan index mọi file nên item nào
        cũng share được, kể cả secret lọt vào workspace."""
        base = Path(self.cfg.workspace_dir)
        indexed = 0
        seen = 0
        skipped_sensitive = 0
        if base.exists():
            base_resolved = base.resolve()
            for p in sorted(base.rglob("*")):
                if p.is_symlink():
                    skipped_sensitive += 1
                    continue
                if not p.is_file():
                    continue
                try:
                    rel = p.relative_to(base)
                except ValueError:
                    skipped_sensitive += 1
                    continue
                if any(part.startswith(".") for part in rel.parts):
                    continue
                if rel.parts and rel.parts[0] == "trash":
                    continue
                try:
                    if not p.resolve().is_relative_to(base_resolved):
                        skipped_sensitive += 1
                        continue
                except Exception:
                    skipped_sensitive += 1
                    continue
                if _denied_reason(p):
                    skipped_sensitive += 1
                    continue
                seen += 1
                before = await self.memory.get_library_item_by_path(
                    str(p))
                if before is None:
                    await self.memory.add_library_item(
                        p.name, kind_of(p), str(p), source="scan")
                    indexed += 1
        return {"ok": True, "files_seen": seen, "indexed": indexed,
                "skipped_sensitive": skipped_sensitive}

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

    # ---------- chia sẻ <= 48h (1.6.0: link thật qua host / tunnel) ----------
    async def share_item(self, item_id: int, hours: float = 48,
                         base_url: str = "") -> dict:
        item = await self.memory.get_library_item(item_id)
        if item is None:
            return {"ok": False, "error": f"không thấy item #{item_id}"}
        if item["status"] != "active":
            return {"ok": False,
                    "error": f"item #{item_id} không ở trạng thái active"}
        # Sửa 1.6.3: kiểm tra lại path lúc share, không chỉ lúc scan
        # — item cũ đã index trước 1.6.3 (symlink, file nhạy cảm,
        # file ngoài workspace) vẫn bị chặn ở đây.
        blocked = _share_blocked_reason(
            Path(item["path"]), Path(self.cfg.workspace_dir))
        if blocked:
            return {"ok": False,
                    "error": f"không chia sẻ được file này ({blocked})"}
        hours = max(0.1, min(float(hours), 48.0))
        expires = (_now() + timedelta(hours=hours)).isoformat(
            timespec="seconds")
        token = secrets.token_urlsafe(16)
        effective_base = (base_url or getattr(self.cfg, "webapp_url", "")).rstrip("/")
        if effective_base:
            share_url = f"{effective_base}/share/{token}"
            share_status = "active"
            note = f"Đã tạo link chia sẻ có hạn {hours:.1f} giờ."
        else:
            share_url = ""
            share_status = "pending_host"
            note = ("Bản này chưa có host công khai — yêu cầu chia sẻ "
                    "đã ghi với hạn <=48h ở trạng thái chờ host, "
                    "chưa có link để gửi.")
        # Sửa 1.6.3: DB chỉ lưu hash của token, không lưu token gốc.
        # Token gốc vẫn trả về cho caller 1 lần để dựng URL.
        await self.memory.update_library_item(
            item_id, share_status=share_status,
            share_expires_at=expires,
            share_token=_share_token_hash(token))
        # Sửa 1.6.1: KHÔNG log share_token vào trajectory. Token
        # chỉ trả về cho caller (để dựng URL) trong cùng lượt này;
        # ghi token vào DB trajectory biến log thành kho token.
        await self.memory.log_trajectory(
            "", "library_share_requested",
            {"item_id": item_id, "share_expires_at": expires,
             "share_status": share_status})
        return {
            "ok": True,
            "item_id": item_id,
            "name": item.get("name", ""),
            "share_status": share_status,
            "share_token": token,
            "share_url": share_url,
            "url": share_url,
            "share_expires_at": expires,
            "note": note,
        }

    # ---------- thu hồi chia sẻ (sửa 1.6.1) ----------
    async def unshare_item(self, item_id: int) -> dict:
        """Thu hồi link chia sẻ của 1 item: xoá token, trạng thái
        về revoked. Trước 1.6.1 không có cách nào giết link sớm —
        link đã phát chỉ chết khi hết hạn (tối đa 48h)."""
        item = await self.memory.get_library_item(item_id)
        if item is None:
            return {"ok": False, "error": f"không thấy item #{item_id}"}
        if item.get("share_status") not in ("active", "pending_host"):
            return {"ok": True, "item_id": item_id,
                    "share_status": item.get("share_status") or "revoked",
                    "note": "Item này hiện không có link chia sẻ đang hiệu lực."}
        await self.memory.update_library_item(
            item_id, share_status="revoked",
            share_expires_at="", share_token="")
        await self.memory.log_trajectory(
            "", "library_share_revoked",
            {"item_id": item_id, "share_status": "revoked"})
        return {"ok": True, "item_id": item_id, "share_status": "revoked",
                "note": "Đã thu hồi link chia sẻ. Link cũ không còn mở được."}

    # ---------- ghim & đổi tên (1.6.0) ----------
    async def pin_item(self, item_id: int, pinned: bool = True) -> dict:
        item = await self.memory.get_library_item(item_id)
        if item is None:
            return {"ok": False, "error": f"không thấy item #{item_id}"}
        val = 1 if pinned else 0
        await self.memory.update_library_item(item_id, pinned=val)
        return {"ok": True, "item_id": item_id, "pinned": bool(val)}

    async def rename_item(self, item_id: int, name: str) -> dict:
        item = await self.memory.get_library_item(item_id)
        if item is None:
            return {"ok": False, "error": f"không thấy item #{item_id}"}
        name = name.strip()
        if not name:
            return {"ok": False, "error": "tên không được để trống"}
        await self.memory.update_library_item(item_id, name=name)
        return {"ok": True, "item_id": item_id, "name": name, "title": name}

    async def get_item_by_token(self, token: str) -> dict:
        if not token:
            return {"ok": False, "error": "thiếu token chia sẻ"}
        # Sửa 1.6.3: tra bằng hash trước (token mới), rồi mới tra
        # plaintext cũ (migration 1 lần). Token cũ gặp lần đầu được
        # tự chuyển sang hash ngay trong lượt đó, để lần sau chỉ
        # còn hash trong DB. Token mới share sau 1.6.3 không bao
        # giờ có bản plaintext trong DB nên không cần bước này.
        item = await self.memory.get_library_item_by_token(
            _share_token_hash(token))
        if item is None:
            legacy = await self.memory.get_library_item_by_token(token)
            if legacy is not None:
                item = legacy
                try:
                    await self.memory.update_library_item(
                        legacy["id"],
                        share_token=_share_token_hash(token))
                except Exception:
                    pass
        if item is None:
            return {"ok": False, "error": "link chia sẻ không tồn tại hoặc đã thu hồi"}
        # Không trả token (kể cả bản legacy vừa migrate) ra ngoài
        # qua dict item — caller chỉ cần path/kind để đọc file.
        item = dict(item)
        item["share_token"] = ""
        if item.get("status") != "active":
            return {"ok": False, "error": "tài liệu không còn khả dụng"}
        # Sửa 1.6.1: chỉ link ở trạng thái active mới mở được.
        # Trước đây item pending_host (chưa có host, chưa phát link
        # thật) hoặc đã revoked nhưng token chưa xoá vẫn đọc được
        # nếu route tới được qua tunnel.
        if item.get("share_status") != "active":
            return {"ok": False, "error": "link chia sẻ không còn hiệu lực"}
        expires_at = item.get("share_expires_at") or ""
        if expires_at:
            try:
                exp_dt = datetime.fromisoformat(expires_at)
                if _now() > exp_dt:
                    return {"ok": False, "error": "link chia sẻ đã hết hạn"}
            except Exception:
                pass
        p = Path(item["path"])
        if not p.is_file():
            return {"ok": False, "error": "file tài liệu không còn trên máy"}
        is_binary = False
        content = ""
        size_bytes = p.stat().st_size
        if item.get("kind") in ("document", "code"):
            try:
                content = p.read_text(encoding="utf-8", errors="replace")
            except Exception:
                is_binary = True
        else:
            is_binary = True
        return {
            "ok": True,
            "item": item,
            "content": content,
            "is_binary": is_binary,
            "size_bytes": size_bytes,
        }


ICON_MAP = {
    "image": "🖼️",
    "media": "🎵",
    "document": "📄",
    "code": "💻",
    "other": "📁",
}


def format_library_list(items: list[dict], title: str = "") -> str:
    if not items:
        return "Library trống."
    header = title if title else f"📚 <b>Thư viện Mulon ({len(items)} mục):</b>\n"
    lines = [header]
    for it in items:
        extra = ""
        pin = "📌 " if it.get("pinned") else ""
        icon = ICON_MAP.get(it.get("kind"), "📁")
        if it.get("share_status") == "active" and it.get("share_token"):
            extra = " <i>(đang chia sẻ)</i>"
        elif it.get("share_status") == "pending_host":
            extra = " <i>(chờ chia sẻ)</i>"
        name_esc = html.escape(str(it.get("name", "")))
        cap = ""
        if it.get("caption"):
            cap = f" — <i>{html.escape(str(it['caption']))}</i>"
        lines.append(f"{pin}• <b>#{it['id']}</b> {icon} <code>{name_esc}</code>{cap}{extra}")
    lines.append("\n💡 <i>Gõ <code>/library &lt;id&gt;</code> (vd: <code>/library 6</code>) để tải file/ảnh gốc về chat, hoặc <code>/library &lt;từ khóa&gt;</code> để tìm kiếm.</i>")
    return "\n".join(lines)


def register_library_tools(registry, library_service: LibraryService) -> list[str]:
    """Đăng ký các tool thao tác Thư viện (Library) cho Agent."""
    from .tools import ToolSpec

    async def search_library_tool(query: str, kind: str = "") -> dict:
        results = await library_service.search(query, kind=kind or None, status="active", limit=20)
        items = [
            {
                "id": it["id"],
                "name": it.get("name", ""),
                "kind": it.get("kind", ""),
                "path": it.get("path", ""),
                "caption": it.get("caption", ""),
                "share_status": it.get("share_status", ""),
                "pinned": bool(it.get("pinned", 0)),
            }
            for it in results
        ]
        return {"ok": True, "query": query, "count": len(items), "items": items}

    async def get_library_item_tool(item_id: int) -> dict:
        item = await library_service.get_item(item_id)
        if not item:
            return {"ok": False, "error": f"Không tìm thấy mục #{item_id} trong Thư viện"}
        return {
            "ok": True,
            "item": {
                "id": item["id"],
                "name": item.get("name", ""),
                "kind": item.get("kind", ""),
                "path": item.get("path", ""),
                "caption": item.get("caption", ""),
                "status": item.get("status", ""),
                "share_status": item.get("share_status", ""),
                "pinned": bool(item.get("pinned", 0)),
            }
        }

    async def share_library_item_tool(item_id: int, hours: float = 48.0) -> dict:
        return await library_service.share_item(item_id, hours=hours)

    specs = [
        ToolSpec(
            name="search_library",
            description="Tìm kiếm tệp, tài liệu, hình ảnh, video, âm thanh trong Thư viện (Library) bằng ngôn ngữ tự nhiên, từ khóa, tên tệp hoặc loại.",
            parameters={
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "Từ khóa hoặc câu tìm kiếm bằng ngôn ngữ tự nhiên (vd: 'hợp đồng', 'ảnh tiệc', 'bản ghi âm')"},
                    "kind": {"type": "string", "description": "Lọc theo loại tệp nếu cần (document, image, media, code, archive)", "default": ""},
                },
                "required": ["query"],
            },
            group="library",
            timeout_s=30,
            handler=search_library_tool,
        ),
        ToolSpec(
            name="get_library_item",
            description="Lấy thông tin chi tiết và đường dẫn của một mục trong Thư viện (Library) theo mã định danh (ID).",
            parameters={
                "type": "object",
                "properties": {
                    "item_id": {"type": "integer", "description": "ID mục trong Thư viện"},
                },
                "required": ["item_id"],
            },
            group="library",
            timeout_s=15,
            handler=get_library_item_tool,
        ),
        ToolSpec(
            name="share_library_item",
            description="Tạo liên kết chia sẻ công khai an toàn cho một mục trong Thư viện (thời hạn tối đa 48 giờ).",
            parameters={
                "type": "object",
                "properties": {
                    "item_id": {"type": "integer", "description": "ID mục cần chia sẻ"},
                    "hours": {"type": "number", "description": "Số giờ hiệu lực của liên kết (tối đa 48 giờ)", "default": 48.0},
                },
                "required": ["item_id"],
            },
            group="library",
            timeout_s=30,
            handler=share_library_item_tool,
        ),
    ]

    for sp in specs:
        registry.register(sp)
    return [sp.name for sp in specs]
