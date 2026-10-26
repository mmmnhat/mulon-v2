"""mulon.paths — Quản lý đường dẫn đa nền tảng và platformdirs cho MuLon.

Cung cấp đường dẫn chuẩn theo từng hệ điều hành (macOS, Linux, Windows)
thông qua platformdirs hoặc chạy chế độ project-local mặc định.
Tuyệt đối tuân thủ Nguyên tắc số 0: không hardcode path của bất kỳ máy nào.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

try:
    from platformdirs import PlatformDirs
    _HAS_PLATFORMDIRS = True
except ImportError:
    _HAS_PLATFORMDIRS = False


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def get_platform_dirs(app_name: str = "mulon", app_author: str = "mulon") -> Optional[PlatformDirs]:
    """Lấy đối tượng PlatformDirs nếu thư viện có sẵn."""
    if _HAS_PLATFORMDIRS:
        return PlatformDirs(appname=app_name, appauthor=app_author)
    return None


def resolve_path(path_str: str | Path, base_dir: Optional[Path] = None) -> Path:
    """Phân giải đường dẫn cross-platform, mở rộng ~ và giải quyết đường dẫn tương đối."""
    base = base_dir or PROJECT_ROOT
    p = Path(path_str).expanduser()
    return p if p.is_absolute() else (base / p)


def get_default_paths(
    use_platformdirs: bool = False,
    project_root: Optional[Path] = None,
) -> dict[str, Path]:
    """Lấy bản đồ các thư mục mặc định của MuLon theo OS hoặc theo thư mục dự án."""
    root = project_root or PROJECT_ROOT
    if use_platformdirs and _HAS_PLATFORMDIRS:
        pdirs = PlatformDirs(appname="mulon", appauthor="mulon")
        data_base = pdirs.user_data_path
        config_base = pdirs.user_config_path
        log_base = pdirs.user_log_path
    else:
        data_base = root / "data"
        config_base = root / "config"
        log_base = root / "data" / "logs"

    return {
        "project_root": root,
        "data_dir": data_base,
        "config_dir": config_base,
        "log_dir": log_base,
        "dossier_dir": root / "dossier",
        "workspace_dir": root / "workspace",
        "artifact_dir": data_base / "artifacts",
        "db_path": data_base / "mulon.db",
        "policy_path": config_base / "policy.json",
        "allowlist_path": data_base / "allowlist.json",
        "claim_token_path": data_base / "claim_token.txt",
    }
