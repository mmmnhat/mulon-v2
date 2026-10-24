"""MCP client thật (thiết kế mục 6, MCP-first) — Phase 3 + 4.

Dùng MCP Python SDK chính thức: kết nối server theo cấu hình
`config/mcp_servers.json` — qua stdio (Phase 3) hoặc streamable
HTTP (Phase 4, entry có `url`; header auth lấy từ biến env theo
tên `auth_env`, giá trị không vào log) — liệt kê tool của server
và đăng ký vào registry chung với tên `mcp_<server>_<tool>`.
Session chết thì tự reconnect 1 lần khi có lời gọi kế tiếp.

Degrade là nguyên tắc cứng: thiếu gói `mcp`, thiếu file cấu hình,
hay từng server lỗi — hệ thống vẫn chạy bình thường, chỉ mất phần
tool của server đó (ghi log + status để truy vết).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from contextlib import AsyncExitStack, suppress
from datetime import timedelta
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

try:  # streamable HTTP (Phase 4) — cùng SDK, import riêng để SDK cũ
    # thiếu module này thì stdio vẫn chạy.
    from mcp.client.streamable_http import streamablehttp_client

    HAS_MCP_HTTP = True
except Exception:  # pragma: no cover - phụ thuộc môi trường
    HAS_MCP_HTTP = False


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


def _transport_of(entry: dict) -> str:
    """'http' khi entry có url hoặc transport khai rõ; còn lại stdio."""
    declared = str(entry.get("transport") or "").lower()
    if declared in ("http", "streamable-http", "streamable_http"):
        return "http"
    if declared == "stdio":
        return "stdio"
    return "http" if entry.get("url") else "stdio"


def _http_headers(entry: dict) -> dict[str, str]:
    """Header cho server HTTP. Giá trị bí mật CHỈ đi qua tên biến
    env (`auth_env`) — không bao giờ ghi giá trị vào log/status."""
    headers: dict[str, str] = {}
    raw = entry.get("headers") or {}
    if isinstance(raw, dict):
        headers.update({str(k): str(v) for k, v in raw.items()})
    auth_env = entry.get("auth_env")
    if auth_env:
        secret = os.environ.get(str(auth_env), "")
        if secret:
            header_name = str(entry.get("auth_header") or "Authorization")
            prefix = str(entry.get("auth_prefix", "Bearer "))
            headers[header_name] = f"{prefix}{secret}"
    return headers


def _local_client_factory(headers=None, timeout=None, auth=None, **_kw):
    """httpx client factory cho streamablehttp_client.

    trust_env=False: server MCP (thường là local/mạng nhà) phải
    được nối thẳng — biến HTTP_PROXY/NO_PROXY của môi trường
    không được can thiệp vào tuyến này.
    """
    import httpx

    return httpx.AsyncClient(
        headers=headers, timeout=timeout, auth=auth,
        trust_env=False, follow_redirects=True)


class _Connection:
    def __init__(self, entry: dict):
        self.entry = entry
        self.name = str(entry["name"])
        self.transport = _transport_of(entry)
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
        # 1.3.0: resolver bí mật (Vault) do MarketplaceService gắn.
        # fn(ref) -> giá trị thật hoặc None. Chỉ resolve vào bản sao
        # trong bộ nhớ khi connect/probe; entry trên đĩa giữ ref.
        self._secret_resolver = None

    # ---------- bí mật qua Vault ref (1.3.0) ----------
    def set_secret_resolver(self, fn) -> None:
        """fn: callable(ref: str) -> Optional[str]."""
        self._secret_resolver = fn

    def _resolve_entry(self, entry: dict) -> dict:
        """Bản sao entry đã gắn giá trị bí mật từ Vault ref vào
        đúng vị trí (env/header/auth). Không có resolver hoặc
        entry không khai ref -> trả nguyên entry. Giá trị đã
        resolve KHÔNG bao giờ được ghi ra đĩa/log."""
        if self._secret_resolver is None:
            return entry
        if not any(k in entry for k in
                   ("env_vault_refs", "auth_vault_ref",
                    "header_vault_refs")):
            return entry
        resolved = dict(entry)
        env = dict(resolved.get("env") or {})
        for name, ref in (resolved.get("env_vault_refs")
                          or {}).items():
            value = self._secret_resolver(str(ref))
            if value is not None:
                env[str(name)] = value
            else:
                logger.warning(
                    "MCP '%s': không resolve được Vault ref cho "
                    "env %s (bỏ qua biến này)",
                    entry.get("name"), name)
        resolved["env"] = env
        headers = dict(resolved.get("headers") or {})
        for name, ref in (resolved.get("header_vault_refs")
                          or {}).items():
            value = self._secret_resolver(str(ref))
            if value is not None:
                headers[str(name)] = value
            else:
                logger.warning(
                    "MCP '%s': không resolve được Vault ref cho "
                    "header %s (bỏ qua header này)",
                    entry.get("name"), name)
        if resolved.get("auth_vault_ref"):
            value = self._secret_resolver(
                str(resolved["auth_vault_ref"]))
            if value is not None:
                header_name = str(resolved.get("auth_header")
                                  or "Authorization")
                prefix = str(resolved.get("auth_prefix", "Bearer "))
                headers[header_name] = f"{prefix}{value}"
                # Đã có vault auth: bỏ auth_env để _http_headers
                # không ghi đè bằng đường env legacy.
                resolved.pop("auth_env", None)
            else:
                logger.warning(
                    "MCP '%s': không resolve được Vault ref cho "
                    "auth chính", entry.get("name"))
        resolved["headers"] = headers
        return resolved

    # ---------- vòng đời ----------
    async def start(self) -> None:
        if not HAS_MCP:
            logger.warning("gói 'mcp' chưa cài — bỏ qua MCP (degrade)")
            return
        enabled = [e for e in self.entries if e.get("enabled", False)]
        for entry in enabled:
            await self._connect(entry)

    async def _connect(self, entry: dict) -> Optional[_Connection]:
        conn = _Connection(self._resolve_entry(entry))
        self._conns[conn.name] = conn
        timeout = float(entry.get("timeout_s") or
                        self.cfg.mcp_connect_timeout_s)
        try:
            await asyncio.wait_for(self._open(conn), timeout=timeout)
            logger.info("MCP server '%s' đã nối: %d tool",
                        conn.name, len(conn.tools))
        except asyncio.CancelledError as exc:
            # Cancel scope của anyio (trong SDK) đôi khi "rò" một
            # CancelledError ra ngoài khi kết nối chết giữa chừng,
            # dù không ai hủy task này thật. Chỉ nuốt khi tầng
            # asyncio không ghi nhận yêu cầu hủy (cancelling()==0);
            # hủy thật từ bên ngoài thì để lan ra như thường.
            task = asyncio.current_task()
            if task is not None and task.cancelling() > 0:
                raise
            conn.error = ("connect_failed: CancelledError: kết nối bị "
                          "hủy giữa chừng (server không phản hồi?)")
            conn.session = None
            logger.warning("MCP server '%s' nối lỗi (degrade): %s",
                           conn.name, conn.error)
        except BaseExceptionGroup as exc:
            # SDK/anyio bọc lỗi kết nối trong ExceptionGroup.
            first = exc.exceptions[0] if exc.exceptions else exc
            conn.error = f"{type(first).__name__}: {first}"
            conn.session = None
            logger.warning("MCP server '%s' nối lỗi (degrade): %s",
                           conn.name, conn.error)
        except Exception as exc:
            conn.error = f"{type(exc).__name__}: {exc}"
            conn.session = None
            logger.warning("MCP server '%s' nối lỗi (degrade): %s",
                           conn.name, conn.error)
        return conn

    async def _open(self, conn: _Connection) -> None:
        if conn.transport == "http":
            await self._open_http(conn)
            return
        await self._open_stdio(conn)

    async def _open_http(self, conn: _Connection) -> None:
        if not HAS_MCP_HTTP:
            raise RuntimeError("SDK thiếu client streamable HTTP")
        entry = conn.entry
        url = str(entry.get("url") or "")
        if not url:
            raise ValueError("server HTTP thiếu 'url' trong cấu hình")
        connect_timeout = float(entry.get("timeout_s") or
                                self.cfg.mcp_connect_timeout_s)
        call_timeout = float(entry.get("call_timeout_s") or
                             self.cfg.mcp_call_timeout_s)
        stack = AsyncExitStack()
        try:
            read, write, _sid = await stack.enter_async_context(
                streamablehttp_client(
                    url,
                    headers=_http_headers(entry) or None,
                    timeout=timedelta(seconds=connect_timeout),
                    sse_read_timeout=timedelta(seconds=call_timeout),
                    httpx_client_factory=_local_client_factory,
                )
            )
            session = await stack.enter_async_context(
                ClientSession(read, write))
            await session.initialize()
            listed = await session.list_tools()
        except BaseException:
            # Dọn stack khi mở nửa vời; lỗi dọn dẹp là phụ, lỗi gốc
            # mới là thứ cần ghi nhận — đừng để nó che lỗi gốc.
            with suppress(Exception):
                await stack.aclose()
            raise
        conn.stack = stack
        conn.session = session
        conn.tools = list(listed.tools or [])
        conn.error = ""

    async def _open_stdio(self, conn: _Connection) -> None:
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

    # ---------- probe tách rời (1.3.0, spec marketplace 9.5) ----
    async def probe_entry(self, entry: dict,
                          timeout_s: Optional[float] = None) -> dict:
        """Kết nối thử MỘT entry mà không đăng ký tool, không giữ
        session trong manager: initialize + list_tools rồi đóng
        chắc chắn. Entry được resolve Vault ref trong bộ nhớ như
        đường connect thật. Trả {ok, latency_ms, tools, error_code,
        error} — error đã rút gọn, không chứa giá trị bí mật."""
        import time as _time

        if not HAS_MCP:
            return {"ok": False, "latency_ms": 0, "tools": [],
                    "error_code": "probe_failed",
                    "error": "gói 'mcp' chưa được cài trên máy này"}
        conn = _Connection(self._resolve_entry(entry))
        timeout = float(timeout_s or entry.get("timeout_s")
                        or self.cfg.mcp_connect_timeout_s)
        started = _time.monotonic()
        try:
            await asyncio.wait_for(self._open(conn), timeout=timeout)
        except (asyncio.TimeoutError, TimeoutError):
            return {"ok": False,
                    "latency_ms": int((_time.monotonic() - started)
                                      * 1000),
                    "tools": [], "error_code": "probe_timeout",
                    "error": f"quá {timeout:.0f}s không kết nối được"}
        except Exception as exc:
            return {"ok": False,
                    "latency_ms": int((_time.monotonic() - started)
                                      * 1000),
                    "tools": [], "error_code": "probe_failed",
                    "error": f"{type(exc).__name__}: {exc}"[:300]}
        tools = [{
            "name": str(t.name),
            "description": str(getattr(t, "description", "") or ""),
            "inputSchema": (t.inputSchema
                            if isinstance(t.inputSchema, dict)
                            else {}),
        } for t in conn.tools]
        latency = int((_time.monotonic() - started) * 1000)
        if conn.stack is not None:
            try:
                await conn.stack.aclose()
            except Exception:
                pass
            conn.stack = None
            conn.session = None
        return {"ok": True, "latency_ms": latency, "tools": tools,
                "error_code": "", "error": ""}

    def tool_snapshot(self) -> dict[str, list[dict]]:
        """Ảnh chụp tool của các server ĐÃ NỐI trong manager:
        {server_name: [{name, description, inputSchema}]} — dùng
        cho boot gate đối chiếu dấu vân tay (marketplace 9.7)."""
        out: dict[str, list[dict]] = {}
        for name, conn in self._conns.items():
            if not conn.connected:
                continue
            out[name] = [{
                "name": str(t.name),
                "description": str(getattr(t, "description", "")
                                   or ""),
                "inputSchema": (t.inputSchema
                                if isinstance(t.inputSchema, dict)
                                else {}),
            } for t in conn.tools]
        return out

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
    def register_into(self, registry,
                      exclude: Optional[set] = None) -> list[str]:
        """Đăng ký tool của mọi server đã nối. Trả tên tool nội bộ.

        ``exclude``: tên server KHÔNG đăng ký (1.3.0: boot gate
        của marketplace giữ tool của server chưa đạt đối chiếu)."""
        exclude = exclude or set()
        registered: list[str] = []
        for conn in self._conns.values():
            if not conn.connected or conn.name in exclude:
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
                "transport": conn.transport,
                "tools": [t.name for t in conn.tools],
                "error": conn.error,
            }
            for name, conn in self._conns.items()
        }
