"""Fixture dùng chung: cấu hình trỏ hết vào tmp_path, không đụng dữ liệu thật."""

import atexit
import threading
from pathlib import Path

import pytest

from mulon.config import Config


def pytest_sessionfinish(session, exitstatus):
    """T-39.1: Đóng triệt để toàn bộ database pools còn mở để tiến trình pytest thoát tức thì."""
    from mulon.db import close_all_pools
    close_all_pools()

    # Kiểm tra an toàn: nếu còn non-daemon thread nào sống thì in cảnh báo
    alive_non_daemons = [
        t for t in threading.enumerate()
        if not t.daemon and t.is_alive() and t != threading.main_thread()
    ]
    if alive_non_daemons:
        print(f"\n[CẢNH BÁO TEARDOWN] Còn {len(alive_non_daemons)} non-daemon thread(s) đang sống: {alive_non_daemons}")







@pytest.fixture
def cfg(tmp_path: Path) -> Config:
    dossier = tmp_path / "dossier"
    dossier.mkdir()
    (dossier / "SOUL.md").write_text("# SOUL\nPersona test.", encoding="utf-8")
    (dossier / "USER.md").write_text("# USER\nUser test.", encoding="utf-8")
    (dossier / "IDENTITY.md").write_text("# IDENTITY\nAgent test.", encoding="utf-8")
    (dossier / "MEMORY.md").write_text("# MEMORY\n", encoding="utf-8")
    (dossier / "BOOTSTRAP.md").write_text("# BOOTSTRAP\n", encoding="utf-8")
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    return Config(
        db_path=tmp_path / "mulon.db",
        dossier_dir=dossier,
        workspace_dir=workspace,
        artifact_dir=tmp_path / "artifacts",
        policy_path=tmp_path / "policy.json",
        vault_path=tmp_path / "vault.json",
    )


_OPEN_MEMORIES = []


async def open_memory(cfg: Config):
    from mulon.memory import Memory

    mem = await Memory.open(cfg.db_path)
    _OPEN_MEMORIES.append(mem)
    return mem


@pytest.fixture(autouse=True)
async def _autoclose_opened_memories():
    yield
    while _OPEN_MEMORIES:
        mem = _OPEN_MEMORIES.pop()
        try:
            await mem.close()
        except Exception:
            pass

