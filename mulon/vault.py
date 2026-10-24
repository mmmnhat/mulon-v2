"""Secure Vault tối thiểu (thiết kế mục 16.12).

Nguyên tắc cứng:
- Giá trị bí mật KHÔNG BAO GIỜ đi qua nội dung chat. User nhập qua
  form web một lần do chính agent host (bind 127.0.0.1 — không phải
  Mini App, không phơi ra mạng ngoài).
- Link form chứa token ngẫu nhiên: dùng ĐÚNG 1 lần, hết hạn sau
  VAULT_TOKEN_TTL_S giây (mặc định 600s ~ 10 phút).
- Giá trị nộp được ghi thẳng vào file vault (quyền 0600) dưới một
  ref dạng ``vault:<uuid>``. Agent và mọi bề mặt khác chỉ cầm ref;
  giá trị không vào chat, không vào DB, không vào trajectory/log
  (server tắt access log; handler không log body).
- Đọc giá trị CHỈ qua VaultStore.resolve(ref) — một cửa duy nhất
  cho các luồng thật sự cần dùng (đăng nhập, gọi API...).
"""

from __future__ import annotations

import html
import json
import logging
import os
import secrets
import threading
import time
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, urlparse

logger = logging.getLogger("mulon.vault")


class VaultStore:
    """File vault JSON {ref: {label, value, created_at}}, quyền 0600."""

    def __init__(self, path: str | Path):
        self.path = Path(path)
        self._lock = threading.Lock()

    def _load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            # File hỏng: coi như rỗng trong bộ nhớ nhưng KHÔNG ghi
            # đè cho tới lần put() sau — tránh mất dữ liệu âm thầm.
            logger.warning("vault file đọc lỗi — tạm coi như rỗng")
            return {}

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        os.replace(tmp, self.path)
        try:
            os.chmod(self.path, 0o600)
        except Exception:
            pass

    def put(self, label: str, value: str) -> str:
        from .memory import now_iso

        ref = f"vault:{uuid.uuid4()}"
        with self._lock:
            data = self._load()
            data[ref] = {"label": label, "value": value,
                         "created_at": now_iso()}
            self._save(data)
        return ref

    def resolve(self, ref: str) -> Optional[str]:
        """CỬA ĐỌC DUY NHẤT. Chỉ các luồng cần dùng giá trị thật mới
        gọi hàm này; mọi bề mặt hiển thị chỉ được thấy ref + label."""
        with self._lock:
            entry = self._load().get(ref)
        return entry.get("value") if isinstance(entry, dict) else None

    def exists(self, ref: str) -> bool:
        with self._lock:
            return ref in self._load()

    def labels(self) -> list[dict]:
        """Danh sách ref + label + thời gian — KHÔNG kèm giá trị."""
        with self._lock:
            data = self._load()
        return [
            {"ref": ref, "label": e.get("label", ""),
             "created_at": e.get("created_at", "")}
            for ref, e in sorted(data.items())
            if isinstance(e, dict)
        ]

    def delete(self, ref: str) -> bool:
        with self._lock:
            data = self._load()
            if ref not in data:
                return False
            del data[ref]
            self._save(data)
            return True

    def delete_by_label(self, label: str) -> int:
        lbl = str(label or "").strip()
        if not lbl:
            return 0
        with self._lock:
            data = self._load()
            to_del = [ref for ref, e in data.items() if isinstance(e, dict) and e.get("label") == lbl]
            if not to_del:
                return 0
            for r in to_del:
                del data[r]
            self._save(data)
            return len(to_del)

    def update(self, ref: str, label: Optional[str] = None, value: Optional[str] = None) -> bool:
        from .memory import now_iso

        ref_str = str(ref or "").strip()
        with self._lock:
            data = self._load()
            if ref_str not in data or not isinstance(data[ref_str], dict):
                return False
            if label is not None and str(label).strip():
                data[ref_str]["label"] = str(label).strip()
            if value is not None and str(value) != "":
                data[ref_str]["value"] = str(value)
            data[ref_str]["updated_at"] = now_iso()
            self._save(data)
            return True


_FORM_HTML = """<!doctype html>
<html lang="vi"><head><meta charset="utf-8">
<title>Mulon Vault</title></head>
<body style="font-family: sans-serif; max-width: 32rem; margin: 2rem auto">
<h3>Nhập bí mật cho: {label}</h3>
<p>Giá trị đi thẳng vào vault trên máy của agent — không qua chat,
không vào log. Link này dùng được đúng 1 lần.</p>
<form method="post">
<input type="password" name="value" autocomplete="off"
       style="width: 100%; padding: .5rem" required>
<p><button type="submit" style="padding: .5rem 1rem">Lưu vào vault</button></p>
</form>
</body></html>"""

