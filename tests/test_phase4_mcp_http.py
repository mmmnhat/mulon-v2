"""Phase 4 — MCP streamable HTTP: nối server HTTP bằng SDK thật
(FastMCP + uvicorn nội bộ trong test), URL chết -> degrade sạch,
header auth lấy từ env theo tên biến (giá trị không lộ)."""

import json
import sys
import threading
import time
from dataclasses import replace
from pathlib import Path

import pytest

from mulon.mcp_client import (MCPManager, _http_headers, _transport_of,
                              load_server_configs)
from mulon.tools import ToolRegistry

ECHO_SERVER = Path(__file__).with_name("mcp_echo_server.py")


def _cfg_with_servers(cfg, tmp_path: Path, servers: list):
    path = tmp_path / "mcp_servers.json"
    path.write_text(json.dumps({"servers": servers}), encoding="utf-8")
    return replace(cfg, mcp_config_path=path)


def test_transport_detection():
    assert _transport_of({"name": "a", "url": "http://x/mcp"}) == "http"
    assert _transport_of({"name": "a", "transport": "http"}) == "http"
    assert _transport_of({"name": "a", "transport": "streamable-http"}) \
        == "http"
    assert _transport_of({"name": "a", "command": "python3"}) == "stdio"
    assert _transport_of({"name": "a", "transport": "stdio",
                          "url": "http://x"}) == "stdio"


def test_http_headers_auth_from_env(monkeypatch):
    monkeypatch.setenv("MY_MCP_TOKEN", "gia-tri-bi-mat")
    entry = {"name": "h", "url": "http://x/mcp",
             "auth_env": "MY_MCP_TOKEN",
             "headers": {"X-Trace": "1"}}
    headers = _http_headers(entry)
    assert headers["Authorization"] == "Bearer gia-tri-bi-mat"
    assert headers["X-Trace"] == "1"
    # env vắng -> không gắn header auth, không lỗi
    monkeypatch.delenv("MY_MCP_TOKEN")
    assert "Authorization" not in _http_headers(entry)
    # header tuỳ biến tên + tiền tố
    monkeypatch.setenv("K", "abc")
    custom = _http_headers({"auth_env": "K", "auth_header": "X-API-Key",
                            "auth_prefix": ""})
    assert custom == {"X-API-Key": "abc"}


async def test_http_dead_url_degrades(cfg, tmp_path):
    entry = {"name": "chet", "transport": "http",
             "url": "http://127.0.0.1:1/mcp", "enabled": True,
             "timeout_s": 5, "call_timeout_s": 5}
    cfg2 = _cfg_with_servers(cfg, tmp_path, [entry])
    manager = MCPManager(cfg2, cfg2.mcp_config_path)
    await manager.start()  # không được raise
    try:
        status = manager.status()
        assert status["chet"]["connected"] is False
        assert status["chet"]["transport"] == "http"
        assert status["chet"]["error"]
        assert manager.register_into(ToolRegistry()) == []
    finally:
        await manager.close()


@pytest.fixture
def http_echo_url():
    """Chạy FastMCP echo qua streamable HTTP bằng uvicorn (thread)."""
    uvicorn = pytest.importorskip("uvicorn")
    from mcp.server.fastmcp import FastMCP

    server_mcp = FastMCP("echo-http")

    @server_mcp.tool()
    def echo(text: str) -> str:
        """Trả lại nguyên văn chuỗi được đưa vào."""
        return f"echo:{text}"

    app = server_mcp.streamable_http_app()
    config = uvicorn.Config(app, host="127.0.0.1", port=0,
                            log_level="error")
    server = uvicorn.Server(config)
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(200):
        if server.started:
            break
        time.sleep(0.05)
    assert server.started, "uvicorn test không khởi động được"
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}/mcp"
    server.should_exit = True
    thread.join(timeout=5)


async def test_http_end_to_end(cfg, tmp_path, http_echo_url):
    entry = {"name": "httpecho", "transport": "http",
             "url": http_echo_url, "enabled": True,
             "timeout_s": 15, "call_timeout_s": 15}
    cfg2 = _cfg_with_servers(cfg, tmp_path, [entry])
    manager = MCPManager(cfg2, cfg2.mcp_config_path)
    await manager.start()
    try:
        status = manager.status()
        assert status["httpecho"]["connected"] is True, status
        assert status["httpecho"]["transport"] == "http"
        registry = ToolRegistry()
        registered = manager.register_into(registry)
        assert "mcp_httpecho_echo" in registered
        out = await registry.execute("mcp_httpecho_echo",
                                     {"text": "qua http"})
        assert out["ok"] is True
        assert out["result"] == "echo:qua http"
    finally:
        await manager.close()


async def test_stdio_still_works_alongside_http(cfg, tmp_path):
    """Thêm transport HTTP không làm gãy đường stdio cũ."""
    entry = {"name": "echo", "command": sys.executable,
             "args": [str(ECHO_SERVER)], "env": {}, "enabled": True,
             "timeout_s": 30, "call_timeout_s": 30}
    cfg2 = _cfg_with_servers(cfg, tmp_path, [entry])
    manager = MCPManager(cfg2, cfg2.mcp_config_path)
    await manager.start()
    try:
        assert manager.status()["echo"]["transport"] == "stdio"
        assert manager.status()["echo"]["connected"] is True
    finally:
        await manager.close()


def test_repo_mcp_config_has_http_example_disabled():
    entries = load_server_configs(
        Path(__file__).resolve().parent.parent
        / "config" / "mcp_servers.json")
    http_entries = [e for e in entries if _transport_of(e) == "http"]
    assert http_entries, "thiếu ví dụ server HTTP trong config mẫu"
    assert all(not e.get("enabled") for e in entries)
