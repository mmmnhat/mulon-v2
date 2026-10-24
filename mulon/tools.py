"""Tool registry + tool lõi (thiết kế mục 6).

Mỗi tool đăng ký kèm: JSON schema, nhóm, timeout. Registry bọc mọi
lỗi thành cấu trúc {"ok": bool, ...} — tool hỏng không bao giờ làm
sập vòng lặp. Đây là lớp contract test sẽ khóa: tên tool trong schema
phải khớp tên đăng ký (bài học lỗi /tasks add của Mulon cũ).

Giai đoạn này là tool native; MCP client cắm vào cùng registry ở
Phase 3.
"""

from __future__ import annotations

import asyncio
import html
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional

Handler = Callable[..., Awaitable[Any]]


@dataclass
class ToolSpec:
    name: str
    description: str
    parameters: dict  # JSON schema cho object arguments
    group: str
    timeout_s: float
    handler: Handler


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolSpec] = {}

    def register(self, spec: ToolSpec) -> ToolSpec:
        if spec.name in self._tools:
            raise ValueError(f"tool trùng tên: {spec.name}")
        self._tools[spec.name] = spec
        return spec

    def get(self, name: str) -> Optional[ToolSpec]:
        return self._tools.get(name)

    def names(self) -> list[str]:
        return sorted(self._tools)

    def specs(self) -> list[ToolSpec]:
        return [self._tools[n] for n in self.names()]

    def schemas(self, names: Optional[list[str]] = None) -> list[dict]:
        """Xuất OpenAI function-calling schema cho các tool được chọn."""
        chosen = self.specs() if names is None else [
            self._tools[n] for n in names if n in self._tools
        ]
        return [
            {
                "type": "function",
                "function": {
                    "name": spec.name,
                    "description": spec.description,
                    "parameters": spec.parameters,
                },
            }
            for spec in chosen
        ]

    async def execute(self, name: str, arguments: dict) -> dict:
        """Chạy 1 tool, luôn trả cấu trúc — không bao giờ raise ra ngoài."""
        spec = self._tools.get(name)
        if spec is None:
            return {"ok": False, "error": f"tool không tồn tại: {name}"}
        try:
            result = await asyncio.wait_for(
                spec.handler(**(arguments or {})), timeout=spec.timeout_s
            )
        except asyncio.TimeoutError:
            return {"ok": False, "error": f"tool {name} timeout sau {spec.timeout_s}s"}
        except TypeError as exc:
            return {"ok": False, "error": f"sai tham số cho {name}: {exc}"}
        except Exception as exc:  # noqa: BLE001 - bọc lỗi là chủ đích
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"}
        if isinstance(result, dict) and "ok" in result:
            return result
        return {"ok": True, "result": result}


# ---------------------------------------------------------------------------
# Tool lõi
# ---------------------------------------------------------------------------

def _resolve_in_workspace(cfg, raw: str) -> Path:
    """Đường dẫn tool luôn neo vào workspace; ra ngoài phải được bật cờ."""
    base = Path(cfg.workspace_dir).resolve()
    p = Path(raw or ".").expanduser()
    resolved = p.resolve() if p.is_absolute() else (base / p).resolve()
    if not cfg.allow_outside_workspace:
        if resolved != base and base not in resolved.parents:
            raise PermissionError(
                f"đường dẫn ngoài workspace bị chặn: {raw} "
                "(bật ALLOW_OUTSIDE_WORKSPACE=1 nếu thật sự cần)"
            )
    return resolved


def _resolve_for_file_tool(cfg, raw: str) -> Path:
    """Neo của các file tool: workspace HOẶC thư mục dossier.

    Đường tương đối vẫn neo vào workspace như cũ. Kết quả resolve
    chỉ được chấp nhận khi rơi vào đúng 1 trong 2 vùng — thư mục
    dossier được mở thêm để agent điền IDENTITY.md/USER.md hoàn
    tất nghi lễ BOOTSTRAP (mục 16.10). Ngoài cả hai vùng vẫn chặn
    như cũ. run_command KHÔNG dùng resolver này (chỉ workspace).
    """
    base = Path(cfg.workspace_dir).resolve()
    p = Path(raw or ".").expanduser()
    resolved = p.resolve() if p.is_absolute() else (base / p).resolve()
    if cfg.allow_outside_workspace:
        return resolved
    dossier_base = Path(cfg.dossier_dir).resolve()
    for root in (base, dossier_base):
        if resolved == root or root in resolved.parents:
            return resolved
    raise PermissionError(
        f"đường dẫn ngoài workspace/dossier bị chặn: {raw} "
        "(bật ALLOW_OUTSIDE_WORKSPACE=1 nếu thật sự cần)"
    )