_DONE_HTML = """<!doctype html>
<html lang="vi"><head><meta charset="utf-8">
<title>Mulon Vault</title></head>
<body style="font-family: sans-serif; max-width: 32rem; margin: 2rem auto">
<h3>Đã lưu vào vault.</h3>
<p>Tham chiếu của bí mật này là:</p>
<p><code>{ref}</code></p>
<p>Đưa ref này cho agent khi một luồng cần dùng. Giá trị thật
không hiển thị ở đây nữa.</p>
</body></html>"""

_GONE_HTML = """<!doctype html>
<html lang="vi"><head><meta charset="utf-8">
<title>Mulon Vault</title></head>
<body style="font-family: sans-serif; max-width: 32rem; margin: 2rem auto">
<h3>Link đã hết hạn hoặc đã được dùng.</h3>
<p>Nhờ agent tạo link mới bằng lệnh /vault.</p>
</body></html>"""


class _VaultHandler(BaseHTTPRequestHandler):
    server_version = "MulonVault/1.0"

    def log_message(self, format, *args):  # noqa: A002 - tắt access log
        pass

    # -- helpers --
    @property
    def _app(self) -> "VaultFormServer":
        return self.server.app  # type: ignore[attr-defined]

    def _token(self) -> Optional[str]:
        parts = [p for p in urlparse(self.path).path.split("/") if p]
        if len(parts) == 2 and parts[0] == "v":
            return parts[1]
        return None

    def _send(self, code: int, body: str) -> None:
        raw = body.encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(raw)

    def do_GET(self):  # noqa: N802
        token = self._token()
        entry = self._app.check_token(token) if token else None
        if entry is None:
            self._send(410, _GONE_HTML)
            return
        self._send(200, _FORM_HTML.format(
            label=html.escape(entry["label"])))

    def do_POST(self):  # noqa: N802
        token = self._token()
        entry = self._app.check_token(token) if token else None
        if entry is None:
            self._send(410, _GONE_HTML)
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        raw = self.rfile.read(min(length, 65536)).decode(
            "utf-8", errors="replace")
        form = parse_qs(raw)
        value = (form.get("value") or [""])[0]
        if not value:
            self._send(400, _GONE_HTML)
            return
        # Đốt token TRƯỚC khi lưu: link chết ngay cả khi lưu lỗi.
        self._app.consume_token(token)
        ref = self._app.store.put(entry["label"], value)
        self._send(200, _DONE_HTML.format(ref=html.escape(ref)))


class VaultFormServer:
    """Server form một lần. start() mở thread nền; stop() đóng."""

    def __init__(self, cfg, store: VaultStore):
        self.cfg = cfg
        self.store = store
        self._tokens: dict[str, dict] = {}
        self._lock = threading.Lock()
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._thread: Optional[threading.Thread] = None

    # ---------- token ----------
    def create_token(self, label: str) -> str:
        token = secrets.token_urlsafe(24)
        with self._lock:
            self._tokens[token] = {
                "label": label,
                "expires_at": time.time() + self.cfg.vault_token_ttl_s,
                "used": False,
            }
        return token

    def check_token(self, token: Optional[str]) -> Optional[dict]:
        if not token:
            return None
        with self._lock:
            entry = self._tokens.get(token)
            if entry is None or entry["used"]:
                return None
            if time.time() > entry["expires_at"]:
                return None
            return dict(entry)

    def consume_token(self, token: str) -> None:
        with self._lock:
            if token in self._tokens:
                self._tokens[token]["used"] = True

    # ---------- vòng đời ----------
    @property
    def port(self) -> int:
        if self._httpd is not None:
            return int(self._httpd.server_address[1])
        return int(self.cfg.vault_port)

    @property
    def running(self) -> bool:
        return self._httpd is not None

    def link_for(self, label: str) -> str:
        token = self.create_token(label)
        return f"http://127.0.0.1:{self.port}/v/{token}"

    def start(self) -> bool:
        if self._httpd is not None:
            return True
        if not self.cfg.vault_port:
            logger.info("vault server TẮT (VAULT_PORT=0)")
            return False
        httpd = ThreadingHTTPServer(
            ("127.0.0.1", int(self.cfg.vault_port)), _VaultHandler)
        httpd.app = self  # type: ignore[attr-defined]
        httpd.daemon_threads = True
        self._httpd = httpd
        self._thread = threading.Thread(
            target=httpd.serve_forever, name="mulon-vault", daemon=True)
        self._thread.start()
        logger.info("vault form server: http://127.0.0.1:%d (chỉ local)",
                    self.port)
        return True

    def stop(self) -> None:
        if self._httpd is not None:
            self._httpd.shutdown()
            self._httpd.server_close()
            self._httpd = None
            self._thread = None


