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
