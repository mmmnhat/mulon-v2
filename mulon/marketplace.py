"""MarketplaceService — Chợ MCP của Mulon (1.3.0).

Hiện thực spec ``spec-mcp-marketplace-1.3.md`` + quyết định owner
mục 15.3 (đã khoá, không thương lượng lại):

- Chỉ server MIỄN PHÍ, chỉ LOCAL STDIO. Remote/paid bị từ chối
  ở khâu chuẩn hoá/phân tích rủi ro — không có đường vòng.
- Nguồn dữ kiện: bundle tuyển chọn đóng gói + import thủ công
  (phương án B). Catalog tự cập nhật từ repo GitHub của dự án
  (kiểm tra lúc khởi động + hàng tuần, kiểm checksum, CHỈ cập
  nhật dữ kiện niêm yết — không bao giờ tự cài).
- Cài đặt qua 2 lần duyệt (probe, rồi commit) trên ApprovalBroker
  với TTL riêng 900s và KHÔNG có "duyệt và nhớ". Tool của server
  cài qua chợ vào group policy ``mcp:<server>`` với verdict mặc
  định ``ask``.
- Bí mật chỉ qua Vault ref (``env_vault_refs``...); không có
  plaintext trong config/catalog/log/API/store. Giá trị thật chỉ
  được resolve trong bộ nhớ lúc connect/probe bởi MCPManager.
- Commit có journal write-ahead + rollback; bot TỰ khởi động lại
  (re-exec) sau cài/gỡ/cập nhật; boot chạy reconciliation +
  boot gate (config fingerprint + tool fingerprint phải khớp
  bản đã duyệt mới được đăng ký tool) và TỰ ROLLBACK cấu hình
  trước đó khi áp dụng thất bại, kèm thông báo cho owner.

Module này không đăng ký agent tool nào cho marketplace (phòng
thủ chính theo spec 13.5): agent chỉ hướng owner vào Mini App.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import os
import re
import sys
import threading
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .marketplace_providers import (
    CATEGORY_LABELS,
    CURATED_PROVIDER_ID,
    MANUAL_PROVIDER_ID,
    MCP_MARKETPLACE_CATEGORIES_FALLBACK,
    CuratedBundleProvider,
    bundle_content_hash,
    canonical_json,
    sha256_hex,
    validate_bundle,
)
from .marketplace_store import MarketplaceStore
from .mcp_client import load_server_configs

logger = logging.getLogger("mulon.marketplace")

NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
VAULT_REF_RE = re.compile(r"^vault:[A-Za-z0-9][A-Za-z0-9\-_]*$")
SENSITIVE_NAME_RE = re.compile(
    r"(TOKEN|SECRET|KEY|PASSWORD|PASSWD|AUTH|CREDENTIAL|PRIVATE)",
    re.IGNORECASE)
SHELL_COMMANDS = {"sh", "bash", "zsh", "dash", "ksh", "cmd",
                  "powershell", "pwsh", "eval", "curl", "wget",
                  "fish", "csh"}
DOWNLOAD_RUNNERS = {"npx": "npm", "bunx": "npm", "pnpm": "npm",
                    "uvx": "pypi", "pipx": "pypi"}
SHELL_META_RE = re.compile(r"[;&|$`\\<>\n\r]")
VERSION_RE = re.compile(
    r"^\d+\.\d+\.\d+(?:[-.+][0-9A-Za-z.-]+)?$"
    r"|^\d{4}\.\d{1,2}\.\d{1,2}(?:[-.+][0-9A-Za-z.-]*)?$")

TERMINAL_STAGES = {"done", "failed", "expired", "cancelled"}
ACTIVE_STAGES = {"draft", "awaiting_secret",
                 "awaiting_probe_approval", "probing",
                 "awaiting_commit_approval", "committing",
                 "pending_restart"}


class MarketplaceError(Exception):
    """Lỗi nghiệp vụ marketplace: ``code`` ổn định cho API/UI,
    ``message`` là tiếng Việt an toàn để hiện thẳng cho owner
    (đã lược bỏ dữ kiện nhạy cảm)."""

    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code
        self.message = message


def _iso(ts: Optional[float] = None) -> str:
    return datetime.fromtimestamp(
        time.time() if ts is None else ts,
        tz=timezone.utc).isoformat()


def short_fp(fingerprint: str) -> str:
    return (fingerprint or "")[:12]


_BEARER_RE = re.compile(r"(?i)(bearer\s+)[A-Za-z0-9._\-+/=]+")
_QS_SECRET_RE = re.compile(
    r"([?&](?:api[_-]?key|access[_-]?token|token|secret|password"
    r"|auth)=)[^&\s\"']+", re.IGNORECASE)


def redact_text(text: str, limit: int = 300) -> str:
    """Lược bỏ mẫu giống bí mật khỏi thông điệp lỗi/log: Bearer
    token và tham số nhạy cảm trong query URL."""
    out = _BEARER_RE.sub(r"\1***", str(text))
    out = _QS_SECRET_RE.sub(r"\1***", out)
    return out[:limit]


# ------------------------------------------------------------------
# Dấu vân tay (spec mục 5.9)
# ------------------------------------------------------------------

def tool_fingerprint(tools: list[dict]) -> str:
    """Hash trên canonical (name + description + inputSchema) đã
    sắp xếp theo tên tool — đổi bất kỳ phần nào là fingerprint
    đổi, kể cả chỉ đổi mô tả."""
    canon = [{
        "name": str(t.get("name") or ""),
        "description": str(t.get("description") or ""),
        "inputSchema": t.get("inputSchema") or {},
    } for t in sorted(tools, key=lambda x: str(x.get("name") or ""))]
    return sha256_hex(canonical_json(canon))


_CONFIG_FP_KEYS = ("name", "command", "args", "env",
                   "env_vault_refs", "cwd", "transport", "url",
                   "headers", "header_vault_refs", "auth_vault_ref",
                   "auth_header", "auth_prefix", "auth_env")


def config_fingerprint(entry: dict) -> str:
    """Fingerprint của entry đã resolve danh tính (binding theo
    vault REF, không theo giá trị) — không gồm ``enabled`` và
    các trường timeout."""
    fields = {k: entry.get(k) for k in _CONFIG_FP_KEYS
              if entry.get(k) not in (None, {}, [])}
    return sha256_hex(canonical_json(fields))


def manifest_fingerprint(manifest: dict) -> str:
    return sha256_hex(canonical_json(manifest))


def plan_fingerprint(plan: dict) -> str:
    core = {"local_name": plan.get("local_name"),
            "manifest": plan.get("manifest"),
            "bindings": plan.get("bindings") or {}}
    return sha256_hex(canonical_json(core))


# ------------------------------------------------------------------
# Chuẩn hoá cấu hình (spec mục 7)
# ------------------------------------------------------------------

def _check_json_shape(obj, depth: int = 0) -> None:
    if depth > 8:
        raise MarketplaceError(
            "invalid_config", "JSON lồng nhau quá sâu (tối đa 8 lớp).")
    if isinstance(obj, dict):
        if len(obj) > 64:
            raise MarketplaceError(
                "invalid_config", "JSON có quá nhiều trường.")
        for value in obj.values():
            _check_json_shape(value, depth + 1)
    elif isinstance(obj, list):
        if len(obj) > 64:
            raise MarketplaceError(
                "invalid_config", "JSON có mảng quá dài.")
        for value in obj:
            _check_json_shape(value, depth + 1)


def _parse_package(args: list[str], ecosystem: str) -> Optional[dict]:
    """Tìm gói + version trong args của runner tải-và-chạy
    (npx/uvx/...). Token gói là đối số vị trí đầu tiên."""
    token = None
    skip_next = False
    for arg in args:
        if skip_next:
            skip_next = False
            continue
        if arg in ("--package", "-p", "--from"):
            skip_next = True
            continue
        if arg.startswith("-"):
            continue
        token = arg
        break
    if token is None:
        return None
    if token.startswith("@"):
        # Gói scoped: @scope/name hoặc @scope/name@version.
        rest = token[1:]
        if "@" in rest:
            name_part, version = rest.rsplit("@", 1)
            name = "@" + name_part
        else:
            name, version = token, ""
    elif "@" in token:
        name, version = token.rsplit("@", 1)
    else:
        name, version = token, ""
    pinned = bool(version) and bool(VERSION_RE.match(version))
    return {"ecosystem": ecosystem, "name": name,
            "version": version or None, "pinned": pinned}


def normalize_server_config(raw, *, source: str,
                            allowed_cwd_roots: list[Path]) -> dict:
    """Chuẩn hoá 1 server object thành manifest bền (không chứa
    secret value). Ném MarketplaceError cho lỗi cứng; các lý do
    "không hỗ trợ ở 1.3" được ghi vào manifest để UI hiển thị
    thay vì giấu (support_state/unsupported_reasons)."""
    if not isinstance(raw, dict):
        raise MarketplaceError(
            "invalid_config", "Cấu hình server phải là JSON object.")
    _check_json_shape(raw)
    manifest: dict = {
        "transport": "stdio",
        "command": None,
        "args": [],
        "package": None,
        "public_env": {},
        "setup_requirements": [],
        "cwd": None,
        "warnings": [],
        "support_state": "supported",
        "unsupported_reasons": [],
    }

    def unsupported(code: str, text: str) -> None:
        manifest["support_state"] = "unsupported"
        manifest["unsupported_reasons"].append(
            {"code": code, "text": text})

    def warn(code: str, severity: str, text: str) -> None:
        manifest["warnings"].append(
            {"code": code, "severity": severity, "text": text})

    has_command = bool(raw.get("command"))
    has_url = bool(raw.get("url"))
    if has_url and not has_command:
        # Quyết định owner 15.3: 1.3 chỉ local stdio — kể cả
        # import thủ công cũng không nhận remote.
        manifest["transport"] = "http"
        unsupported(
            "unsupported_transport",
            "Bản 1.3 chỉ hỗ trợ server chạy local (stdio). "
            "Server remote (URL) chưa được hỗ trợ.")
        url = str(raw.get("url"))
        qs = url.split("?", 1)[1] if "?" in url else ""
        if qs and any(SENSITIVE_NAME_RE.search(part.split("=")[0])
                      for part in qs.split("&") if "=" in part):
            unsupported(
                "unsupported_auth_in_url",
                "URL chứa tham số giống bí mật — không lưu URL "
                "kiểu này vào cấu hình.")
        return manifest
    if has_url and has_command:
        raise MarketplaceError(
            "invalid_config",
            "Cấu hình có cả command và url — không rõ transport, "
            "hãy giữ đúng một trong hai.")
    if not has_command:
        raise MarketplaceError(
            "invalid_config",
            "Thiếu 'command' — server local stdio cần một lệnh "
            "chạy trực tiếp.")

    command = raw.get("command")
    if not isinstance(command, str) or not command.strip():
        raise MarketplaceError("invalid_config",
                               "'command' phải là chuỗi lệnh.")
    command = command.strip()
    if any(ch.isspace() for ch in command) or \
            SHELL_META_RE.search(command):
        unsupported(
            "unsupported_shell_config",
            "Command là chuỗi shell — Mulon chỉ chạy executable "
            "trực tiếp, không qua shell.")
        manifest["command"] = command
        return manifest
    base = Path(command).name.lower()
    if base in SHELL_COMMANDS:
        unsupported(
            "unsupported_shell_config",
            f"'{base}' là shell/công cụ tải-chạy — không được "
            "dùng làm command của MCP server.")
        manifest["command"] = command
        return manifest
    manifest["command"] = command

    args = raw.get("args") or []
    if not isinstance(args, list) or \
            any(not isinstance(a, str) for a in args):
        raise MarketplaceError(
            "invalid_config", "'args' phải là mảng chuỗi.")
    if len(args) > 32 or any(len(a) > 512 for a in args):
        raise MarketplaceError(
            "invalid_config",
            "'args' vượt giới hạn (tối đa 32 mục, mỗi mục 512 ký tự).")
    manifest["args"] = list(args)
    if any(a in ("-c", "-lc", "--command") for a in args):
        unsupported(
            "unsupported_shell_config",
            "Args chứa cờ chạy lệnh qua shell (-c) — không hỗ trợ.")

    ecosystem = DOWNLOAD_RUNNERS.get(base)
    if ecosystem:
        package = _parse_package(args, ecosystem)
        manifest["package"] = package
        warn("download_and_run", "medium",
             f"'{base}' tải mã từ registry mỗi lần chạy — chỉ "
             "cài khi tin nguồn gói.")
        if package and not package["pinned"]:
            warn("unpinned_package", "high",
                 "Gói chưa ghim version cố định — bản chạy có thể "
                 "thay đổi bất cứ lúc nào ngoài ý muốn.")
        if package:
            manifest["package"] = package
    if any(a.startswith(("http://", "https://")) for a in args):
        warn("url_in_args", "high",
             "Args chứa URL — server có thể tải nội dung từ "
             "mạng khi chạy.")

    # env: tách công khai / bí mật. Giá trị bí mật literal KHÔNG
    # bao giờ được nhận (spec 7.4).
    env = raw.get("env") or {}
    if not isinstance(env, dict):
        raise MarketplaceError("invalid_config",
                               "'env' phải là JSON object.")
    requirements: dict[str, dict] = {}

    def add_requirement(name: str, location: str, label: str = "",
                        bound_ref: Optional[str] = None) -> None:
        key = f"{location}:{name}"
        req = {"name": name, "location": location, "required": True,
               "secret": True,
               "label": label or f"Giá trị bí mật cho {name}"}
        if bound_ref:
            req["bound_ref"] = bound_ref
        requirements[key] = req

    for key, value in env.items():
        name = str(key)
        text = "" if value is None else str(value)
        if VAULT_REF_RE.match(text):
            add_requirement(name, "stdio_env", bound_ref=text)
        elif SENSITIVE_NAME_RE.search(name):
            if text:
                raise MarketplaceError(
                    "secret_literal_rejected",
                    f"Biến {name} trông như bí mật nhưng đang chứa "
                    "giá trị thật trong bản dán. Hãy để trống và "
                    "gắn qua Vault ở bước cài.")
            add_requirement(name, "stdio_env")
        else:
            manifest["public_env"][name] = text

    if raw.get("headers"):
        raise MarketplaceError(
            "invalid_config",
            "Server stdio không dùng 'headers' — hãy bỏ trường "
            "này khỏi cấu hình.")
    if raw.get("auth_vault_ref"):
        ref = str(raw["auth_vault_ref"])
        if not VAULT_REF_RE.match(ref):
            raise MarketplaceError(
                "invalid_config", "auth_vault_ref không đúng dạng vault ref.")
        add_requirement(str(raw.get("auth_header") or "Authorization"),
                        "auth_header", bound_ref=ref)
    for extra_key in ("apiKey", "api_key", "token", "password",
                      "secret"):
        if raw.get(extra_key):
            raise MarketplaceError(
                "secret_literal_rejected",
                f"Trường '{extra_key}' chứa giá trị bí mật — "
                "không nhận bí mật dạng chữ trong cấu hình.")

    # Yêu cầu khai sẵn (bundle tuyển chọn khai rõ biến cần Vault).
    for declared in raw.get("setup_requirements") or []:
        if not isinstance(declared, dict) or not declared.get("name"):
            continue
        name = str(declared["name"])
        location = str(declared.get("location") or "stdio_env")
        key = f"{location}:{name}"
        if key not in requirements:
            req = {"name": name, "location": location,
                   "required": bool(declared.get("required", True)),
                   "secret": bool(declared.get("secret", True)),
                   "label": str(declared.get("label")
                                or f"Giá trị cho {name}")}
            if declared.get("bound_ref"):
                req["bound_ref"] = str(declared["bound_ref"])
            requirements[key] = req
    manifest["setup_requirements"] = list(requirements.values())
    if isinstance(raw.get("package"), dict) and \
            raw["package"].get("name"):
        declared_pkg = raw["package"]
        manifest["package"] = {
            "ecosystem": str(declared_pkg.get("ecosystem")
                             or (ecosystem or "local")),
            "name": str(declared_pkg["name"]),
            "version": declared_pkg.get("version"),
            "pinned": bool(declared_pkg.get("pinned")),
        }

    cwd = raw.get("cwd")
    if cwd:
        resolved = Path(str(cwd)).expanduser().resolve()
        roots = [Path(r).resolve() for r in allowed_cwd_roots]
        if not any(resolved == r or r in resolved.parents
                   for r in roots):
            raise MarketplaceError(
                "invalid_config",
                "Thư mục làm việc (cwd) nằm ngoài vùng cho phép "
                "của Mulon.")
        manifest["cwd"] = str(resolved)
    return manifest


def slugify_local_name(text: str) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "-", str(text).lower()).strip("-")
    slug = re.sub(r"-{2,}", "-", slug)[:64].strip("-")
    return slug or "server"


def build_entry(local_name: str, manifest: dict,
                bindings: dict) -> dict:
    """Entry cho mcp_servers.json từ manifest + binding Vault ref.
    Entry bền KHÔNG chứa giá trị bí mật — chỉ ref."""
    entry: dict = {"name": local_name,
                   "command": manifest.get("command"),
                   "args": list(manifest.get("args") or []),
                   "enabled": True,
                   # Trần nối hào phóng cho server cài qua chợ:
                   # runner npx/uvx lần đầu phải tải gói, và một số
                   # server tham chiếu (Node SDK cũ) initialize mất
                   # ~70s qua MCP Python SDK — đã đo thật khi rà
                   # soát bundle 2026-10-24.
                   "timeout_s": 120,
                   "call_timeout_s": 60}
    if manifest.get("public_env"):
        entry["env"] = dict(manifest["public_env"])
    env_refs: dict[str, str] = {}
    header_refs: dict[str, str] = {}
    for req in manifest.get("setup_requirements") or []:
        ref = bindings.get(req["name"]) or req.get("bound_ref")
        if not ref:
            continue
        if req["location"] == "stdio_env":
            env_refs[req["name"]] = ref
        elif req["location"] == "auth_header":
            entry["auth_vault_ref"] = ref
            entry["auth_header"] = req["name"]
        else:
            header_refs[req["name"]] = ref
    if env_refs:
        entry["env_vault_refs"] = env_refs
    if header_refs:
        entry["header_vault_refs"] = header_refs
    if manifest.get("cwd"):
        entry["cwd"] = manifest["cwd"]
    return entry


def command_line_of(manifest: dict) -> str:
    parts = [str(manifest.get("command") or "")]
    parts.extend(str(a) for a in manifest.get("args") or [])
    return redact_text(" ".join(p for p in parts if p), 200)


def make_reexec_restarter(delay_s: float = 1.5):
    """Restarter mặc định: hẹn giờ ngắn rồi re-exec chính tiến
    trình (bot tự khởi động lại sau cài/gỡ/cập nhật — owner
    không phải thao tác)."""
    def _restart() -> None:
        def _go() -> None:
            time.sleep(delay_s)
            logger.warning("marketplace: tự khởi động lại tiến "
                           "trình để áp dụng thay đổi MCP")
            os.execv(sys.executable, [sys.executable, *sys.argv])
        threading.Thread(target=_go, daemon=True,
                         name="marketplace-restart").start()
    return _restart


# ------------------------------------------------------------------
# Kho cấu hình mcp_servers.json (đọc-ghi nguyên tử, giữ nguyên
# entry thủ công + trường lạ — spec mục 6.4/6.5)
# ------------------------------------------------------------------

def read_mcp_file(path: Path) -> dict:
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if isinstance(data, dict):
            return data
    except Exception:
        pass
    return {"servers": []}


def write_mcp_file(path: Path, data: dict) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    tmp.replace(path)


def _entries_of(data: dict) -> list[dict]:
    servers = data.get("servers")
    if servers is None:
        servers = data.get("mcpServers")
    if isinstance(servers, dict):
        return [{"name": k, **v} if isinstance(v, dict) else {"name": k}
                for k, v in servers.items()]
    return servers if isinstance(servers, list) else []


class MarketplaceService:
    """Điều phối toàn bộ vòng đời marketplace. Mọi method đổi
    trạng thái đều đi qua store (journal) — không bề mặt nào
    được ghi file cấu hình trực tiếp cho server managed."""

    def __init__(self, cfg, *, policy, broker, vault_store,
                 mcp_manager, restarter=None, fetcher=None):
        self.cfg = cfg
        self.policy = policy
        self.broker = broker
        self.vault = vault_store
        self.mcp = mcp_manager
        self.store = MarketplaceStore(cfg.marketplace_store_path)
        self.provider = CuratedBundleProvider(
            cfg.marketplace_curated_path, cfg.marketplace_catalog_path)
        self.restarter = restarter
        self._fetcher = fetcher
        self._config_lock = threading.RLock()
        self._tasks: set = set()
        self._notifier = None
        self._boot_needs_restart = False
        self._mkt_categories_cache: Optional[list[dict]] = None
        self._mkt_categories_fetched_at: float = 0
        if self.mcp is not None and self.vault is not None:
            self.mcp.set_secret_resolver(self._resolve_vault_ref)

    # ---------- hạ tầng ----------
    def _resolve_vault_ref(self, ref: str) -> Optional[str]:
        try:
            return self.vault.resolve(ref)
        except Exception:
            return None

    def bind_notifier(self, fn) -> None:
        """fn: async callable(text) gửi tin cho owner (Telegram)."""
        self._notifier = fn

    def bind_card_presenter(self, fn) -> None:
        """fn: async callable(payload) trình thẻ duyệt marketplace
        vào chat của owner (operation mở từ Mini App không có
        lượt agent nào để neo thẻ). Không gắn presenter thì quyết
        định vẫn thực hiện được ở màn Phê duyệt của Mini App."""
        self._card_presenter = fn

    async def _present_card(self, payload: dict) -> None:
        presenter = getattr(self, "_card_presenter", None)
        if presenter is None:
            return
        try:
            await presenter(payload)
        except Exception:
            logger.exception("marketplace: trình thẻ duyệt lỗi")

    def _trigger_restart(self) -> None:
        if self.restarter is not None:
            try:
                self.restarter()
            except Exception:
                logger.exception("marketplace: restarter lỗi")

    def _spawn(self, coro) -> None:
        task = asyncio.ensure_future(coro)
        self._tasks.add(task)
        task.add_done_callback(self._tasks.discard)

    def _substitute_workspace(self, manifest: dict) -> dict:
        """Thay placeholder {{workspace_dir}} trong args của
        manifest tuyển chọn bằng thư mục workspace thật của bản
        cài này (vd server filesystem cần 1 thư mục cho phép cụ
        thể). Fingerprint luôn tính SAU khi thay — đúng bản sẽ
        chạy thật."""
        marker = "{{workspace_dir}}"
        args = [str(a).replace(marker, str(self.cfg.workspace_dir))
                for a in manifest.get("args") or []]
        manifest = dict(manifest)
        manifest["args"] = args
        return manifest

    def _allowed_cwd_roots(self) -> list[Path]:
        roots = [Path(self.cfg.workspace_dir),
                 Path(self.cfg.dossier_dir).parent,
                 Path(self.cfg.mcp_config_path).parent.parent]
        return roots

    def _journal(self, op: dict, step: str, detail: str = "") -> None:
        op.setdefault("journal", []).append(
            {"at": _iso(), "step": step,
             "detail": redact_text(detail, 200)})
        op["updated_at"] = _iso()

    def _save_op(self, op: dict) -> dict:
        self.store.put_operation(op)
        return op

    # ---------- catalog: đọc ----------
    def catalog_meta(self) -> dict:
        _bundle, meta = self.provider.effective()
        state = self.store.catalog_update_state()
        meta = dict(meta)
        if meta["status"] == "fresh" and state.get("last_result") \
                == "error" and state.get("last_check_at"):
            meta["status"] = "stale"
        meta["last_check_at"] = (
            _iso(state["last_check_at"])
            if state.get("last_check_at") else None)
        return meta

    def summary(self) -> dict:
        installed = self.store.all_installed()
        pending = sum(
            1 for r in installed.values()
            if str(r.get("lifecycle_state", "")).endswith(
                "pending_restart"))
        if self.store.restart_pending():
            pending = max(pending, 1)
        updates = sum(
            1 for r in installed.values()
            if r.get("available_revision")
            and r["available_revision"] != r.get("installed_revision"))
        return {"installed_count": len(installed),
                "pending_restart": pending,
                "updates_available": updates,
                "catalog": self.catalog_meta()}

    def _installed_state_for(self, canonical_id: str) -> tuple:
        for record in self.store.all_installed().values():
            if record.get("canonical_id") == canonical_id:
                update = bool(
                    record.get("available_revision")
                    and record["available_revision"]
                    != record.get("installed_revision"))
                return record.get("lifecycle_state", "installed"), update
        for tomb in self.store.tombstones():
            if tomb.get("canonical_id") == canonical_id:
                return "uninstalled", False
        return "not_installed", False

    def listing_summary(self, listing: dict) -> dict:
        canonical_id = f"{listing.get('provider_id') or CURATED_PROVIDER_ID}:{listing.get('slug')}"
        state, update = self._installed_state_for(canonical_id)
        security = listing.get("security") or {}
        pricing = listing.get("pricing") or {"model": "free"}
        return {
            "canonical_id": canonical_id,
            "provider_id": listing.get("provider_id")
            or CURATED_PROVIDER_ID,
            "slug": listing.get("slug"),
            "name": listing.get("name"),
            "creator_name": listing.get("creator_name"),
            "summary": listing.get("summary"),
            "categories": listing.get("categories") or [],
            "locality": listing.get("locality") or "local_process",
            "transport": listing.get("transport") or "stdio",
            "pricing": {"model": pricing.get("model", "free"),
                        "label": pricing.get("label")
                        or ("Miễn phí" if pricing.get("model")
                            == "free" else "Có phí")},
            "security": {
                "score": security.get("score"),
                "risk_label": security.get("risk_label"),
                "critical_findings_count":
                    security.get("critical_findings_count", 0)},
            "tool_count_known": listing.get("tool_count_known") or 0,
            "installed_state": state,
            "update_available": update,
            "support_state": listing.get("support_state", "supported"),
            "unsupported_reasons":
                listing.get("unsupported_reasons") or [],
        }

    def listing_detail(self, provider_id: str, slug: str) -> dict:
        if provider_id == CURATED_PROVIDER_ID:
            listing = self.provider.get_listing(slug)
            if listing is None:
                raise MarketplaceError(
                    "catalog_unavailable",
                    "Không tìm thấy listing trong dữ kiện hiện có.")
            listing = dict(listing)
            listing["provider_id"] = CURATED_PROVIDER_ID
        elif provider_id == MANUAL_PROVIDER_ID:
            draft = self.store.get_draft(slug)
            if draft is None:
                raise MarketplaceError(
                    "invalid_config",
                    "Bản nháp nhập thủ công không còn tồn tại.")
            listing = dict(draft["listing"])
        else:
            raise MarketplaceError(
                "provider_unverified",
                "Nguồn cung cấp này chưa được hỗ trợ ở bản 1.3.")
        detail = self.listing_summary(listing)
        security = listing.get("security") or {}
        detail.update({
            "description": listing.get("description"),
            "source_url": listing.get("source_url"),
            "homepage_url": listing.get("homepage_url"),
            "security": {
                "score": security.get("score"),
                "risk_label": security.get("risk_label"),
                "critical_findings_count":
                    security.get("critical_findings_count", 0),
                "findings": security.get("findings") or [],
                "scanned_at": security.get("scanned_at"),
                "scan_source": security.get("scan_source")},
            "permissions": listing.get("permissions") or [],
            "tool_names_known": listing.get("tool_names_known") or [],
            "manifest_state": listing.get("manifest_state", "ready"),
        })
        manifest = listing.get("_manifest")
        if manifest is None and provider_id == CURATED_PROVIDER_ID:
            manifest = self._substitute_workspace(
                normalize_server_config(
                    listing.get("install") or {}, source="curated",
                    allowed_cwd_roots=self._allowed_cwd_roots()))
        if manifest is not None:
            detail["manifest"] = {
                "transport": manifest.get("transport"),
                "command": manifest.get("command"),
                "args": manifest.get("args") or [],
                "package": manifest.get("package"),
                "public_env": manifest.get("public_env") or {},
                "setup_requirements":
                    manifest.get("setup_requirements") or [],
                "warnings": manifest.get("warnings") or [],
            }
            detail["support_state"] = manifest.get(
                "support_state", detail["support_state"])
            detail["unsupported_reasons"] = manifest.get(
                "unsupported_reasons", detail["unsupported_reasons"])
        installed = None
        for record in self.store.all_installed().values():
            if record.get("canonical_id") == detail["canonical_id"]:
                installed = self.installed_view(record)
                break
        detail["installed"] = installed
        return detail

    def _mcp_marketplace_item_to_listing(self, item: dict,
                                          cat_slug: str = "") -> dict:
        slug = item.get("slug") or ""
        canonical_id = f"mcp-marketplace:{slug}"
        installed_state, update = self._installed_state_for(canonical_id)
        sec_score = item.get("security_score")
        risk_level = item.get("risk_level")
        pricing_str = (item.get("pricing") or "Free").lower()
        cat = cat_slug or item.get("category") or ""
        return {
            "canonical_id": canonical_id,
            "provider_id": "mcp-marketplace",
            "slug": slug,
            "name": item.get("name") or slug,
            "creator_name": item.get("creator") or "",
            "summary": item.get("tagline") or "",
            "categories": [cat] if cat else [],
            "locality": item.get("mode") or "local_process",
            "transport": "stdio",
            "pricing": {
                "model": "free" if pricing_str == "free" else pricing_str,
                "label": "Miễn phí" if pricing_str == "free" else "Có phí",
            },
            "security": {
                "score": sec_score,
                "risk_label": risk_level,
                "critical_findings_count": item.get("critical_findings") or 0,
            },
            "tool_count_known": None,
            "installed_state": installed_state,
            "update_available": update,
            "support_state": "supported",
            "unsupported_reasons": [],
            "installs": item.get("installs", 0),
            "github_stars": item.get("github_stars", 0),
            "source_url": item.get("url") or "",
        }

    def _mcp_marketplace_to_detail(self, raw: dict) -> dict:
        slug = raw.get("slug") or ""
        item_summary = self._mcp_marketplace_item_to_listing(raw)
        detail = self.listing_summary(item_summary)
        detail["description"] = (raw.get("description")
                                 or raw.get("tagline") or "")
        detail["source_url"] = (raw.get("url")
                                or raw.get("github_url") or "")
        detail["homepage_url"] = raw.get("github_url") or ""
        detail["version"] = raw.get("version") or "1.0.0"

        sec_raw = raw.get("security") or {}
        detail["security"] = {
            "score": (sec_raw.get("score")
                      if sec_raw.get("score") is not None
                      else raw.get("security_score")),
            "risk_label": (sec_raw.get("risk_level")
                           or raw.get("risk_level")),
            "critical_findings_count": len(
                sec_raw.get("critical_findings") or []),
            "findings": sec_raw.get("critical_findings") or [],
            "scanned_at": sec_raw.get("scanned_at"),
            "scan_source": "mcp-marketplace.io",
        }
        detail["permissions"] = sec_raw.get("permissions") or []
        detail["tool_names_known"] = raw.get("tool_names") or []
        detail["manifest_state"] = "ready"

        install_info = raw.get("install") or {}
        config_local = install_info.get("config_local") or {}
        mcp_servers = config_local.get("mcpServers") or {}
        server_cfg = {}
        if mcp_servers:
            server_cfg = next(iter(mcp_servers.values()), {})

        slug = str(raw.get("slug") or "")
        if server_cfg and server_cfg.get("command"):
            command = server_cfg.get("command")
            args = server_cfg.get("args") or []
            env = server_cfg.get("env") or {}
            detail["manifest"] = {
                "transport": "stdio",
                "command": command,
                "args": args,
                "package": (raw.get("pypi_package")
                            or raw.get("npm_package")),
                "public_env": env,
                "setup_requirements": (raw.get("setup_requirements")
                                       or []),
                "warnings": [],
            }
            detail["support_state"] = "supported"
            detail["unsupported_reasons"] = []
        elif slug == "google-workspace-mcp":
            detail["manifest"] = {
                "transport": "stdio",
                "command": "uvx",
                "args": ["--python", "3.12", "workspace-mcp", "--single-user", "--tool-tier", "core"],
                "package": {
                    "ecosystem": "pypi",
                    "name": "workspace-mcp",
                    "version": "2.2.0",
                    "pinned": False,
                },
                "public_env": {},
                "setup_requirements": [],
                "warnings": [
                    {
                        "code": "download_and_run",
                        "severity": "medium",
                        "text": "'uvx' tải và chạy Google Workspace MCP từ PyPI (workspace-mcp).",
                    }
                ],
            }
            detail["support_state"] = "supported"
            detail["unsupported_reasons"] = []
        else:
            detail["manifest"] = None
            detail["support_state"] = "unsupported"
            detail["unsupported_reasons"] = [
                "Server này chưa có cấu hình lệnh chạy (command) từ kho Marketplace."
            ]

        installed = None
        for record in self.store.all_installed().values():
            if record.get("canonical_id") == detail["canonical_id"]:
                installed = self.installed_view(record)
                break
        detail["installed"] = installed
        return detail

    async def get_listing_detail(self, provider_id: str,
                                 slug: str) -> dict:
        if provider_id == "mcp-marketplace":
            if self.mcp is not None:
                try:
                    res = await self.mcp.call_tool(
                        "mcp-marketplace", "get_server", {"slug": slug})
                    if isinstance(res, dict) and res.get("ok"):
                        raw = res.get("result") or {}
                        return self._mcp_marketplace_to_detail(raw)
                except Exception as exc:
                    logger.warning("lỗi get_server từ mcp-marketplace: %s",
                                   exc)
            raise MarketplaceError(
                "catalog_unavailable",
                f"Không thể tải chi tiết server '{slug}' từ MCP Marketplace.")
        return self.listing_detail(provider_id, slug)

    def search_catalog(self, *, query: str = "", category: str = "",
                       pricing: str = "", installed: str = "",
                       cursor: str = "", limit: int = 20) -> dict:
        items = [self.listing_summary(item)
                 for item in self.provider.listings()]
        for item in items:
            item["provider_id"] = CURATED_PROVIDER_ID
        if query:
            needle = query.lower()
            items = [i for i in items
                     if needle in str(i.get("name") or "").lower()
                     or needle in str(i.get("summary") or "").lower()
                     or needle in str(i.get("creator_name")
                                      or "").lower()]
        if category:
            items = [i for i in items
                     if category in (i.get("categories") or [])]
        if pricing:
            items = [i for i in items
                     if (i.get("pricing") or {}).get("model")
                     == pricing]
        if installed == "installed":
            items = [i for i in items
                     if i["installed_state"]
                     not in ("not_installed", "uninstalled")]
        elif installed == "not_installed":
            items = [i for i in items
                     if i["installed_state"]
                     in ("not_installed", "uninstalled")]
        start = 0
        if cursor:
            try:
                start = int(cursor)
            except ValueError:
                start = 0
        limit = max(1, min(int(limit or 20), 50))
        page = items[start:start + limit]
        next_cursor = (str(start + limit)
                       if start + limit < len(items) else None)
        return {"items": page, "next_cursor": next_cursor,
                "snapshot": self.catalog_meta()}

    async def search_catalog_async(self, *, query: str = "",
                                  category: str = "",
                                  pricing: str = "",
                                  installed: str = "",
                                  cursor: str = "",
                                  page: int = 1,
                                  limit: int = 20) -> dict:
        cur_page = max(1, int(page or 1))
        req_limit = max(1, min(int(limit or 20), 25))

        items: list[dict] = []
        curated_slugs = set()
        curated_count = 0
        if cur_page == 1:
            res = self.search_catalog(query=query, category=category,
                                      pricing=pricing, installed=installed,
                                      cursor=cursor, limit=req_limit)
            items = list(res.get("items") or [])
            curated_slugs = {it["slug"] for it in items}
            curated_count = len(items)

        total_matches = curated_count
        has_more = False

        if self.mcp is not None:
            try:
                args: dict = {"limit": req_limit, "page": cur_page}
                if category:
                    args["category"] = category
                if query:
                    args["query"] = query
                mkt_res = await self.mcp.call_tool(
                    "mcp-marketplace", "search_servers", args)
                if isinstance(mkt_res, dict) and mkt_res.get("ok"):
                    data = mkt_res.get("result") or {}
                    raw_results = data.get("results") or []
                    has_more = bool(data.get("has_more", False))
                    total_matches += int(data.get("total_matches") or 0)
                    for raw in raw_results:
                        rslug = raw.get("slug")
                        if rslug and rslug not in curated_slugs:
                            it = self._mcp_marketplace_item_to_listing(
                                raw, cat_slug=category)
                            if (pricing and it.get("pricing", {}).get(
                                    "model") != pricing):
                                continue
                            if (installed == "installed"
                                    and it["installed_state"]
                                    in ("not_installed", "uninstalled")):
                                continue
                            if (installed == "not_installed"
                                    and it["installed_state"]
                                    not in ("not_installed", "uninstalled")):
                                continue
                            items.append(it)
                            curated_slugs.add(rslug)
            except Exception as exc:
                logger.debug("lỗi search_servers từ mcp-marketplace: %s",
                             exc)

        next_cursor = str(cur_page + 1) if has_more else None
        return {
            "items": items,
            "page": cur_page,
            "limit": req_limit,
            "total": total_matches,
            "has_more": has_more,
            "next_cursor": next_cursor,
            "snapshot": self.catalog_meta(),
        }

    def _format_categories_list(self, raw_list: list[dict]) -> list[dict]:
        seen = set()
        out = []
        for item in raw_list:
            slug = item.get("slug") or ""
            if not slug:
                continue
            seen.add(slug)
            label = CATEGORY_LABELS.get(slug, item.get("name") or slug)
            desc = item.get("description") or ""
            count = int(item.get("server_count") or 0)
            out.append({
                "id": slug,
                "label": label,
                "description": desc,
                "count": count,
                "source": "mcp-marketplace",
            })
        curated_cats = self.provider.categories()
        for c in curated_cats:
            cid = c.get("id")
            if cid and cid not in seen:
                out.append({
                    "id": cid,
                    "label": c.get("label", cid),
                    "description": "",
                    "count": c.get("count", 0),
                    "source": CURATED_PROVIDER_ID,
                })
        return out

    def _merged_fallback_categories(self) -> list[dict]:
        return self._format_categories_list(
            MCP_MARKETPLACE_CATEGORIES_FALLBACK)

    async def _fetch_mcp_marketplace_categories(self) -> list[dict]:
        if self.mcp is None:
            return []
        try:
            res = await self.mcp.call_tool(
                "mcp-marketplace", "list_categories", {})
            if isinstance(res, dict) and res.get("ok"):
                raw_list = res.get("result") or []
                if raw_list and isinstance(raw_list, list):
                    return self._format_categories_list(raw_list)
        except Exception as exc:
            logger.debug(
                "không thể lấy categories từ mcp-marketplace: %s", exc)
        return []

    async def get_categories(self) -> dict:
        now = time.time()
        if (self._mkt_categories_cache is not None
                and now - self._mkt_categories_fetched_at < 300):
            return {"categories": self._mkt_categories_cache,
                    "freshness": self.catalog_meta()}

        cats = await self._fetch_mcp_marketplace_categories()
        if not cats:
            cats = self._merged_fallback_categories()
        self._mkt_categories_cache = cats
        self._mkt_categories_fetched_at = now
        return {"categories": cats, "freshness": self.catalog_meta()}

    def categories(self) -> dict:
        if self._mkt_categories_cache:
            cats = self._mkt_categories_cache
        else:
            cats = self._merged_fallback_categories()
        return {"categories": cats,
                "freshness": self.catalog_meta()}

    # ---------- import thủ công ----------
    def parse_import(self, *, text: Optional[str] = None,
                     url: Optional[str] = None,
                     name: Optional[str] = None) -> dict:
        if url:
            raise MarketplaceError(
                "unsupported_transport",
                "Bản 1.3 không nhập từ URL — hãy dán trực tiếp "
                "cấu hình JSON của server local.")
        if not text or not text.strip():
            raise MarketplaceError(
                "invalid_config", "Chưa có nội dung JSON để phân tích.")
        if len(text.encode("utf-8")) > self.cfg \
                .marketplace_max_input_bytes:
            raise MarketplaceError(
                "invalid_config",
                "Bản dán quá lớn (vượt giới hạn cho phép).")
        try:
            parsed = json.loads(text)
        except Exception:
            raise MarketplaceError(
                "invalid_config",
                "Không đọc được JSON — kiểm tra lại bản dán.")
        server_name = name or ""
        server_obj = None
        if isinstance(parsed, dict) and isinstance(
                parsed.get("mcpServers"), dict):
            servers = parsed["mcpServers"]
            if len(servers) == 0:
                raise MarketplaceError(
                    "invalid_config",
                    "Khối mcpServers rỗng — không có server nào.")
            if len(servers) > 1:
                return {"ok": False, "code": "invalid_config",
                        "error": "Bản dán có nhiều server — hãy "
                                 "dán đúng một server mỗi lần.",
                        "candidates": sorted(servers.keys())}
            server_name = server_name or next(iter(servers))
            server_obj = servers[server_name]
        elif isinstance(parsed, dict) and (
                parsed.get("command") or parsed.get("url")):
            server_obj = parsed
            server_name = server_name or str(
                parsed.get("name") or "imported")
        else:
            raise MarketplaceError(
                "invalid_config",
                "Không nhận ra cấu hình server: cần khối "
                "mcpServers hoặc một object có command.")
        manifest = normalize_server_config(
            server_obj, source="manual",
            allowed_cwd_roots=self._allowed_cwd_roots())
        local_name = slugify_local_name(server_name)
        draft_id = "draft_" + uuid.uuid4().hex[:12]
        listing = {
            "provider_id": MANUAL_PROVIDER_ID,
            "slug": draft_id,
            "name": server_name,
            "creator_name": "Bạn nhập thủ công",
            "summary": "Cấu hình dán thủ công — chưa qua rà soát "
                       "của danh mục tuyển chọn.",
            "description": None,
            "source_url": None,
            "categories": [],
            "locality": "local_process",
            "transport": manifest.get("transport") or "stdio",
            "pricing": {"model": "free", "label": "Miễn phí"},
            "security": {"score": None, "risk_label": None,
                         "critical_findings_count": 0,
                         "findings": [], "scanned_at": None,
                         "scan_source": None},
            "permissions": [],
            "tool_count_known": 0,
            "tool_names_known": [],
            "support_state": manifest.get("support_state"),
            "unsupported_reasons":
                manifest.get("unsupported_reasons") or [],
            "_manifest": manifest,
        }
        self.store.put_draft({
            "id": draft_id, "created_at": time.time(),
            "local_name": local_name, "manifest": manifest,
            "listing": {k: v for k, v in listing.items()
                        if k != "_manifest"}})
        detail = self.listing_detail(MANUAL_PROVIDER_ID, draft_id)
        return {"ok": True, "draft_id": draft_id, "listing": detail,
                "support_state": detail["support_state"],
                "unsupported_reasons": detail["unsupported_reasons"]}

    # ---------- prepare (tạo plan) ----------
    def _resolve_source(self, source: dict) -> tuple:
        """Trả (manifest, security, subject) cho nguồn cài."""
        if source.get("draft_id"):
            draft = self.store.get_draft(source["draft_id"])
            if draft is None:
                raise MarketplaceError(
                    "invalid_config",
                    "Bản nháp nhập thủ công đã hết hạn — hãy dán "
                    "lại cấu hình.")
            listing = draft["listing"]
            return (draft["manifest"], listing.get("security"),
                    {"name": listing.get("name"),
                     "canonical_id":
                         f"{MANUAL_PROVIDER_ID}:{draft['id']}",
                     "provider_id": MANUAL_PROVIDER_ID,
                     "slug": draft["id"],
                     "local_base": draft["local_name"],
                     "source_url": None,
                     "revision": "manual"})
        if source.get("provider_id") == "mcp-marketplace":
            slug = source.get("slug") or ""
            install_cfg = source.get("install") or {}
            manifest = self._substitute_workspace(
                normalize_server_config(
                    install_cfg, source="curated",
                    allowed_cwd_roots=self._allowed_cwd_roots()))
            return (manifest, source.get("security"),
                    {"name": source.get("name") or slug,
                     "canonical_id": f"mcp-marketplace:{slug}",
                     "provider_id": "mcp-marketplace",
                     "slug": slug,
                     "local_base": slug,
                     "source_url": source.get("source_url"),
                     "revision": source.get("version") or "1.0.0"})
        slug = source.get("slug") or ""
        listing = self.provider.get_listing(slug)
        if listing is None:
            raise MarketplaceError(
                "catalog_unavailable",
                "Listing không còn trong dữ kiện hiện có.")
        manifest = self._substitute_workspace(
            normalize_server_config(
                listing.get("install") or {}, source="curated",
                allowed_cwd_roots=self._allowed_cwd_roots()))
        return (manifest, listing.get("security"),
                {"name": listing.get("name"),
                 "canonical_id": f"{CURATED_PROVIDER_ID}:{slug}",
                 "provider_id": CURATED_PROVIDER_ID,
                 "slug": slug,
                 "local_base": slug,
                 "source_url": listing.get("source_url"),
                 "revision": listing.get("revision")
                 or self.catalog_meta().get("bundle_version")})

    def _check_security_gates(self, manifest: dict, security,
                                source_kind: str) -> None:
        if manifest.get("support_state") != "supported":
            reasons = manifest.get("unsupported_reasons") or []
            first = reasons[0] if reasons else {
                "code": "unsupported_transport",
                "text": "Cấu hình chưa được hỗ trợ ở bản 1.3."}
            raise MarketplaceError(first["code"], first["text"])
        security = security or {}
        if int(security.get("critical_findings_count") or 0) > 0:
            raise MarketplaceError(
                "security_critical_blocked",
                "Listing có phát hiện bảo mật mức nghiêm trọng — "
                "bản 1.3 chặn cài đặt, không có ngoại lệ.")
        score = security.get("score")
        if source_kind == "curated" and score is not None and \
                float(score) < float(
                    self.cfg.marketplace_security_min_score):
            raise MarketplaceError(
                "security_below_threshold",
                f"Điểm bảo mật {score} thấp hơn ngưỡng "
                f"{self.cfg.marketplace_security_min_score} — "
                "không cài nhanh ở bản 1.3.")

    def _existing_names(self) -> set:
        names = {str(e.get("name")) for e in
                 load_server_configs(self.cfg.mcp_config_path)}
        names.update(self.store.all_installed().keys())
        return names

    def prepare_install(self, source: dict, *,
                        alias: Optional[str] = None,
                        idempotency_key: str = "",
                        op_type: str = "install",
                        existing_local: str = "") -> dict:
        if idempotency_key:
            prior = self.store.idempotent_get(
                f"prepare:{idempotency_key}")
            if prior:
                op = self.store.get_operation(prior)
                if op is not None:
                    return self.operation_view(op)
        manifest, security, subject = self._resolve_source(source)
        self._check_security_gates(
            manifest, security,
            "manual" if subject["provider_id"] == MANUAL_PROVIDER_ID
            else "curated")
        if op_type == "update" and existing_local:
            local_name = existing_local
        else:
            local_name = slugify_local_name(
                alias or subject["local_base"])
            if not NAME_RE.match(local_name):
                raise MarketplaceError(
                    "invalid_config",
                    "Tên local không hợp lệ (chỉ chữ thường, số, "
                    "- và _, tối đa 64 ký tự).")
            if local_name in self._existing_names():
                raise MarketplaceError(
                    "name_collision",
                    f"Tên '{local_name}' đã có trong cấu hình — "
                    "hãy chọn tên khác (alias) ở bước chuẩn bị.")
        bindings: dict[str, str] = {}
        for req in manifest.get("setup_requirements") or []:
            if req.get("bound_ref"):
                bindings[req["name"]] = req["bound_ref"]
        plan = {"local_name": local_name,
                "manifest": manifest,
                "bindings": bindings,
                "subject": subject,
                "security": security}
        unbound = [r for r in manifest.get("setup_requirements")
                   or [] if r.get("required")
                   and r["name"] not in bindings]
        now = time.time()
        op = {"id": "op_" + uuid.uuid4().hex[:12],
              "type": op_type,
              "stage": "awaiting_secret" if unbound
              else "awaiting_probe_approval",
              "local_name": local_name,
              "subject_name": subject["name"],
              "plan": plan,
              "plan_fingerprint": plan_fingerprint(plan),
              "probe_result": None,
              "probe_plan_fingerprint": "",
              "approvals": [],
              "error": None,
              "last_note": "",
              "created_at": _iso(now),
              "created_ts": now,
              "updated_at": _iso(now),
              "expires_at": _iso(
                  now + self.cfg.marketplace_operation_ttl_s),
              "journal": []}
        self._journal(op, "prepared",
                      f"{op_type} cho {subject['name']}")
        self._save_op(op)
        if idempotency_key:
            self.store.idempotent_put(
                f"prepare:{idempotency_key}", op["id"])
        return self.operation_view(op)

    # ---------- bind secrets ----------
    def bind_secrets(self, operation_id: str,
                     bindings: dict) -> dict:
        op = self._get_op(operation_id)
        if op["stage"] in TERMINAL_STAGES or \
                op["stage"] in ("probing", "committing",
                                "pending_restart"):
            raise MarketplaceError(
                "operation_conflict",
                "Operation đang ở trạng thái không gắn thêm bí "
                "mật được.")
        if not isinstance(bindings, dict) or not bindings:
            raise MarketplaceError(
                "invalid_config", "Chưa có binding nào được gửi.")
        plan = op["plan"]
        known = {r["name"] for r in
                 plan["manifest"].get("setup_requirements") or []}
        merged = dict(plan.get("bindings") or {})
        for name, ref in bindings.items():
            if name not in known:
                raise MarketplaceError(
                    "invalid_config",
                    f"Biến '{name}' không nằm trong yêu cầu của "
                    "server này.")
            if not isinstance(ref, str) or \
                    not VAULT_REF_RE.match(ref):
                raise MarketplaceError(
                    "secret_literal_rejected",
                    "Chỉ chấp nhận tham chiếu Vault (vault:...) — "
                    "không nhận giá trị bí mật trực tiếp.")
            if self.vault is None or not self.vault.exists(ref):
                raise MarketplaceError(
                    "secret_missing",
                    f"Vault không có mục cho biến {name} — hãy "
                    "tạo trước bằng /vault trong chat.")
            merged[name] = ref
        plan["bindings"] = merged
        op["plan_fingerprint"] = plan_fingerprint(plan)
        if op.get("probe_result"):
            # Đổi binding làm plan cũ hết hiệu lực: probe lại.
            op["probe_result"] = None
            op["probe_plan_fingerprint"] = ""
        unbound = [r for r in
                   plan["manifest"].get("setup_requirements") or []
                   if r.get("required") and r["name"] not in merged]
        op["stage"] = ("awaiting_secret" if unbound
                        else "awaiting_probe_approval")
        self._journal(op, "secrets_bound",
                      f"đã gắn {len(bindings)} biến qua Vault")
        return self.operation_view(self._save_op(op))

    # ---------- duyệt theo stage ----------
    def _get_op(self, operation_id: str) -> dict:
        op = self.store.get_operation(operation_id)
        if op is None:
            raise MarketplaceError(
                "invalid_config", "Không tìm thấy operation này.")
        if op["stage"] in ACTIVE_STAGES and \
                time.time() > op.get("created_ts", 0) + \
                self.cfg.marketplace_operation_ttl_s and \
                op["stage"] != "pending_restart":
            op["stage"] = "expired"
            op["error"] = {
                "code": "plan_stale",
                "message": "Kế hoạch đã hết hạn — hãy chuẩn bị "
                           "lại từ đầu."}
            self._save_op(op)
            raise MarketplaceError("plan_stale", op["error"]["message"])
        return op

    def request_stage_approval(self, operation_id: str,
                               stage: str) -> dict:
        op = self._get_op(operation_id)
        local_name = op["local_name"]
        if stage == "probe":
            if op["stage"] != "awaiting_probe_approval":
                raise MarketplaceError(
                    "operation_conflict",
                    "Operation chưa sẵn sàng để xin duyệt chạy thử.")
            title = f"Chạy thử MCP server {op['subject_name']}"
            summary = ("Kết nối thử để liệt kê tool — chưa cài, "
                       "chưa đăng ký tool nào cho agent.")
        elif stage == "commit":
            if op["stage"] != "awaiting_commit_approval":
                raise MarketplaceError(
                    "operation_conflict",
                    "Cần chạy thử thành công trước khi xin duyệt "
                    "bước cuối.")
            if op["type"] != "uninstall" and \
                    op.get("probe_plan_fingerprint") != \
                    op.get("plan_fingerprint"):
                raise MarketplaceError(
                    "plan_stale",
                    "Kế hoạch đã đổi sau khi chạy thử — hãy chạy "
                    "thử lại.")
            titles = {"install": "Cài MCP server",
                      "update": "Cập nhật MCP server",
                      "uninstall": "Gỡ MCP server"}
            title = (f"{titles.get(op['type'], 'Áp dụng MCP server')}"
                     f" {op['subject_name']}")
            summary = self._commit_summary(op)
        else:
            raise MarketplaceError("invalid_config",
                                   "Stage duyệt không hợp lệ.")
        for entry in op.get("approvals") or []:
            if entry.get("stage") == stage and entry.get("pending"):
                raise MarketplaceError(
                    "approval_pending",
                    "Đã có thẻ duyệt đang chờ cho bước này.")
        seq = 1 + sum(1 for a in op.get("approvals") or []
                      if a.get("stage") == stage)
        approval_id = f"mkt_{operation_id}_{stage}_{seq}"
        ttl = float(self.cfg.marketplace_operation_ttl_s)
        payload = {
            "kind": "marketplace_operation",
            "operation_id": operation_id,
            "stage": stage,
            "title": title,
            "summary": summary,
            "target": command_line_of(op["plan"]["manifest"])
            if op["type"] != "uninstall"
            else f"server local: {local_name}",
            "fingerprint": short_fp(op["plan_fingerprint"]),
            "server_name": op["subject_name"],
            "local_name": local_name,
            "tool": "",
            "group": "marketplace",
            "reason": "",
            "marketplace_ttl_s": ttl,
        }
        payload["approval_id"] = approval_id
        self.broker.open(approval_id, payload, ttl_s=ttl)
        op.setdefault("approvals", []).append({
            "stage": stage, "approval_id": approval_id,
            "pending": True, "expires_at": _iso(time.time() + ttl)})
        self._journal(op, f"{stage}_approval_requested", approval_id)
        self._save_op(op)
        self._spawn(self._present_card(payload))
        self._spawn(self._await_stage(operation_id, stage,
                                      approval_id))
        return {"approval_id": approval_id,
                "operation": self.operation_view(op)}

    def _commit_summary(self, op: dict) -> str:
        plan = op["plan"]
        if op["type"] == "uninstall":
            refs = (plan.get("uninstall") or {}).get(
                "delete_vault_refs") or []
            tail = (f" Sẽ xoá {len(refs)} mục Vault chỉ thuộc "
                    "server này." if refs else "")
            return (f"Gỡ {op['local_name']} khỏi cấu hình, chặn "
                    f"tool ngay và khởi động lại để hoàn tất.{tail}")
        probe = op.get("probe_result") or {}
        return (f"{command_line_of(plan['manifest'])} — "
                f"{probe.get('tool_count', 0)} tool, vào group "
                f"mcp:{op['local_name']} với nấc Hỏi trước. Bot "
                "tự khởi động lại để áp dụng; lỗi sẽ tự khôi "
                "phục cấu hình trước đó.")

    async def _await_stage(self, operation_id: str, stage: str,
                           approval_id: str) -> None:
        record = await self.broker.wait(approval_id)
        op = self.store.get_operation(operation_id)
        if op is None:
            return
        for entry in op.get("approvals") or []:
            if entry.get("approval_id") == approval_id:
                entry["pending"] = False
        outcome = record.get("outcome")
        if outcome == "approved":
            self._journal(op, f"{stage}_approved", approval_id)
            self._save_op(op)
            if stage == "probe":
                await self._run_probe(operation_id)
            else:
                await self._run_commit(operation_id)
        elif outcome == "denied":
            op["stage"] = "cancelled"
            op["error"] = {
                "code": "approval_denied",
                "message": "Bạn đã chặn ở bước duyệt — operation "
                           "kết thúc, chưa có gì được ghi."}
            self._journal(op, f"{stage}_denied", approval_id)
            self._save_op(op)
        else:
            back = {"probe": "awaiting_probe_approval",
                    "commit": "awaiting_commit_approval"}[stage]
            if op["stage"] not in TERMINAL_STAGES:
                op["stage"] = back
            op["last_note"] = ("Thẻ duyệt đã hết hạn — bấm xin "
                               "duyệt lại khi sẵn sàng.")
            self._journal(op, f"{stage}_approval_expired",
                          approval_id)
            self._save_op(op)

    async def _run_probe(self, operation_id: str) -> None:
        op = self._get_op(operation_id)
        op["stage"] = "probing"
        self._journal(op, "probe_started")
        self._save_op(op)
        entry = build_entry(op["local_name"], op["plan"]["manifest"],
                            op["plan"].get("bindings") or {})
        if self.mcp is None:
            result = {"ok": False, "error_code": "probe_failed",
                      "error": "MCP manager chưa sẵn sàng",
                      "tools": [], "latency_ms": 0}
        else:
            result = await self.mcp.probe_entry(entry, timeout_s=120)
        op = self._get_op(operation_id)
        if not result.get("ok"):
            op["stage"] = "failed"
            op["error"] = {
                "code": result.get("error_code") or "probe_failed",
                "message": "Chạy thử thất bại: "
                           + redact_text(result.get("error") or "")}
            self._journal(op, "probe_failed",
                          result.get("error_code") or "")
            self._save_op(op)
            return
        tools = result.get("tools") or []
        if not tools:
            op["stage"] = "failed"
            op["error"] = {"code": "no_tools",
                           "message": "Server chạy được nhưng "
                                      "không khai báo tool nào — "
                                      "không cài."}
            self._journal(op, "probe_no_tools")
            self._save_op(op)
            return
        op["probe_result"] = {
            "ok": True,
            "latency_ms": result.get("latency_ms", 0),
            "tool_count": len(tools),
            "tools": [{
                "name": t["name"],
                "description": redact_text(
                    t.get("description") or "", 200),
                "required": list((t.get("inputSchema") or {})
                                 .get("required") or []),
            } for t in tools],
            "tool_fingerprint": tool_fingerprint(tools),
            "at": _iso(),
        }
        op["probe_plan_fingerprint"] = op["plan_fingerprint"]
        op["stage"] = "awaiting_commit_approval"
        self._journal(op, "probe_ok",
                      f"{len(tools)} tool, "
                      f"{result.get('latency_ms', 0)}ms")
        self._save_op(op)

    async def install_one_click(self, operation_id: str) -> dict:
        """Cài đặt một chạm (1.6.0): owner bấm cài trực tiếp trong Mini App
        thì cài luôn, không gửi 2 thẻ duyệt vào Telegram chat.
        Tự động: probe -> đối chiếu bảo mật -> commit."""
        op = self._get_op(operation_id)
        if op["stage"] in TERMINAL_STAGES:
            raise MarketplaceError("operation_conflict",
                                   "Operation đã kết thúc.")
        if op["stage"] == "awaiting_secret":
            raise MarketplaceError("operation_conflict",
                                   "Cần gắn bí mật trước khi cài đặt.")
        self._journal(op, "probe_auto_approved", "one_click_webapp")
        self._save_op(op)
        await self._run_probe(operation_id)
        op = self._get_op(operation_id)
        if op["stage"] == "failed":
            return self.operation_view(op)
        if op["stage"] == "awaiting_commit_approval":
            self._journal(op, "commit_auto_approved", "one_click_webapp")
            self._save_op(op)
            await self._run_commit(operation_id)
        op = self._get_op(operation_id)
        return self.operation_view(op)

    def cancel_operation(self, operation_id: str) -> dict:
        op = self._get_op(operation_id)
        if op["stage"] in TERMINAL_STAGES or \
                op["stage"] == "pending_restart":
            raise MarketplaceError(
                "operation_conflict",
                "Operation đã kết thúc hoặc đang chờ áp dụng — "
                "không huỷ được nữa.")
        for entry in op.get("approvals") or []:
            if entry.get("pending"):
                self.broker.resolve(entry["approval_id"], False)
                entry["pending"] = False
        op["stage"] = "cancelled"
        op["error"] = {"code": "cancelled",
                       "message": "Bạn đã huỷ operation."}
        self._journal(op, "cancelled")
        return self.operation_view(self._save_op(op))

    def operation_view(self, op: dict) -> dict:
        plan = op.get("plan") or {}
        probe = op.get("probe_result")
        return {
            "id": op["id"],
            "type": op["type"],
            "stage": op["stage"],
            "local_name": op.get("local_name"),
            "subject_name": op.get("subject_name"),
            "plan": {
                "local_name": op.get("local_name"),
                "command_line": command_line_of(
                    plan.get("manifest") or {}),
                "package": (plan.get("manifest") or {}).get("package"),
                "policy_effect": "ask",
                "policy_group": f"mcp:{op.get('local_name')}",
                "fingerprint": short_fp(
                    op.get("plan_fingerprint") or ""),
                "secret_requirements": [
                    {"name": r["name"], "location": r["location"],
                     "required": r.get("required", True),
                     "bound": r["name"] in (plan.get("bindings")
                                            or {})}
                    for r in (plan.get("manifest") or {}).get(
                        "setup_requirements") or []],
                "warnings": (plan.get("manifest") or {}).get(
                    "warnings") or [],
            },
            "probe_result": probe,
            "approvals": op.get("approvals") or [],
            "error": op.get("error"),
            "last_note": op.get("last_note", ""),
            "created_at": op.get("created_at"),
            "expires_at": op.get("expires_at"),
        }


    # ---------- commit + rollback (spec 9.6) ----------
    def _manual_entry_hashes(self, data: dict,
                             extra_managed: set) -> dict:
        managed = set(self.store.all_installed()) | extra_managed
        return {str(e.get("name")): config_fingerprint(e)
                for e in _entries_of(data)
                if isinstance(e, dict) and e.get("name")
                and str(e.get("name")) not in managed}

    def _snapshot_for(self, local_name: str) -> dict:
        data = read_mcp_file(self.cfg.mcp_config_path)
        previous_entry = None
        record = self.store.get_installed(local_name)
        if record is not None:
            for entry in _entries_of(data):
                if isinstance(entry, dict) and \
                        entry.get("name") == local_name:
                    previous_entry = copy.deepcopy(entry)
                    break
        group = f"mcp:{local_name}"
        return {"local_name": local_name,
                "previous_entry": previous_entry,
                "previous_policy_verdict":
                    self.policy.get_host_verdict("group", group)
                    if self.policy else None,
                "previous_installed": copy.deepcopy(record)}

    def _write_entry(self, local_name: str,
                     new_entry: Optional[dict]) -> dict:
        """Read-modify-write nguyên tử trên mcp_servers.json:
        thay/bỏ đúng entry managed, giữ nguyên mọi entry khác +
        trường lạ của file. Trả file sau khi ghi."""
        with self._config_lock:
            data = read_mcp_file(self.cfg.mcp_config_path)
            servers = [e for e in _entries_of(data)
                       if not (isinstance(e, dict)
                               and e.get("name") == local_name)]
            if new_entry is not None:
                servers.append(new_entry)
            data["servers"] = servers
            write_mcp_file(self.cfg.mcp_config_path, data)
            return read_mcp_file(self.cfg.mcp_config_path)

    def _restore_snapshot(self, snapshot: dict) -> None:
        local_name = snapshot["local_name"]
        group = f"mcp:{local_name}"
        if self.policy is not None:
            previous = snapshot.get("previous_policy_verdict")
            if previous is None:
                self.policy.remove_host_rule("group", group)
            else:
                self.policy.set_host_rule("group", group, previous)
        self._write_entry(local_name,
                          snapshot.get("previous_entry"))

    def _installed_record(self, op: dict, entry: dict,
                          lifecycle: str) -> dict:
        plan = op["plan"]
        subject = plan["subject"]
        probe = op.get("probe_result") or {}
        previous = self.store.get_installed(op["local_name"]) or {}
        bindings = [{"name": r["name"], "location": r["location"],
                     "vault_ref": (plan.get("bindings") or {})
                     .get(r["name"])}
                    for r in plan["manifest"].get(
                        "setup_requirements") or []]
        return {
            "local_name": op["local_name"],
            "canonical_id": subject["canonical_id"],
            "provider_id": subject["provider_id"],
            "slug": subject.get("slug"),
            "name": subject["name"],
            "source_kind": subject["provider_id"],
            "source_url": subject.get("source_url"),
            "desired_state": "enabled",
            "lifecycle_state": lifecycle,
            "health_state": "unknown",
            "health_detail": "",
            "health_checked_at": None,
            "manifest_fingerprint": manifest_fingerprint(
                plan["manifest"]),
            "config_fingerprint": config_fingerprint(entry),
            "approved_tool_fingerprint":
                probe.get("tool_fingerprint", ""),
            "tool_count": probe.get("tool_count", 0),
            "policy": {"group": f"mcp:{op['local_name']}",
                       "managed_verdict": "ask",
                       "origin": "marketplace_default"},
            "bindings": bindings,
            "installed_revision": subject.get("revision"),
            "available_revision": previous.get("available_revision"),
            "created_at": previous.get("created_at") or _iso(),
            "updated_at": _iso(),
        }

    async def _run_commit(self, operation_id: str) -> None:
        op = self._get_op(operation_id)
        if op["type"] == "uninstall":
            self._commit_uninstall(op)
        else:
            self._commit_install(op)

    def _commit_install(self, op: dict) -> None:
        local_name = op["local_name"]
        group = f"mcp:{local_name}"
        op["stage"] = "committing"
        snapshot = self._snapshot_for(local_name)
        op["rollback"] = snapshot
        self._journal(op, "commit_started")
        self._save_op(op)
        entry = build_entry(local_name, op["plan"]["manifest"],
                            op["plan"].get("bindings") or {})
        record = self._installed_record(op, entry, "committing")
        record["rollback_snapshot"] = snapshot
        try:
            self.store.put_installed(record)
            if self.policy is not None:
                # Tool của server chợ mặc định ở nấc HỎI (ask).
                self.policy.set_host_rule("group", group, "ask")
            manual_before = self._manual_entry_hashes(
                read_mcp_file(self.cfg.mcp_config_path),
                {local_name})
            after = self._write_entry(local_name, entry)
            manual_after = self._manual_entry_hashes(
                after, {local_name})
            if manual_before != manual_after:
                raise RuntimeError(
                    "entry thủ công bị thay đổi ngoài ý muốn")
            written = next(
                (e for e in _entries_of(after)
                 if isinstance(e, dict)
                 and e.get("name") == local_name), None)
            if written is None or config_fingerprint(written) != \
                    config_fingerprint(entry):
                raise RuntimeError(
                    "đọc lại cấu hình không khớp bản đã duyệt")
            record = self._installed_record(op, entry,
                                            "pending_restart")
            record["rollback_snapshot"] = snapshot
            self.store.put_installed(record)
            generation = self.store.next_apply_generation()
            self.store.set_restart_pending({
                "operation_id": op["id"], "generation": generation,
                "kind": op["type"], "local_names": [local_name],
                "rollback_attempted": False, "at": _iso()})
            op["stage"] = "pending_restart"
            self._journal(op, "commit_ok_pending_restart",
                          f"generation {generation}")
            self._save_op(op)
            self.store.prune_operations()
            self._trigger_restart()
        except Exception as exc:
            logger.exception("marketplace: commit thất bại cho %s",
                             local_name)
            restored = True
            try:
                self._restore_snapshot(snapshot)
                if snapshot.get("previous_installed"):
                    prev = snapshot["previous_installed"]
                    self.store.put_installed(prev)
                else:
                    failed = self._installed_record(
                        op, entry, "quarantined")
                    failed["health_state"] = "down"
                    failed["health_detail"] = (
                        "Cài đặt thất bại giữa chừng — đã khôi "
                        "phục cấu hình trước đó.")
                    self.store.put_installed(failed)
            except Exception:
                restored = False
                logger.exception("marketplace: rollback commit lỗi")
            op["stage"] = "failed"
            op["error"] = {
                "code": "commit_failed" if restored
                else "rollback_failed",
                "message": "Ghi cấu hình thất bại"
                           + (" — đã tự khôi phục trạng thái "
                              "trước đó." if restored else
                              " và khôi phục cũng lỗi — kiểm tra "
                              "mục Đã cài.")
                           + f" ({redact_text(str(exc), 120)})"}
            self._journal(op, "commit_failed_restored"
                          if restored else "rollback_failed")
            self._save_op(op)

    # ---------- gỡ cài đặt ----------
    def prepare_uninstall(self, local_name: str, *,
                          delete_vault_refs: Optional[list] = None,
                          idempotency_key: str = "") -> dict:
        record = self.store.get_installed(local_name)
        if record is None:
            raise MarketplaceError(
                "invalid_config",
                "Server này không do marketplace quản lý.")
        if idempotency_key:
            prior = self.store.idempotent_get(
                f"uninstall:{idempotency_key}")
            if prior:
                op = self.store.get_operation(prior)
                if op is not None:
                    return self.operation_view(op)
        # Vault ref độc quyền của server này (không record nào
        # khác dùng chung) mới được phép chọn xoá.
        others: set = set()
        for other in self.store.all_installed().values():
            if other["local_name"] == local_name:
                continue
            for binding in other.get("bindings") or []:
                if binding.get("vault_ref"):
                    others.add(binding["vault_ref"])
        exclusive = []
        for binding in record.get("bindings") or []:
            ref = binding.get("vault_ref")
            if ref and ref not in others and ref not in exclusive:
                exclusive.append(ref)
        chosen = [r for r in (delete_vault_refs or [])
                  if r in exclusive]
        now = time.time()
        plan = {"local_name": local_name,
                "manifest": {"command": None, "args": [],
                             "setup_requirements": []},
                "bindings": {},
                "subject": {"name": record.get("name"),
                            "canonical_id":
                                record.get("canonical_id"),
                            "provider_id":
                                record.get("provider_id"),
                            "slug": record.get("slug")},
                "uninstall": {
                    "exclusive_vault_refs": exclusive,
                    "delete_vault_refs": chosen,
                    "policy_group": f"mcp:{local_name}",
                    "policy_origin": (record.get("policy") or {})
                    .get("origin")}}
        op = {"id": "op_" + uuid.uuid4().hex[:12],
              "type": "uninstall",
              "stage": "awaiting_commit_approval",
              "local_name": local_name,
              "subject_name": record.get("name"),
              "plan": plan,
              "plan_fingerprint": plan_fingerprint(plan),
              "probe_result": None,
              "probe_plan_fingerprint": "n/a",
              "approvals": [], "error": None, "last_note": "",
              "created_at": _iso(now), "created_ts": now,
              "updated_at": _iso(now),
              "expires_at": _iso(now + self.cfg
                                 .marketplace_operation_ttl_s),
              "journal": []}
        self._journal(op, "prepared", "gỡ cài đặt")
        self._save_op(op)
        if idempotency_key:
            self.store.idempotent_put(
                f"uninstall:{idempotency_key}", op["id"])
        return self.operation_view(op)

    def _commit_uninstall(self, op: dict) -> None:
        local_name = op["local_name"]
        group = f"mcp:{local_name}"
        op["stage"] = "committing"
        snapshot = self._snapshot_for(local_name)
        op["rollback"] = snapshot
        self._journal(op, "commit_started")
        self._save_op(op)
        try:
            if self.policy is not None:
                # Chặn tool ngay từ lúc này, trước cả restart.
                self.policy.set_host_rule("group", group, "deny")
            manual_before = self._manual_entry_hashes(
                read_mcp_file(self.cfg.mcp_config_path),
                {local_name})
            after = self._write_entry(local_name, None)
            if self._manual_entry_hashes(after, {local_name}) != \
                    manual_before:
                raise RuntimeError(
                    "entry thủ công bị thay đổi ngoài ý muốn")
            record = self.store.get_installed(local_name)
            if record is not None:
                record["lifecycle_state"] = \
                    "uninstall_pending_restart"
                record["desired_state"] = "disabled"
                record["uninstall_finalize"] = {
                    "delete_vault_refs": (op["plan"].get(
                        "uninstall") or {}).get(
                        "delete_vault_refs") or [],
                    "policy_origin": (op["plan"].get("uninstall")
                                      or {}).get("policy_origin"),
                    "snapshot": snapshot}
                record["updated_at"] = _iso()
                self.store.put_installed(record)
            generation = self.store.next_apply_generation()
            self.store.set_restart_pending({
                "operation_id": op["id"], "generation": generation,
                "kind": "uninstall", "local_names": [local_name],
                "rollback_attempted": False, "at": _iso()})
            op["stage"] = "pending_restart"
            self._journal(op, "uninstall_pending_restart")
            self._save_op(op)
            self._trigger_restart()
        except Exception as exc:
            logger.exception("marketplace: gỡ %s thất bại",
                             local_name)
            restored = True
            try:
                self._restore_snapshot(snapshot)
                if snapshot.get("previous_installed"):
                    self.store.put_installed(
                        snapshot["previous_installed"])
            except Exception:
                restored = False
            op["stage"] = "failed"
            op["error"] = {
                "code": "commit_failed" if restored
                else "rollback_failed",
                "message": "Gỡ cài đặt thất bại"
                           + (" — đã khôi phục như cũ."
                              if restored else
                              " và khôi phục cũng lỗi.")
                           + f" ({redact_text(str(exc), 120)})"}
            self._journal(op, "uninstall_failed")
            self._save_op(op)

    # ---------- bật/tắt, kiểm tra, cập nhật ----------
    def _toggle(self, local_name: str, enable: bool) -> dict:
        record = self.store.get_installed(local_name)
        if record is None:
            raise MarketplaceError(
                "invalid_config",
                "Server này không do marketplace quản lý.")
        if record.get("lifecycle_state") in (
                "config_drift", "quarantined"):
            raise MarketplaceError(
                "config_drift",
                "Server đang bị giữ vì cấu hình/tool đã lệch bản "
                "đã duyệt — hãy Kiểm tra hoặc Cập nhật trước.")
        entry_now = next(
            (e for e in load_server_configs(self.cfg.mcp_config_path)
             if e.get("name") == local_name), None)
        if entry_now is None or \
                config_fingerprint(entry_now) != \
                record.get("config_fingerprint"):
            raise MarketplaceError(
                "config_drift",
                "Cấu hình hiện tại không khớp bản đã duyệt — "
                "không bật/tắt cho tới khi đối chiếu lại.")
        group = f"mcp:{local_name}"
        snapshot = self._snapshot_for(local_name)
        now = time.time()
        op = {"id": "op_" + uuid.uuid4().hex[:12],
              "type": "enable" if enable else "disable",
              "stage": "committing",
              "local_name": local_name,
              "subject_name": record.get("name"),
              "plan": {"local_name": local_name,
                       "manifest": {"command": None, "args": [],
                                    "setup_requirements": []},
                       "bindings": {},
                       "subject": {"name": record.get("name")}},
              "plan_fingerprint": "", "probe_result": None,
              "probe_plan_fingerprint": "", "approvals": [],
              "error": None, "last_note": "",
              "created_at": _iso(now), "created_ts": now,
              "updated_at": _iso(now), "expires_at": _iso(now),
              "journal": [], "rollback": snapshot}
        try:
            if self.policy is not None:
                if enable:
                    verdict = record.pop("pre_disable_verdict",
                                         None) or (record.get(
                                             "policy") or {}).get(
                                             "managed_verdict",
                                             "ask")
                    self.policy.set_host_rule("group", group,
                                              verdict)
                else:
                    current = self.policy.get_host_verdict(
                        "group", group)
                    if current is not None:
                        record["pre_disable_verdict"] = current
                    self.policy.set_host_rule("group", group,
                                              "deny")
            new_entry = dict(entry_now)
            new_entry["enabled"] = enable
            # config_fingerprint không gồm 'enabled' nên bật/tắt
            # không làm lệch đối chiếu.
            self._write_entry(local_name, new_entry)
            record["desired_state"] = "enabled" if enable \
                else "disabled"
            record["lifecycle_state"] = "pending_restart"
            record["updated_at"] = _iso()
            self.store.put_installed(record)
            generation = self.store.next_apply_generation()
            self.store.set_restart_pending({
                "operation_id": op["id"], "generation": generation,
                "kind": op["type"], "local_names": [local_name],
                "rollback_attempted": False, "at": _iso()})
            op["stage"] = "pending_restart"
            self._journal(op, "toggle_pending_restart")
            self._save_op(op)
            self._trigger_restart()
        except MarketplaceError:
            raise
        except Exception as exc:
            try:
                self._restore_snapshot(snapshot)
            except Exception:
                pass
            op["stage"] = "failed"
            op["error"] = {"code": "commit_failed",
                           "message": "Bật/tắt thất bại — đã khôi "
                                      "phục như cũ. ("
                                      + redact_text(str(exc), 120)
                                      + ")"}
            self._save_op(op)
            raise MarketplaceError("commit_failed",
                                   op["error"]["message"])
        return {"operation_id": op["id"]}

    def enable(self, local_name: str) -> dict:
        return self._toggle(local_name, True)

    def disable(self, local_name: str) -> dict:
        return self._toggle(local_name, False)

    async def run_health_check(self, local_name: str) -> dict:
        record = self.store.get_installed(local_name)
        if record is None:
            raise MarketplaceError(
                "invalid_config",
                "Server này không do marketplace quản lý.")
        now = time.time()
        op = {"id": "op_" + uuid.uuid4().hex[:12],
              "type": "health_check", "stage": "probing",
              "local_name": local_name,
              "subject_name": record.get("name"),
              "plan": {"local_name": local_name,
                       "manifest": {"command": None, "args": [],
                                    "setup_requirements": []},
                       "bindings": {}, "subject": {}},
              "plan_fingerprint": "", "probe_result": None,
              "probe_plan_fingerprint": "", "approvals": [],
              "error": None, "last_note": "",
              "created_at": _iso(now), "created_ts": now,
              "updated_at": _iso(now), "expires_at": _iso(now),
              "journal": []}
        self._save_op(op)
        entry = next(
            (e for e in load_server_configs(self.cfg.mcp_config_path)
             if e.get("name") == local_name), None)
        if entry is None:
            record["health_state"] = "config_drift"
            record["health_detail"] = "Không thấy entry trong " \
                                      "file cấu hình."
            record["health_checked_at"] = _iso()
            record["lifecycle_state"] = "config_drift"
            self.store.put_installed(record)
            op["stage"] = "failed"
            op["error"] = {"code": "config_drift",
                           "message": record["health_detail"]}
            self._save_op(op)
            return {"operation_id": op["id"],
                    "health_state": "config_drift"}
        result = await self.mcp.probe_entry(entry, timeout_s=120) \
            if self.mcp is not None else {
                "ok": False, "error": "MCP manager chưa sẵn sàng",
                "tools": [], "error_code": "probe_failed"}
        record = self.store.get_installed(local_name) or record
        record["health_checked_at"] = _iso()
        if not result.get("ok"):
            record["health_state"] = "down"
            record["health_detail"] = redact_text(
                result.get("error") or "không kết nối được")
            if record.get("lifecycle_state") == "active":
                record["lifecycle_state"] = "degraded"
            op["stage"] = "failed"
            op["error"] = {"code": result.get("error_code")
                           or "probe_failed",
                           "message": record["health_detail"]}
        else:
            observed = tool_fingerprint(result.get("tools") or [])
            if observed != record.get("approved_tool_fingerprint"):
                record["health_state"] = "blocked_tool_drift"
                record["health_detail"] = (
                    "Tool đã thay đổi so với bản đã duyệt — "
                    "cần duyệt lại qua Cập nhật.")
                op["stage"] = "failed"
                op["error"] = {"code": "tool_drift",
                               "message": record["health_detail"]}
            else:
                record["health_state"] = "healthy"
                record["health_detail"] = (
                    f"{len(result.get('tools') or [])} tool, "
                    f"{result.get('latency_ms', 0)}ms — khớp bản "
                    "đã duyệt.")
                record["tool_count"] = len(
                    result.get("tools") or [])
                if record.get("lifecycle_state") == "degraded":
                    record["lifecycle_state"] = "active"
                op["stage"] = "done"
        self.store.put_installed(record)
        self._save_op(op)
        return {"operation_id": op["id"],
                "health_state": record["health_state"]}

    def update_check(self, local_name: str) -> dict:
        record = self.store.get_installed(local_name)
        if record is None:
            raise MarketplaceError(
                "invalid_config",
                "Server này không do marketplace quản lý.")
        if record.get("provider_id") != CURATED_PROVIDER_ID:
            return {"update_available": False, "diff": None}
        listing = self.provider.get_listing(record.get("slug")
                                            or "")
        if listing is None:
            return {"update_available": False, "diff": None}
        latest_manifest = self._substitute_workspace(
            normalize_server_config(
                listing.get("install") or {}, source="curated",
                allowed_cwd_roots=self._allowed_cwd_roots()))
        latest_fp = manifest_fingerprint(latest_manifest)
        latest_revision = listing.get("revision") or \
            self.catalog_meta().get("bundle_version")
        record["available_revision"] = latest_revision
        self.store.put_installed(record)
        if latest_fp == record.get("manifest_fingerprint"):
            return {"update_available": False, "diff": None}
        old_pkg = None
        new_pkg = latest_manifest.get("package")
        security = listing.get("security") or {}
        diff = {
            "command_changed": True,
            "package_to": new_pkg,
            "security_score": security.get("score"),
            "revision_from": record.get("installed_revision"),
            "revision_to": latest_revision,
            "note": "Cấu hình niêm yết đã khác bản đang cài — "
                    "chuẩn bị cập nhật để xem chi tiết và duyệt "
                    "lại từ đầu.",
        }
        return {"update_available": True, "diff": diff}

    def prepare_update(self, local_name: str, *,
                       idempotency_key: str = "") -> dict:
        record = self.store.get_installed(local_name)
        if record is None:
            raise MarketplaceError(
                "invalid_config",
                "Server này không do marketplace quản lý.")
        if record.get("provider_id") == CURATED_PROVIDER_ID:
            source = {"provider_id": CURATED_PROVIDER_ID,
                      "slug": record.get("slug")}
        else:
            raise MarketplaceError(
                "invalid_config",
                "Server nhập thủ công không có nguồn cập nhật — "
                "hãy gỡ rồi cài lại bằng bản dán mới.")
        return self.prepare_install(
            source, idempotency_key=idempotency_key,
            op_type="update", existing_local=local_name)

    # ---------- view đã cài ----------
    def installed_view(self, record: dict) -> dict:
        lifecycle = record.get("lifecycle_state", "")
        return {
            "local_name": record.get("local_name"),
            "canonical_id": record.get("canonical_id"),
            "name": record.get("name"),
            "provider_id": record.get("provider_id"),
            "managed": True,
            "lifecycle_state": lifecycle,
            "health_state": record.get("health_state", "unknown"),
            "health_detail": record.get("health_detail", ""),
            "health_checked_at": record.get("health_checked_at"),
            "tool_count": record.get("tool_count", 0),
            "desired_state": record.get("desired_state"),
            "installed_revision": record.get("installed_revision"),
            "available_revision": record.get("available_revision"),
            "update_available": bool(
                record.get("available_revision")
                and record["available_revision"]
                != record.get("installed_revision")),
            "pending_restart": lifecycle.endswith(
                "pending_restart"),
            "policy_verdict": (record.get("policy") or {}).get(
                "managed_verdict", "ask"),
            "config_fingerprint": short_fp(
                record.get("config_fingerprint") or ""),
            "approved_tool_fingerprint": short_fp(
                record.get("approved_tool_fingerprint") or ""),
            "source_url": record.get("source_url"),
            "bindings": [{"name": b.get("name"),
                          "location": b.get("location"),
                          "vault_ref": b.get("vault_ref"),
                          "vault_label": None}
                         for b in record.get("bindings") or []],
        }

    def installed_list(self) -> list[dict]:
        return [self.installed_view(r) for r in
                self.store.all_installed().values()]

    def installed_detail(self, local_name: str) -> dict:
        record = self.store.get_installed(local_name)
        if record is None:
            raise MarketplaceError(
                "invalid_config",
                "Không thấy server managed này.")
        view = self.installed_view(record)
        labels = {}
        if self.vault is not None:
            labels = {item["ref"]: item["label"]
                      for item in self.vault.labels()}
        for binding in view["bindings"]:
            binding["vault_label"] = labels.get(
                binding["vault_ref"])
        return view

    # ---------- boot gate + reconciliation (spec 9.7) ----------
    async def boot_gate(self) -> set:
        """Chạy sau khi MCPManager.start() và TRƯỚC register_into.
        Trả tập tên server managed bị giữ (không đăng ký tool).
        Đồng thời: huỷ operation dở từ tiến trình trước, đối
        chiếu từng record, xử lý restart pending (kèm tự rollback
        khi áp dụng thất bại — tối đa 1 lần)."""
        excluded: set = set()
        if not self.cfg.marketplace_enabled:
            return excluded
        # 1) Operation dở dang từ tiến trình trước: không tự
        # tiếp tục (spec 10.5), trừ operation đang chờ áp dụng.
        for op in self.store.all_operations().values():
            if op.get("stage") in ACTIVE_STAGES and \
                    op.get("stage") != "pending_restart":
                op["stage"] = "failed"
                op["error"] = {
                    "code": "aborted_restart",
                    "message": "Tiến trình bị ngắt bởi khởi động "
                               "lại — hãy thực hiện lại từ đầu."}
                self._journal(op, "aborted_restart")
                self._save_op(op)
        entries = {str(e.get("name")): e for e in
                   load_server_configs(self.cfg.mcp_config_path)}
        snapshot = self.mcp.tool_snapshot() \
            if self.mcp is not None else {}
        statuses = self.mcp.status() if self.mcp is not None \
            else {}
        pending = self.store.restart_pending()
        pending_names = set((pending or {}).get("local_names")
                            or [])
        for record in list(self.store.all_installed().values()):
            name = record["local_name"]
            entry = entries.get(name)
            lifecycle = record.get("lifecycle_state")
            if lifecycle == "uninstall_pending_restart":
                if entry is None:
                    self._finalize_uninstall(record)
                else:
                    record["lifecycle_state"] = "active"
                    record["health_detail"] = (
                        "Gỡ chưa áp dụng được — entry vẫn còn "
                        "trong cấu hình.")
                    self.store.put_installed(record)
                continue
            if entry is None:
                if record.get("desired_state") == "disabled" and \
                        lifecycle in ("pending_restart",
                                      "disabled"):
                    record["lifecycle_state"] = "disabled"
                else:
                    record["lifecycle_state"] = "config_drift"
                    record["health_state"] = "config_drift"
                    record["health_detail"] = (
                        "Không thấy entry trong file cấu hình.")
                self.store.put_installed(record)
                excluded.add(name)
                continue
            if config_fingerprint(entry) != \
                    record.get("config_fingerprint"):
                record["lifecycle_state"] = "config_drift"
                record["health_state"] = "config_drift"
                record["health_detail"] = (
                    "Cấu hình đã lệch bản đã duyệt — tool bị giữ "
                    "cho tới khi đối chiếu lại.")
                self.store.put_installed(record)
                excluded.add(name)
                continue
            if not entry.get("enabled", True):
                record["lifecycle_state"] = "disabled"
                self.store.put_installed(record)
                excluded.add(name)
                continue
            tools = snapshot.get(name)
            if tools is None:
                record["lifecycle_state"] = "degraded"
                record["health_state"] = "down"
                record["health_detail"] = redact_text(
                    (statuses.get(name) or {}).get("error")
                    or "server không kết nối được lúc khởi động")
                self.store.put_installed(record)
                excluded.add(name)
                continue
            observed_fp = tool_fingerprint(tools)
            if observed_fp != record.get(
                    "approved_tool_fingerprint"):
                record["lifecycle_state"] = "degraded"
                record["health_state"] = "blocked_tool_drift"
                record["health_detail"] = (
                    "Tool đã thay đổi so với bản đã duyệt — bị "
                    "giữ, cần duyệt lại qua Cập nhật.")
                self.store.put_installed(record)
                excluded.add(name)
                continue
            record["lifecycle_state"] = "active"
            record["health_state"] = "healthy"
            record["health_checked_at"] = _iso()
            record["tool_count"] = len(tools)
            self.store.put_installed(record)
        # 2) Quyết toán restart pending.
        if pending:
            self._settle_restart_pending(pending, excluded)
        return excluded

    def _apply_succeeded(self, pending: dict) -> bool:
        kind = pending.get("kind")
        for name in pending.get("local_names") or []:
            record = self.store.get_installed(name)
            entries = {str(e.get("name")) for e in
                       load_server_configs(
                           self.cfg.mcp_config_path)}
            if kind == "uninstall":
                if record is not None or name in entries:
                    return False
            elif kind == "rollback":
                if pending.get("rollback_of") == "install":
                    if record is not None or name in entries:
                        return False
                elif record is None:
                    return False
            elif kind == "disable":
                if record is None or record.get(
                        "lifecycle_state") != "disabled":
                    return False
            else:
                if record is None or record.get(
                        "lifecycle_state") != "active":
                    return False
        return True

    def _settle_restart_pending(self, pending: dict,
                                excluded: set) -> None:
        kind = pending.get("kind")
        names = pending.get("local_names") or []
        op_id = pending.get("operation_id")
        op = self.store.get_operation(op_id) if op_id else None
        if self._apply_succeeded(pending):
            labels = {"install": "Đã cài xong",
                      "update": "Đã cập nhật xong",
                      "uninstall": "Đã gỡ xong",
                      "enable": "Đã bật lại",
                      "disable": "Đã tắt",
                      "rollback": "Đã khôi phục cấu hình trước đó"}
            for name in names:
                record = self.store.get_installed(name)
                tools = record.get("tool_count") \
                    if record else None
                tail = f" ({tools} tool đang hoạt động)" \
                    if tools else ""
                self.store.push_notification(
                    f"✅ {labels.get(kind, 'Đã áp dụng')} MCP "
                    f"server '{name}'{tail}.", kind="marketplace")
            if op is not None and op.get("stage") == \
                    "pending_restart":
                op["stage"] = "done"
                self._journal(op, "applied_after_restart")
                self._save_op(op)
            self.store.set_restart_pending(None)
            return
        if kind == "rollback":
            # Rollback cũng không xong: giữ nguyên trạng thái,
            # báo owner, không khởi động lại thêm (tránh vòng lặp).
            for name in names:
                record = self.store.get_installed(name)
                if record is not None:
                    record["lifecycle_state"] = "quarantined"
                    self.store.put_installed(record)
                excluded.add(name)
            self.store.push_notification(
                "⚠️ Khôi phục cấu hình MCP cũ cũng không đạt — "
                "server liên quan đã bị giữ (quarantined). Mở "
                "Mini App > Cài đặt > Công cụ kết nối để xử lý.",
                kind="marketplace")
            if op is not None:
                op["stage"] = "failed"
                op["error"] = {"code": "rollback_failed",
                               "message": "Khôi phục cấu hình "
                                          "trước đó không đạt."}
                self._save_op(op)
            self.store.set_restart_pending(None)
            return
        if not pending.get("rollback_attempted"):
            # Tự rollback cấu hình trước đó từ snapshot đã lưu
            # trong record, rồi khởi động lại đúng 1 lần nữa.
            rolled = []
            for name in names:
                record = self.store.get_installed(name)
                snapshot = (record or {}).get(
                    "rollback_snapshot") or {}
                if not snapshot:
                    continue
                try:
                    self._restore_snapshot(snapshot)
                    if snapshot.get("previous_installed"):
                        self.store.put_installed(
                            snapshot["previous_installed"])
                    else:
                        self.store.remove_installed(name)
                    rolled.append(name)
                except Exception:
                    logger.exception(
                        "marketplace: tự rollback %s lỗi", name)
            pending["rollback_attempted"] = True
            pending["kind"] = "rollback"
            pending["rollback_of"] = kind
            self.store.set_restart_pending(pending)
            self.store.push_notification(
                "⚠️ Áp dụng thay đổi MCP không đạt — Mulon đã "
                "tự khôi phục cấu hình trước đó và sẽ khởi động "
                "lại lần nữa để hoàn tất khôi phục.",
                kind="marketplace")
            if op is not None:
                op["stage"] = "failed"
                op["error"] = {
                    "code": "apply_rolled_back",
                    "message": "Áp dụng sau khởi động lại không "
                               "đạt — đã tự khôi phục cấu hình "
                               "trước đó."}
                self._save_op(op)
            self._boot_needs_restart = True
            return
        # Đã rollback 1 lần mà vẫn lệch (nhánh dự phòng).
        for name in names:
            record = self.store.get_installed(name)
            if record is not None:
                record["lifecycle_state"] = "quarantined"
                self.store.put_installed(record)
            excluded.add(name)
        self.store.push_notification(
            "⚠️ Thay đổi MCP không áp dụng được kể cả sau khôi "
            "phục — server đã bị giữ (quarantined).",
            kind="marketplace")
        if op is not None and op.get("stage") == "pending_restart":
            op["stage"] = "failed"
            op["error"] = {"code": "apply_failed",
                           "message": "Áp dụng sau khởi động lại "
                                      "không đạt."}
            self._save_op(op)
        self.store.set_restart_pending(None)

    def _finalize_uninstall(self, record: dict) -> None:
        local_name = record["local_name"]
        finalize = record.get("uninstall_finalize") or {}
        deleted_labels: list[str] = []
        if self.vault is not None:
            labels = {i["ref"]: i["label"]
                      for i in self.vault.labels()}
            for ref in finalize.get("delete_vault_refs") or []:
                label = labels.get(ref)
                if self.vault.delete(ref):
                    deleted_labels.append(label or ref)
        # Dọn rule policy do installer tạo nếu owner chưa đổi.
        group = f"mcp:{local_name}"
        if self.policy is not None and \
                finalize.get("policy_origin") == \
                "marketplace_default":
            if self.policy.get_host_verdict("group",
                                            group) == "deny":
                self.policy.remove_host_rule("group", group)
        self.store.add_tombstone({
            "local_name": local_name,
            "canonical_id": record.get("canonical_id"),
            "name": record.get("name"),
            "uninstalled_at": _iso(),
            "deleted_vault_labels": deleted_labels})
        self.store.remove_installed(local_name)

    async def settle_boot(self) -> None:
        """Sau khi bề mặt Telegram sẵn sàng: gửi các thông báo
        marketplace đang chờ + thực thi restart lần 2 nếu boot
        gate vừa rollback (đúng 1 lần)."""
        notes = self.store.pop_notifications()
        if self._notifier is not None:
            for note in notes:
                try:
                    await self._notifier(note["text"])
                except Exception:
                    logger.exception(
                        "marketplace: gửi thông báo owner lỗi")
        if self._boot_needs_restart:
            self._boot_needs_restart = False
            self._trigger_restart()

    # ---------- catalog tự cập nhật (owner duyệt riêng) -------
    async def _fetch(self, url: str, timeout: float) -> bytes:
        if self._fetcher is not None:
            result = self._fetcher(url, timeout)
            if asyncio.iscoroutine(result):
                return await result
            return result

        def _blocking() -> bytes:
            import urllib.request
            request = urllib.request.Request(
                url, headers={"User-Agent": "Mulon/1.3 catalog"})
            with urllib.request.urlopen(request,
                                        timeout=timeout) as resp:
                return resp.read()

        return await asyncio.to_thread(_blocking)

    async def maybe_update_catalog(self, *, force: bool = False) \
            -> dict:
        """Kiểm tra + tải catalog tuyển chọn mới nếu có. CHỈ
        cập nhật dữ kiện niêm yết sau khi kiểm checksum — không
        bao giờ tự cài/cập nhật server nào."""
        cfg = self.cfg
        state = self.store.catalog_update_state()
        now = time.time()
        if not cfg.marketplace_catalog_auto_update and not force:
            return {"result": "disabled"}
        if not force and state.get("last_check_at") and \
                now - float(state["last_check_at"]) < \
                cfg.marketplace_catalog_check_interval_s:
            return {"result": "fresh_enough"}
        try:
            raw = await self._fetch(
                cfg.marketplace_catalog_url,
                cfg.marketplace_catalog_timeout_s)
            if len(raw) > cfg.marketplace_max_input_bytes * 64:
                raise ValueError("catalog tải về quá lớn")
            bundle = json.loads(raw.decode("utf-8"))
            error = validate_bundle(bundle)
            if error:
                raise ValueError(error)
            if bundle.get("content_sha256") != \
                    bundle_content_hash(bundle):
                raise ValueError(
                    "checksum nội dung catalog không khớp — giữ "
                    "nguyên dữ kiện cũ")
            current, _meta = self.provider.effective()
            current_version = str((current or {}).get(
                "bundle_version") or "")
            if current is not None and \
                    str(bundle.get("bundle_version")) <= \
                    current_version:
                self.store.set_catalog_update_state(
                    last_check_at=now, last_result="no_change",
                    last_error="")
                return {"result": "no_change"}
            bundle["_fetched_at"] = _iso(now)
            path = Path(cfg.marketplace_catalog_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            tmp = path.with_suffix(path.suffix + ".tmp")
            tmp.write_text(json.dumps(bundle, ensure_ascii=False,
                                      indent=2),
                           encoding="utf-8")
            tmp.replace(path)
            self.store.set_catalog_update_state(
                last_check_at=now, last_result="updated",
                last_error="")
            logger.info("marketplace: catalog tự cập nhật lên "
                        "bản %s (chỉ dữ kiện)",
                        bundle.get("bundle_version"))
            return {"result": "updated",
                    "bundle_version": bundle.get("bundle_version")}
        except Exception as exc:
            self.store.set_catalog_update_state(
                last_check_at=now, last_result="error",
                last_error=redact_text(str(exc), 160))
            logger.warning("marketplace: kiểm tra catalog lỗi: %s",
                           redact_text(str(exc), 160))
            return {"result": "error",
                    "error": redact_text(str(exc), 160)}

    async def refresh_catalog(self) -> dict:
        result = await self.maybe_update_catalog(force=True)
        return {"result": result.get("result"),
                "catalog": self.catalog_meta()}

    async def catalog_loop(self) -> None:
        """Job nền hẹp duy nhất của marketplace (owner đã duyệt):
        kiểm tra lúc khởi động rồi mỗi ngày xét điều kiện tuần.
        Chỉ tải dữ kiện catalog — không cài đặt gì."""
        while True:
            try:
                await self.maybe_update_catalog()
            except Exception:
                logger.exception("marketplace: catalog loop lỗi")
            await asyncio.sleep(24 * 3600)