def register_vault_tools(registry, cfg, notifier=None) -> None:
    """Đăng ký tool request_vault_secret (1.6.0) cho agent.

    Khi agent thiếu bí mật (API key, OAuth credentials, tokens...),
    thay vì bắt người dùng gõ lệnh thủ công trong chat, agent gọi tool này
    để gửi thẻ hành động có nút mở Mini App điền sẵn nhãn và khóa nhãn.
    Giá trị người dùng dán vào sẽ đi thẳng vào Kho mã hóa an toàn.
    """
    from .tools import ToolSpec

    async def request_vault_secret(label: str, description: str = "") -> dict:
        lbl = str(label or "").strip()
        if not lbl:
            return {"ok": False, "error": "thiếu nhãn (label) bí mật"}
        safe_param = "vault_" + lbl.replace(":", "__")
        bot_username = getattr(cfg, "_bot_username", "") or "Mulon_bot"
        app_url = ""
        if getattr(cfg, "webapp_url", "") and getattr(cfg, "webapp_app_name", ""):
            app_url = (f"https://t.me/{bot_username}/{cfg.webapp_app_name}"
                       f"?startapp={safe_param}&mode=compact")

        info = {
            "label": lbl,
            "description": str(description or "").strip(),
            "startapp_param": safe_param,
            "direct_url": app_url,
        }
        sent = False
        if notifier is not None:
            try:
                res = notifier(info)
                if hasattr(res, "__await__"):
                    await res
                sent = True
            except Exception as exc:
                logger.warning("Gửi thẻ Vault qua notifier thất bại: %s", exc)

        return {
            "ok": True,
            "label": lbl,
            "card_sent": sent,
            "direct_url": app_url,
            "message": (f"Đã gửi thẻ yêu cầu nhập bí mật cho '{lbl}' vào chat."
                        if sent else f"Vui lòng nhập bí mật cho '{lbl}' trong Mini App."),
        }

    registry.register(ToolSpec(
        name="request_vault_secret",
        description=(
            "Gửi thẻ tương tác vào chat để yêu cầu chủ nhân nhập bí mật "
            "(như API key, Client ID/Secret...) vào Kho lưu trữ an toàn. "
            "Nhãn được điền sẵn, giá trị bảo mật được mã hóa lưu thẳng "
            "vào Kho, không đi qua nội dung chat."
        ),
        parameters={
            "type": "object",
            "properties": {
                "label": {
                    "type": "string",
                    "description": "Nhãn bí mật (vd: google:client_id, google:client_secret)",
                },
                "description": {
                    "type": "string",
                    "description": "Mục đích hoặc hướng dẫn ngắn gọn cho chủ nhân",
                },
            },
            "required": ["label"],
        },
        group="vault",
        timeout_s=15,
        handler=request_vault_secret,
    ), overwrite=True)

    store = VaultStore(cfg.vault_path)

    async def list_vault_secrets() -> dict:
        items = store.labels()
        return {
            "ok": True,
            "count": len(items),
            "secrets": items,
        }

    registry.register(ToolSpec(
        name="list_vault_secrets",
        description=(
            "Liệt kê danh sách các bí mật đang có trong Kho lưu trữ an toàn (chỉ nhãn, ref "
            "và thời gian tạo — KHÔNG BAO GIỜ hiện giá trị bí mật)."
        ),
        parameters={"type": "object", "properties": {}},
        group="vault",
        timeout_s=10,
        handler=list_vault_secrets,
    ), overwrite=True)

    async def delete_vault_secret(ref: str = "", label: str = "") -> dict:
        r = str(ref or "").strip()
        lbl = str(label or "").strip()
        if not r and not lbl:
            return {"ok": False, "error": "cần cung cấp ref (dạng vault:...) hoặc nhãn (label) để xoá"}
        deleted = 0
        if r:
            if store.delete(r):
                deleted += 1
        elif lbl:
            deleted = store.delete_by_label(lbl)
        if deleted > 0:
            return {"ok": True, "message": f"Đã xoá {deleted} bí mật khỏi kho an toàn."}
        return {"ok": False, "error": "Không tìm thấy bí mật tương ứng để xoá."}

    registry.register(ToolSpec(
        name="delete_vault_secret",
        description="Xoá một bí mật khỏi Kho lưu trữ an toàn theo mã tham chiếu ref hoặc nhãn label.",
        parameters={
            "type": "object",
            "properties": {
                "ref": {"type": "string", "description": "Mã tham chiếu dạng vault:<uuid>"},
                "label": {"type": "string", "description": "Tên nhãn của bí mật"},
            },
        },
        group="vault",
        timeout_s=15,
        handler=delete_vault_secret,
    ), overwrite=True)
