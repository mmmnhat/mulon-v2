"""Fixture dùng chung: cấu hình trỏ hết vào tmp_path, không đụng dữ liệu thật."""

from pathlib import Path

import pytest

from mulon.config import Config


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
    )


async def open_memory(cfg: Config):
    from mulon.memory import Memory

    return await Memory.open(cfg.db_path)
