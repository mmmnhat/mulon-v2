"""Test T-14: Tích hợp CLIProxyAPI làm cổng model chính thức.

Quy tắc kiểm tra:
1. Nhận diện & Quản lý CLIProxyAPI:
   - Tìm kiếm file thực thi đa nền tảng (macOS, Linux, Windows), tôn trọng CLIPROXY_BINARY_PATH.
   - Kiểm tra sống/chết (TCP connect + GET /v1/models) qua probe_cliproxy_health.
   - Quản lý vòng đời (start, stop) qua CLIProxyManager, degrade nếu thiếu binary hoặc lỗi.
2. Quản lý danh sách Provider, Model & Tài khoản CLI:
   - detect_cliproxy_accounts: đọc cấu hình, che mờ định danh tài khoản (masking).
   - Bảo mật (Rule 5): KHÔNG trả về API key thật, token hay secret trong account metadata.
   - Phân loại model theo provider chính xác (Google, Anthropic, OpenAI, Muse, v.v.).
3. Nguyên tắc Proxy-only (127.0.0.1:8317) & Degrade:
   - validate_proxy_base_url vẫn khoá chặt localhost:8317.
   - Khi proxy down: báo rõ người dùng qua format_degrade_message, bot không sập.
4. API Endpoints Mini App:
   - GET /api/cliproxy/status, GET /api/cliproxy/models, GET /api/cliproxy/accounts.
"""

import asyncio
import json
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mulon.cliproxy import (
    DEFAULT_CLIPROXY_HOST,
    DEFAULT_CLIPROXY_PORT,
    CLIProxyManager,
    categorize_model_provider,
    detect_cliproxy_accounts,
    find_cliproxy_executable,
    mask_secret_identifier,
    probe_cliproxy_health,
)
from mulon.config import Config, validate_proxy_base_url


def test_mask_secret_identifier():
    assert mask_secret_identifier("dev@example.com") == "de***@example.com"
    assert mask_secret_identifier("a@b.com") == "a***@b.com"
    assert mask_secret_identifier("administrator") == "adm***or"
    assert mask_secret_identifier("key") == "k***"
    assert mask_secret_identifier("") == "tài khoản ẩn danh"
    assert mask_secret_identifier(None) == "tài khoản ẩn danh"


def test_categorize_model_provider():
    assert categorize_model_provider("gemini-3.8-flash") == "Google Gemini"
    assert categorize_model_provider("models/gemini-2.0-flash") == "Google Gemini"
    assert categorize_model_provider("claude-3-7-sonnet") == "Anthropic Claude"
    assert categorize_model_provider("gpt-4o") == "OpenAI"
    assert categorize_model_provider("o1-preview") == "OpenAI"
    assert categorize_model_provider("muse/muse-spark") == "Muse (muse2api)"
    assert categorize_model_provider("muse-spark") == "Muse (muse2api)"
    assert categorize_model_provider("deepseek-chat") == "DeepSeek"
    assert categorize_model_provider("qwen-max") == "Qwen"
    assert categorize_model_provider("codex-cli") == "Codex"
    assert categorize_model_provider("custom-private-model") == "Khác / Tuỳ chỉnh"
    assert categorize_model_provider("") == "Không xác định"


def test_find_cliproxy_executable_with_custom(tmp_path):
    fake_bin = tmp_path / ("cliproxy_test.exe" if sys.platform == "win32" else "cliproxy_test")
    fake_bin.write_text("#!/bin/sh\necho ok\n", encoding="utf-8")
    fake_bin.chmod(0o755)

    found = find_cliproxy_executable(str(fake_bin))
    assert found == fake_bin

    # Thử qua env CLIPROXY_BINARY_PATH
    with patch.dict(os.environ, {"CLIPROXY_BINARY_PATH": str(fake_bin)}):
        assert find_cliproxy_executable() == fake_bin


def test_find_cliproxy_executable_not_found():
    with patch.dict(os.environ, {"CLIPROXY_BINARY_PATH": "/duong/dan/khong/ton/tai/cliproxy"}):
        with patch("shutil.which", return_value=None):
            found = find_cliproxy_executable()
            assert found is None


