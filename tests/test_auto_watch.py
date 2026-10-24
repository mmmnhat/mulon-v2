"""Kiểm thử cho sửa 1.6.3 của scripts/auto_watch.py.

Chỉ test các helper thuần (backup/stash/pop/cờ bật) trên repo git
tạm trong tmp_path — KHÔNG chạy watcher thật, KHÔNG chạm bot thật.
"""

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from auto_watch import (  # noqa: E402
    auto_watch_enabled,
    backup_local_changes,
    latest_stash_ref,
    pop_stash,
    stash_local_changes,
)


def _git(repo: Path, *args: str):
    subprocess.run(["git", *args], cwd=repo, check=True,
                   capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    _git(tmp_path, "init", "-b", "main")
    _git(tmp_path, "config", "user.email", "test@example.com")
    _git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "tracked.txt").write_text("dòng gốc\n", encoding="utf-8")
    _git(tmp_path, "add", "tracked.txt")
    _git(tmp_path, "commit", "-m", "gốc")
    return tmp_path


def test_auto_watch_default_off():
    assert auto_watch_enabled(env={}) is False
    assert auto_watch_enabled(env={"AUTO_WATCH_ENABLED": "0"}) is False
    assert auto_watch_enabled(env={"AUTO_WATCH_ENABLED": "1"}) is True
    assert auto_watch_enabled(env={}, flag=True) is True


def test_backup_stash_pop_roundtrip(repo: Path):
    (repo / "tracked.txt").write_text("dòng đã sửa local\n", encoding="utf-8")
    backup = backup_local_changes(repo)
    assert backup is not None
    assert backup.name.startswith("local-")
    assert "dòng đã sửa local" in backup.read_text(encoding="utf-8")
    ref = stash_local_changes(repo)
    assert ref.startswith("stash@{0}")
    assert (repo / "tracked.txt").read_text(encoding="utf-8") == "dòng gốc\n"
    ok, _ = pop_stash(repo)
    assert ok is True
    assert (repo / "tracked.txt").read_text(encoding="utf-8") == "dòng đã sửa local\n"
    assert latest_stash_ref(repo) == ""


def test_backup_none_when_clean(repo: Path):
    assert backup_local_changes(repo) is None
    assert stash_local_changes(repo) == ""


def test_pop_conflict_keeps_stash(repo: Path):
    # Sửa -> stash -> sửa nền theo hướng xung đột -> pop phải báo
    # False và stash vẫn còn, không được âm thầm mất local changes.
    (repo / "tracked.txt").write_text("phiên bản A\n", encoding="utf-8")
    ref = stash_local_changes(repo)
    assert ref.startswith("stash@{0}")
    (repo / "tracked.txt").write_text("phiên bản B xung đột\n", encoding="utf-8")
    _git(repo, "add", "tracked.txt")
    _git(repo, "commit", "-m", "nền mới")
    ok, kept = pop_stash(repo)
    assert ok is False
    assert kept.startswith("stash@{0}")
    assert latest_stash_ref(repo).startswith("stash@{0}")
