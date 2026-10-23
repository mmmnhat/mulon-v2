"""Phase 5 — backup/restore: round-trip thật, gói hỏng bị từ chối,
danh sách gói, và .env không bao giờ lọt vào gói."""

import zipfile

import pytest

from mulon.backup import BackupError, create_backup, list_backups, \
    restore_backup, verify_backup
from tests.conftest import open_memory


async def _seed_fact(cfg, text: str, subject: str = "test"):
    memory = await open_memory(cfg)
    try:
        return await memory.add_fact(text, subject=subject, source="test")
    finally:
        await memory.close()


async def _active_facts(cfg):
    memory = await open_memory(cfg)
    try:
        return await memory.active_facts()
    finally:
        await memory.close()


async def test_backup_restore_roundtrip(cfg, tmp_path):
    await _seed_fact(cfg, "Fact gốc trước backup")
    soul_before = (cfg.dossier_dir / "SOUL.md").read_text(encoding="utf-8")

    pkg = create_backup(cfg, out_dir=tmp_path / "backups")
    assert pkg.exists()
    manifest = verify_backup(pkg)
    paths = [f["path"] for f in manifest["files"]]
    assert "mulon.db" in paths
    assert "dossier/SOUL.md" in paths
    assert ".env.example" in paths
    assert not any(p.endswith(".env") for p in paths)

    # Phá dữ liệu hiện tại: thêm fact mới + sửa SOUL.
    await _seed_fact(cfg, "Fact sinh sau backup")
    (cfg.dossier_dir / "SOUL.md").write_text("SOUL BỊ SỬA", encoding="utf-8")
    assert len(await _active_facts(cfg)) == 2

    result = restore_backup(cfg, pkg)
    assert "mulon.db" in result["restored"]
    facts = await _active_facts(cfg)
    assert [f["fact"] for f in facts] == ["Fact gốc trước backup"]
    assert (cfg.dossier_dir / "SOUL.md").read_text(
        encoding="utf-8") == soul_before


async def test_restore_rejects_corrupted_package(cfg, tmp_path):
    await _seed_fact(cfg, "Fact để có DB mà backup")
    pkg = create_backup(cfg, out_dir=tmp_path / "backups")
    # Dựng gói giả: nội dung 1 file khác với checksum trong manifest.
    broken = tmp_path / "broken.zip"
    with zipfile.ZipFile(pkg) as src, \
            zipfile.ZipFile(broken, "w") as dst:
        for name in src.namelist():
            data = src.read(name)
            if name == "dossier/SOUL.md":
                data = b"noi dung bi sua doi"
            dst.writestr(name, data)
    with pytest.raises(BackupError):
        verify_backup(broken)
    with pytest.raises(BackupError):
        restore_backup(cfg, broken)


async def test_list_backups(cfg, tmp_path):
    out_dir = tmp_path / "backups"
    assert list_backups(out_dir) == []
    await _seed_fact(cfg, "Fact để có DB mà backup")
    pkg = create_backup(cfg, out_dir=out_dir)
    items = list_backups(out_dir)
    assert len(items) == 1
    assert items[0]["name"] == pkg.name
    assert items[0]["valid"] is True
    assert items[0]["files"] >= 3
    assert items[0]["created_at"]
