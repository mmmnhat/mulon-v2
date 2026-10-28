"""1.3.0: chuẩn hoá cấu hình import (spec marketplace mục 7) +
dấu vân tay (mục 5.9). Thuần logic, không cần async."""

from pathlib import Path

import pytest

from mulon.marketplace import (
    MarketplaceError, config_fingerprint, normalize_server_config,
    slugify_local_name, tool_fingerprint)


@pytest.fixture
def roots(tmp_path):
    return [tmp_path]


def _norm(raw, roots):
    return normalize_server_config(raw, source="manual",
                                   allowed_cwd_roots=roots)


def test_basic_stdio_manifest(roots):
    m = _norm({"command": "python3", "args": ["-m", "my_server"],
               "env": {"MODE": "dev"}}, roots)
    assert m["support_state"] == "supported"
    assert m["command"] == "python3"
    assert m["public_env"] == {"MODE": "dev"}
    assert m["setup_requirements"] == []
    assert m["package"] is None


def test_npx_package_pinned_and_unpinned(roots):
    m = _norm({"command": "npx",
               "args": ["-y", "@scope/pkg@1.2.3"]}, roots)
    assert m["package"] == {"ecosystem": "npm", "name": "@scope/pkg",
                            "version": "1.2.3", "pinned": True}
    assert any(w["code"] == "download_and_run"
               for w in m["warnings"])
    m2 = _norm({"command": "uvx", "args": ["some-tool"]}, roots)
    assert m2["package"]["pinned"] is False
    assert any(w["code"] == "unpinned_package"
               and w["severity"] == "high" for w in m2["warnings"])


def test_command_and_url_is_ambiguous(roots):
    with pytest.raises(MarketplaceError) as ei:
        _norm({"command": "python3", "url": "https://x.test/mcp"},
              roots)
    assert ei.value.code == "invalid_config"


def test_remote_url_supported(roots):
    m = _norm({"url": "https://mcp.example.com/sse"}, roots)
    assert m["support_state"] == "supported"
    assert m["transport"] == "http"
    assert m["url"] == "https://mcp.example.com/sse"
    m_dis = normalize_server_config(
        {"url": "https://mcp.example.com/sse"},
        source="manual", allowed_cwd_roots=roots, allow_remote=False)
    assert m_dis["support_state"] == "unsupported"
    codes = [r["code"] for r in m_dis["unsupported_reasons"]]
    assert "unsupported_transport" in codes


def test_secret_in_url_query_flagged(roots):
    m = _norm({"url": "https://x.test/mcp?api_key=abc123"}, roots)
    codes = [r["code"] for r in m["unsupported_reasons"]]
    assert "unsupported_auth_in_url" in codes


def test_shell_string_command_rejected(roots):
    m = _norm({"command": "npx -y some-server"}, roots)
    assert m["support_state"] == "unsupported"
    assert m["unsupported_reasons"][0]["code"] == \
        "unsupported_shell_config"
    m2 = _norm({"command": "bash", "args": ["-lc", "run.sh"]}, roots)
    assert m2["support_state"] == "unsupported"


def test_secret_literal_env_rejected(roots):
    with pytest.raises(MarketplaceError) as ei:
        _norm({"command": "python3",
               "env": {"API_KEY": "sk-live-real-value"}}, roots)
    assert ei.value.code == "secret_literal_rejected"


def test_empty_secret_env_becomes_requirement(roots):
    m = _norm({"command": "python3", "env": {"API_KEY": ""}}, roots)
    reqs = m["setup_requirements"]
    assert len(reqs) == 1
    assert reqs[0]["name"] == "API_KEY"
    assert reqs[0]["secret"] is True
    assert m["public_env"] == {}


def test_vault_ref_env_becomes_bound_requirement(roots):
    m = _norm({"command": "python3",
               "env": {"API_KEY": "vault:api-key-1"}}, roots)
    reqs = m["setup_requirements"]
    assert reqs[0]["bound_ref"] == "vault:api-key-1"


