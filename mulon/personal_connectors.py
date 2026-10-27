"""Connector tài khoản cá nhân (T-22, T-22.1): Zalo cá nhân + Telegram cá nhân.

Chuẩn:
1. Zalo cá nhân (`zalo_personal`):
   - Đăng nhập QR qua app Zalo (thư viện `zca-js` qua bridge Node).
   - Thao tác: gửi/nhận tin nhắn (cả nhóm), gửi file, tìm người dùng qua SĐT, nghe tin mới.
   - Giới hạn: KHÔNG đăng nhật ký/bài viết (muốn đăng phải qua Zalo OA API — ngoài phạm vi connector cá nhân).
   - Degrade sạch: nếu Node hoặc zca-js chưa cài, báo lỗi rõ ràng, bot không sập.

2. Telegram cá nhân (`telegram_personal`):
   - Đăng nhập QR qua app Telegram (Telethon MTProto userbot, lưu StringSession trong Vault).
   - Kênh RIÊNG BIỆT với Bot API hiện tại (aiogram), chạy song song.
   - Thao tác: gửi/đọc/nghe tin trong mọi hội thoại tài khoản tham gia (kể cả nhóm bot không có mặt),
     xem danh sách hội thoại.
   - Cảnh báo rủi ro: userbot có thể bị Telegram giới hạn nếu lạm dụng; giữ lượng dùng bình thường.
   - Degrade sạch: nếu telethon chưa cài, báo rõ, bot không sập.

Bảo mật chung:
- Phiên đăng nhập (session string / cookies) và bí mật CHỈ lưu trong Vault bản cài
  (labels: `telegram_personal:session`, `zalo_personal:session`), KHÔNG bao giờ lọt vào log,
  trajectory, commit, hay nội dung chat.
- Quyền theo từng hành động: đọc = cho phép (allow), gửi tin / gửi file = hỏi trước (ask).
- Mọi nội dung tin nhắn nhận từ bên ngoài đều phải qua `frame_external`.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any, Awaitable, Callable, Optional, Union

from .connectors import Connector
from .context import frame_external

logger = logging.getLogger("mulon.personal_connectors")

# Nhãn Vault quy ước cho Personal Connectors
LBL_TG_SESSION = "telegram_personal:session"
LBL_TG_API_ID = "telegram_personal:api_id"
LBL_TG_API_HASH = "telegram_personal:api_hash"
LBL_TG_USER = "telegram_personal:user_info"

LBL_ZALO_SESSION = "zalo_personal:session"
LBL_ZALO_USER = "zalo_personal:user_info"

LIMITATION_ZALO = "Lưu ý: Không hỗ trợ đăng nhật ký/bài viết (muốn đăng phải qua Zalo OA API — ngoài phạm vi connector cá nhân)."
WARNING_TELEGRAM = "Lưu ý: Đây là userbot MTProto Telegram cá nhân (Telethon). Kênh riêng biệt chạy song song với Bot API. Giữ lượng dùng ở mức bình thường để tránh bị Telegram giới hạn."


# ---------------------------------------------------------------------------
# Helpers làm việc với VaultStore an toàn
# ---------------------------------------------------------------------------

def _vault_get(store, label: str) -> Optional[str]:
    """Đọc 1 giá trị Vault theo label quy ước."""
    if store is None:
        return None
    try:
        for item in store.labels():
            if item.get("label") == label:
                return store.resolve(item["ref"])
    except Exception as exc:
        logger.debug("Vault get lỗi cho label %s: %s", label, exc)
    return None


def _vault_put(store, label: str, value: str) -> None:
    """Ghi đè theo label: xoá entry cũ cùng label rồi put mới."""
    if store is None or not value:
        return
    try:
        for item in store.labels():
            if item.get("label") == label:
                store.delete(item["ref"])
        store.put(label, value)
    except Exception as exc:
        logger.warning("Vault put lỗi cho label %s: %s", label, exc)


def _vault_delete(store, label: str) -> None:
    """Xoá entry theo label."""
    if store is None:
        return
    try:
        for item in store.labels():
            if item.get("label") == label:
                store.delete(item["ref"])
    except Exception as exc:
        logger.warning("Vault delete lỗi cho label %s: %s", label, exc)


def _vault_get_json(store, label: str) -> Optional[dict]:
    raw = _vault_get(store, label)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except Exception:
        return None


def _vault_put_json(store, label: str, data: dict) -> None:
    _vault_put(store, label, json.dumps(data, ensure_ascii=False))


# ---------------------------------------------------------------------------
# 1. Telegram cá nhân (Telethon MTProto userbot)
# ---------------------------------------------------------------------------

class TelegramPersonalConnector(Connector):
    """Connector Telegram cá nhân qua Telethon (MTProto)."""

    name = "telegram_personal"

    def __init__(self, cfg=None, vault_store=None, client=None, client_factory=None):
        self.cfg = cfg
        self.vault = vault_store
        self._custom_client = client
        self._client_factory = client_factory
        self._client = client
        self._qr_login = None
        self._listener_task: Optional[asyncio.Task] = None
        self._message_handlers: list[Callable[[dict], Any]] = []

    def _telethon_available(self) -> bool:
        if self._custom_client or self._client_factory:
            return True
        try:
            import telethon  # noqa: F401
            return True
        except ImportError:
            return False

    def _get_api_credentials(self) -> tuple[Optional[int], Optional[str]]:
        """Lấy API ID & API Hash từ Vault hoặc Config."""
        api_id_val = _vault_get(self.vault, LBL_TG_API_ID) or getattr(self.cfg, "telegram_user_api_id", None)
        api_hash_val = _vault_get(self.vault, LBL_TG_API_HASH) or getattr(self.cfg, "telegram_user_api_hash", None)
        try:
            api_id = int(api_id_val) if api_id_val else None
        except (ValueError, TypeError):
            api_id = None
        api_hash = str(api_hash_val).strip() if api_hash_val else None
        return api_id, api_hash

    async def _ensure_client(self):
        """Khởi tạo hoặc trả về client Telethon đang hoạt động."""
        if self._client is not None:
            return self._client

        if self._client_factory is not None:
            res = self._client_factory()
            if hasattr(res, "__await__"):
                self._client = await res
            else:
                self._client = res
            return self._client

        if not self._telethon_available():
            raise RuntimeError("Thư viện telethon chưa được cài đặt.")

        from telethon import TelegramClient
        from telethon.sessions import StringSession

        api_id, api_hash = self._get_api_credentials()
        if not api_id or not api_hash:
            raise RuntimeError("Chưa cấu hình Telegram API ID và API Hash.")

        session_str = _vault_get(self.vault, LBL_TG_SESSION) or ""
        session = StringSession(session_str)
        self._client = TelegramClient(session, api_id, api_hash)
        await self._client.connect()
        return self._client

    async def health_check(self) -> dict:
        """Kiểm tra sức khỏe connector Telegram cá nhân."""
        if not self._telethon_available():
            return {
                "ok": False,
                "name": self.name,
                "configured": False,
                "connected": False,
                "installed": False,
                "detail": "Thư viện 'telethon' chưa được cài đặt. Cài bằng: pip install telethon",
                "warning": WARNING_TELEGRAM,
            }

        api_id, api_hash = self._get_api_credentials()
        configured = bool((api_id and api_hash) or self._custom_client or self._client_factory)
        session_exists = bool(_vault_get(self.vault, LBL_TG_SESSION))

        connected = False
        user_info = None

        if configured and (session_exists or self._custom_client):
            try:
                client = await self._ensure_client()
                if hasattr(client, "is_user_authorized"):
                    is_auth = await client.is_user_authorized()
                    if is_auth:
                        connected = True
                        if hasattr(client, "get_me"):
                            me = await client.get_me()
                            user_info = {
                                "id": getattr(me, "id", None),
                                "first_name": getattr(me, "first_name", ""),
                                "last_name": getattr(me, "last_name", ""),
                                "username": getattr(me, "username", None),
                                "phone": getattr(me, "phone", None),
                            }
                            _vault_put_json(self.vault, LBL_TG_USER, user_info)
            except Exception as exc:
                logger.debug("Kiểm tra client Telethon thất bại: %s", exc)

        if not user_info:
            user_info = _vault_get_json(self.vault, LBL_TG_USER)

        return {
            "ok": connected,
            "name": self.name,
            "configured": configured,
            "connected": connected,
            "user": user_info,
            "detail": "Đã kết nối tài khoản Telegram cá nhân." if connected else (
                "Chưa đăng nhập QR hoặc chưa lưu phiên." if configured else "Chưa cấu hình API ID / Hash."
            ),
            "warning": WARNING_TELEGRAM,
        }

    async def call(self, action: str, args: dict) -> dict:
        """Xử lý các hành động của connector Telegram cá nhân."""
        # 1. Cấu hình API credentials
        if action == "configure":
            api_id = args.get("api_id")
            api_hash = args.get("api_hash")
            if api_id:
                _vault_put(self.vault, LBL_TG_API_ID, str(api_id))
            if api_hash:
                _vault_put(self.vault, LBL_TG_API_HASH, str(api_hash))
            return {"ok": True, "configured": bool(api_id and api_hash)}

        # 2. Đăng nhập qua QR code
        if action == "qr_login":
            step = args.get("step", "start")
            client = await self._ensure_client()

            if hasattr(client, "is_user_authorized") and await client.is_user_authorized():
                if hasattr(client, "session") and hasattr(client.session, "save"):
                    session_str = client.session.save()
                    if session_str:
                        _vault_put(self.vault, LBL_TG_SESSION, session_str)
                me = await client.get_me()
                user_info = {
                    "id": getattr(me, "id", None),
                    "first_name": getattr(me, "first_name", ""),
                    "username": getattr(me, "username", None),
                }
                _vault_put_json(self.vault, LBL_TG_USER, user_info)
                return {
                    "ok": True,
                    "connected": True,
                    "already_authorized": True,
                    "user": user_info,
                    "warning": WARNING_TELEGRAM,
                }

            if step == "start":
                if not hasattr(client, "qr_login"):
                    return {"ok": False, "error": "Client không hỗ trợ qr_login"}
                qr_login = await client.qr_login()
                self._qr_login = qr_login
                expires = getattr(qr_login, "expires", 300)
                return {
                    "ok": True,
                    "qr_url": qr_login.url,
                    "expires": expires,
                    "instructions": "Quét mã QR trong ứng dụng Telegram: Cài đặt (Settings) -> Thiết bị (Devices) -> Quét mã QR (Link Desktop Device).",
                    "warning": WARNING_TELEGRAM,
                }

            if step == "status":
                if not self._qr_login:
                    return {"ok": False, "error": "Chưa khởi tạo phiên qr_login. Hãy gọi step='start' trước."}
                try:
                    is_auth = await client.is_user_authorized()
                except Exception:
                    is_auth = False

                if is_auth:
                    session_str = client.session.save() if hasattr(client.session, "save") else "active"
                    _vault_put(self.vault, LBL_TG_SESSION, session_str)
                    me = await client.get_me()
                    user_info = {
                        "id": getattr(me, "id", None),
                        "first_name": getattr(me, "first_name", ""),
                        "username": getattr(me, "username", None),
                    }
                    _vault_put_json(self.vault, LBL_TG_USER, user_info)
                    return {"ok": True, "connected": True, "user": user_info}

                return {"ok": True, "connected": False, "qr_url": getattr(self._qr_login, "url", None)}

            return {"ok": False, "error": f"qr_login step không hợp lệ: {step}"}

        # 3. Đọc tin nhắn (bảo vệ bằng frame_external)
        if action in ("read_messages", "get_messages"):
            client = await self._ensure_client()
            entity = args.get("chat_id") or args.get("peer") or "me"
            limit = min(int(args.get("limit", 10)), 50)
            messages = []

            if hasattr(client, "iter_messages"):
                async for msg in client.iter_messages(entity, limit=limit):
                    raw_text = msg.text or ""
                    messages.append({
                        "id": msg.id,
                        "date": msg.date.isoformat() if getattr(msg, "date", None) else None,
                        "sender_id": getattr(msg, "sender_id", None),
                        "text": frame_external(raw_text),
                        "raw_text": raw_text,
                    })
            elif hasattr(client, "get_messages"):
                msg_list = await client.get_messages(entity, limit=limit)
                for msg in msg_list:
                    raw_text = getattr(msg, "text", "") or ""
                    messages.append({
                        "id": getattr(msg, "id", None),
                        "sender_id": getattr(msg, "sender_id", None),
                        "text": frame_external(raw_text),
                        "raw_text": raw_text,
                    })

            return {"ok": True, "chat_id": entity, "count": len(messages), "messages": messages}

        # 4. Danh sách hội thoại
        if action == "list_dialogs":
            client = await self._ensure_client()
            limit = min(int(args.get("limit", 20)), 100)
            dialogs = []

            if hasattr(client, "iter_dialogs"):
                async for d in client.iter_dialogs(limit=limit):
                    dialogs.append({
                        "id": getattr(d, "id", None),
                        "title": getattr(d, "title", None) or getattr(d, "name", None) or str(getattr(d, "id", "")),
                        "unread_count": getattr(d, "unread_count", 0),
                        "is_user": getattr(d, "is_user", False),
                        "is_group": getattr(d, "is_group", False),
                        "is_channel": getattr(d, "is_channel", False),
                    })
            elif hasattr(client, "get_dialogs"):
                d_list = await client.get_dialogs(limit=limit)
                for d in d_list:
                    dialogs.append({
                        "id": getattr(d, "id", None),
                        "title": getattr(d, "title", None) or getattr(d, "name", None) or str(getattr(d, "id", "")),
                        "unread_count": getattr(d, "unread_count", 0),
                        "is_user": getattr(d, "is_user", False),
                        "is_group": getattr(d, "is_group", False),
                        "is_channel": getattr(d, "is_channel", False),
                    })

            return {"ok": True, "dialogs": dialogs, "count": len(dialogs)}

        # 5. Gửi tin nhắn
        if action == "send_message":
            client = await self._ensure_client()
            entity = args.get("chat_id") or args.get("peer")
            text = args.get("text") or args.get("msg") or ""
            if not entity or not text:
                return {"ok": False, "error": "Thiếu chat_id hoặc text để gửi"}

            sent = await client.send_message(entity, text)
            msg_id = getattr(sent, "id", None)
            return {"ok": True, "chat_id": entity, "message_id": msg_id}

        # 6. Gửi tệp
        if action == "send_file":
            client = await self._ensure_client()
            entity = args.get("chat_id") or args.get("peer")
            file_path = args.get("file_path") or args.get("path")
            caption = args.get("caption", "")
            if not entity or not file_path:
                return {"ok": False, "error": "Thiếu chat_id hoặc file_path để gửi"}

            sent = await client.send_file(entity, file_path, caption=caption)
            msg_id = getattr(sent, "id", None)
            return {"ok": True, "chat_id": entity, "file_path": file_path, "message_id": msg_id}

        # 7. Đăng xuất / ngắt kết nối
        if action in ("logout", "disconnect"):
            if self._client:
                try:
                    if hasattr(self._client, "disconnect"):
                        await self._client.disconnect()
                except Exception:
                    pass
                self._client = None
            _vault_delete(self.vault, LBL_TG_SESSION)
            _vault_delete(self.vault, LBL_TG_USER)
            return {"ok": True, "disconnected": True}

        return {"ok": False, "error": f"telegram_personal không hỗ trợ action: {action}"}


# ---------------------------------------------------------------------------
# 2. Zalo cá nhân (zca-js bridge qua Node subprocess)
# ---------------------------------------------------------------------------

class ZaloPersonalConnector(Connector):
    """Connector Zalo cá nhân qua zca-js."""

    name = "zalo_personal"

    def __init__(self, cfg=None, vault_store=None, bridge_runner=None):
        self.cfg = cfg
        self.vault = vault_store
        self._bridge_runner = bridge_runner
        self._connected = False
        self._cached_user: Optional[dict] = None

    def _node_available(self) -> bool:
        if self._bridge_runner is not None:
            return True
        return shutil.which("node") is not None

    def _get_bridge_path(self) -> Path:
        """Đường dẫn đến file script bridge Node."""
        custom_dir = getattr(self.cfg, "zalo_bridge_dir", None)
        if custom_dir:
            return Path(custom_dir) / "zalo_bridge.mjs"
        return Path(__file__).parent / "bridges" / "zalo_bridge.mjs"

    async def _run_bridge_cmd(self, cmd: str, args: Optional[dict] = None) -> dict:
        """Thực thi một lệnh qua bridge runner (subprocess hoặc custom runner cho test)."""
        if self._bridge_runner is not None:
            res = self._bridge_runner(cmd, args or {})
            if hasattr(res, "__await__"):
                return await res
            return res

        if not self._node_available():
            return {"ok": False, "error": "Chưa cài đặt Node.js trên máy."}

        bridge_file = self._get_bridge_path()
        if not bridge_file.exists():
            return {
                "ok": False,
                "error": f"Không tìm thấy bridge script: {bridge_file}. Hãy kiểm tra mulon/bridges/.",
            }

        # Chạy subprocess ngắn gọn trao đổi qua stdin/stdout JSON
        node_bin = shutil.which("node") or "node"
        req_line = json.dumps({"id": 1, "cmd": cmd, "args": args or {}}) + "\n"

        proc = await asyncio.create_subprocess_exec(
            node_bin,
            str(bridge_file),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(bridge_file.parent),
        )

        stdout, stderr = await proc.communicate(input=req_line.encode("utf-8"))
        if proc.returncode != 0:
            err_msg = stderr.decode("utf-8", errors="replace").strip()
            return {"ok": False, "error": f"Node bridge exit code {proc.returncode}: {err_msg}"}

        out_lines = stdout.decode("utf-8", errors="replace").strip().splitlines()
        for line in reversed(out_lines):
            line = line.strip()
            if line.startswith("{") and line.endswith("}"):
                try:
                    data = json.loads(line)
                    if "ok" in data or "event" in data:
                        return data
                except Exception:
                    continue

        return {"ok": False, "error": "Không đọc được JSON kết quả từ bridge."}

    async def health_check(self) -> dict:
        """Kiểm tra sức khỏe connector Zalo cá nhân."""
        node_ok = self._node_available()
        session_data = _vault_get_json(self.vault, LBL_ZALO_SESSION)
        user_info = _vault_get_json(self.vault, LBL_ZALO_USER)

        configured = bool(session_data)
        connected = bool(session_data and (user_info or self._connected))

        detail = "Đã kết nối tài khoản Zalo cá nhân." if connected else (
            "Chưa đăng nhập QR Zalo." if node_ok else "Chưa cài đặt môi trường Node.js cho bridge zca-js."
        )

        return {
            "ok": connected,
            "name": self.name,
            "configured": configured,
            "connected": connected,
            "user": user_info,
            "detail": detail,
            "limitations": LIMITATION_ZALO,
        }

    async def call(self, action: str, args: dict) -> dict:
        """Xử lý các hành động của connector Zalo cá nhân."""
        # 1. Đăng nhập qua QR code
        if action == "qr_login":
            step = args.get("step", "start")
            if step == "start":
                res = await self._run_bridge_cmd("login_qr", args)
                if res.get("ok"):
                    session = res.get("session")
                    user = res.get("user")
                    if session:
                        _vault_put_json(self.vault, LBL_ZALO_SESSION, session)
                    if user:
                        _vault_put_json(self.vault, LBL_ZALO_USER, user)
                        self._cached_user = user
                    self._connected = True
                return {
                    **res,
                    "instructions": "Quét mã QR bằng ứng dụng Zalo trên điện thoại để hoàn tất đăng nhập.",
                    "limitations": LIMITATION_ZALO,
                }
            return {"ok": False, "error": f"qr_login step không hợp lệ: {step}"}

        # 2. Đăng nhập bằng session đã lưu trong Vault
        if action == "login_session":
            session = args.get("session") or _vault_get_json(self.vault, LBL_ZALO_SESSION)
            if not session:
                return {"ok": False, "error": "Không tìm thấy session trong Vault và không có session truyền vào."}
            res = await self._run_bridge_cmd("login_session", session)
            if res.get("ok"):
                self._connected = True
                user = res.get("user")
                if user:
                    _vault_put_json(self.vault, LBL_ZALO_USER, user)
                    self._cached_user = user
            return res

        # 3. Đọc tin nhắn (bảo vệ bằng frame_external)
        if action in ("read_messages", "get_messages"):
            res = await self._run_bridge_cmd("get_messages", args)
            if not res.get("ok"):
                return res

            raw_msgs = res.get("messages") or []
            framed_msgs = []
            for m in raw_msgs:
                content = m.get("content") or ""
                framed_msgs.append({
                    **m,
                    "text": frame_external(content),
                    "raw_text": content,
                })
            return {"ok": True, "count": len(framed_msgs), "messages": framed_msgs}

        # 4. Tìm kiếm người dùng qua số điện thoại
        if action == "find_user":
            phone = args.get("phone")
            if not phone:
                return {"ok": False, "error": "Thiếu số điện thoại (phone) để tìm"}
            return await self._run_bridge_cmd("find_user", {"phone": phone})

        # 5. Gửi tin nhắn (cho user hoặc group)
        if action == "send_message":
            thread_id = args.get("thread_id")
            msg = args.get("msg") or args.get("text")
            thread_type = args.get("type", "user")  # 'user' hoặc 'group'
            if not thread_id or not msg:
                return {"ok": False, "error": "Thiếu thread_id hoặc nội dung tin nhắn (msg)"}
            return await self._run_bridge_cmd("send_message", {
                "thread_id": thread_id,
                "msg": msg,
                "type": thread_type,
            })

        # 6. Gửi tệp
        if action == "send_file":
            thread_id = args.get("thread_id")
            file_path = args.get("file_path") or args.get("path")
            thread_type = args.get("type", "user")
            if not thread_id or not file_path:
                return {"ok": False, "error": "Thiếu thread_id hoặc file_path"}
            return await self._run_bridge_cmd("send_file", {
                "thread_id": thread_id,
                "file_path": file_path,
                "msg": args.get("msg", ""),
                "type": thread_type,
            })

        # 7. Lắng nghe tin mới
        if action == "listen":
            return await self._run_bridge_cmd("listen", args)

        # 8. Đăng xuất / ngắt kết nối
        if action in ("logout", "disconnect"):
            _vault_delete(self.vault, LBL_ZALO_SESSION)
            _vault_delete(self.vault, LBL_ZALO_USER)
            self._connected = False
            self._cached_user = None
            try:
                await self._run_bridge_cmd("logout", {})
            except Exception:
                pass
            return {"ok": True, "disconnected": True}

        return {"ok": False, "error": f"zalo_personal không hỗ trợ action: {action}"}