def build_default_registry(cfg, memory) -> ToolRegistry:
    reg = ToolRegistry()

    def spec(name, desc, params, group, timeout):
        def deco(fn):
            reg.register(ToolSpec(name, desc, params, group, timeout, fn))
            return fn

        return deco

    # --- file ---
    @spec(
        "read_file",
        "Đọc file trong workspace hoặc thư mục dossier "
        "(mặc định tối đa 400 dòng).",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "start_line": {"type": "integer", "default": 1},
                "end_line": {"type": "integer", "default": 0},
            },
            "required": ["path"],
        },
        "file", 15,
    )
    async def read_file(path: str, start_line: int = 1, end_line: int = 0):
        p = _resolve_for_file_tool(cfg, path)
        if not p.is_file():
            return {"ok": False, "error": f"không thấy file: {path}"}
        lines = p.read_text(encoding="utf-8", errors="replace").splitlines()
        start = max(1, int(start_line))
        end = int(end_line) if end_line else min(len(lines), start + 399)
        shown = lines[start - 1: end]
        return {
            "ok": True,
            "path": str(p),
            "total_lines": len(lines),
            "shown_lines": f"{start}-{start + len(shown) - 1}" if shown else "0",
            "content": "\n".join(shown),
        }

    @spec(
        "write_file",
        "Ghi (tạo mới/ghi đè) file trong workspace hoặc thư mục dossier.",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
        "file", 15,
    )
    async def write_file(path: str, content: str):
        p = _resolve_for_file_tool(cfg, path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
        if memory is not None:
            await memory.append_ledger(str(p), "write_file", content)
        return {"ok": True, "path": str(p), "bytes_written": len(content.encode())}

    @spec(
        "edit_file",
        "Thay đúng 1 đoạn văn bản khớp chính xác trong file "
        "(workspace hoặc thư mục dossier).",
        {
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "old_text": {"type": "string"},
                "new_text": {"type": "string"},
            },
            "required": ["path", "old_text", "new_text"],
        },
        "file", 15,
    )
    async def edit_file(path: str, old_text: str, new_text: str):
        p = _resolve_for_file_tool(cfg, path)
        if not p.is_file():
            return {"ok": False, "error": f"không thấy file: {path}"}
        text = p.read_text(encoding="utf-8")
        if old_text not in text:
            return {"ok": False, "error": "old_text không khớp trong file"}
        updated = text.replace(old_text, new_text, 1)
        p.write_text(updated, encoding="utf-8")
        if memory is not None:
            await memory.append_ledger(str(p), "edit_file", updated)
        return {"ok": True, "path": str(p)}

    @spec(
        "list_dir",
        "Liệt kê thư mục trong workspace hoặc thư mục dossier.",
        {
            "type": "object",
            "properties": {"path": {"type": "string", "default": "."}},
            "required": [],
        },
        "file", 10,
    )
    async def list_dir(path: str = "."):
        p = _resolve_for_file_tool(cfg, path)
        if not p.is_dir():
            return {"ok": False, "error": f"không phải thư mục: {path}"}
        entries = [
            {"name": e.name, "type": "dir" if e.is_dir() else "file"}
            for e in sorted(p.iterdir(), key=lambda x: x.name)
            if not e.name.startswith(".")
        ]
        return {"ok": True, "path": str(p), "entries": entries[:200]}

    # --- shell ---
    @spec(
        "run_command",
        "Chạy lệnh shell trong workspace. cwd tường minh, có timeout.",
        {
            "type": "object",
            "properties": {
                "command": {"type": "string"},
                "cwd": {"type": "string", "default": ""},
                "timeout": {"type": "integer", "default": 60},
            },
            "required": ["command"],
        },
        "shell", 130,
    )
    async def run_command(command: str, cwd: str = "", timeout: int = 60):
        workdir = _resolve_in_workspace(cfg, cwd) if cwd else Path(
            cfg.workspace_dir
        ).resolve()
        workdir.mkdir(parents=True, exist_ok=True)
        proc = await asyncio.create_subprocess_shell(
            command,
            cwd=str(workdir),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(
                proc.communicate(), timeout=float(timeout)
            )
        except asyncio.TimeoutError:
            proc.kill()
            return {"ok": False, "error": f"lệnh timeout sau {timeout}s"}
        return {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stdout": out.decode("utf-8", "replace")[-8000:],
            "stderr": err.decode("utf-8", "replace")[-2000:],
        }

    # --- web ---
    @spec(
        "web_fetch",
        "Đọc nội dung text của 1 URL (chỉ đọc, không tương tác).",
        {
            "type": "object",
            "properties": {"url": {"type": "string"}},
            "required": ["url"],
        },
        "web", 30,
    )
    async def web_fetch(url: str):
        import httpx

        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=20.0,
            headers={"User-Agent": "MulonAgent/0.1 (+personal agent)"},
        ) as client:
            resp = await client.get(url)
        raw = resp.text or ""
        text = re.sub(r"<script[\s\S]*?</script>|<style[\s\S]*?</style>", " ", raw)
        text = re.sub(r"<[^>]+>", " ", text)
        text = html.unescape(re.sub(r"\s+", " ", text)).strip()
        return {
            "ok": True,
            "url": str(resp.url),
            "status_code": resp.status_code,
            "content": text[:12_000],
        }

    # --- memory ---
    @spec(
        "memory_search",
        "Tìm ký ức liên quan (fact bền + đoạn hội thoại cũ nguyên văn).",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 8},
            },
            "required": ["query"],
        },
        "memory", 10,
    )
    async def memory_search(query: str, limit: int = 8):
        hits = await memory.recall(query, limit=int(limit))
        return {"ok": True, "hits": hits}

    @spec(
        "session_search",
        "Tìm trong các phiên TRƯỚC: trả NGUYÊN VĂN tin nhắn gốc kèm "
        "session id + thời gian (không tóm tắt). Dùng khi cần nhớ lại "
        "đúng lời đã nói ở phiên cũ.",
        {
            "type": "object",
            "properties": {
                "query": {"type": "string"},
                "limit": {"type": "integer", "default": 8},
            },
            "required": ["query"],
        },
        "memory", 10,
    )
    async def session_search(query: str, limit: int = 8):
        results = await memory.session_search(query, limit=int(limit))
        return {"ok": True, "results": results}

    @spec(
        "memory_get",
        "Đọc 1 bản ghi ký ức theo loại ('fact' hoặc 'message') và id.",
        {
            "type": "object",
            "properties": {
                "kind": {"type": "string", "enum": ["fact", "message"]},
                "id": {"type": "integer"},
            },
            "required": ["kind", "id"],
        },
        "memory", 10,
    )
    async def memory_get(kind: str, id: int):
        if kind == "fact":
            item = await memory.get_fact(int(id))
        else:
            item = await memory.get_message(int(id))
        if item is None:
            return {"ok": False, "error": f"không thấy {kind}#{id}"}
        return {"ok": True, "item": item}

    @spec(
        "add_memory_fact",
        "Lưu 1 sự kiện bền vào ký ức dài hạn. supersedes: danh sách id fact "
        "cũ bị fact này thay thế (đóng vòng đời, không xóa).",
        {
            "type": "object",
            "properties": {
                "fact": {"type": "string"},
                "subject": {"type": "string", "default": ""},
                "salience": {"type": "number", "default": 0.5},
                "supersedes": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "default": [],
                },
            },
            "required": ["fact"],
        },
        "memory", 10,
    )
    async def add_memory_fact(fact: str, subject: str = "",
                              salience: float = 0.5, supersedes=None):
        new_id = await memory.add_fact(
            fact, subject=subject, salience=float(salience),
            source="tool:add_memory_fact",
            supersedes=[int(x) for x in (supersedes or [])],
        )
        return {"ok": True, "fact_id": new_id}

    # --- misc ---
    @spec(
        "now",
        "Giờ hiện tại của hệ thống (UTC + giờ địa phương của máy).",
        {"type": "object", "properties": {}, "required": []},
        "system", 5,
    )
    async def now_tool():
        utc = datetime.now(timezone.utc)
        return {
            "ok": True,
            "utc": utc.isoformat(timespec="seconds"),
            "local": datetime.now().astimezone().isoformat(timespec="seconds"),
        }

    return reg


def result_to_text(result: dict) -> str:
    """Ép kết quả tool thành text để đưa vào prompt (trước bước trim)."""
    return json.dumps(result, ensure_ascii=False, default=str)
