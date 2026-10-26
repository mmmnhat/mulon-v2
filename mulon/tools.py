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
import ipaddress
import json
import re
import socket
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional
from urllib.parse import urljoin, urlparse

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

    def register(self, spec: ToolSpec, overwrite: bool = False) -> ToolSpec:
        if spec.name in self._tools and not overwrite:
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
    """Đường dẫn tool neo vào workspace HOẶC codebase (nếu trỏ tới dự án); ra ngoài phải được bật cờ."""
    base = Path(cfg.workspace_dir).resolve()
    project_root = (getattr(cfg, "project_root", None) or Path(__file__).resolve().parent.parent).resolve()
    p = Path(raw or ".").expanduser()
    if p.is_absolute():
        resolved = p.resolve()
    else:
        first = p.parts[0] if p.parts else ""
        if first in {"mulon", "tests", "scripts", "docs", "config"} or (first != ".." and (project_root / p).exists()):
            resolved = (project_root / p).resolve()
        else:
            resolved = (base / p).resolve()

    if not cfg.allow_outside_workspace:
        allowed = False
        if resolved == base or base in resolved.parents:
            allowed = True
        elif resolved == project_root or project_root in resolved.parents:
            first = p.parts[0] if p.parts else ""
            if p.is_absolute() or first in {"mulon", "tests", "scripts", "docs", "config"} or (first != ".." and (project_root / p).exists()):
                allowed = True
        if not allowed:
            raise PermissionError(
                f"đường dẫn ngoài workspace bị chặn: {raw} "
                "(bật ALLOW_OUTSIDE_WORKSPACE=1 nếu thật sự cần)"
            )
    return resolved


def _resolve_for_file_tool(cfg, raw: str) -> Path:
    """Neo của các file tool: workspace HOẶC thư mục dossier HOẶC codebase dự án.

    Đường tương đối trỏ vào mulon/, tests/, scripts/ hoặc tồn tại trong
    project_root sẽ tự động neo vào project_root để bot có thể tự đọc và
    sửa chính mình. Ra ngoài cả 3 vùng vẫn bị chặn.
    """
    base = Path(cfg.workspace_dir).resolve()
    dossier_base = Path(cfg.dossier_dir).resolve()
    project_root = (getattr(cfg, "project_root", None) or Path(__file__).resolve().parent.parent).resolve()
    p = Path(raw or ".").expanduser()
    if p.is_absolute():
        resolved = p.resolve()
    else:
        first = p.parts[0] if p.parts else ""
        if first in {"mulon", "tests", "scripts", "docs", "config"} or (first != ".." and (project_root / p).exists()):
            resolved = (project_root / p).resolve()
        elif first == "dossier" or (first != ".." and (dossier_base / p).exists()):
            resolved = (dossier_base / p).resolve()
        else:
            resolved = (base / p).resolve()

    # Denylist cứng (vá audit 2026-10-26): file tool không bao giờ
    # được đọc/ghi file bí mật, kể cả khi nằm trong project_root
    # (self-evolution) hay bật ALLOW_OUTSIDE_WORKSPACE. .env.example
    # là template công khai nên được phép.
    _lname = resolved.name.lower()
    if (
        (_lname.startswith(".env") and _lname != ".env.example")
        or _lname.endswith((".pem", ".key"))
        or "secret" in _lname
        or _lname == "vault.json"
        or _lname.endswith((".db", ".sqlite", ".sqlite3"))
    ):
        raise PermissionError(
            f"file nhạy cảm bị chặn với file tool: {raw}")

    if cfg.allow_outside_workspace:
        return resolved

    allowed = False
    for root in (base, dossier_base):
        if resolved == root or root in resolved.parents:
            allowed = True
            break
    if not allowed and (resolved == project_root or project_root in resolved.parents):
        first = p.parts[0] if p.parts else ""
        if p.is_absolute() or first in {"mulon", "tests", "scripts", "docs", "config"} or (first != ".." and (project_root / p).exists()):
            allowed = True

    if not allowed:
        raise PermissionError(
            f"đường dẫn ngoài workspace/dossier/codebase bị chặn: {raw} "
            "(bật ALLOW_OUTSIDE_WORKSPACE=1 nếu thật sự cần)"
        )
    return resolved