def test_top_level_secret_field_rejected(roots):
    with pytest.raises(MarketplaceError) as ei:
        _norm({"command": "python3", "apiKey": "xyz"}, roots)
    assert ei.value.code == "secret_literal_rejected"


def test_cwd_outside_roots_rejected(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    with pytest.raises(MarketplaceError) as ei:
        normalize_server_config(
            {"command": "python3", "cwd": "/etc"},
            source="manual", allowed_cwd_roots=[ws])
    assert ei.value.code == "invalid_config"
    m = normalize_server_config(
        {"command": "python3", "cwd": str(ws)},
        source="manual", allowed_cwd_roots=[tmp_path])
    assert m["cwd"] == str(ws.resolve())


def test_config_fingerprint_stable_and_sensitive():
    a = {"name": "s", "command": "python3", "args": ["-m", "x"],
         "env": {"A": "1"}, "enabled": True, "timeout_s": 5}
    b = {"timeout_s": 99, "enabled": False, "env": {"A": "1"},
         "args": ["-m", "x"], "command": "python3", "name": "s"}
    # Thứ tự khóa + enabled + timeout không làm đổi fingerprint.
    assert config_fingerprint(a) == config_fingerprint(b)
    c = dict(a, args=["-m", "y"])
    assert config_fingerprint(c) != config_fingerprint(a)
    d = dict(a, env_vault_refs={"API_KEY": "vault:k1"})
    assert config_fingerprint(d) != config_fingerprint(a)


def test_tool_fingerprint_order_free_but_content_bound():
    t1 = [{"name": "echo", "description": "d",
           "inputSchema": {"type": "object"}},
          {"name": "add", "description": "cộng",
           "inputSchema": {}}]
    t2 = list(reversed(t1))
    assert tool_fingerprint(t1) == tool_fingerprint(t2)
    t3 = [dict(t1[0], description="khác"), t1[1]]
    assert tool_fingerprint(t3) != tool_fingerprint(t1)
    t4 = [dict(t1[0], inputSchema={"type": "object",
                                   "required": ["x"]}), t1[1]]
    assert tool_fingerprint(t4) != tool_fingerprint(t1)


def test_slugify():
    assert slugify_local_name("My Server!") == "my-server"
    assert slugify_local_name("echo_test") == "echo_test"
    assert slugify_local_name("@@@") == "server"


def test_windows_paths_and_shell_distinction(roots):
    # Đường dẫn Windows chứa khoảng trắng và dấu gạch chéo ngược hợp lệ
    win_py = r"E:\New folder\lane1\.venv\Scripts\python.exe"
    m1 = _norm({"command": win_py, "args": ["-m", "server"]}, roots)
    assert m1["support_state"] == "supported"
    assert m1["command"] == win_py

    prog_files = r"C:\Program Files\Python312\python.exe"
    m2 = _norm({"command": prog_files}, roots)
    assert m2["support_state"] == "supported"
    assert m2["command"] == prog_files

    quoted = r'"C:\Program Files\Nodejs\node.exe"'
    m3 = _norm({"command": quoted}, roots)
    assert m3["support_state"] == "supported"
    assert m3["command"] == r"C:\Program Files\Nodejs\node.exe"

    # Lệnh shell có cờ/arguments trong command bị từ chối đúng
    m_shell_args = _norm({"command": r"C:\Python312\python.exe -m my_server"}, roots)
    assert m_shell_args["support_state"] == "unsupported"
    assert m_shell_args["unsupported_reasons"][0]["code"] == "unsupported_shell_config"

    # Shell binary có đuôi .exe bị từ chối đúng
    m_cmd = _norm({"command": "cmd.exe"}, roots)
    assert m_cmd["support_state"] == "unsupported"
    assert m_cmd["unsupported_reasons"][0]["code"] == "unsupported_shell_config"

    m_ps = _norm({"command": "powershell.exe"}, roots)
    assert m_ps["support_state"] == "unsupported"
    assert m_ps["unsupported_reasons"][0]["code"] == "unsupported_shell_config"

