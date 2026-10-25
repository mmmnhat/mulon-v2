"""Tests for self-evolution tools and codebase path resolution."""

import pytest
from pathlib import Path
from mulon.evolution import register_evolution_tools
from mulon.tools import ToolRegistry, _resolve_for_file_tool, _resolve_in_workspace


@pytest.mark.asyncio
async def test_evolution_tools_registration(cfg):
    reg = ToolRegistry()
    register_evolution_tools(reg, cfg)
    assert "restart_bot" in reg.names()
    spec = reg.get("restart_bot")
    assert spec is not None
    assert spec.group == "system"


def test_codebase_file_resolution(cfg):
    # Đường dẫn trỏ vào mulon/ phải neo vào project root
    p = _resolve_for_file_tool(cfg, "mulon/main.py")
    assert p.name == "main.py"
    assert "mulon" in p.parts

    # Đường dẫn file thường vẫn neo vào workspace
    p_ws = _resolve_for_file_tool(cfg, "workspace_file.txt")
    assert Path(cfg.workspace_dir).resolve() in p_ws.parents or p_ws == Path(cfg.workspace_dir).resolve()

    # Thử escape ngoài vùng cho phép vẫn bị chặn
    with pytest.raises(PermissionError):
        _resolve_for_file_tool(cfg, "../escape.txt")
