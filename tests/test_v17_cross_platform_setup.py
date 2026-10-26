"""Kiểm thử cho tính năng mở khoá cài đặt và hỗ trợ đa nền tảng (T-15)."""

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mulon.allowlist import (
    add_allowed_user,
    claim_ownership,
    get_or_create_claim_token,
    load_allowlist,
    remove_allowed_user,
    save_allowlist,
    verify_claim_token,
)
from mulon.config import Config
from mulon.os_service import (
    LaunchdManager,
    SystemdManager,
    WindowsServiceManager,
    get_current_os,
    get_service_manager,
)
from mulon.paths import get_default_paths, get_platform_dirs, resolve_path
from mulon.setup_wizard import run_setup
from mulon.webapp_server import validate_init_data


def test_paths_resolve():
    base = Path("/tmp/mulon_test_base")
    p1 = resolve_path("data/test.db", base_dir=base)
    assert p1 == base / "data" / "test.db"

    # Absolute path
    p2 = resolve_path("/var/log/mulon.log", base_dir=base)
    assert str(p2).startswith("/var/log/mulon.log")


def test_paths_default_structure():
    base = Path(tempfile.mkdtemp(prefix="mulon_test_paths_"))
    paths = get_default_paths(use_platformdirs=False, project_root=base)
    assert paths["project_root"] == base
    assert paths["db_path"] == base / "data" / "mulon.db"
    assert paths["allowlist_path"] == base / "data" / "allowlist.json"
    assert paths["claim_token_path"] == base / "data" / "claim_token.txt"

    # Test platformdirs
    pdirs = get_platform_dirs()
    assert pdirs is not None


def test_allowlist_crud():
    with tempfile.TemporaryDirectory() as tmpdir:
        allow_file = Path(tmpdir) / "allowlist.json"

        # Ban đầu chưa có file
        owner, users = load_allowlist(allow_file)
        assert owner == 0
        assert users == []

        # Lưu allowlist
        ok = save_allowlist(allow_file, owner_id=111, allowed_users=[111, 222])
        assert ok is True
        owner, users = load_allowlist(allow_file)
        assert owner == 111
        assert 111 in users
        assert 222 in users

        # Thêm user
        ok, msg = add_allowed_user(allow_file, 333)
        assert ok is True
        _, users = load_allowlist(allow_file)
        assert 333 in users

        # Thêm user trùng
        ok, msg = add_allowed_user(allow_file, 333)
        assert ok is True
        assert users.count(333) == 1

        # Xóa user thường
        ok, msg = remove_allowed_user(allow_file, 222)
        assert ok is True
        _, users = load_allowlist(allow_file)
        assert 222 not in users

        # Không cho phép xóa owner
        ok, msg = remove_allowed_user(allow_file, 111)
        assert ok is False
        assert "Không thể xóa chủ sở hữu" in msg
        owner, _ = load_allowlist(allow_file)
        assert owner == 111


def test_claim_token_and_ownership():
    with tempfile.TemporaryDirectory() as tmpdir:
        claim_file = Path(tmpdir) / "claim.txt"
        allow_file = Path(tmpdir) / "allowlist.json"

        # Sinh token
        tok = get_or_create_claim_token(claim_file)
        assert len(tok) == 8
        assert claim_file.is_file()

        # Token đọc lại giữ nguyên
        tok2 = get_or_create_claim_token(claim_file)
        assert tok == tok2

        # Xác thực sai
        assert verify_claim_token(claim_file, "WRONGTOKEN") is False

        # Xác thực đúng (không phân biệt hoa thường)
        assert verify_claim_token(claim_file, tok.lower()) is True

        # Nhận quyền chủ bot bằng token
        ok, msg = claim_ownership(claim_file, allow_file, tok, user_id=999888)
        assert ok is True
        assert "thành công" in msg
        assert not claim_file.exists()  # Đã dọn file sau khi claim

        # Allowlist đã cập nhật owner 999888
        owner, users = load_allowlist(allow_file)
        assert owner == 999888
        assert 999888 in users


def test_config_load_with_allowlist():
    with tempfile.TemporaryDirectory() as tmpdir:
        allow_file = Path(tmpdir) / "allowlist.json"
        save_allowlist(allow_file, owner_id=777, allowed_users=[777, 888])

        # Test khi không set ALLOWED_USER_ID trong env
        with patch.dict(os.environ, {"MULON_ALLOWLIST_PATH": str(allow_file), "ALLOWED_USER_ID": "0"}):
            cfg = Config.load()
            assert cfg.allowed_user_id == 777
            assert 777 in cfg.allowed_user_ids
            assert 888 in cfg.allowed_user_ids
            assert cfg.is_user_allowed(777) is True
            assert cfg.is_user_allowed(888) is True
            assert cfg.is_user_allowed(999) is False
            assert cfg.is_user_allowed(0) is False
            assert cfg.is_user_allowed(None) is False

        # Test khi env ALLOWED_USER_ID ưu tiên ghi đè
        with patch.dict(os.environ, {"MULON_ALLOWLIST_PATH": str(allow_file), "ALLOWED_USER_ID": "555"}):
            cfg = Config.load()
            assert cfg.allowed_user_id == 555
            assert cfg.is_user_allowed(555) is True
            assert cfg.is_user_allowed(888) is True


