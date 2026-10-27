"""Kiểm thử hồi quy cho các bản vá lỗi eval vàng T-33.

Bao gồm:
1. Ca tool-list-dir: list_dir(".") phải neo vào workspace_dir thay vì repo root.
2. Ca self-read-own-source: _resolve_for_file_tool ưu tiên file trong workspace nếu tồn tại
   (cho phép mock file trong test/eval), và fallback về codebase nếu không có trong workspace.
3. Tự nhận thức MCP Marketplace: build_self_knowledge chứa chỉ dẫn về Chợ MCP,
   Công cụ kết nối, Mini App, và quy tắc local / miễn phí.
"""

from pathlib import Path
import pytest
from mulon.tools import build_default_registry, _resolve_for_file_tool
from mulon.agent import build_self_knowledge
from mulon.memory import Memory


def test_list_dir_resolves_to_workspace(cfg):
    """Ca tool-list-dir: list_dir('.') phải neo vào workspace_dir."""
    ws = Path(cfg.workspace_dir)
    (ws / "a.txt").write_text("hello a", encoding="utf-8")
    (ws / "b.txt").write_text("hello b", encoding="utf-8")

    # Kiểm tra resolver
    resolved = _resolve_for_file_tool(cfg, ".")
    assert resolved == ws.resolve()

    resolved_empty = _resolve_for_file_tool(cfg, "")
    assert resolved_empty == ws.resolve()


@pytest.mark.asyncio
async def test_list_dir_tool_execution(cfg):
    """Chạy hàm list_dir thật qua ToolRegistry và kiểm tra danh sách file."""
    ws = Path(cfg.workspace_dir)
    (ws / "file1.txt").write_text("content 1", encoding="utf-8")
    (ws / "file2.txt").write_text("content 2", encoding="utf-8")

    memory = await Memory.open(cfg.db_path)
    try:
        reg = build_default_registry(cfg, memory)
        list_tool = reg.get("list_dir")
        assert list_tool is not None

        res = await list_tool.handler(path=".")
        assert res.get("ok") is True
        names = [entry["name"] for entry in res.get("entries", [])]
        assert "file1.txt" in names
        assert "file2.txt" in names
        # Không được lẫn các file của project root như AGENTS.md, README.md
        assert "AGENTS.md" not in names
    finally:
        await memory.close()


def test_self_read_own_source_workspace_precedence(cfg):
    """Ca self-read-own-source: ưu tiên file trong workspace nếu mock tồn tại."""
    ws = Path(cfg.workspace_dir)
    mock_dir = ws / "mulon"
    mock_dir.mkdir(parents=True, exist_ok=True)
    mock_file = mock_dir / "tools.py"
    mock_file.write_text("# mock tools.py with read_file", encoding="utf-8")

    # Khi có file trong workspace, phải resolve về workspace
    p = _resolve_for_file_tool(cfg, "mulon/tools.py")
    assert p == mock_file.resolve()

    # Khi không có file trong workspace, fallback về repo root
    p_main = _resolve_for_file_tool(cfg, "mulon/main.py")
    project_root = Path(__file__).resolve().parent.parent
    assert p_main == (project_root / "mulon" / "main.py").resolve()


def test_self_knowledge_contains_mcp_marketplace(cfg):
    """Tự nhận thức về MCP và Marketplace phải có trong build_self_knowledge."""
    knowledge = build_self_knowledge(cfg, None)
    assert "CHỢ MCP & CÔNG CỤ KẾT NỐI" in knowledge
    assert "Mini App" in knowledge
    assert "Công cụ kết nối" in knowledge
    assert "miễn phí" in knowledge
    assert "local" in knowledge
