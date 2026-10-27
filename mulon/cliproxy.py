"""mulon.cliproxy — Quản lý cổng model chính thức CLIProxyAPI (T-14).

Formal hoá CLIProxyAPI (github.com/router-for-me/CLIProxyAPI) làm cổng
model chính thức của MuLon:
- Nhận diện / quản lý tiến trình CLIProxyAPI đi kèm (kiểm tra sống/chết,
  tự khởi chạy theo cấu hình bản cài, báo trạng thái Mini App).
- Quản lý danh sách provider, model và tài khoản CLI đã đăng nhập (chỉ
  hiển thị trạng thái, bí mật nằm ngoài repo).
- Tuân thủ luật proxy-only: model vẫn CHỈ gọi qua proxy local (127.0.0.1:8317);
  đổi provider là đổi phía sau proxy, không gọi thẳng API ngoài.
- Degrade: proxy chết => báo rõ cho người dùng, bot không sập.
- Đa nền tảng theo T-15: dùng bản CLIProxyAPI phù hợp từng OS (macOS, Linux, Windows),
  không hardcode path.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import platform
import re
import shutil
import socket
import sys
import time
from pathlib import Path
from typing import Any, Optional

from .paths import PROJECT_ROOT, resolve_path

logger = logging.getLogger(__name__)

DEFAULT_CLIPROXY_HOST = "127.0.0.1"
DEFAULT_CLIPROXY_PORT = 8317
DEFAULT_CLIPROXY_BASE_URL = f"http://{DEFAULT_CLIPROXY_HOST}:{DEFAULT_CLIPROXY_PORT}/v1"

# Danh sách tên file thực thi thông dụng của CLIProxyAPI trên các hệ điều hành
_EXECUTABLE_NAMES = (
    "cliproxyapi",
    "cliproxyapi.exe",
    "CLIProxyAPI",
    "CLIProxyAPI.exe",
    "EasyCLIProxyAPI",
    "EasyCLIProxyAPI.exe",
    "easycliproxyapi",
)


def find_cliproxy_executable(custom_path: Optional[str | Path] = None) -> Optional[Path]:
    """Tìm file thực thi CLIProxyAPI trên hệ thống (cross-platform, T-15).
    
    Thứ tự tìm kiếm:
    1. custom_path nếu được truyền vào hoặc cấu hình qua env CLIPROXY_BINARY_PATH.
    2. Trong thư mục bin/ của dự án (bin/cliproxyapi, bin/CLIProxyAPI, v.v.).
    3. Thư mục gốc dự án.
    4. PATH hệ thống (shutil.which).
    5. Thư mục mặc định người dùng: ~/.cliproxy/bin hoặc Application Support / AppData.
    """
    if custom_path:
        p = resolve_path(custom_path)
        if p.is_file() and os.access(p, os.X_OK if sys.platform != "win32" else os.R_OK):
            return p

    env_path = os.environ.get("CLIPROXY_BINARY_PATH", "").strip()
    if env_path:
        p = resolve_path(env_path)
        if p.is_file() and os.access(p, os.X_OK if sys.platform != "win32" else os.R_OK):
            return p

    # Quét trong bin/ của dự án và root dự án
    search_dirs = [
        PROJECT_ROOT / "bin",
        PROJECT_ROOT,
        Path.home() / ".cliproxy" / "bin",
        Path.home() / ".cliproxy",
        Path.home() / ".local" / "bin",
    ]
    if sys.platform == "darwin":
        search_dirs.append(Path.home() / "Library" / "Application Support" / "CLIProxyAPI")
    elif sys.platform.startswith("win"):
        appdata = os.environ.get("APPDATA")
        if appdata:
            search_dirs.append(Path(appdata) / "CLIProxyAPI")

    for d in search_dirs:
        if not d.is_dir():
            continue
        for name in _EXECUTABLE_NAMES:
            candidate = d / name
            if candidate.is_file() and os.access(candidate, os.X_OK if sys.platform != "win32" else os.R_OK):
                return candidate

    # Quét PATH
    for name in _EXECUTABLE_NAMES:
        found = shutil.which(name)
        if found:
            p = Path(found).resolve()
            if p.is_file():
                return p

    return None


def mask_secret_identifier(raw: str) -> str:
    """Che chuỗi định danh tài khoản để tránh lộ thông tin nhạy cảm (Rule 5)."""
    raw = str(raw or "").strip()
    if not raw:
        return "tài khoản ẩn danh"
    if "@" in raw:
        parts = raw.split("@", 1)
        name, domain = parts[0], parts[1]
        masked_name = name[:2] + "***" if len(name) > 2 else name[:1] + "***"
        return f"{masked_name}@{domain}"
    if len(raw) <= 4:
        return raw[:1] + "***"
    return raw[:3] + "***" + raw[-2:]


def categorize_model_provider(model_name: str) -> str:
    """Phân loại nhà cung cấp (provider) từ tên model của CLIProxyAPI."""
    m = (model_name or "").lower().strip()
    if not m:
        return "Không xác định"
    if m.startswith("gemini") or "google" in m or m.startswith("models/gemini"):
        return "Google Gemini"
    if m.startswith("claude") or "anthropic" in m:
        return "Anthropic Claude"
    if m.startswith(("gpt-", "o1-", "o3-", "chatgpt-", "text-embedding-", "dall-e")):
        return "OpenAI"
    if m.startswith("muse/") or m.startswith("muse-"):
        return "Muse (muse2api)"
    if "codex" in m:
        return "Codex"
    if "grok" in m or "xai" in m:
        return "xAI Grok"
    if "kimi" in m or "moonshot" in m:
        return "Moonshot Kimi"
    if "deepseek" in m:
        return "DeepSeek"
    if "qwen" in m:
        return "Qwen"
    return "Khác / Tuỳ chỉnh"


def detect_cliproxy_accounts(
    config_path: Optional[str | Path] = None,
    cliproxy_dir: Optional[str | Path] = None,
) -> list[dict[str, Any]]:
    """Phát hiện danh sách tài khoản CLI / Upstream đã cấu hình trong CLIProxyAPI.
    
    Quy tắc bảo mật (Rule 5):
    - Tuyệt đối không trả về API key thật, token hay mật khẩu.
    - Định danh tài khoản/email được che (masking).
    """
    accounts: list[dict[str, Any]] = []
    candidates: list[Path] = []

    if config_path:
        candidates.append(resolve_path(config_path))
    if cliproxy_dir:
        cdir = resolve_path(cliproxy_dir)
        candidates.extend([cdir / "config.yaml", cdir / "config.yml", cdir / "config.json"])

    env_cfg = os.environ.get("CLIPROXY_CONFIG_PATH", "").strip()
    if env_cfg:
        candidates.append(resolve_path(env_cfg))

    candidates.extend([
        PROJECT_ROOT / "config" / "cliproxy.yaml",
        PROJECT_ROOT / "config" / "cliproxy.json",
        Path.home() / ".cliproxy" / "config.yaml",
        Path.home() / ".cliproxy" / "config.json",
    ])

    seen_files = set()
    for f in candidates:
        if not f.is_file() or str(f) in seen_files:
            continue
        seen_files.add(str(f))
        try:
            content = f.read_text(encoding="utf-8")
            data = None
            if f.suffix in (".yaml", ".yml"):
                try:
                    import yaml
                    data = yaml.safe_load(content)
                except Exception:
                    pass
            elif f.suffix == ".json":
                try:
                    data = json.loads(content)
                except Exception:
                    pass

            if isinstance(data, dict):
                # 1. Quét openai-compatibility (như muse2api hoặc upstream bên thứ ba)
                compat = data.get("openai-compatibility") or []
                if isinstance(compat, list):
                    for item in compat:
                        if isinstance(item, dict):
                            name = item.get("name") or "openai-upstream"
                            prefix = item.get("prefix") or ""
                            models = [m.get("name") if isinstance(m, dict) else str(m) for m in item.get("models", [])]
                            accounts.append({
                                "provider": name,
                                "prefix": prefix,
                                "account_id": f"upstream:{prefix or name}",
                                "status": "active",
                                "type": "upstream",
                                "models": models,
                            })

                # 2. Quét các CLI accounts theo provider
                for prov in ("google", "anthropic", "openai", "codex", "kimi", "grok", "accounts"):
                    prov_data = data.get(prov)
                    if isinstance(prov_data, list):
                        for idx, entry in enumerate(prov_data):
                            if isinstance(entry, dict):
                                email = entry.get("email") or entry.get("user") or entry.get("id") or f"cli_acc_{idx+1}"
                                accounts.append({
                                    "provider": prov,
                                    "account_id": mask_secret_identifier(str(email)),
                                    "status": "ready" if entry.get("active", True) else "disabled",
                                    "type": "cli_account",
                                    "models": entry.get("models") or [],
                                })
                    elif isinstance(prov_data, dict):
                        email = prov_data.get("email") or prov_data.get("user") or "cli_account"
                        accounts.append({
                            "provider": prov,
                            "account_id": mask_secret_identifier(str(email)),
                            "status": "ready",
                            "type": "cli_account",
                            "models": prov_data.get("models") or [],
                        })
        except Exception as exc:
            logger.debug("Lỗi đọc cấu hình cliproxy từ %s: %s", f, exc)

    return accounts


async def probe_cliproxy_health(
    host: str = DEFAULT_CLIPROXY_HOST,
    port: int = DEFAULT_CLIPROXY_PORT,
    timeout_s: float = 1.0,
) -> dict[str, Any]:
    """Kiểm tra sức khoẻ cổng CLIProxyAPI bằng TCP connect và truy vấn /v1/models (async).
    
    Quy tắc kiến trúc:
    - CHỈ kiểm tra cổng local (127.0.0.1 / localhost).
    - Degrade trung thực: kết nối bị từ chối -> down; timeout -> degraded; kết nối tốt -> ok.
    """
    base_url = f"http://{host}:{port}/v1"
    res: dict[str, Any] = {
        "status": "unknown",
        "running": False,
        "host": host,
        "port": port,
        "base_url": base_url,
        "latency_ms": 0.0,
        "models_count": 0,
        "models": [],
        "providers": [],
        "error": None,
        "detail": "Đang kiểm tra...",
    }

    t0 = time.monotonic()
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(host, port),
            timeout=timeout_s,
        )
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        t_tcp = round((time.monotonic() - t0) * 1000, 1)
        res["latency_ms"] = t_tcp
        res["running"] = True
    except (ConnectionRefusedError, OSError) as exc:
        res["status"] = "down"
        res["running"] = False
        res["error"] = str(exc)
        res["detail"] = f"Cổng {port} đang đóng — tiến trình CLIProxyAPI chưa chạy."
        return res
    except asyncio.TimeoutError:
        res["status"] = "unknown"
        res["running"] = False
        res["error"] = "TCP timeout"
        res["detail"] = f"Hết thời gian chờ kết nối tới {host}:{port}."
        return res

    # TCP đã thông, truy vấn GET /v1/models trên loopback
    try:
        models, raw_providers = await _fetch_remote_models(host, port, timeout_s=max(1.5, timeout_s))
        res["status"] = "ok"
        res["running"] = True
        res["models_count"] = len(models)
        res["models"] = models
        res["providers"] = sorted(list(raw_providers))
        res["detail"] = f"Đang hoạt động tại {host}:{port} ({len(models)} model sẵn sàng)."
    except Exception as exc:
        res["status"] = "unknown"
        res["running"] = True
        res["error"] = str(exc)
        res["detail"] = f"Cổng {port} mở nhưng chưa trả lời danh sách model: {exc}"

    return res


async def _fetch_remote_models(host: str, port: int, timeout_s: float = 1.5) -> tuple[list[str], set[str]]:
    """Gọi GET /v1/models qua HTTP loopback an toàn bằng asyncio streams."""
    reader, writer = await asyncio.wait_for(
        asyncio.open_connection(host, port),
        timeout=timeout_s,
    )
    req = (
        f"GET /v1/models HTTP/1.1\r\n"
        f"Host: {host}:{port}\r\n"
        f"User-Agent: MuLon-CLIProxy-Probe\r\n"
        f"Accept: application/json\r\n"
        f"Connection: close\r\n\r\n"
    )
    writer.write(req.encode("ascii"))
    await writer.drain()

    raw_resp = await asyncio.wait_for(reader.read(65536), timeout=timeout_s)
    writer.close()
    try:
        await writer.wait_closed()
    except Exception:
        pass

    resp_text = raw_resp.decode("utf-8", errors="replace")
    parts = resp_text.split("\r\n\r\n", 1)
    if len(parts) < 2:
        raise ValueError("Phản hồi HTTP từ proxy không đúng chuẩn")

    header_text, body_text = parts[0], parts[1]
    if " 200 " not in header_text.split("\r\n", 1)[0]:
        raise ValueError(f"Proxy trả về HTTP status không phải 200: {header_text.splitlines()[0]}")

    data = json.loads(body_text)
    models_list = []
    providers: set[str] = set()

    data_entries = data.get("data") if isinstance(data, dict) else (data if isinstance(data, list) else [])
    for entry in data_entries or []:
        mid = entry.get("id") or entry.get("name") if isinstance(entry, dict) else str(entry)
        if mid:
            models_list.append(str(mid))
            providers.add(categorize_model_provider(str(mid)))

    return models_list, providers


class CLIProxyManager:
    """Bộ điều khiển chính thức CLIProxyAPI (T-14)."""

    def __init__(self, cfg: Optional[Any] = None) -> None:
        self.cfg = cfg
        self._process: Optional[asyncio.subprocess.Process] = None
        self._cache: Optional[tuple[float, dict[str, Any]]] = None
        self._cache_ttl_s: float = 3.0

    @property
    def host(self) -> str:
        return DEFAULT_CLIPROXY_HOST

    @property
    def port(self) -> int:
        return DEFAULT_CLIPROXY_PORT

    @property
    def base_url(self) -> str:
        if self.cfg and getattr(self.cfg, "proxy_base_url", None):
            return str(self.cfg.proxy_base_url)
        return DEFAULT_CLIPROXY_BASE_URL

    async def get_status(self, force_refresh: bool = False) -> dict[str, Any]:
        """Lấy thông tin trạng thái toàn diện của cổng CLIProxyAPI (có cache)."""
        now = time.monotonic()
        if not force_refresh and self._cache is not None:
            ts, cached = self._cache
            if now - ts < self._cache_ttl_s:
                return dict(cached)

        health = await probe_cliproxy_health(self.host, self.port)
        accounts = self.get_accounts()
        exe = self.get_executable()

        status: dict[str, Any] = {
            **health,
            "executable": str(exe) if exe else None,
            "executable_found": exe is not None,
            "managed_process_running": self._process is not None and self._process.returncode is None,
            "managed_pid": self._process.pid if (self._process and self._process.returncode is None) else None,
            "auto_start_configured": bool(getattr(self.cfg, "cliproxy_auto_start", False)),
            "accounts_count": len(accounts),
            "accounts": accounts,
        }
        self._cache = (now, status)
        return status

    def get_executable(self) -> Optional[Path]:
        custom = getattr(self.cfg, "cliproxy_binary_path", None)
        return find_cliproxy_executable(custom)

    def get_accounts(self) -> list[dict[str, Any]]:
        cfg_path = getattr(self.cfg, "cliproxy_config_path", None)
        cdir = getattr(self.cfg, "cliproxy_dir", None)
        return detect_cliproxy_accounts(cfg_path, cdir)

    async def fetch_models(self) -> list[dict[str, Any]]:
        """Lấy danh sách model kèm thông tin phân loại nhà cung cấp."""
        health = await self.get_status(force_refresh=True)
        models_out = []
        for m in health.get("models", []):
            models_out.append({
                "id": m,
                "name": m,
                "provider": categorize_model_provider(m),
            })
        return models_out

    async def start_process(self) -> dict[str, Any]:
        """Tự động khởi chạy tiến trình CLIProxyAPI nếu chưa chạy."""
        cur = await probe_cliproxy_health(self.host, self.port)
        if cur.get("running"):
            return {
                "ok": True,
                "already_running": True,
                "detail": f"CLIProxyAPI đã đang chạy tại {self.host}:{self.port}.",
            }

        exe = self.get_executable()
        if not exe:
            return {
                "ok": False,
                "error": "Không tìm thấy file thực thi CLIProxyAPI. Vui lòng cài đặt CLIProxyAPI hoặc chỉ định đường dẫn qua CLIPROXY_BINARY_PATH.",
            }

        cmd = [str(exe)]
        cfg_path = getattr(self.cfg, "cliproxy_config_path", None)
        if cfg_path and Path(cfg_path).is_file():
            cmd.extend(["--config", str(cfg_path)])

        try:
            self._process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            # Chờ cổng sẵn sàng trong tối đa 3 giây
            for _ in range(10):
                await asyncio.sleep(0.3)
                check = await probe_cliproxy_health(self.host, self.port, timeout_s=0.5)
                if check.get("running"):
                    return {
                        "ok": True,
                        "pid": self._process.pid,
                        "detail": f"Đã khởi chạy CLIProxyAPI (PID {self._process.pid}) thành công tại {self.host}:{self.port}.",
                    }

            return {
                "ok": False,
                "error": f"Tiến trình khởi chạy (PID {self._process.pid}) nhưng cổng {self.port} chưa phản hồi sau 3 giây.",
            }
        except Exception as exc:
            logger.error("Lỗi khởi chạy CLIProxyAPI: %s", exc)
            return {"ok": False, "error": f"Lỗi khởi chạy: {exc}"}

    async def stop_process(self) -> dict[str, Any]:
        """Dừng tiến trình CLIProxyAPI nếu do MuLon quản lý."""
        if self._process is not None and self._process.returncode is None:
            try:
                self._process.terminate()
                await asyncio.wait_for(self._process.wait(), timeout=3.0)
            except Exception:
                try:
                    self._process.kill()
                except Exception:
                    pass
            pid = self._process.pid
            self._process = None
            return {"ok": True, "detail": f"Đã dừng tiến trình CLIProxyAPI (PID {pid})."}
        return {"ok": False, "error": "Không có tiến trình CLIProxyAPI nào do MuLon quản lý đang chạy."}

    def format_degrade_message(self, status: Optional[dict[str, Any]] = None) -> str:
        """Thông báo degrade rõ ràng cho người dùng khi proxy bị down."""
        st = status or {}
        detail = st.get("detail") or f"cổng {self.port} không phản hồi"
        return (
            f"⚠️ <b>Cổng model (CLIProxyAPI) không sẵn sàng</b> ({detail}).\n\n"
            "Bot vẫn hoạt động an toàn (không sập), nhưng các yêu cầu gọi model AI sẽ tạm dừng "
            "cho đến khi tiến trình CLIProxyAPI tại <code>127.0.0.1:8317</code> được khởi chạy lại."
        )