def test_setup_wizard_non_interactive():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        ok = run_setup(
            bot_token="test_bot_token_123",
            owner_id=12345678,
            proxy_url="http://127.0.0.1:8317/v1",
            model_brain="gemini-3.8-flash",
            timezone="Asia/Ho_Chi_Minh",
            non_interactive=True,
            project_root=root,
        )
        assert ok is True
        env_file = root / ".env"
        assert env_file.is_file()
        content = env_file.read_text(encoding="utf-8")
        assert "test_bot_token_123" in content
        assert "ALLOWED_USER_ID=12345678" in content

        # Allowlist đã được tạo
        allow_file = root / "data" / "allowlist.json"
        owner, users = load_allowlist(allow_file)
        assert owner == 12345678
        assert 12345678 in users


def test_os_service_managers():
    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)

        # 1. Launchd
        lm = LaunchdManager(project_root=root)
        plist = lm._render_bot_plist()
        assert "com.mulon.bot" in plist
        assert str(root) in plist

        # 2. Systemd
        sm = SystemdManager(project_root=root)
        unit = sm._render_bot_unit()
        assert "mulon.main" in unit
        assert str(root) in unit

        # 3. Windows
        wm = WindowsServiceManager(project_root=root)
        wm._generate_bat_launchers()
        assert (root / "scripts" / "run_bot.bat").is_file()
        assert (root / "scripts" / "run_autowatch.bat").is_file()

        # Manager theo hệ điều hành
        cur_os = get_current_os()
        assert cur_os in ("darwin", "linux", "win32")
        mgr = get_service_manager(project_root=root)
        assert mgr is not None


def test_webapp_validate_init_data_with_allowlist():
    import hashlib
    import hmac
    import time
    from urllib.parse import urlencode

    token = "test_bot_token_webapp"
    user_data = json.dumps({"id": 222, "first_name": "TestUser"})
    auth_date = int(time.time())

    params = {
        "auth_date": str(auth_date),
        "user": user_data,
    }
    check_string = "\n".join(f"{k}={v}" for k, v in sorted(params.items()))
    secret = hmac.new(b"WebAppData", token.encode("utf-8"), hashlib.sha256).digest()
    sig = hmac.new(secret, check_string.encode("utf-8"), hashlib.sha256).hexdigest()
    params["hash"] = sig
    raw_init_data = urlencode(params)

    # Allowlist chứa 222
    res = validate_init_data(raw_init_data, token, allowed_user_id={111, 222})
    assert res is not None
    assert res["id"] == 222

    # Allowlist không chứa 222
    res_rejected = validate_init_data(raw_init_data, token, allowed_user_id={111, 333})
    assert res_rejected is None


@pytest.mark.asyncio
async def test_telegram_setup_claim_flow():
    from mulon.telegram_bot import TelegramSurface

    with tempfile.TemporaryDirectory() as tmpdir:
        root = Path(tmpdir)
        claim_file = root / "claim.txt"
        allow_file = root / "allowlist.json"
        tok = get_or_create_claim_token(claim_file)

        cfg = Config(
            telegram_bot_token="fake:token",
            allowed_user_id=0,
            allowed_user_ids=(),
            allowlist_path=allow_file,
            claim_token_path=claim_file,
        )
        surface = TelegramSurface(cfg=cfg, agent=MagicMock(), memory=MagicMock(), dossier=MagicMock())

        # Người dùng gửi /setup không kèm token khi chưa có owner
        msg_no_token = MagicMock()
        msg_no_token.from_user.id = 555666
        msg_no_token.text = "/setup"
        msg_no_token.answer = AsyncMock()
        await surface._handle_setup_command(msg_no_token)
        msg_no_token.answer.assert_called_once()
        assert "Bot này chưa có chủ sở hữu" in msg_no_token.answer.call_args[0][0]

        # Người dùng gửi /setup sai token
        msg_wrong_tok = MagicMock()
        msg_wrong_tok.from_user.id = 555666
        msg_wrong_tok.text = "/setup WRONGTOKEN"
        msg_wrong_tok.answer = AsyncMock()
        await surface._handle_setup_command(msg_wrong_tok)
        assert "Xác thực thất bại" in msg_wrong_tok.answer.call_args[0][0]

        # Người dùng gửi /setup đúng token -> Ghép nối thành công!
        msg_correct = MagicMock()
        msg_correct.from_user.id = 555666
        msg_correct.text = f"/setup {tok}"
        msg_correct.answer = AsyncMock()
        await surface._handle_setup_command(msg_correct)
        assert "Ghép nối thành công" in msg_correct.answer.call_args[0][0]
        assert surface.cfg.allowed_user_id == 555666

        # Khi đã là chủ sở hữu, gọi /setup để xem cấu hình
        msg_status = MagicMock()
        msg_status.from_user.id = 555666
        msg_status.text = "/setup"
        msg_status.answer = AsyncMock()
        await surface._handle_setup_command(msg_status)
        assert "Cấu hình bản cài MuLon" in msg_status.answer.call_args[0][0]

        # Chủ sở hữu thêm người dùng vào allowlist: /setup add 777888
        msg_add = MagicMock()
        msg_add.from_user.id = 555666
        msg_add.text = "/setup add 777888"
        msg_add.answer = AsyncMock()
        await surface._handle_setup_command(msg_add)
        assert "Đã thêm người dùng" in msg_add.answer.call_args[0][0]
        assert 777888 in surface.cfg.allowed_user_ids

        # Chủ sở hữu xóa người dùng: /setup remove 777888
        msg_rem = MagicMock()
        msg_rem.from_user.id = 555666
        msg_rem.text = "/setup remove 777888"
        msg_rem.answer = AsyncMock()
        await surface._handle_setup_command(msg_rem)
        assert "Đã xóa người dùng" in msg_rem.answer.call_args[0][0]
        assert 777888 not in surface.cfg.allowed_user_ids
