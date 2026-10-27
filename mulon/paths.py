"""mulon.paths — Quản lý đường dẫn đa nền tảng và platformdirs cho MuLon.

Cung cấp đường dẫn chuẩn theo từng hệ điều hành (macOS, Linux, Windows)
thông qua platformdirs hoặc chạy chế độ project-local mặc định.
Tuyệt đối tuân thủ Nguyên tắc số 0: không hardcode path của bất kỳ máy nào.
"""

from __future__ import annotations

import os
import re
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


def sanitize_path_display(path_str: str | Path) -> str:
    """Rút gọn đường dẫn hiển thị để ẩn tuyệt đối path máy chủ cục bộ (T-23.2).

    Chỉ hiển thị đường dẫn tương đối so với project hoặc tên thư mục/file hợp lý.
    """
    if not path_str:
        return ""
    p_str = str(path_str).strip()
    if not p_str:
        return ""
    # Chuyển backslash Windows thành slash để xử lý đồng nhất
    normalized = p_str.replace("\\", "/")

    # Nếu nằm trong project root
    try:
        p = Path(p_str)
        if p.is_absolute():
            try:
                rel = p.relative_to(PROJECT_ROOT)
                return str(rel).replace("\\", "/")
            except ValueError:
                pass
    except Exception:
        pass

    # Rút gọn các tiền tố máy cụ thể (/Volumes/..., /Users/..., /home/..., C:\...)
    parts = [part for part in normalized.split("/") if part]
    if "skills" in parts:
        idx = len(parts) - 1 - parts[::-1].index("skills")
        return "/".join(parts[idx:])
    if "mulon" in parts:
        idx = len(parts) - 1 - parts[::-1].index("mulon")
        return "/".join(parts[idx:])

    # Loại bỏ prefix /Volumes/<name>, /Users/<name>, /home/<name>
    if normalized.startswith(("/Volumes/", "/Users/", "/home/")):
        if len(parts) > 2:
            return ".../" + "/".join(parts[-2:])
        return parts[-1] if parts else normalized

    # Windows paths C:/Users/...
    if re.match(r"^[a-zA-Z]:/", normalized):
        if len(parts) > 2:
            return ".../" + "/".join(parts[-2:])
        return parts[-1] if parts else normalized

    return normalized


def fix_glued_words(text: str) -> str:
    """Sửa các trường hợp dính chữ do thiếu khoảng trắng (T-23.2 / Q-02).

    Ví dụ: 'toàn bộ63/63 bài đăngcủa' -> 'toàn bộ 63/63 bài đăng của'.
    Không tách dấu chấm để bảo toàn phần mở rộng file (.md, .py...) và số thực.
    """
    if not text:
        return ""
    s = str(text)
    # Chữ cái tiếng Việt/Latin dính với số hoặc phân số
    s = re.sub(r"([a-zA-ZÀ-ỹ])(\d+(?:/\d+)?)", r"\1 \2", s)
    # Số hoặc phân số dính với chữ cái
    s = re.sub(r"(\d+(?:/\d+)?)([a-zA-ZÀ-ỹ])", r"\1 \2", s)
    # Cụm từ dính cụ thể ghi nhận trong QA: 'bài đăng' dính với 'của'
    s = re.sub(r"(bài đăng)(của\b)", r"\1 \2", s, flags=re.IGNORECASE)
    # Dấu phẩy hoặc chấm phẩy hoặc hai chấm dính chữ (không đụng dấu chấm file extension)
    s = re.sub(r"([,;:])([a-zA-ZÀ-ỹ])", r"\1 \2", s)
    return s