# ---------------------------------------------------------------------------
# Sửa 1.6.3: chặn SSRF cho các đường đọc web (web_fetch, websearch,
# browser web_read). KHÔNG áp cho proxy model 127.0.0.1:8317 vì các
# đường này KHÔNG đi qua proxy đó: httpx client ở đây không truyền
# proxy (trust_env mặc định của httpx vẫn có thể đọc HTTP_PROXY của
# môi trường — xem lưu ý ở http_get_public), còn proxy chỉ được dùng
# ở gateway.py (LiteLLM api_base) và voice.py (TTS POST). Vì vậy
# chặn localhost ở đây không làm gãy proxy, và ngược lại proxy vẫn
# bị khóa riêng ở config.validate_proxy_base_url.
# ---------------------------------------------------------------------------

def _ip_is_private_or_reserved(ip) -> bool:
    """True nếu IP không phải địa chỉ công cộng (loopback, private,
    link-local, multicast, reserved, unspecified, IPv4-mapped về
    các nhóm đó). is_global=False là điều kiện đủ cho mọi nhóm này
    trên Python 3.12, kể cả CGNAT 100.64/10 (is_private=True)."""
    try:
        mapped = getattr(ip, "ipv4_mapped", None)
        if mapped is not None:
            ip = mapped
    except Exception:
        pass
    return not ip.is_global


def ssrf_error_for_url(url: str) -> Optional[str]:
    """Kiểm tra tĩnh (không DNS): trả chuỗi lỗi nếu URL rõ ràng là
    nội bộ, None nếu qua được vòng này. Hostname chưa phân giải
    được thì phải qua assert_url_public (DNS) mới kết luận."""
    raw = (url or "").strip()
    if not raw:
        return "URL trống — từ chối để khỏi đọc nhầm đích nội bộ"
    try:
        parsed = urlparse(raw)
    except Exception:
        return "URL không phân tích được — từ chối (fail-closed)"
    if parsed.scheme not in {"http", "https"}:
        return (f"scheme {parsed.scheme!r} không phải http/https "
                "— từ chối (SSRF guard)")
    host = (parsed.hostname or "").lower()
    if not host or host == "localhost" or host.endswith(".localhost"):
        return "host localhost — từ chối (SSRF guard)"
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return None  # hostname: chờ kiểm tra DNS ở assert_url_public
    if _ip_is_private_or_reserved(ip):
        return "địa chỉ IP nội bộ/loopback/link-local — từ chối (SSRF guard)"
    return None


async def assert_url_public(url: str) -> Optional[str]:
    """Kiểm tra đầy đủ cho 1 URL: vòng tĩnh + phân giải DNS của
    hostname, mọi địa chỉ phân giải ra đều phải là công cộng.
    Trả chuỗi lỗi nếu bị chặn, None nếu đạt. DNS lỗi -> chặn
    (fail-closed): fetch thật cũng sẽ lỗi DNS, nên chặn sớm không
    làm mất trang hợp lệ nào ngoài trang đã không đọc được."""
    err = ssrf_error_for_url(url)
    if err:
        return err
    host = (urlparse(url).hostname or "").lower()
    try:
        ipaddress.ip_address(host)
        return None  # IP literal đã qua vòng tĩnh
    except ValueError:
        pass
    try:
        loop = asyncio.get_running_loop()
        infos = await loop.getaddrinfo(host, 443,
                                       proto=socket.IPPROTO_TCP)
    except Exception:
        return f"không phân giải được host {host!r} — từ chối (fail-closed)"
    if not infos:
        return f"không phân giải được host {host!r} — từ chối (fail-closed)"
    for info in infos:
        sockaddr = info[4] if len(info) > 4 else None
        if not sockaddr:
            continue
        try:
            ip = ipaddress.ip_address(sockaddr[0])
        except ValueError:
            return "địa chỉ phân giải không hợp lệ — từ chối (SSRF guard)"
        if _ip_is_private_or_reserved(ip):
            return (f"host {host!r} phân giải ra địa chỉ nội bộ "
                    "— từ chối (SSRF guard)")
    return None


