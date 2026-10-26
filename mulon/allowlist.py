"""mulon.allowlist — Quản lý quyền sở hữu và allowlist bản cài đặt cho MuLon.

Cho phép mở khóa cài đặt cho bất kỳ chủ sở hữu nào (T-15), không khoá cứng một ID cá nhân.
Mặc định vẫn bảo vệ nghiêm ngặt: chỉ chủ sở hữu và các tài khoản được cấp quyền
trong allowlist local mới có thể tương tác với bot và Mini App.
"""

from __future__ import annotations

import json
import logging
import secrets
from pathlib import Path
from typing import Optional

logger = logging.getLogger("mulon.allowlist")


def load_allowlist(allowlist_path: Path) -> tuple[int, list[int]]:
    """Đọc allowlist từ file JSON local. Trả về (owner_id, [allowed_user_ids])."""
    if not allowlist_path.is_file():
        return 0, []
    try:
        data = json.loads(allowlist_path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return 0, []
        owner_id = int(data.get("owner_id") or 0)
        users: list[int] = []
        for u in data.get("allowed_users", []):
            try:
                uid = int(u)
                if uid > 0 and uid not in users:
                    users.append(uid)
            except (ValueError, TypeError):
                continue
        if owner_id > 0 and owner_id not in users:
            users.insert(0, owner_id)
        return owner_id, users
    except Exception as e:
        logger.warning("Không thể đọc allowlist từ %s: %s", allowlist_path, e)
        return 0, []


def save_allowlist(allowlist_path: Path, owner_id: int, allowed_users: list[int]) -> bool:
    """Lưu allowlist ra file JSON local."""
    try:
        allowlist_path.parent.mkdir(parents=True, exist_ok=True)
        unique_users: list[int] = []
        if owner_id > 0:
            unique_users.append(owner_id)
        for u in allowed_users:
            if u > 0 and u not in unique_users:
                unique_users.append(u)

        payload = {
            "owner_id": owner_id,
            "allowed_users": unique_users,
        }
        allowlist_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8")
        return True
    except Exception as e:
        logger.error("Lỗi ghi allowlist vào %s: %s", allowlist_path, e)
        return False


def add_allowed_user(allowlist_path: Path, user_id: int) -> tuple[bool, str]:
    """Thêm một user_id vào allowlist."""
    if user_id <= 0:
        return False, "ID người dùng không hợp lệ"
    owner_id, users = load_allowlist(allowlist_path)
    if user_id in users:
        return True, "Người dùng đã có trong danh sách allowlist"
    users.append(user_id)
    if owner_id <= 0:
        owner_id = user_id
    ok = save_allowlist(allowlist_path, owner_id, users)
    if ok:
        return True, f"Đã thêm người dùng {user_id} vào allowlist"
    return False, "Lỗi khi ghi file allowlist"


def remove_allowed_user(allowlist_path: Path, user_id: int) -> tuple[bool, str]:
    """Xóa một user_id khỏi allowlist (không cho phép xóa owner)."""
    owner_id, users = load_allowlist(allowlist_path)
    if user_id == owner_id:
        return False, "Không thể xóa chủ sở hữu (Owner) khỏi allowlist"
    if user_id not in users:
        return False, "Người dùng không nằm trong allowlist"
    users = [u for u in users if u != user_id]
    ok = save_allowlist(allowlist_path, owner_id, users)
    if ok:
        return True, f"Đã xóa người dùng {user_id} khỏi allowlist"
    return False, "Lỗi khi ghi file allowlist"


def get_or_create_claim_token(claim_path: Path) -> str:
    """Lấy hoặc tạo mã claim token ngẫu nhiên để xác thực chủ nhân lần chạy đầu."""
    if claim_path.is_file():
        try:
            tok = claim_path.read_text(encoding="utf-8").strip()
            if tok:
                return tok
        except Exception:
            pass
    try:
        claim_path.parent.mkdir(parents=True, exist_ok=True)
        tok = secrets.token_hex(4).upper()  # 8 ký tự hex dễ gõ, ví dụ: A1B2C3D4
        claim_path.write_text(tok, encoding="utf-8")
        return tok
    except Exception as e:
        logger.error("Không thể ghi claim token: %s", e)
        return secrets.token_hex(4).upper()


def verify_claim_token(claim_path: Path, token: str) -> bool:
    """Xác thực token người dùng gửi với claim token đang lưu."""
    if not claim_path.is_file():
        return False
    try:
        saved = claim_path.read_text(encoding="utf-8").strip()
        return bool(saved and secrets.compare_digest(saved.upper(), token.strip().upper()))
    except Exception:
        return False


def claim_ownership(claim_path: Path, allowlist_path: Path, token: str, user_id: int) -> tuple[bool, str]:
    """Xác thực token và nhận quyền chủ nhân cho Telegram user_id."""
    if not verify_claim_token(claim_path, token):
        return False, "Mã xác thực không đúng hoặc đã hết hạn"
    ok = save_allowlist(allowlist_path, owner_id=user_id, allowed_users=[user_id])
    if not ok:
        return False, "Lỗi lưu quyền chủ nhân vào hệ thống"
    try:
        claim_path.unlink()
    except OSError:
        pass
    return True, f"Tài khoản {user_id} đã nhận quyền chủ sở hữu thành công"
