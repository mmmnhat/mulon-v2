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

import asyncio
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
    """File vault JSON {ref: {label, value|value_enc, created_at}}, quyền 0600.

    LƯU Ý AN TOÀN (sửa 1.6.1): mặc định file này KHÔNG mã hoá
    at-rest. Quyền 0600 chỉ chống user khác trên cùng máy đọc file;
    bất kỳ tiến trình nào chạy cùng user, hoặc bản sao file, đều
    đọc được giá trị rõ. Đừng diễn đạt Kho này là "kho mã hoá" ở
    bất kỳ bề mặt nào khi mã hoá chưa bật — xem các docstring/card
    đã sửa theo cùng đợt này.

    MÃ HOÁ AT-REST TUỲ CHỌN (sửa 1.6.2): nếu có key Fernet
    (tham số ``encryption_key`` hoặc env ``VAULT_ENCRYPTION_KEY``)
    VÀ gói ``cryptography`` đã cài thì giá trị mới được mã hoá
    bằng Fernet và lưu ở trường ``value_enc`` (kèm ``enc="fernet"``).
    Không có key, thiếu gói, hoặc key sai định dạng -> vẫn lưu
    plaintext ở trường ``value`` (``enc="none"``) và ghi cảnh báo
    vào log — KHÔNG BAO GIỜ tự nhận là đã mã hoá khi chưa mã hoá.
    Không dùng crypto tự chế: chỉ dùng Fernet của ``cryptography``;
    gói này CHƯA có trong requirements.txt nên muốn bật mã hoá
    phải cài thêm (xem ghi chú trong requirements.txt).
    Migration: entry plaintext cũ vẫn đọc được nguyên vẹn; entry
    cũ chỉ thành mã hoá khi được put/update lại cùng label/ref
    trong lúc key đang bật — KHÔNG ghi đè hàng loạt âm thầm.
    MẤT KEY = MẤT TOÀN BỘ entry đã mã hoá: backup key riêng,
    tách khỏi file vault.
    """

    def __init__(self, path: str | Path, encryption_key: str = None):
        self.path = Path(path)
        self._lock = threading.Lock()
        self._capture_listeners: list = []
        # Sửa 1.6.2: key lấy từ tham số (config đã đọc env) trước,
        # rồi mới tới env trực tiếp — để VaultStore vẫn bật mã hoá
        # khi được dựng từ cfg test thiếu trường mới.
        if encryption_key is None:
            encryption_key = os.environ.get("VAULT_ENCRYPTION_KEY", "")
        self._encryption_key = str(encryption_key or "").strip()
        self._cipher = None
        self._cipher_checked = False
        self._cipher_warned = False

    def on_captured(self, fn) -> None:
        """Đăng ký listener được gọi khi có bí mật mới được lưu vào Kho (label, ref)."""
        self._capture_listeners.append(fn)

    def _notify_captured(self, label: str, ref: str) -> None:
        for fn in list(self._capture_listeners):
            try:
                res = fn(label, ref)
                if hasattr(res, "__await__"):
                    try:
                        asyncio.get_event_loop().create_task(res)
                    except RuntimeError:
                        pass
            except Exception as exc:
                logger.warning("listener vault capture lỗi (bỏ qua): %s", exc)

    @property
    def encryption_active(self) -> bool:
        """True chỉ khi có key hợp lệ VÀ gói cryptography đã cài."""
        return self._get_cipher() is not None

    def _get_cipher(self):
        # Lazy: lỗi key/gói không được làm gãy khởi động bot, chỉ
        # ảnh hưởng đúng các thao tác Vault (put/resolve).
        if self._cipher_checked:
            return self._cipher
        self._cipher_checked = True
        if not self._encryption_key:
            return None
        try:
            from cryptography.fernet import Fernet
        except ImportError:
            if not self._cipher_warned:
                self._cipher_warned = True
                logger.warning(
                    "VAULT_ENCRYPTION_KEY đã đặt nhưng gói "
                    "'cryptography' chưa cài — Vault vẫn lưu plaintext "
                    "JSON 0600, KHÔNG mã hoá. Cài bằng: "
                    "pip install cryptography")
            return None
        try:
            self._cipher = Fernet(self._encryption_key.encode("utf-8"))
        except Exception:
            if not self._cipher_warned:
                self._cipher_warned = True
                logger.warning(
                    "VAULT_ENCRYPTION_KEY không phải Fernet key hợp lệ "
                    "— Vault vẫn lưu plaintext, KHÔNG mã hoá. Tạo key "
                    "bằng: python3 -c \"from cryptography.fernet import "
                    "Fernet; print(Fernet.generate_key().decode())\"")
            self._cipher = None
        return self._cipher

    def _encrypt_value(self, value: str) -> Optional[str]:
        cipher = self._get_cipher()
        if cipher is None:
            return None
        return cipher.encrypt(value.encode("utf-8")).decode("ascii")

    def _decrypt_entry(self, entry: dict) -> Optional[str]:
        token = entry.get("value_enc")
        if not isinstance(token, str) or not token:
            return None
        cipher = self._get_cipher()
        if cipher is None:
            logger.warning(
                "vault entry đã mã hoá nhưng không giải mã được "
                "(thiếu key hoặc thiếu gói cryptography)")
            return None
        try:
            return cipher.decrypt(token.encode("ascii")).decode("utf-8")
        except Exception:
            logger.warning(
                "vault entry mã hoá giải mã lỗi — có thể sai key "
                "hoặc file đã bị sửa")
            return None

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
        tmp = self.path.with_suffix(
            f"{self.path.suffix}.tmp.{os.getpid()}.{uuid.uuid4().hex[:8]}")
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
            # Sửa 1.6.1: khử trùng theo label. Trước đây mỗi lần nhập
            # là 1 ref mới cùng label, còn _vault_get chỉ lấy entry
            # đầu tiên theo thứ tự UUID nên bot có thể dùng mãi bản
            # cũ/sai mà owner không biết bản nào đang hiệu lực.
            # Từ nay 1 label chỉ còn đúng 1 entry: entry mới nhất.
            lbl = str(label or "").strip()
            for old_ref in [r for r, e in data.items()
                            if isinstance(e, dict) and e.get("label") == lbl]:
                del data[old_ref]
            # Sửa 1.6.2: entry mới mã hoá khi cipher bật, ngược lại
            # plaintext như cũ — entry cũ khác label không bị đụng tới.
            entry = {"label": lbl, "created_at": now_iso()}
            enc = self._encrypt_value(value)
            if enc is not None:
                entry["value_enc"] = enc
                entry["enc"] = "fernet"
            else:
                entry["value"] = value
                entry["enc"] = "none"
            data[ref] = entry
            self._save(data)
        self._notify_captured(lbl, ref)
        return ref

    def resolve(self, ref: str) -> Optional[str]:
        """CỬA ĐỌC DUY NHẤT. Chỉ các luồng cần dùng giá trị thật mới
        gọi hàm này; mọi bề mặt hiển thị chỉ được thấy ref + label."""
        with self._lock:
            data = self._load()
            entry = data.get(ref)
            if not isinstance(entry, dict):
                # Cho phép resolve bằng label nếu truyền nhãn thay vì ref UUID
                for e in data.values():
                    if isinstance(e, dict) and e.get("label") == ref:
                        entry = e
                        break
        if not isinstance(entry, dict):
            return None
        # Sửa 1.6.2: entry mã hoá đọc qua giải mã; entry plaintext
        # cũ (kể cả file từ trước khi bật mã hoá) vẫn đọc như cũ.
        if entry.get("value_enc") is not None:
            return self._decrypt_entry(entry)
        return entry.get("value")

    def exists(self, ref: str) -> bool:
        with self._lock:
            data = self._load()
            if ref in data:
                return True
            return any(isinstance(e, dict) and e.get("label") == ref for e in data.values())

    def labels(self) -> list[dict]:
        """Danh sách ref + label + thời gian — KHÔNG kèm giá trị."""
        with self._lock:
            data = self._load()
        return [
            {"ref": ref, "label": e.get("label", ""),
             "created_at": e.get("created_at", ""),
             # Sửa 1.6.2: chỉ báo trạng thái mã hoá, không kèm giá trị.
             "encrypted": e.get("enc") == "fernet"}
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
                # Sửa 1.6.2: entry đang mã hoá mà cipher không bật
                # (mất key / thiếu gói) thì TỪ CHỐI ghi đè giá trị
                # thay vì hạ cấp âm thầm xuống plaintext.
                if (data[ref_str].get("value_enc") is not None
                        and self._get_cipher() is None):
                    return False
                enc = self._encrypt_value(str(value))
                if enc is not None:
                    data[ref_str]["value_enc"] = enc
                    data[ref_str]["enc"] = "fernet"
                    data[ref_str].pop("value", None)
                else:
                    data[ref_str]["value"] = str(value)
                    data[ref_str]["enc"] = "none"
                    data[ref_str].pop("value_enc", None)
            data[ref_str]["updated_at"] = now_iso()
            self._save(data)
        if value is not None and str(value) != "":
            self._notify_captured(data[ref_str].get("label", ""), ref_str)
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


class VaultBroker:
    """Quản lý các yêu cầu bí mật Vault đang chờ trong phiên (1.7.3 T-10.1)."""

    def __init__(self):
        self._pending: dict[str, dict] = {}

    def open(self, label: str, info: dict) -> dict:
        loop = asyncio.get_event_loop()
        entry = {
            "label": label,
            "info": dict(info),
            "future": loop.create_future(),
            "created_at": time.time(),
        }
        self._pending[label] = entry
        return entry

    def is_waiting(self, label: str) -> bool:
        return label in self._pending and not self._pending[label]["future"].done()

    def resolve(self, label: str, ref: str) -> bool:
        entry = self._pending.pop(label, None)
        if entry is None or entry["future"].done():
            return False
        entry["future"].set_result(ref)
        return True

    async def wait(self, label: str, timeout_s: float = 60.0) -> Optional[str]:
        entry = self._pending.get(label)
        if entry is None:
            return None
        try:
            return await asyncio.wait_for(asyncio.shield(entry["future"]), timeout=timeout_s)
        except asyncio.TimeoutError:
            self._pending.pop(label, None)
            return None


def register_vault_tools(registry, cfg, notifier=None,
                         vault_broker: Optional[VaultBroker] = None) -> None:
    """Đăng ký tool request_vault_secret (1.6.0 + 1.7.3) cho agent.

    Khi agent thiếu bí mật (API key, OAuth credentials, tokens...),
    thay vì bắt người dùng gõ lệnh thủ công trong chat, agent gọi tool này
    để gửi thẻ hành động có nút mở Mini App điền sẵn nhãn và khóa nhãn.
    Giá trị người dùng dán vào sẽ đi thẳng vào Kho trên máy
    (file JSON quyền 0600; chỉ mã hoá at-rest khi bật
    VAULT_ENCRYPTION_KEY + gói cryptography — xem VaultStore).
    """
    from .tools import ToolSpec

    async def request_vault_secret(label: str, description: str = "",
                                   wait_timeout_s: float = 0.0) -> dict:
        lbl = str(label or "").strip()
        if not lbl:
            return {"ok": False, "error": "thiếu nhãn (label) bí mật"}
        safe_param = "vault_" + lbl.replace(":", "__")
        bot_username = (getattr(cfg, "bot_username", "")
                        or getattr(cfg, "_bot_username", "")
                        or "Mulon_bot")
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
        if vault_broker is not None:
            vault_broker.open(lbl, info)

        sent = False
        if notifier is not None:
            try:
                res = notifier(info)
                if hasattr(res, "__await__"):
                    res = await res
                if res is False:
                    sent = False
                elif isinstance(res, dict) and not res.get("ok", True):
                    sent = False
                else:
                    sent = True
            except Exception as exc:
                logger.warning("Gửi thẻ Vault qua notifier thất bại: %s", exc)
                sent = False

        ok = sent if notifier is not None else False
        if not ok:
            return {
                "ok": False,
                "label": lbl,
                "card_sent": False,
                "direct_url": app_url,
                "message": f"Chưa gửi được thẻ cho '{lbl}'. Vui lòng nhập bí mật cho nhãn này trong Mini App.",
            }

        if wait_timeout_s > 0.0 and vault_broker is not None:
            ref = await vault_broker.wait(lbl, timeout_s=wait_timeout_s)
            if ref:
                return {
                    "ok": True,
                    "label": lbl,
                    "ref": ref,
                    "card_sent": True,
                    "direct_url": app_url,
                    "message": f"Bí mật cho nhãn '{lbl}' đã được lưu vào Kho an toàn (mã tham chiếu: {ref}). Có thể tiếp tục thực hiện công việc.",
                }
            return {
                "ok": False,
                "timeout": True,
                "label": lbl,
                "card_sent": True,
                "direct_url": app_url,
                "message": f"Hết thời gian chờ ({int(wait_timeout_s)}s) người dùng nhập bí mật cho '{lbl}'.",
            }

        return {
            "ok": True,
            "label": lbl,
            "card_sent": True,
            "direct_url": app_url,
            "message": (f"Đã gửi thẻ yêu cầu nhập bí mật cho '{lbl}' vào chat."
                        if sent else f"Chưa gửi được thẻ cho '{lbl}'. "
                        "Vui lòng nhập bí mật cho nhãn này trong Mini App."),
        }

    registry.register(ToolSpec(
        name="request_vault_secret",
        description=(
            "Gửi thẻ tương tác vào chat để yêu cầu chủ nhân nhập bí mật "
            "(như API key, Client ID/Secret...) vào Kho lưu trữ trên máy. "
            "Nhãn được điền sẵn, giá trị bảo mật được lưu thẳng "
            "vào Kho (file JSON quyền 0600; mã hoá at-rest chỉ khi "
            "bật VAULT_ENCRYPTION_KEY + gói cryptography), "
            "không đi qua nội dung chat."
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
                "wait_timeout_s": {
                    "type": "number",
                    "description": "Số giây chờ người dùng nhập bí mật (0 = không chờ trong tool, nhận qua callback)",
                },
            },
            "required": ["label"],
        },
        group="vault",
        timeout_s=120,
        handler=request_vault_secret,
    ), overwrite=True)

    # Sửa 1.6.2: truyền key mã hoá (nếu cfg có) để store này cũng
    # mã hoá như store dựng ở main.py; thiếu trường thì VaultStore
    # tự đọc env VAULT_ENCRYPTION_KEY.
    store = VaultStore(cfg.vault_path,
                       getattr(cfg, "vault_encryption_key", ""))

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