async def http_get_public(client, url: str, max_redirects: int = 3):
    """GET qua httpx client (phải đặt follow_redirects=False) với
    kiểm tra SSRF ở MỖI hop redirect, tối đa max_redirects lần.
    Trả response cuối (không phải redirect). Raise ValueError khi
    URL/hop bị chặn hoặc vượt trần redirect — caller bọc thành
    {ok: False, error} theo quy ước của từng đường (registry đã
    bọc mọi exception của web_fetch; websearch tự bọc)."""
    current = (url or "").strip()
    for hop in range(max_redirects + 1):
        err = await assert_url_public(current)
        if err:
            raise ValueError(err)
        resp = await client.get(current)
        location = resp.headers.get("location") or ""
        if resp.status_code in {301, 302, 303, 307, 308} and location:
            if hop >= max_redirects:
                raise ValueError(
                    f"vượt quá {max_redirects} redirect — từ chối "
                    "(SSRF guard: không theo redirect vô hạn)")
            current = urljoin(current, location)
            continue
        return resp
    raise ValueError("không tới được response cuối sau các redirect")


def build_default_registry(cfg, memory, dossier=None, vault_store=None) -> ToolRegistry:
    reg = ToolRegistry()

    def spec(name, desc, params, group, timeout):
        def deco(fn):
            reg.register(ToolSpec(name, desc, params, group, timeout, fn))
            return fn

        return deco

    def _maybe_reload_dossier(p: Path) -> None:
        if dossier is not None:
            try:
                dossier_base = Path(cfg.dossier_dir).resolve()
                if p.resolve().is_relative_to(dossier_base):
                    dossier.reload()
            except Exception as exc:
                logger.warning("reload dossier sau khi đổi file lỗi: %s", exc)

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
        _maybe_reload_dossier(p)
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
        _maybe_reload_dossier(p)
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
        "Chạy lệnh shell trong workspace. cwd tường minh, có timeout. Tự động giải mã tham chiếu vault:<uuid> khi chạy và giấu key khỏi kết quả.",
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
        project_root = (getattr(cfg, "project_root", None) or Path(__file__).resolve().parent.parent).resolve()
        if cwd:
            workdir = _resolve_in_workspace(cfg, cwd)
        else:
            cmd_lower = command.lower().strip()
            if any(cmd_lower.startswith(pfx) for pfx in ("git ", "pytest", "python3 -m pytest", "python -m pytest", "python3 -m mulon", "python -m mulon", "python3 scripts/", "python scripts/", "ruff ")):
                workdir = project_root
            else:
                workdir = Path(cfg.workspace_dir).resolve()
        workdir.mkdir(parents=True, exist_ok=True)
        # Tự động thay thế tham chiếu vault:<uuid> thành giá trị thật trước khi chạy
        exec_cmd = command
        secret_map = {}
        if vault_store is not None:
            refs = re.findall(r"vault:[A-Za-z0-9\-_]+", command)
            for ref in refs:
                val = vault_store.resolve(ref)
                if val:
                    secret_map[val] = ref
                    exec_cmd = exec_cmd.replace(ref, val)

        proc = await asyncio.create_subprocess_shell(
            exec_cmd,
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

        stdout_str = out.decode("utf-8", "replace")[-8000:]
        stderr_str = err.decode("utf-8", "replace")[-2000:]
        # Redaction: bảo đảm giá trị bí mật không bao giờ lộ ra kết quả
        for val, ref in secret_map.items():
            stdout_str = stdout_str.replace(val, ref)
            stderr_str = stderr_str.replace(val, ref)

        return {
            "ok": proc.returncode == 0,
            "exit_code": proc.returncode,
            "stdout": stdout_str,
            "stderr": stderr_str,
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

        # Sửa 1.6.3: SSRF guard + follow redirect thủ công có kiểm
        # tra mỗi hop (xem http_get_public). trust_env=False để
        # biến HTTP_PROXY của môi trường không âm thầm chuyển
        # hướng request này qua 1 proxy khác với URL đã kiểm tra.
        async with httpx.AsyncClient(
            follow_redirects=False,
            timeout=20.0,
            trust_env=False,
            headers={"User-Agent": "MulonAgent/0.1 (+personal agent)"},
        ) as client:
            try:
                resp = await http_get_public(client, url)
            except ValueError as exc:
                return {"ok": False, "error": str(exc)}
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
