"""MCP client thật (thiết kế mục 6, MCP-first) — Phase 3.

Dùng MCP Python SDK chính thức: kết nối server qua stdio theo cấu
hình `config/mcp_servers.json`, liệt kê tool của server và đăng ký
vào registry chung với tên `mcp_<server>_<tool>`. Session chết thì
tự reconnect 1 lần khi có lời gọi kế tiếp.

Degrade là nguyên tắc cứng: thiếu gói `mcp`, thiếu file cấu hình,
hay từng server lỗi — hệ thống vẫn chạy bình thường, chỉ mất phần
tool của server đó (ghi log + status để truy vết).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from contextlib import AsyncExitStack
from pathlib import Path
from typing import Any, Optional

from .tools import ToolSpec

logger = logging.getLogger("mulon.mcp")

try:  # gói mcp là dependency Phase 3, nhưng vắng thì degrade, không sập
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import get_default_environment, stdio_client

    HAS_MCP = True
except Exception:  # pragma: no cover - phụ thuộc môi trường
    HAS_MCP = False


def _safe_name(text: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_-]+", "_", text).strip("_") or "x"


def load_server_configs(path: str | Path) -> list[dict]:
    """Đọc file cấu hình MCP. Mọi lỗi đều trả [] (degrade)."""
    p = Path(path)
    if not p.is_file():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("đọc %s lỗi: %s", p, exc)
        return []
    servers = data.get("servers") if isinstance(data, dict) else None
    if not isinstance(servers, list):
        return []
    return [s for s in servers if isinstance(s, dict) and s.get("name")]


def _result_to_dict(result) -> dict:
    """CallToolResult của SDK -> cấu trúc tool nội bộ."""
    is_error = bool(getattr(result, "isError", False))
    structured = getattr(result, "structuredContent", None)
    if structured is not None:
        # FastMCP bọc giá trị nguyên thuỷ thành {"result": <giá trị>} —
        # bóc lớp bọc để agent nhận đúng giá trị server trả.
        if isinstance(structured, dict) and set(structured) == {"result"}:
            structured = structured["result"]
        return {"ok": not is_error, "result": structured}
    parts: list[str] = []
    for item in getattr(result, "content", None) or []:
        text = getattr(item, "text", None)
        if isinstance(text, str):
            parts.append(text)
        else:
            try:
                parts.append(json.dumps(item.model_dump(), ensure_ascii=False))
            except Exception:
                parts.append(str(item))
    text = "\n".join(parts)
    # Server trả JSON thì giữ dạng cấu trúc cho agent dễ dùng.
    try:
        parsed = json.loads(text)
        if isinstance(parsed, (dict, list)):
            return {"ok": not is_error, "result": parsed}
    except Exception:
        pass
    return {"ok": not is_error, "result": text}


class _Connection:
    def __init__(self, entry: dict):
        self.entry = entry
        self.name = str(entry["name"])
        self.stack: Optional[AsyncExitStack] = None
        self.session = None
        self.tools: list = []
        self.error: str = ""

    @property
    def connected(self) -> bool:
        return self.session is not None


class MCPManager:
    """Quản lý vòng đời các MCP server + cầu nối vào registry."""

    def __init__(self, cfg, config_path: str | Path):
        self.cfg = cfg
        self.config_path = Path(config_path)
        self.entries = load_server_configs(self.config_path)
        self._conns: dict[str, _Connection] = {}
        self._lock = asyncio.Lock()

    # ---------- vòng đời ----------
    async def start(self) -> None:
        if not HAS_MCP:
            logger.warning("gói 'mcp' chưa cài — bỏ qua MCP (degrade)")
            return
        enabled = [e for e in self.entries if e.get("enabled", False)]
        for entry in enabled:
            await self._connect(entry)

    async def _connect(self, entry: dict) -> Optional[_Connection]:
        conn = _Connection(entry)
        self._conns[conn.name] = conn
        timeout = float(entry.get("timeout_s") or
                        self.cfg.mcp_connect_timeout_s)
        try:
            await asyncio.wait_for(self._open(conn), timeout=timeout)
            logger.info("MCP server '%s' đã nối: %d tool",
                        conn.name, len(conn.tools))
        except Exception as exc:
            conn.error = f"{type(exc).__name__}: {exc}"
            conn.session = None
            logger.warning("MCP server '%s' nối lỗi (degrade): %s",
                           conn.name, conn.error)
        return conn

    async def _open(self, conn: _Connection) -> None:
        entry = conn.entry
        env = dict(get_default_environment())
        extra_env = entry.get("env") or {}
        if isinstance(extra_env, dict):
            env.update({str(k): str(v) for k, v in extra_env.items()})
        params = StdioServerParameters(
            command=str(entry["command"]),
            args=[str(a) for a in entry.get("args") or []],
            env=env,
            cwd=str(entry["cwd"]) if entry.get("cwd") else None,
        )
        stack = AsyncExitStack()
        read, write = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(read, write))
        await session.initialize()
        listed = await session.list_tools()
        conn.stack = stack
        conn.session = session
        conn.tools = list(listed.tools or [])
        conn.error = ""

    async def close(self) -> None:
        for conn in list(self._conns.values()):
            if conn.stack is not None:
                try:
                    await conn.stack.aclose()
                except Exception:
                    pass
            conn.stack = None
            conn.session = None

    async def _reconnect(self, name: str) -> Optional[_Connection]:
        conn = self._conns.get(name)
        if conn is None:
            return None
        if conn.stack is not None:
            try:
                await conn.stack.aclose()
            except Exception:
                pass
            conn.stack = None
            conn.session = None
        await self._connect(conn.entry)
        return self._conns.get(name)

    # ---------- gọi tool ----------
    async def call_tool(self, server: str, tool: str,
                        arguments: dict) -> dict:
        conn = self._conns.get(server)
        if conn is None:
            return {"ok": False, "error": f"MCP server không có: {server}"}
        timeout = float(conn.entry.get("call_timeout_s") or
                        self.cfg.mcp_call_timeout_s)
        for attempt in (1, 2):
            if conn.session is None:
                if attempt == 2:
                    return {"ok": False,
                            "error": f"MCP server '{server}' chưa kết nối"
                                     f" ({conn.error})"}
                conn = await self._reconnect(server) or conn
                continue
            try:
                result = await asyncio.wait_for(
                    conn.session.call_tool(tool, arguments or {}),
                    timeout=timeout,
                )
                return _result_to_dict(result)
            except Exception as exc:
                logger.warning(
                    "MCP call %s/%s lỗi (lần %d): %s — reconnect",
                    server, tool, attempt, exc,
                )
                conn.session = None  # đánh dấu chết, vòng sau reconnect
                if attempt == 2:
                    return {"ok": False,
                            "error": f"MCP {server}/{tool}: {exc}"}
        return {"ok": False, "error": "MCP call không rõ trạng thái"}

    # ---------- đăng ký vào registry chung ----------
    def register_into(self, registry) -> list[str]:
        """Đăng ký tool của mọi server đã nối. Trả tên tool nội bộ."""
        registered: list[str] = []
        for conn in self._conns.values():
            if not conn.connected:
                continue
            for tool in conn.tools:
                local = f"mcp_{_safe_name(conn.name)}_{_safe_name(tool.name)}"
                if registry.get(local) is not None:
                    continue
                schema = tool.inputSchema or {}
                if not isinstance(schema, dict) or \
                        schema.get("type") != "object":
                    schema = {
                        "type": "object",
                        "properties": schema.get("properties", {})
                        if isinstance(schema, dict) else {},
                        "required": schema.get("required", [])
                        if isinstance(schema, dict) else [],
                    }
                server_name, tool_name = conn.name, tool.name

                async def handler(_server=server_name, _tool=tool_name,
                                  **kwargs):
                    return await self.call_tool(_server, _tool, kwargs)

                registry.register(ToolSpec(
                    name=local,
                    description=(
                        f"[MCP:{server_name}] "
                        f"{tool.description or tool_name}"
                    ),
                    parameters=schema,
                    group=f"mcp:{server_name}",
                    timeout_s=float(conn.entry.get("call_timeout_s") or
                                    self.cfg.mcp_call_timeout_s) + 5,
                    handler=handler,
                ))
                registered.append(local)
        return registered

    def status(self) -> dict[str, Any]:
        return {
            name: {
                "connected": conn.connected,
                "tools": [t.name for t in conn.tools],
                "error": conn.error,
            }
            for name, conn in self._conns.items()
        }
