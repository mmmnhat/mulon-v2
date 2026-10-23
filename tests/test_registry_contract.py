"""Contract của registry: tên tool trong schema phải khớp tên đăng ký,
schema hợp lệ, mọi tool bọc lỗi thành cấu trúc (bài học Mulon cũ)."""

import json

from mulon.tools import build_default_registry
from tests.conftest import open_memory

EXPECTED_TOOLS = {
    "read_file", "write_file", "edit_file", "list_dir", "run_command",
    "web_fetch", "memory_search", "memory_get", "add_memory_fact", "now",
}


async def test_all_core_tools_registered(cfg):
    memory = await open_memory(cfg)
    reg = build_default_registry(cfg, memory)
    assert set(reg.names()) == EXPECTED_TOOLS
    await memory.close()


async def test_schema_names_match_registration(cfg):
    memory = await open_memory(cfg)
    reg = build_default_registry(cfg, memory)
    schemas = reg.schemas()
    schema_names = {s["function"]["name"] for s in schemas}
    assert schema_names == set(reg.names())
    for s in schemas:
        params = s["function"]["parameters"]
        assert params["type"] == "object"
        props = params.get("properties", {})
        for req in params.get("required", []):
            assert req in props, f"{s['function']['name']}: required '{req}' thiếu trong properties"
        json.dumps(s)  # schema phải serialize được
    await memory.close()


async def test_unknown_tool_returns_structured_error(cfg):
    memory = await open_memory(cfg)
    reg = build_default_registry(cfg, memory)
    result = await reg.execute("tool_khong_ton_tai", {})
    assert result["ok"] is False
    assert "error" in result
    await memory.close()


async def test_write_read_roundtrip_and_jail(cfg):
    memory = await open_memory(cfg)
    reg = build_default_registry(cfg, memory)
    w = await reg.execute("write_file", {"path": "note.txt", "content": "xin chào"})
    assert w["ok"] is True
    r = await reg.execute("read_file", {"path": "note.txt"})
    assert r["ok"] is True and "xin chào" in r["content"]
    # Ra ngoài workspace phải bị chặn
    escape = await reg.execute("read_file", {"path": "../secret.txt"})
    assert escape["ok"] is False
    await memory.close()


async def test_run_command_and_now(cfg):
    memory = await open_memory(cfg)
    reg = build_default_registry(cfg, memory)
    out = await reg.execute("run_command", {"command": "echo mulon-ok"})
    assert out["ok"] is True and "mulon-ok" in out["stdout"]
    now = await reg.execute("now", {})
    assert now["ok"] is True and "utc" in now
    await memory.close()