def test_detect_cliproxy_accounts_rule_5_no_secrets(tmp_path):
    cfg_file = tmp_path / "cliproxy.json"
    cfg_data = {
        "openai-compatibility": [
            {
                "name": "muse2api",
                "prefix": "muse",
                "base-url": "http://127.0.0.1:18610/v1",
                "keys": [{"api-key": "SUPER_SECRET_KEY_NEVER_LEAK"}],
                "models": [{"name": "muse-spark"}],
            }
        ],
        "google": [
            {
                "email": "myaccount@gmail.com",
                "refresh_token": "RAW_REFRESH_TOKEN_SECRET",
                "models": ["gemini-3.8-flash"],
            }
        ],
        "anthropic": [
            {
                "user": "claude_user_pro",
                "session_key": "SECRET_SESSION_KEY",
                "models": ["claude-3-7-sonnet"],
            }
        ],
    }
    cfg_file.write_text(json.dumps(cfg_data), encoding="utf-8")

    accounts = detect_cliproxy_accounts(config_path=cfg_file)
    assert len(accounts) == 3

    acc_json = json.dumps(accounts)
    # Tuyệt đối không chứa secret trong đầu ra
    assert "SUPER_SECRET_KEY_NEVER_LEAK" not in acc_json
    assert "RAW_REFRESH_TOKEN_SECRET" not in acc_json
    assert "SECRET_SESSION_KEY" not in acc_json

    # Kiểm tra che thông tin
    email_acc = [a for a in accounts if a["provider"] == "google"][0]
    assert "myaccount@gmail.com" not in email_acc["account_id"]
    assert "my***@gmail.com" == email_acc["account_id"]


@pytest.mark.asyncio
async def test_probe_cliproxy_health_when_port_closed():
    # Sử dụng cổng chắc chắn đóng trên loopback (vd: 59999)
    res = await probe_cliproxy_health(host="127.0.0.1", port=59999, timeout_s=0.2)
    assert res["status"] == "down"
    assert res["running"] is False
    assert "đang đóng" in res["detail"]


@pytest.mark.asyncio
async def test_probe_cliproxy_health_when_ok():
    # Giả lập server HTTP trả về /v1/models trên cổng loopback ngẫu nhiên
    async def handle_client(reader, writer):
        await reader.read(1024)
        body = json.dumps({
            "data": [
                {"id": "gemini-3.8-flash"},
                {"id": "claude-3-7-sonnet"},
                {"id": "muse/muse-spark"},
            ]
        })
        resp = (
            f"HTTP/1.1 200 OK\r\n"
            f"Content-Type: application/json\r\n"
            f"Content-Length: {len(body)}\r\n"
            f"Connection: close\r\n\r\n"
            f"{body}"
        )
        writer.write(resp.encode("utf-8"))
        await writer.drain()
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(handle_client, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]

    try:
        res = await probe_cliproxy_health(host="127.0.0.1", port=port, timeout_s=1.0)
        assert res["status"] == "ok"
        assert res["running"] is True
        assert res["models_count"] == 3
        assert "gemini-3.8-flash" in res["models"]
        assert "Google Gemini" in res["providers"]
        assert "Anthropic Claude" in res["providers"]
        assert "Muse (muse2api)" in res["providers"]
    finally:
        server.close()
        await server.wait_closed()


@pytest.mark.asyncio
async def test_cliproxy_manager_status_and_degrade():
    cfg = SimpleNamespace(
        proxy_base_url="http://127.0.0.1:8317/v1",
        cliproxy_auto_start=False,
        cliproxy_binary_path=None,
        cliproxy_config_path=None,
        cliproxy_dir=None,
    )
    mgr = CLIProxyManager(cfg)

    with patch("mulon.cliproxy.probe_cliproxy_health", new_callable=AsyncMock) as mock_probe:
        mock_probe.return_value = {
            "status": "down",
            "running": False,
            "host": "127.0.0.1",
            "port": 8317,
            "detail": "Cổng 8317 đang đóng",
            "models_count": 0,
            "models": [],
            "providers": [],
        }
        st = await mgr.get_status(force_refresh=True)
        assert st["status"] == "down"
        assert st["running"] is False
        assert st["auto_start_configured"] is False

        # Kiểm tra thông báo degrade khi proxy chết (bot không sập)
        degrade_msg = mgr.format_degrade_message(st)
        assert "127.0.0.1:8317" in degrade_msg
        assert "không sập" in degrade_msg or "an toàn" in degrade_msg


