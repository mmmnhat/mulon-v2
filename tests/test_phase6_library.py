"""Phase 6 — Library (mục 16.7): lập chỉ mục workspace, thùng rác
30 ngày khôi phục được, chia sẻ <=48h ở trạng thái chờ host
(không bịa link)."""

from datetime import datetime, timedelta, timezone

from mulon.library import LibraryService, format_library_list, kind_of
from tests.conftest import open_memory


async def test_scan_indexes_workspace_files(cfg):
    memory = await open_memory(cfg)
    ws = cfg.workspace_dir
    (ws / "bao-cao.md").write_text("# báo cáo", encoding="utf-8")
    (ws / "anh.png").write_bytes(b"\x89PNG fake")
    sub = ws / "outputs"
    sub.mkdir()
    (sub / "clip.mp4").write_bytes(b"fake-video")
    (ws / ".hidden").write_text("ẩn", encoding="utf-8")
    trash = ws / "trash"
    trash.mkdir()
    (trash / "rac.md").write_text("rác", encoding="utf-8")

    lib = LibraryService(cfg, memory)
    result = await lib.scan()
    assert result["indexed"] == 3  # ẩn + thùng rác bị bỏ qua
    items = await lib.list_items()
    names = {it["name"] for it in items}
    assert names == {"bao-cao.md", "anh.png", "clip.mp4"}
    kinds = {it["name"]: it["kind"] for it in items}
    assert kinds["bao-cao.md"] == "document"
    assert kinds["anh.png"] == "image"
    assert kinds["clip.mp4"] == "media"
    # Quét lại không nhân đôi.
    again = await lib.scan()
    assert again["indexed"] == 0
    await memory.close()


async def test_trash_and_restore_roundtrip(cfg, tmp_path):
    memory = await open_memory(cfg)
    f = cfg.workspace_dir / "ghi-chu.txt"
    f.write_text("nội dung quan trọng", encoding="utf-8")
    lib = LibraryService(cfg, memory)
    item = await lib.index_file(f)
    assert item is not None

    trashed = await lib.trash_item(item["id"])
    assert trashed["ok"] is True
    assert not f.exists()
    assert (cfg.workspace_dir / "trash"
            / f"{item['id']}_ghi-chu.txt").exists()
    assert (await lib.list_items()) == []
    trash_items = await lib.list_items(status="trashed")
    assert len(trash_items) == 1

    restored = await lib.restore_item(item["id"])
    assert restored["ok"] is True
    assert f.exists()
    assert f.read_text(encoding="utf-8") == "nội dung quan trọng"
    assert len(await lib.list_items()) == 1
    await memory.close()


async def test_restore_after_30_days_refused(cfg):
    memory = await open_memory(cfg)
    f = cfg.workspace_dir / "cu.txt"
    f.write_text("cũ", encoding="utf-8")
    lib = LibraryService(cfg, memory)
    item = await lib.index_file(f)
    await lib.trash_item(item["id"])
    old = (datetime.now(timezone.utc)
           - timedelta(days=31)).isoformat(timespec="seconds")
    await memory.db.execute(
        "UPDATE library_items SET trashed_at=? WHERE id=?",
        (old, item["id"]))
    await memory.db.commit()
    result = await lib.restore_item(item["id"])
    assert result["ok"] is False
    assert "30 ngày" in result["error"]
    await memory.close()


async def test_share_clamps_to_48h_and_is_pending_host(cfg):
    memory = await open_memory(cfg)
    f = cfg.workspace_dir / "chia-se.md"
    f.write_text("nội dung", encoding="utf-8")
    lib = LibraryService(cfg, memory)
    item = await lib.index_file(f)
    result = await lib.share_item(item["id"], hours=999)
    assert result["ok"] is True
    assert result["share_status"] == "pending_host"
    expires = datetime.fromisoformat(result["share_expires_at"])
    delta = expires - datetime.now(timezone.utc)
    assert timedelta(hours=47) < delta <= timedelta(hours=48, minutes=1)
    # Trung thực: không có URL nào được bịa ra.
    assert "http" not in str(result)
    assert (await lib.share_item(999999))["ok"] is False
    await memory.close()


def test_kind_of_and_format():
    from pathlib import Path

    assert kind_of(Path("a.md")) == "document"
    assert kind_of(Path("a.webp")) == "image"
    assert kind_of(Path("a.py")) == "code"
    assert kind_of(Path("a.xyz")) == "other"
    text = format_library_list(
        [{"id": 1, "kind": "document", "name": "x.md", "path": "/x.md",
          "share_status": "", "share_expires_at": ""}])
    assert "#1" in text and "x.md" in text
    assert format_library_list([]) == "Library trống."
