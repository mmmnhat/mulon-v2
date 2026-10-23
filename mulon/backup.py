"""Sao lưu / khôi phục (thiết kế mục 9, 11) — Phase 5.

Một gói backup là 1 file .zip tự mô tả:

- ``mulon.db`` — bản sao DB chụp bằng SQLite backup API (nhất quán
  kể cả khi bot đang chạy, không copy file thô đang WAL).
- ``dossier/`` — toàn bộ hồ sơ (SOUL/USER/MEMORY/alignment...).
- ``config/`` + ``.env.example`` — cấu hình KHÔNG secret. File
  ``.env`` chứa secret KHÔNG BAO GIỜ được đưa vào gói.
- ``manifest.json`` — SHA-256 + kích thước từng file trong gói.

Restore kiểm checksum TOÀN BỘ gói trước khi ghi đè bất cứ thứ gì;
gói lỗi checksum / thiếu manifest / đường dẫn lạ -> từ chối, dữ
liệu hiện tại nguyên vẹn. Lưu ý vận hành: restore khi bot đang
chạy có thể bị bot ghi đè ngược — hãy dừng bot trước khi restore.

CLI:
    python -m mulon.backup create [--out DIR]
    python -m mulon.backup list
    python -m mulon.backup restore <goi.zip>
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
import shutil
import sqlite3
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger("mulon.backup")

MANIFEST_NAME = "manifest.json"
DB_ARCNAME = "mulon.db"


class BackupError(Exception):
    """Gói backup không hợp lệ hoặc thao tác bị từ chối."""


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _safe_arcname(name: str) -> bool:
    """Tên trong zip phải là đường dẫn tương đối, không thoát ra ngoài."""
    if not name or name.startswith(("/", "\\")):
        return False
    parts = Path(name).parts
    return all(p not in ("..", "") for p in parts)


def _collect_payload(cfg, staging: Path) -> list[dict]:
    """Chụp DB + copy dossier/config vào staging; trả manifest files."""
    files: list[dict] = []

    def _add(src_bytes: bytes, arcname: str):
        dest = staging / arcname
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(src_bytes)
        files.append({
            "path": arcname,
            "sha256": _sha256_bytes(src_bytes),
            "size": len(src_bytes),
        })

    # --- DB qua backup API (nhất quán với WAL) ---
    db_path = Path(cfg.db_path)
    if db_path.exists():
        tmp_db = staging / DB_ARCNAME
        # Kết nối thường (không mode=ro) để đọc được cả khi DB
        # đang WAL và tiến trình bot còn giữ kết nối mở.
        src = sqlite3.connect(str(db_path))
        try:
            dst = sqlite3.connect(str(tmp_db))
            try:
                src.backup(dst)
            finally:
                dst.close()
        finally:
            src.close()
        data = tmp_db.read_bytes()
        files.append({
            "path": DB_ARCNAME,
            "sha256": _sha256_bytes(data),
            "size": len(data),
        })

    # --- dossier/ ---
    dossier_dir = Path(cfg.dossier_dir)
    if dossier_dir.is_dir():
        for item in sorted(dossier_dir.rglob("*")):
            if item.is_file():
                arc = f"dossier/{item.relative_to(dossier_dir).as_posix()}"
                _add(item.read_bytes(), arc)

    # --- config không secret: thư mục config/ của project + .env.example.
    # .env (chứa secret) bị loại tường minh, kể cả khi nằm lẫn trong
    # thư mục config.
    project_root = Path(__file__).resolve().parent.parent
    config_dir = project_root / "config"
    if config_dir.is_dir():
        for item in sorted(config_dir.rglob("*")):
            if item.is_file() and item.name != ".env":
                arc = f"config/{item.relative_to(config_dir).as_posix()}"
                _add(item.read_bytes(), arc)
    example = project_root / ".env.example"
    if example.exists():
        _add(example.read_bytes(), ".env.example")
    return files


def create_backup(cfg, out_dir: Optional[str | Path] = None) -> Path:
    """Tạo gói backup .zip, trả đường dẫn gói."""
    dest_dir = Path(out_dir) if out_dir else Path(cfg.backup_dir)
    dest_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d-%H%M%S")
    zip_path = dest_dir / f"mulon-backup-{stamp}.zip"
    suffix = 1
    while zip_path.exists():
        suffix += 1
        zip_path = dest_dir / f"mulon-backup-{stamp}-{suffix}.zip"

    staging = Path(tempfile.mkdtemp(prefix="mulon-backup-"))
    try:
        files = _collect_payload(cfg, staging)
        manifest = {
            "format": 1,
            "created_at": datetime.now(timezone.utc).isoformat(
                timespec="seconds"),
            "app": "mulon",
            "files": files,
        }
        manifest_bytes = json.dumps(
            manifest, ensure_ascii=False, indent=2).encode("utf-8")
        with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
            for entry in files:
                zf.write(staging / entry["path"], entry["path"])
            zf.writestr(MANIFEST_NAME, manifest_bytes)
    finally:
        shutil.rmtree(staging, ignore_errors=True)
    logger.info("đã tạo backup %s (%d file)", zip_path, len(files))
    return zip_path


def _read_manifest(zf: zipfile.ZipFile) -> dict:
    try:
        raw = zf.read(MANIFEST_NAME)
    except KeyError as exc:
        raise BackupError("gói thiếu manifest.json") from exc
    try:
        manifest = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise BackupError(f"manifest.json hỏng: {exc}") from exc
    if not isinstance(manifest.get("files"), list):
        raise BackupError("manifest.json không có danh sách files")
    return manifest


def verify_backup(zip_path: str | Path) -> dict:
    """Kiểm checksum toàn gói. Trả manifest nếu hợp lệ, raise nếu lỗi."""
    zip_path = Path(zip_path)
    if not zip_path.exists():
        raise BackupError(f"không thấy gói: {zip_path}")
    try:
        zf = zipfile.ZipFile(zip_path)
    except zipfile.BadZipFile as exc:
        raise BackupError(f"không phải file zip hợp lệ: {exc}") from exc
    with zf:
        manifest = _read_manifest(zf)
        names = set(zf.namelist())
        for entry in manifest["files"]:
            arc = str(entry.get("path", ""))
            if not _safe_arcname(arc):
                raise BackupError(f"đường dẫn lạ trong manifest: {arc!r}")
            if arc not in names:
                raise BackupError(f"gói thiếu file khai trong manifest: {arc}")
            data = zf.read(arc)
            if _sha256_bytes(data) != entry.get("sha256"):
                raise BackupError(f"checksum sai: {arc}")
            if len(data) != int(entry.get("size", -1)):
                raise BackupError(f"kích thước sai: {arc}")
    return manifest


def restore_backup(cfg, zip_path: str | Path) -> dict:
    """Khôi phục từ gói. Kiểm checksum TRƯỚC, chỉ ghi đè khi gói sạch."""
    manifest = verify_backup(zip_path)  # raise -> chưa đụng gì
    project_root = Path(__file__).resolve().parent.parent
    restored: list[str] = []
    with zipfile.ZipFile(zip_path) as zf:
        for entry in manifest["files"]:
            arc = str(entry["path"])
            data = zf.read(arc)
            if arc == DB_ARCNAME:
                dest = Path(cfg.db_path)
                dest.parent.mkdir(parents=True, exist_ok=True)
                tmp = dest.with_suffix(".db.restore-tmp")
                tmp.write_bytes(data)
                tmp.replace(dest)
                # Xoá WAL/SHM cũ: chúng thuộc DB trước restore.
                for side in ("-wal", "-shm"):
                    stale = Path(str(dest) + side)
                    if stale.exists():
                        stale.unlink()
            elif arc.startswith("dossier/"):
                dest = Path(cfg.dossier_dir) / arc[len("dossier/"):]
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
            elif arc.startswith("config/"):
                dest = project_root / arc
                dest.parent.mkdir(parents=True, exist_ok=True)
                dest.write_bytes(data)
            elif arc == ".env.example":
                dest = project_root / ".env.example"
                dest.write_bytes(data)
            else:
                raise BackupError(f"không biết khôi phục file: {arc}")
            restored.append(arc)
    logger.info("đã restore %d file từ %s", len(restored), zip_path)
    return {"restored": restored, "manifest": manifest}


def list_backups(backup_dir: str | Path) -> list[dict]:
    """Liệt kê các gói trong thư mục backup, mới nhất trước."""
    base = Path(backup_dir)
    if not base.is_dir():
        return []
    out: list[dict] = []
    for item in sorted(base.glob("mulon-backup-*.zip"), reverse=True):
        info: dict = {
            "path": str(item),
            "name": item.name,
            "size": item.stat().st_size,
            "created_at": "",
            "files": 0,
            "valid": False,
        }
        try:
            manifest = verify_backup(item)
            info["created_at"] = str(manifest.get("created_at", ""))
            info["files"] = len(manifest["files"])
            info["valid"] = True
        except BackupError:
            pass
        out.append(info)
    return out


# ------------------------------------------------------------------
# CLI
# ------------------------------------------------------------------
def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="mulon.backup")
    sub = parser.add_subparsers(dest="cmd", required=True)
    p_create = sub.add_parser("create", help="tạo gói backup")
    p_create.add_argument("--out", default=None,
                          help="thư mục đích (mặc định BACKUP_DIR)")
    sub.add_parser("list", help="liệt kê các gói backup")
    p_restore = sub.add_parser("restore", help="khôi phục từ 1 gói")
    p_restore.add_argument("package", help="đường dẫn file .zip")
    parser.add_argument("--env-file", default=None)
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    from .config import Config

    cfg = Config.load(env_file=args.env_file)
    if args.cmd == "create":
        path = create_backup(cfg, out_dir=args.out)
        print(f"Đã tạo: {path}")
        return 0
    if args.cmd == "list":
        items = list_backups(cfg.backup_dir)
        if not items:
            print(f"Chưa có gói backup nào trong {cfg.backup_dir}")
            return 0
        for info in items:
            mark = "ok" if info["valid"] else "LỖI checksum"
            print(f"{info['name']}  {info['size']} bytes  "
                  f"{info['files']} file  {info['created_at']}  [{mark}]")
        return 0
    if args.cmd == "restore":
        try:
            result = restore_backup(cfg, args.package)
        except BackupError as exc:
            print(f"Từ chối restore: {exc}", file=sys.stderr)
            return 1
        print(f"Đã khôi phục {len(result['restored'])} file từ "
              f"{args.package}")
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