@pytest.mark.asyncio
async def test_cliproxy_manager_start_already_running():
    cfg = SimpleNamespace(
        proxy_base_url="http://127.0.0.1:8317/v1",
        cliproxy_auto_start=True,
    )
    mgr = CLIProxyManager(cfg)

    with patch("mulon.cliproxy.probe_cliproxy_health", new_callable=AsyncMock) as mock_probe:
        mock_probe.return_value = {"running": True, "status": "ok"}
        res = await mgr.start_process()
        assert res["ok"] is True
        assert res["already_running"] is True


@pytest.mark.asyncio
async def test_cliproxy_manager_start_no_binary():
    cfg = SimpleNamespace(
        proxy_base_url="http://127.0.0.1:8317/v1",
        cliproxy_auto_start=True,
        cliproxy_binary_path="/duong/dan/khong/co",
    )
    mgr = CLIProxyManager(cfg)

    with patch("mulon.cliproxy.probe_cliproxy_health", new_callable=AsyncMock) as mock_probe:
        mock_probe.return_value = {"running": False, "status": "down"}
        with patch.object(mgr, "get_executable", return_value=None):
            res = await mgr.start_process()
            assert res["ok"] is False
            assert "Không tìm thấy file thực thi" in res["error"]


def test_proxy_only_invariant_remains_enforced():
    # Quy tắc bất biến: model CHỈ gọi qua proxy 127.0.0.1:8317 hoặc localhost:8317
    validate_proxy_base_url("http://127.0.0.1:8317/v1")
    validate_proxy_base_url("http://localhost:8317/v1")

    with pytest.raises(ValueError):
        validate_proxy_base_url("http://127.0.0.1:8000/v1")

    with pytest.raises(ValueError):
        validate_proxy_base_url("https://api.openai.com/v1")


def test_config_cliproxy_fields():
    # Kiểm tra Config dataclass và nạp env cho CLIProxyAPI
    c = Config()
    assert hasattr(c, "cliproxy_auto_start")
    assert hasattr(c, "cliproxy_binary_path")
    assert hasattr(c, "cliproxy_config_path")
    assert hasattr(c, "cliproxy_dir")
    assert c.cliproxy_auto_start is False

    with patch.dict(os.environ, {
        "CLIPROXY_AUTO_START": "1",
        "CLIPROXY_BINARY_PATH": "bin/cliproxyapi",
    }):
        loaded = Config.load()
        assert loaded.cliproxy_auto_start is True
        assert loaded.cliproxy_binary_path is not None
        assert str(Path("bin/cliproxyapi")) in str(loaded.cliproxy_binary_path)


@pytest.mark.asyncio
async def test_webapp_cliproxy_api_endpoints(tmp_path):
    from aiohttp import ClientSession
    from tests.test_v12_webapp_auth import TOKEN, OWNER, make_init_data
    from tests.test_v12_webapp_api import _start

    cfg = Config(
        db_path=tmp_path / "test.db",
        workspace_dir=tmp_path / "workspace",
        artifact_dir=tmp_path / "artifacts",
        dossier_dir=tmp_path / "dossier",
        policy_path=tmp_path / "policy.json",
        vault_path=tmp_path / "vault.json",
        telegram_bot_token=TOKEN,
        allowed_user_id=OWNER,
        webapp_port=0,
    )
    cfg2, memory, broker, server = await _start(cfg)
    try:
        init_data = make_init_data()
        headers = {"X-Telegram-Init-Data": init_data}

        async with ClientSession() as session:
            # 1. GET /api/cliproxy/status
            async with session.get(f"http://127.0.0.1:{server.port}/api/cliproxy/status", headers=headers) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data["ok"] is True
                assert "status" in data
                assert "port" in data
                assert data["port"] == 8317

            # 2. GET /api/cliproxy/models
            async with session.get(f"http://127.0.0.1:{server.port}/api/cliproxy/models", headers=headers) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data["ok"] is True
                assert isinstance(data["models"], list)

            # 3. GET /api/cliproxy/accounts
            async with session.get(f"http://127.0.0.1:{server.port}/api/cliproxy/accounts", headers=headers) as resp:
                assert resp.status == 200
                data = await resp.json()
                assert data["ok"] is True
                assert isinstance(data["accounts"], list)
    finally:
        await server.stop()
        await memory.close()

