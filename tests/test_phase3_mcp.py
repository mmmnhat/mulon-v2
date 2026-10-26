"""Phase 3 — MCP client thật: nối server stdio bằng SDK chính thức,
đăng ký tool vào registry chung, gọi end-to-end; server lỗi thì
degrade sạch."""

import json
import sys
from dataclasses import replace
from pathlib import Path

from mulon.mcp_client import MCPManager, load_server_configs
from mulon.tools import ToolRegistry
from tests.conftest import open_memory  # noqa: F401  (giữ import nhất quán)

ECHO_SERVER = Path(__file__).with_name("mcp_echo_server.py")


def _cfg_with_servers(cfg, tmp_path: Path, servers: list) -> object:
    path = tmp_path / "mcp_servers.json"
    path.write_text(json.dumps({"servers": servers}), encoding="utf-8")
    return replace(cfg, mcp_config_path=path)


def _echo_entry(**over):
    entry = {
        "name": "echo",
        "command": sys.executable,
        "args": [str(ECHO_SERVER)],
        "env": {},
        "enabled": True,
        "timeout_s": 30,
        "call_timeout_s": 30,
    }
    entry.update(over)
    return entry


async def test_mcp_end_to_end_echo(cfg, tmp_path):
    cfg2 = _cfg_with_servers(cfg, tmp_path, [_echo_entry()])
    manager = MCPManager(cfg2, cfg2.mcp_config_path)
    await manager.start()
    try:
        status = manager.status()
        assert status["echo"]["connected"] is True
        assert "echo" in status["echo"]["tools"]

        registry = ToolRegistry()
        registered = manager.register_into(registry)
        assert "mcp_echo_echo" in registered
        assert "mcp_echo_add" in registered

        out = await registry.execute("mcp_echo_echo", {"text": "xin chào"})
        assert out["ok"] is True
        assert out["result"] == "echo:xin chào"

        out_add = await registry.execute("mcp_echo_add", {"a": 2, "b": 40})
        assert out_add["ok"] is True
        assert out_add["result"] == 42
    finally:
        await manager.close()


async def test_mcp_bad_server_degrades(cfg, tmp_path):
    cfg2 = _cfg_with_servers(cfg, tmp_path, [
        _echo_entry(name="hỏng", command="/khong/ton/tai/mcp-server-xyz"),
    ])
    manager = MCPManager(cfg2, cfg2.mcp_config_path)
    await manager.start()  # không được raise
    try:
        status = manager.status()
        assert status["hỏng"]["connected"] is False
        assert status["hỏng"]["error"]
        registry = ToolRegistry()
        assert manager.register_into(registry) == []
        out = await manager.call_tool("hỏng", "echo", {"text": "x"})
        assert out["ok"] is False
    finally:
        await manager.close()


async def test_mcp_missing_config_is_empty(cfg, tmp_path):
    missing = tmp_path / "khong_co.json"
    assert load_server_configs(missing) == []
    manager = MCPManager(cfg, missing)
    await manager.start()
    assert manager.status() == {}
    await manager.close()


async def test_mcp_disabled_server_not_started(cfg, tmp_path):
    cfg2 = _cfg_with_servers(cfg, tmp_path, [_echo_entry(enabled=False)])
    manager = MCPManager(cfg2, cfg2.mcp_config_path)
    await manager.start()
    try:
        assert manager.status() == {}
    finally:
        await manager.close()


def test_mcp_env_placeholder_expansion(tmp_path, monkeypatch):
    """Vá audit hardcode 2026-10-26: ${VAR} trong env của mcp config
    được mở rộng từ environ; biến thiếu thì bỏ key, không để URL
    tunnel chết cứng lọt xuống MCP server."""
    cfg_file = tmp_path / "mcp_servers.json"
    cfg_file.write_text(json.dumps({"servers": {"gw": {
        "command": "uvx",
        "env": {"GOOGLE_OAUTH_REDIRECT_URI": "${WEBAPP_URL}/oauth2callback",
                "OTHER": "${MISSING_VAR_XYZ}/x", "PLAIN": "ok"}}}}),
        encoding="utf-8")
    monkeypatch.setenv("WEBAPP_URL", "https://abc.trycloudflare.com")
    monkeypatch.delenv("MISSING_VAR_XYZ", raising=False)
    entries = load_server_configs(cfg_file)
    env = entries[0]["env"]
    assert env["GOOGLE_OAUTH_REDIRECT_URI"] == "https://abc.trycloudflare.com/oauth2callback"
    assert "OTHER" not in env
    assert env["PLAIN"] == "ok"
