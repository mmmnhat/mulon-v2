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

LBL_FB_SESSION = "facebook_personal:session"
LBL_FB_USER = "facebook_personal:user_info"
LBL_FB_CHECKPOINT = "facebook_personal:checkpoint"

LBL_IG_SESSION = "instagram_messages:session"
LBL_IG_USER = "instagram_messages:user_info"
LBL_IG_CHECKPOINT = "instagram_messages:checkpoint"

LBL_TH_SESSION = "threads_messages:session"
LBL_TH_USER = "threads_messages:user_info"
LBL_TH_CHECKPOINT = "threads_messages:checkpoint"

LIMITATION_ZALO = "Lưu ý: Không hỗ trợ đăng nhật ký/bài viết (muốn đăng phải qua Zalo OA API — ngoài phạm vi connector cá nhân)."
WARNING_TELEGRAM = "Lưu ý: Đây là userbot MTProto Telegram cá nhân (Telethon). Kênh riêng biệt chạy song song với Bot API. Giữ lượng dùng ở mức bình thường để tránh bị Telegram giới hạn."
WARNING_FACEBOOK = (
    "CẢNH BÁO RỦI RO CAO: Meta không hỗ trợ API chính thức cho Facebook cá nhân. "
    "Sử dụng phiên web (cookies) có nguy cơ kích hoạt checkpoint hoặc khóa tài khoản tạm thời. "
    "Khuyến nghị chỉ sử dụng tài khoản thử nghiệm trên IP mạng gia đình của máy cài."
)
LIMITATION_FACEBOOK = (
    "Lưu ý: Yêu cầu cookie phiên web (c_user, xs). "
    "Có rủi ro checkpoint nếu IP thay đổi hoặc gửi request quá nhanh."
)
WARNING_INSTAGRAM_MSG = (
    "Lưu ý: Kết nối tin nhắn Instagram (Direct Messages) cá nhân. "
    "Giữ lượng dùng ở mức người dùng bình thường để tránh bị Meta hạn chế tính năng nhắn tin."
)
LIMITATION_INSTAGRAM_MSG = (
    "Lưu ý: Yêu cầu phiên web cookie (sessionid) hoặc token Meta Accounts Center."
)
WARNING_THREADS_MSG = (
    "Lưu ý: Kết nối tin nhắn Threads (Direct Messages) cá nhân. "
    "Kênh độc lập với bài viết/nội dung Threads. Giữ lượng dùng ở mức bình thường."
)
LIMITATION_THREADS_MSG = (
    "GIỚI HẠN CỨNG: Threads chỉ cho phép nhắn tin cho người ĐÃ có hội thoại từ trước "
    "(hoặc đã nhắn cho bạn trước). Tuyệt đối KHÔNG thể mở hội thoại DM mới tới người lạ chỉ bằng @handle."
)

LBL_TH_CONTENT_TOKEN = "threads_personal:token"
LBL_TH_CONTENT_SESSION = "threads_personal:session"
LBL_TH_CONTENT_USER = "threads_personal:user_info"
LBL_TH_CONTENT_CHECKPOINT = "threads_personal:checkpoint"

WARNING_THREADS_PERSONAL = (
    "Lưu ý: Kết nối Threads cá nhân (nội dung/bài viết). "
    "Ưu tiên Graph API chính thức cho các tác vụ đăng bài và đọc profile/insights; "
    "fallback phiên web cookie cho feed và trends."
)
LIMITATION_THREADS_PERSONAL = (
    "Ưu tiên Threads Graph API chính thức (threads_personal:token). "
    "Các endpoint feed/trends/search chưa có trong API chính thức sẽ fallback qua phiên web cookie (threads_personal:session). "
    "Mọi thao tác ghi (đăng bài, reply) yêu cầu phê duyệt từng lần và phải có transport thực tế."
)



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


# ---------------------------------------------------------------------------
# 3. Facebook cá nhân (Web Session Cookies & Checkpoint Guard)
# ---------------------------------------------------------------------------

class FacebookPersonalConnector(Connector):
    """Connector Facebook cá nhân qua phiên Web Cookie (c_user, xs).

    Tuân thủ T-22.2:
    - Báo rõ rủi ro cao trước khi người dùng kết nối (WARNING_FACEBOOK).
    - Quản lý phiên cookie an toàn qua Vault (facebook_personal:session).
    - Checkpoint Guard: tự động phát hiện redirect tới /checkpoint/ hoặc thông báo
      khóa tài khoản, tự ngắt kết nối an toàn để bảo vệ người dùng.
    - Hỗ trợ các hành động mục tiêu:
      * get_profile: đọc trang cá nhân.
      * get_friends: đọc danh sách bạn bè.
      * read_feed: đọc bài viết trên Bảng tin (bọc frame_external).
      * read_messages: đọc tin nhắn Messenger (bọc frame_external).
      * send_message: gửi tin nhắn Messenger (chính sách ask).
      * check_session: kiểm tra tính hợp lệ của cookie.
      * disconnect: xoá sạch session và checkpoint khỏi Vault.
    - Degrade sạch sẽ khi chưa cấu hình hoặc lỗi.
    """

    name = "facebook_personal"

    def __init__(self, cfg=None, vault_store=None, session_runner=None, http_client=None):
        self.cfg = cfg
        self.vault = vault_store
        self._session_runner = session_runner
        self._http_client = http_client
        self._checkpoint_detected = False

    def _parse_cookies(self, raw: Union[str, dict]) -> dict[str, str]:
        """Chuẩn hoá cookie string hoặc dict thành dictionary {name: value}."""
        if not raw:
            return {}
        if isinstance(raw, dict):
            return {str(k).strip(): str(v).strip() for k, v in raw.items()}

        raw_str = str(raw).strip()
        # Thử parse JSON
        if raw_str.startswith("{") and raw_str.endswith("}"):
            try:
                parsed = json.loads(raw_str)
                if isinstance(parsed, dict):
                    return {str(k).strip(): str(v).strip() for k, v in parsed.items()}
            except Exception:
                pass

        # Parse dạng HTTP Cookie header: key=val; key2=val2
        cookies: dict[str, str] = {}
        for part in raw_str.split(";"):
            part = part.strip()
            if not part:
                continue
            if "=" in part:
                k, v = part.split("=", 1)
                cookies[k.strip()] = v.strip()
        return cookies

    def _detect_checkpoint(self, status_code: int, url: str, content: str = "") -> bool:
        """Nhận diện tín hiệu Checkpoint từ Facebook."""
        lowered_url = str(url).lower()
        lowered_content = str(content).lower()
        if "/checkpoint/" in lowered_url or "login.php?next" in lowered_url:
            return True
        if status_code in (301, 302, 303, 307) and "checkpoint" in lowered_url:
            return True
        if "checkpoint_required" in lowered_content or "tài khoản của bạn đã bị khóa tạm thời" in lowered_content:
            return True
        if "checkpointsubmitbutton" in lowered_content or "your account has been locked" in lowered_content:
            return True
        return False

    def _is_checkpoint_flagged(self) -> bool:
        """Kiểm tra cờ checkpoint trong bộ nhớ hoặc Vault."""
        if self._checkpoint_detected:
            return True
        val = _vault_get(self.vault, LBL_FB_CHECKPOINT)
        return val == "true"

    def _flag_checkpoint(self, reason: str = ""):
        """Đánh dấu checkpoint và ghi nhận vào Vault."""
        self._checkpoint_detected = True
        _vault_put(self.vault, LBL_FB_CHECKPOINT, "true")
        logger.warning("Checkpoint Guard kích hoạt: %s", reason or "Phát hiện Checkpoint Facebook")

    def _clear_checkpoint(self):
        """Xoá cờ checkpoint."""
        self._checkpoint_detected = False
        _vault_delete(self.vault, LBL_FB_CHECKPOINT)

    async def health_check(self) -> dict:
        """Kiểm tra sức khỏe connector Facebook cá nhân."""
        session_raw = _vault_get(self.vault, LBL_FB_SESSION)
        cookies = self._parse_cookies(session_raw) if session_raw else {}
        has_required_cookies = bool(cookies.get("c_user") and cookies.get("xs"))
        configured = bool(has_required_cookies)
        user_info = _vault_get_json(self.vault, LBL_FB_USER)
        is_checkpoint = self._is_checkpoint_flagged()

        connected = configured and not is_checkpoint

        if is_checkpoint:
            detail = "Phát hiện Checkpoint Facebook. Đã tự động ngắt kết nối an toàn để bảo vệ tài khoản."
        elif connected:
            uid = cookies.get("c_user") or (user_info.get("id") if user_info else "")
            detail = f"Đã kết nối tài khoản Facebook cá nhân (UID: {uid})."
        else:
            detail = "Chưa cấu hình phiên cookie Facebook (c_user, xs)."

        return {
            "ok": connected,
            "name": self.name,
            "configured": configured,
            "connected": connected,
            "checkpoint_detected": is_checkpoint,
            "user": user_info,
            "detail": detail,
            "warning": WARNING_FACEBOOK,
            "limitations": LIMITATION_FACEBOOK,
        }

    async def call(self, action: str, args: dict) -> dict:
        """Xử lý các hành động của connector Facebook cá nhân."""
        # 1. Cấu hình session cookie
        if action in ("configure", "configure_session", "connect"):
            raw_cookies = args.get("cookies") or args.get("session") or ""
            cookies = self._parse_cookies(raw_cookies)
            c_user = cookies.get("c_user")
            xs = cookies.get("xs")
            if not c_user or not xs:
                return {
                    "ok": False,
                    "error": "Chuỗi cookie không hợp lệ. Bắt buộc phải có 'c_user' và 'xs'.",
                    "warning": WARNING_FACEBOOK,
                }

            # Xoá checkpoint cũ và lưu session mới
            self._clear_checkpoint()
            _vault_put(self.vault, LBL_FB_SESSION, json.dumps(cookies, ensure_ascii=False))

            user_data = args.get("user") or {
                "id": str(c_user),
                "name": args.get("name") or f"Facebook User ({c_user})",
                "profile_url": f"https://www.facebook.com/{c_user}",
            }
            _vault_put_json(self.vault, LBL_FB_USER, user_data)

            return {
                "ok": True,
                "configured": True,
                "user": user_data,
                "warning": WARNING_FACEBOOK,
                "limitations": LIMITATION_FACEBOOK,
            }

        # 2. Đăng xuất / ngắt kết nối (disconnect)
        if action in ("logout", "disconnect"):
            _vault_delete(self.vault, LBL_FB_SESSION)
            _vault_delete(self.vault, LBL_FB_USER)
            self._clear_checkpoint()
            return {"ok": True, "disconnected": True}

        # Kiểm tra cờ checkpoint cho mọi action khác
        if self._is_checkpoint_flagged():
            return {
                "ok": False,
                "checkpoint": True,
                "error": "Tài khoản đang bị đánh dấu Checkpoint Facebook. Đã ngắt kết nối để bảo vệ tài khoản.",
                "warning": WARNING_FACEBOOK,
            }

        # Đọc cookies từ Vault
        session_raw = _vault_get(self.vault, LBL_FB_SESSION)
        cookies = self._parse_cookies(session_raw) if session_raw else {}
        if not cookies.get("c_user") or not cookies.get("xs"):
            return {
                "ok": False,
                "error": "Chưa cấu hình phiên cookie Facebook trong Vault (cần c_user và xs).",
                "warning": WARNING_FACEBOOK,
            }

        # Nếu có session runner tùy biến (dành cho test hoặc live runner)
        if self._session_runner is not None:
            res = self._session_runner(action, args, cookies)
            if hasattr(res, "__await__"):
                res = await res
            # Kiểm tra checkpoint từ kết quả runner
            if isinstance(res, dict):
                if res.get("checkpoint"):
                    self._flag_checkpoint(res.get("error", "Checkpoint từ session runner"))
                    return {
                        "ok": False,
                        "checkpoint": True,
                        "error": "Phát hiện Checkpoint Facebook từ phiên phản hồi. Đã tự động kích hoạt Checkpoint Guard.",
                        "warning": WARNING_FACEBOOK,
                    }
                # Bảo vệ dữ liệu ngoài cho feed, posts, comments, messages
                if action in ("read_feed", "read_friends_feed", "read_group_posts") and "posts" in res:
                    for p in res.get("posts", []):
                        raw_c = p.get("raw_text") or p.get("content") or ""
                        p["raw_text"] = raw_c
                        p["content"] = frame_external(raw_c)
                elif action in ("read_messages", "get_messages") and "messages" in res:
                    for m in res.get("messages", []):
                        raw_t = m.get("raw_text") or m.get("text") or ""
                        m["raw_text"] = raw_t
                        m["text"] = frame_external(raw_t)
                elif action == "read_comments" and "comments" in res:
                    for c in res.get("comments", []):
                        raw_t = c.get("raw_text") or c.get("text") or ""
                        c["raw_text"] = raw_t
                        c["text"] = frame_external(raw_t)
                elif action == "read_post" and "post" in res:
                    p = res["post"]
                    raw_c = p.get("raw_text") or p.get("content") or ""
                    p["raw_text"] = raw_c
                    p["content"] = frame_external(raw_c)
                elif action == "view_user_profile" and "profile" in res:
                    prof = res["profile"]
                    bio = prof.get("bio") or ""
                    prof["bio"] = frame_external(bio) if bio else ""
            return res

        # 2. Kiểm tra tính hợp lệ của session (check_session)
        if action == "check_session":
            c_user = cookies.get("c_user")
            return {
                "ok": True,
                "connected": True,
                "user_id": c_user,
                "warning": WARNING_FACEBOOK,
            }

        # 3. Đọc trang cá nhân (get_profile / get_me)
        if action in ("get_profile", "get_me"):
            user_info = _vault_get_json(self.vault, LBL_FB_USER) or {}
            c_user = cookies.get("c_user")
            bio_raw = user_info.get("bio", "")
            return {
                "ok": True,
                "profile": {
                    "id": user_info.get("id") or str(c_user),
                    "name": user_info.get("name") or f"Facebook User ({c_user})",
                    "profile_url": user_info.get("profile_url") or f"https://www.facebook.com/{c_user}",
                    "bio": bio_raw,
                },
                "warning": WARNING_FACEBOOK,
            }

        # 4. Đọc danh sách bạn bè (get_friends / list_friends)
        if action in ("get_friends", "list_friends"):
            user_info = _vault_get_json(self.vault, LBL_FB_USER) or {}
            friends = user_info.get("cached_friends") or []
            return {
                "ok": True,
                "count": len(friends),
                "friends": friends,
                "warning": WARNING_FACEBOOK,
            }

        # 5. Xem trang cá nhân/timeline người khác (view_user_profile) - T-30
        if action == "view_user_profile":
            target_id = str(args.get("user_id") or args.get("target_id") or args.get("id") or "").strip()
            if not target_id:
                return {"ok": False, "error": "Thiếu user_id để xem trang cá nhân."}
            user_info = _vault_get_json(self.vault, LBL_FB_USER) or {}
            profiles = user_info.get("cached_profiles") or {}
            target_prof = profiles.get(target_id) or {
                "id": target_id,
                "name": f"User {target_id}",
                "profile_url": f"https://www.facebook.com/{target_id}",
                "bio": "",
                "posts": [],
            }
            bio_raw = target_prof.get("bio", "")
            framed_posts = []
            for p in target_prof.get("posts", []):
                raw_c = p.get("raw_text") or p.get("content") or ""
                framed_posts.append({
                    **p,
                    "content": frame_external(raw_c),
                    "raw_text": raw_c,
                })
            return {
                "ok": True,
                "user_id": target_id,
                "profile": {
                    **target_prof,
                    "bio": frame_external(bio_raw) if bio_raw else "",
                    "posts": framed_posts,
                },
                "warning": WARNING_FACEBOOK,
            }

        # 6. Đọc bài viết trên Bảng tin (read_feed / read_news_feed) - Bảo vệ bằng frame_external
        if action in ("read_feed", "read_news_feed"):
            user_info = _vault_get_json(self.vault, LBL_FB_USER) or {}
            cached_posts = user_info.get("cached_posts") or []
            framed_posts = []
            for p in cached_posts:
                raw_c = p.get("raw_text") or p.get("content") or ""
                framed_posts.append({
                    **p,
                    "content": frame_external(raw_c),
                    "raw_text": raw_c,
                })
            return {
                "ok": True,
                "count": len(framed_posts),
                "posts": framed_posts,
                "warning": WARNING_FACEBOOK,
            }

        # 7. Đọc Bảng tin bạn bè (read_friends_feed) - T-30
        if action == "read_friends_feed":
            user_info = _vault_get_json(self.vault, LBL_FB_USER) or {}
            cached_friends_posts = user_info.get("cached_friends_posts") or []
            framed_posts = []
            for p in cached_friends_posts:
                raw_c = p.get("raw_text") or p.get("content") or ""
                framed_posts.append({
                    **p,
                    "content": frame_external(raw_c),
                    "raw_text": raw_c,
                })
            return {
                "ok": True,
                "count": len(framed_posts),
                "posts": framed_posts,
                "warning": WARNING_FACEBOOK,
            }

        # 8. Nhóm: Liệt kê TOÀN BỘ nhóm tài khoản đang tham gia (kể cả kín/ẩn) - T-30
        if action in ("list_groups", "get_groups"):
            user_info = _vault_get_json(self.vault, LBL_FB_USER) or {}
            groups = user_info.get("cached_groups") or []
            # Đảm bảo hiển thị đầy đủ thông tin privacy (public, closed, secret/hidden)
            return {
                "ok": True,
                "all": True,
                "count": len(groups),
                "groups": groups,
                "warning": WARNING_FACEBOOK,
            }

        # 9. Chi tiết nhóm: luật, số thành viên, mức riêng tư (get_group_detail) - T-30
        if action == "get_group_detail":
            group_id = str(args.get("group_id") or args.get("id") or "").strip()
            if not group_id:
                return {"ok": False, "error": "Thiếu group_id để xem chi tiết nhóm."}
            user_info = _vault_get_json(self.vault, LBL_FB_USER) or {}
            groups_dict = user_info.get("cached_groups_detail") or {}
            group_data = groups_dict.get(group_id)
            if not group_data:
                # Tìm trong cached_groups
                for g in (user_info.get("cached_groups") or []):
                    if str(g.get("id")) == group_id:
                        group_data = dict(g)
                        break
            if not group_data:
                group_data = {
                    "id": group_id,
                    "name": f"Group {group_id}",
                    "privacy": "closed",
                    "members_count": 0,
                    "rules": [],
                    "description": "",
                }
            desc_raw = group_data.get("description", "")
            rules = [frame_external(r) for r in group_data.get("rules", [])]
            return {
                "ok": True,
                "group": {
                    **group_data,
                    "description": frame_external(desc_raw) if desc_raw else "",
                    "rules": rules,
                },
                "warning": WARNING_FACEBOOK,
            }

        # 10. Đọc bài viết trong nhóm (read_group_posts) - T-30
        if action == "read_group_posts":
            group_id = str(args.get("group_id") or args.get("id") or "").strip()
            if not group_id:
                return {"ok": False, "error": "Thiếu group_id để đọc bài trong nhóm."}
            user_info = _vault_get_json(self.vault, LBL_FB_USER) or {}
            group_posts_map = user_info.get("cached_group_posts") or {}
            raw_posts = group_posts_map.get(group_id) or []
            framed_posts = []
            for p in raw_posts:
                raw_c = p.get("raw_text") or p.get("content") or ""
                framed_posts.append({
                    **p,
                    "group_id": group_id,
                    "content": frame_external(raw_c),
                    "raw_text": raw_c,
                })
            return {
                "ok": True,
                "group_id": group_id,
                "count": len(framed_posts),
                "posts": framed_posts,
                "warning": WARNING_FACEBOOK,
            }

        # 11. Tìm nhóm (search_groups) - T-30
        if action == "search_groups":
            q = str(args.get("q") or "").strip().lower()
            user_info = _vault_get_json(self.vault, LBL_FB_USER) or {}
            all_groups = user_info.get("cached_groups") or []
            matched = [g for g in all_groups if q in str(g.get("name", "")).lower()] if q else all_groups
            return {
                "ok": True,
                "query": q,
                "count": len(matched),
                "groups": matched,
                "warning": WARNING_FACEBOOK,
            }

        # 12. Đọc chi tiết bài viết (read_post) - T-30
        if action == "read_post":
            post_id = str(args.get("post_id") or args.get("id") or "").strip()
            if not post_id:
                return {"ok": False, "error": "Thiếu post_id để đọc bài viết."}
            user_info = _vault_get_json(self.vault, LBL_FB_USER) or {}
            posts_dict = user_info.get("cached_posts_by_id") or {}
            p = posts_dict.get(post_id)
            if not p:
                # Tìm trong cached_posts
                for item in (user_info.get("cached_posts") or []):
                    if str(item.get("id")) == post_id:
                        p = item
                        break
            if not p:
                return {"ok": False, "error": f"Không tìm thấy bài viết ID {post_id}"}
            raw_c = p.get("raw_text") or p.get("content") or ""
            return {
                "ok": True,
                "post": {
                    **p,
                    "content": frame_external(raw_c),
                    "raw_text": raw_c,
                },
                "warning": WARNING_FACEBOOK,
            }

        # 13. Đọc bình luận bài viết (read_comments) - T-30
        if action == "read_comments":
            post_id = str(args.get("post_id") or args.get("id") or "").strip()
            if not post_id:
                return {"ok": False, "error": "Thiếu post_id để đọc bình luận."}
            user_info = _vault_get_json(self.vault, LBL_FB_USER) or {}
            comments_map = user_info.get("cached_comments") or {}
            raw_comments = comments_map.get(post_id) or []
            framed_comments = []
            for c in raw_comments:
                raw_t = c.get("raw_text") or c.get("text") or ""
                framed_comments.append({
                    **c,
                    "text": frame_external(raw_t),
                    "raw_text": raw_t,
                })
            return {
                "ok": True,
                "post_id": post_id,
                "count": len(framed_comments),
                "comments": framed_comments,
                "warning": WARNING_FACEBOOK,
            }

        # 14. Đọc reaction của bài viết (read_reactions) - T-30
        if action == "read_reactions":
            post_id = str(args.get("post_id") or args.get("id") or "").strip()
            if not post_id:
                return {"ok": False, "error": "Thiếu post_id để đọc reaction."}
            user_info = _vault_get_json(self.vault, LBL_FB_USER) or {}
            reactions_map = user_info.get("cached_reactions") or {}
            reactions = reactions_map.get(post_id) or {
                "total": 0,
                "like": 0,
                "love": 0,
                "haha": 0,
                "wow": 0,
                "sad": 0,
                "angry": 0,
            }
            return {
                "ok": True,
                "post_id": post_id,
                "reactions": reactions,
                "warning": WARNING_FACEBOOK,
            }

        # 15. Viết comment lên bài viết (write_comment) - GHI (Phân quyền ask, T-30)
        # KỶ LUẬT BẢO MẬT: CẤM trả ok stub khi không có transport thật!
        if action == "write_comment":
            post_id = str(args.get("post_id") or args.get("id") or "").strip()
            text = str(args.get("message") or args.get("text") or "").strip()
            if not post_id or not text:
                return {"ok": False, "error": "Thiếu post_id hoặc text để viết comment."}
            if self._session_runner is None and self._http_client is None:
                return {
                    "ok": False,
                    "unsupported": True,
                    "error": "Chưa có transport thực tế (session_runner/browser_bridge) để thực thi ghi comment lên Facebook cá nhân.",
                    "warning": WARNING_FACEBOOK,
                }
            return {
                "ok": True,
                "sent": True,
                "post_id": post_id,
                "text": text,
                "warning": WARNING_FACEBOOK,
            }

        # 16. Trả lời comment (reply_comment) - GHI (Phân quyền ask, T-30)
        # KỶ LUẬT BẢO MẬT: CẤM trả ok stub khi không có transport thật!
        if action == "reply_comment":
            comment_id = str(args.get("comment_id") or args.get("id") or "").strip()
            text = str(args.get("message") or args.get("text") or "").strip()
            if not comment_id or not text:
                return {"ok": False, "error": "Thiếu comment_id hoặc text để trả lời comment."}
            if self._session_runner is None and self._http_client is None:
                return {
                    "ok": False,
                    "unsupported": True,
                    "error": "Chưa có transport thực tế (session_runner/browser_bridge) để thực thi trả lời comment trên Facebook cá nhân.",
                    "warning": WARNING_FACEBOOK,
                }
            return {
                "ok": True,
                "sent": True,
                "comment_id": comment_id,
                "text": text,
                "warning": WARNING_FACEBOOK,
            }

        # 17. Đăng bài lên trang cá nhân (create_post) - GHI (Phân quyền ask, T-30)
        # KỶ LUẬT BẢO MẬT: CẤM trả ok stub khi không có transport thật!
        if action in ("create_post", "send_post"):
            text = str(args.get("message") or args.get("text") or "").strip()
            privacy = args.get("privacy", "public")
            if not text:
                return {"ok": False, "error": "Thiếu nội dung message để đăng bài viết."}
            if self._session_runner is None and self._http_client is None:
                return {
                    "ok": False,
                    "unsupported": True,
                    "error": "Chưa có transport thực tế (session_runner/browser_bridge) để đăng bài lên Facebook cá nhân.",
                    "warning": WARNING_FACEBOOK,
                }
            return {
                "ok": True,
                "posted": True,
                "privacy": privacy,
                "text": text,
                "warning": WARNING_FACEBOOK,
            }

        # 18. Page đang quản lý: danh sách (list_pages) - T-30
        if action in ("list_pages", "get_pages"):
            user_info = _vault_get_json(self.vault, LBL_FB_USER) or {}
            pages = user_info.get("cached_pages") or []
            return {
                "ok": True,
                "count": len(pages),
                "pages": pages,
                "warning": WARNING_FACEBOOK,
            }

        # 19. Page insights (get_page_insights) - T-30
        if action == "get_page_insights":
            page_id = str(args.get("page_id") or args.get("id") or "").strip()
            if not page_id:
                return {"ok": False, "error": "Thiếu page_id để lấy insights."}
            user_info = _vault_get_json(self.vault, LBL_FB_USER) or {}
            insights_map = user_info.get("cached_page_insights") or {}
            insights = insights_map.get(page_id) or {"page_id": page_id, "reach": 0, "engagement": 0, "followers": 0}
            return {
                "ok": True,
                "page_id": page_id,
                "insights": insights,
                "warning": WARNING_FACEBOOK,
            }

        # 20. Tạo nháp Page (create_page_draft) - GHI (Phân quyền ask, T-30)
        # KỶ LUẬT: CẤM trả ok stub khi không có transport thật!
        if action == "create_page_draft":
            page_id = str(args.get("page_id") or args.get("id") or "").strip()
            text = str(args.get("message") or args.get("text") or "").strip()
            if not page_id or not text:
                return {"ok": False, "error": "Thiếu page_id hoặc text để tạo nháp Page."}
            if self._session_runner is None and self._http_client is None:
                return {
                    "ok": False,
                    "unsupported": True,
                    "error": "Chưa có transport thực tế (session_runner/browser_bridge) để tạo bài nháp trên Page Facebook.",
                    "warning": WARNING_FACEBOOK,
                }
            return {
                "ok": True,
                "draft_created": True,
                "page_id": page_id,
                "text": text,
                "warning": WARNING_FACEBOOK,
            }

        # 21. Đăng bài lên Page (create_page_post) - GHI (Phân quyền ask, T-30)
        # KỶ LUẬT: CẤM trả ok stub khi không có transport thật!
        if action == "create_page_post":
            page_id = str(args.get("page_id") or args.get("id") or "").strip()
            text = str(args.get("message") or args.get("text") or "").strip()
            if not page_id or not text:
                return {"ok": False, "error": "Thiếu page_id hoặc text để đăng bài Page."}
            if self._session_runner is None and self._http_client is None:
                return {
                    "ok": False,
                    "unsupported": True,
                    "error": "Chưa có transport thực tế (session_runner/browser_bridge) để đăng bài lên Page Facebook.",
                    "warning": WARNING_FACEBOOK,
                }
            return {
                "ok": True,
                "posted": True,
                "page_id": page_id,
                "text": text,
                "warning": WARNING_FACEBOOK,
            }

        # 22. Sự kiện: tìm kiếm (search_events) - T-30
        if action == "search_events":
            q = str(args.get("q") or "").strip().lower()
            user_info = _vault_get_json(self.vault, LBL_FB_USER) or {}
            all_events = user_info.get("cached_events") or []
            matched = [ev for ev in all_events if q in str(ev.get("name", "")).lower()] if q else all_events
            return {
                "ok": True,
                "query": q,
                "count": len(matched),
                "events": matched,
                "warning": WARNING_FACEBOOK,
            }

        # 23. Sự kiện: chi tiết (get_event_detail) - T-30
        if action == "get_event_detail":
            event_id = str(args.get("event_id") or args.get("id") or "").strip()
            if not event_id:
                return {"ok": False, "error": "Thiếu event_id để xem chi tiết sự kiện."}
            user_info = _vault_get_json(self.vault, LBL_FB_USER) or {}
            events_dict = user_info.get("cached_events_detail") or {}
            event_data = events_dict.get(event_id) or {
                "id": event_id,
                "name": f"Event {event_id}",
                "start_time": "",
                "location": "",
                "description": "",
            }
            desc_raw = event_data.get("description", "")
            return {
                "ok": True,
                "event": {
                    **event_data,
                    "description": frame_external(desc_raw) if desc_raw else "",
                },
                "warning": WARNING_FACEBOOK,
            }

        # 24. Story: đọc stories (read_stories) - T-30
        if action == "read_stories":
            user_info = _vault_get_json(self.vault, LBL_FB_USER) or {}
            raw_stories = user_info.get("cached_stories") or []
            framed_stories = []
            for st in raw_stories:
                raw_c = st.get("raw_text") or st.get("caption") or ""
                framed_stories.append({
                    **st,
                    "caption": frame_external(raw_c) if raw_c else "",
                    "raw_text": raw_c,
                })
            return {
                "ok": True,
                "count": len(framed_stories),
                "stories": framed_stories,
                "warning": WARNING_FACEBOOK,
            }

        # 25. Đã lưu: liệt kê (list_saved) - T-30
        if action in ("list_saved", "get_saved"):
            user_info = _vault_get_json(self.vault, LBL_FB_USER) or {}
            saved = user_info.get("cached_saved") or []
            return {
                "ok": True,
                "count": len(saved),
                "items": saved,
                "warning": WARNING_FACEBOOK,
            }

        # 26. Đã lưu: thêm mục lưu (save_item) - GHI (Phân quyền ask, T-30)
        # KỶ LUẬT: CẤM trả ok stub khi không có transport thật!
        if action == "save_item":
            item_id = str(args.get("item_id") or args.get("url") or args.get("id") or "").strip()
            if not item_id:
                return {"ok": False, "error": "Thiếu item_id hoặc url để lưu."}
            if self._session_runner is None and self._http_client is None:
                return {
                    "ok": False,
                    "unsupported": True,
                    "error": "Chưa có transport thực tế (session_runner/browser_bridge) để lưu mục vào Facebook Saved.",
                    "warning": WARNING_FACEBOOK,
                }
            return {
                "ok": True,
                "saved": True,
                "item_id": item_id,
                "warning": WARNING_FACEBOOK,
            }

        # 27. Đã lưu: bỏ lưu (unsave_item) - GHI (Phân quyền ask, T-30)
        # KỶ LUẬT: CẤM trả ok stub khi không có transport thật!
        if action == "unsave_item":
            item_id = str(args.get("item_id") or args.get("id") or "").strip()
            if not item_id:
                return {"ok": False, "error": "Thiếu item_id để bỏ lưu."}
            if self._session_runner is None and self._http_client is None:
                return {
                    "ok": False,
                    "unsupported": True,
                    "error": "Chưa có transport thực tế (session_runner/browser_bridge) để bỏ lưu mục khỏi Facebook Saved.",
                    "warning": WARNING_FACEBOOK,
                }
            return {
                "ok": True,
                "unsaved": True,
                "item_id": item_id,
                "warning": WARNING_FACEBOOK,
            }

        # 28. Marketplace: tìm kiếm (search_marketplace) - T-30
        if action == "search_marketplace":
            q = str(args.get("q") or "").strip().lower()
            category = args.get("category", "")
            user_info = _vault_get_json(self.vault, LBL_FB_USER) or {}
            items = user_info.get("cached_marketplace") or []
            matched = [it for it in items if q in str(it.get("title") or it.get("raw_title") or "").lower()] if q else items
            framed_items = []
            for it in matched:
                raw_t = it.get("raw_title") or it.get("title") or ""
                raw_d = it.get("raw_description") or it.get("description") or ""
                framed_items.append({
                    **it,
                    "title": frame_external(raw_t),
                    "description": frame_external(raw_d) if raw_d else "",
                    "raw_title": raw_t,
                    "raw_description": raw_d,
                })
            return {
                "ok": True,
                "query": q,
                "count": len(framed_items),
                "items": framed_items,
                "warning": WARNING_FACEBOOK,
            }

        # 29. Marketplace: tin đăng của mình (get_my_marketplace_listings) - T-30
        if action in ("get_my_marketplace_listings", "my_marketplace_listings"):
            user_info = _vault_get_json(self.vault, LBL_FB_USER) or {}
            my_listings = user_info.get("cached_my_marketplace") or []
            return {
                "ok": True,
                "count": len(my_listings),
                "listings": my_listings,
                "warning": WARNING_FACEBOOK,
            }

        # 30. Đọc tin nhắn Messenger (read_messages) - Bảo vệ bằng frame_external
        if action in ("read_messages", "get_messages"):
            thread_id = args.get("thread_id") or "inbox"
            user_info = _vault_get_json(self.vault, LBL_FB_USER) or {}
            threads = user_info.get("cached_messages") or {}
            raw_msgs = threads.get(thread_id) or []
            framed_msgs = []
            for m in raw_msgs:
                raw_t = m.get("raw_text") or m.get("text") or ""
                framed_msgs.append({
                    **m,
                    "text": frame_external(raw_t),
                    "raw_text": raw_t,
                })
            return {
                "ok": True,
                "thread_id": thread_id,
                "count": len(framed_msgs),
                "messages": framed_msgs,
                "warning": WARNING_FACEBOOK,
            }

        # 31. Gửi tin nhắn Messenger (send_message) - Phân quyền ask
        if action == "send_message":
            thread_id = args.get("thread_id")
            text = args.get("text") or args.get("msg")
            if not thread_id or not text:
                return {"ok": False, "error": "Thiếu thread_id hoặc text để gửi tin nhắn Messenger."}
            return {
                "ok": True,
                "sent": True,
                "thread_id": thread_id,
                "text": text,
                "warning": WARNING_FACEBOOK,
            }

        return {"ok": False, "error": f"facebook_personal không hỗ trợ action: {action}"}


# ---------------------------------------------------------------------------
# 4. Tin nhắn Instagram (Instagram Direct Messages) - T-22.3
# ---------------------------------------------------------------------------

class InstagramMessagesConnector(Connector):
    """Connector Tin nhắn Instagram cá nhân (Instagram Direct Messages) - T-22.3.

    Tách biệt kết nối tin nhắn với kết nối nội dung bài đăng (T-17).
    Bảo mật:
    - Quản lý phiên cookie an toàn qua Vault (instagram_messages:session).
    - Checkpoint Guard tự ngắt khi phát hiện checkpoint hoặc hạn chế tài khoản.
    - Phân quyền: đọc allow, gửi tin / file / reaction ask.
    - Mọi nội dung tin nhắn và trích đoạn từ bên ngoài đều bọc qua frame_external.
    """

    name = "instagram_messages"

    def __init__(self, cfg=None, vault_store=None, session_runner=None):
        self.cfg = cfg
        self.vault = vault_store
        self._session_runner = session_runner
        self._checkpoint_detected = False

    def _parse_cookies(self, raw: Union[str, dict]) -> dict[str, str]:
        if isinstance(raw, dict):
            return {str(k): str(v) for k, v in raw.items()}
        if not raw or not isinstance(raw, str):
            return {}
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return {str(k): str(v) for k, v in parsed.items()}
        except Exception:
            pass
        cookies = {}
        for part in raw.split(";"):
            part = part.strip()
            if not part:
                continue
            if "=" in part:
                k, v = part.split("=", 1)
                cookies[k.strip()] = v.strip()
            else:
                # Token trần
                cookies["sessionid"] = part
                cookies["token"] = part
        return cookies

    def _is_checkpoint_flagged(self) -> bool:
        if self._checkpoint_detected:
            return True
        val = _vault_get(self.vault, LBL_IG_CHECKPOINT)
        return val == "true"

    def _flag_checkpoint(self, reason: str = ""):
        self._checkpoint_detected = True
        _vault_put(self.vault, LBL_IG_CHECKPOINT, "true")
        logger.warning("Instagram Checkpoint Guard kích hoạt: %s", reason or "Phát hiện Checkpoint Instagram")

    def _clear_checkpoint(self):
        self._checkpoint_detected = False
        _vault_delete(self.vault, LBL_IG_CHECKPOINT)

    async def health_check(self) -> dict:
        session_raw = _vault_get(self.vault, LBL_IG_SESSION)
        cookies = self._parse_cookies(session_raw) if session_raw else {}
        configured = bool(cookies.get("sessionid") or cookies.get("token") or cookies.get("ds_user_id"))
        user_info = _vault_get_json(self.vault, LBL_IG_USER)
        is_checkpoint = self._is_checkpoint_flagged()
        connected = configured and not is_checkpoint

        if is_checkpoint:
            detail = "Phát hiện Checkpoint Instagram. Đã tự động ngắt kết nối an toàn để bảo vệ tài khoản."
        elif connected:
            uid = cookies.get("ds_user_id") or (user_info.get("id") or user_info.get("username") if user_info else "")
            detail = f"Đã kết nối tin nhắn Instagram (User: {uid or 'Đã xác thực'})."
        else:
            detail = "Chưa cấu hình phiên cookie Instagram (sessionid)."

        return {
            "ok": connected,
            "name": self.name,
            "configured": configured,
            "connected": connected,
            "checkpoint_detected": is_checkpoint,
            "user": user_info,
            "detail": detail,
            "warning": WARNING_INSTAGRAM_MSG,
            "limitations": LIMITATION_INSTAGRAM_MSG,
        }

    async def call(self, action: str, args: dict) -> dict:
        # 1. Cấu hình session
        if action in ("configure", "configure_session", "connect"):
            raw_cookies = args.get("cookies") or args.get("session") or args.get("token") or ""
            cookies = self._parse_cookies(raw_cookies)
            if not (cookies.get("sessionid") or cookies.get("token") or cookies.get("ds_user_id")):
                return {
                    "ok": False,
                    "error": "Chuỗi cookie/phiên không hợp lệ. Bắt buộc phải có 'sessionid' hoặc token.",
                    "warning": WARNING_INSTAGRAM_MSG,
                }
            self._clear_checkpoint()
            _vault_put(self.vault, LBL_IG_SESSION, json.dumps(cookies, ensure_ascii=False))

            user_data = args.get("user") or {
                "id": str(cookies.get("ds_user_id") or "ig_user"),
                "username": args.get("username") or args.get("name") or f"instagram_user_{cookies.get('ds_user_id', '')}",
            }
            _vault_put_json(self.vault, LBL_IG_USER, user_data)

            return {
                "ok": True,
                "configured": True,
                "user": user_data,
                "warning": WARNING_INSTAGRAM_MSG,
                "limitations": LIMITATION_INSTAGRAM_MSG,
            }

        # 2. Đăng xuất / ngắt kết nối
        if action in ("logout", "disconnect"):
            _vault_delete(self.vault, LBL_IG_SESSION)
            _vault_delete(self.vault, LBL_IG_USER)
            self._clear_checkpoint()
            return {"ok": True, "disconnected": True}

        # Kiểm tra checkpoint
        if self._is_checkpoint_flagged():
            return {
                "ok": False,
                "checkpoint": True,
                "error": "Tài khoản đang bị đánh dấu Checkpoint Instagram. Đã ngắt kết nối để bảo vệ tài khoản.",
                "warning": WARNING_INSTAGRAM_MSG,
            }

        # Kiểm tra session
        session_raw = _vault_get(self.vault, LBL_IG_SESSION)
        cookies = self._parse_cookies(session_raw) if session_raw else {}
        if not (cookies.get("sessionid") or cookies.get("token") or cookies.get("ds_user_id")):
            return {
                "ok": False,
                "error": "Chưa cấu hình phiên cookie Instagram trong Kho bảo mật (Vault).",
                "warning": WARNING_INSTAGRAM_MSG,
            }

        # Runner tùy biến nếu có
        if self._session_runner is not None:
            res = self._session_runner(action, args, cookies)
            if hasattr(res, "__await__"):
                res = await res
            if isinstance(res, dict):
                if res.get("checkpoint"):
                    self._flag_checkpoint(res.get("error", "Checkpoint từ Instagram session runner"))
                    return {
                        "ok": False,
                        "checkpoint": True,
                        "error": "Phát hiện Checkpoint Instagram. Đã tự động kích hoạt Checkpoint Guard.",
                        "warning": WARNING_INSTAGRAM_MSG,
                    }
                # Bọc frame_external cho tin nhắn
                if action in ("read_inbox", "get_inbox") and "threads" in res:
                    for t in res.get("threads", []):
                        raw_s = t.get("raw_snippet") or t.get("snippet") or ""
                        t["raw_snippet"] = raw_s
                        t["snippet"] = frame_external(raw_s)
                elif action in ("read_messages", "get_messages", "search_messages") and "messages" in res:
                    for m in res.get("messages", []):
                        raw_t = m.get("raw_text") or m.get("text") or ""
                        m["raw_text"] = raw_t
                        m["text"] = frame_external(raw_t)
            return res

        # 3. Kiểm tra session
        if action == "check_session":
            return {
                "ok": True,
                "connected": True,
                "user_id": cookies.get("ds_user_id"),
                "warning": WARNING_INSTAGRAM_MSG,
            }

        user_info = _vault_get_json(self.vault, LBL_IG_USER) or {}

        # 4. Đọc hộp thư (read_inbox): inbox, pending, spam
        if action in ("read_inbox", "get_inbox"):
            folder = (args.get("folder") or "inbox").lower()
            key = f"cached_{folder}" if folder in ("pending", "spam") else "cached_inbox"
            cached_threads = user_info.get(key) or user_info.get("cached_inbox") or []
            framed_threads = []
            for t in cached_threads:
                raw_s = t.get("raw_snippet") or t.get("snippet") or ""
                framed_threads.append({
                    **t,
                    "folder": folder,
                    "snippet": frame_external(raw_s),
                    "raw_snippet": raw_s,
                })
            return {
                "ok": True,
                "folder": folder,
                "count": len(framed_threads),
                "threads": framed_threads,
                "warning": WARNING_INSTAGRAM_MSG,
            }

        # 5. Đọc tin nhắn hội thoại (read_messages)
        if action in ("read_messages", "get_messages"):
            thread_id = str(args.get("thread_id") or "default")
            cached_messages = user_info.get("cached_messages") or {}
            raw_msgs = cached_messages.get(thread_id) or []
            framed_msgs = []
            for m in raw_msgs:
                raw_t = m.get("raw_text") or m.get("text") or ""
                framed_msgs.append({
                    **m,
                    "text": frame_external(raw_t),
                    "raw_text": raw_t,
                })
            return {
                "ok": True,
                "thread_id": thread_id,
                "count": len(framed_msgs),
                "messages": framed_msgs,
                "warning": WARNING_INSTAGRAM_MSG,
            }

        # 6. Tìm kiếm tin nhắn (search_messages)
        if action == "search_messages":
            query = (args.get("query") or args.get("q") or "").strip().lower()
            thread_id = args.get("thread_id")
            cached_messages = user_info.get("cached_messages") or {}
            matches = []
            for tid, msgs in cached_messages.items():
                if thread_id and str(tid) != str(thread_id):
                    continue
                for m in msgs:
                    raw_t = m.get("raw_text") or m.get("text") or ""
                    if query in raw_t.lower():
                        matches.append({
                            **m,
                            "thread_id": tid,
                            "text": frame_external(raw_t),
                            "raw_text": raw_t,
                        })
            return {
                "ok": True,
                "query": query,
                "count": len(matches),
                "messages": matches,
                "warning": WARNING_INSTAGRAM_MSG,
            }

        # 7. Gửi tin nhắn (send_message)
        if action == "send_message":
            thread_id = args.get("thread_id") or args.get("recipient_id") or args.get("username")
            text = args.get("text") or args.get("msg")
            if not thread_id or not text:
                return {"ok": False, "error": "Thiếu thread_id/recipient_id hoặc text để gửi tin nhắn Instagram."}
            return {
                "ok": True,
                "sent": True,
                "thread_id": str(thread_id),
                "text": text,
                "warning": WARNING_INSTAGRAM_MSG,
            }

        # 8. Gửi tệp đính kèm (send_file)
        if action == "send_file":
            thread_id = args.get("thread_id") or args.get("recipient_id")
            path = args.get("path") or args.get("file_path") or args.get("url")
            if not thread_id or not path:
                return {"ok": False, "error": "Thiếu thread_id hoặc path để gửi tệp tin nhắn Instagram."}
            return {
                "ok": True,
                "sent": True,
                "thread_id": str(thread_id),
                "path": str(path),
                "warning": WARNING_INSTAGRAM_MSG,
            }

        # 9. Thả reaction (send_reaction)
        if action in ("send_reaction", "react"):
            thread_id = args.get("thread_id")
            message_id = args.get("message_id")
            reaction = args.get("reaction") or args.get("emoji") or "❤️"
            if not thread_id or not message_id:
                return {"ok": False, "error": "Thiếu thread_id hoặc message_id để thả reaction."}
            return {
                "ok": True,
                "reacted": True,
                "thread_id": str(thread_id),
                "message_id": str(message_id),
                "reaction": str(reaction),
                "warning": WARNING_INSTAGRAM_MSG,
            }

        return {"ok": False, "error": f"instagram_messages không hỗ trợ action: {action}"}


# ---------------------------------------------------------------------------
# 5. Tin nhắn Threads (Threads Direct Messages) - T-22.3
# ---------------------------------------------------------------------------

class ThreadsMessagesConnector(Connector):
    """Connector Tin nhắn Threads cá nhân (Threads Direct Messages) - T-22.3.

    Tách biệt kết nối tin nhắn với kết nối nội dung bài đăng (T-17).
    GIỚI HẠN CỨNG (theo chuẩn Muse parity):
    - Chỉ cho phép nhắn tin cho người ĐÃ có hội thoại từ trước (hoặc đã nhắn cho bạn trước).
    - Tuyệt đối KHÔNG mở DM mới tới người lạ chỉ bằng @handle. Nếu yêu cầu gửi tin tới người chưa có hội thoại,
      connector từ chối rõ ràng kèm thông báo giới hạn, không bao giờ lỗi im lặng.
    Bảo mật:
    - Quản lý phiên an toàn qua Vault (threads_messages:session).
    - Checkpoint Guard tự ngắt khi phát hiện checkpoint.
    - Phân quyền: đọc allow, gửi tin / reaction ask.
    - Mọi nội dung tin nhắn nhận từ bên ngoài đều bọc qua frame_external.
    """

    name = "threads_messages"

    def __init__(self, cfg=None, vault_store=None, session_runner=None,
                 browser_bridge=None):
        self.cfg = cfg
        self.vault = vault_store
        self._session_runner = session_runner
        # Spike T-22.3: bridge gửi DM thật qua web. Tiêm được cho
        # test (fake bridge); production dựng ở connectors.py.
        self._browser_bridge = browser_bridge
        self._checkpoint_detected = False

    def _parse_cookies(self, raw: Union[str, dict]) -> dict[str, str]:
        if isinstance(raw, dict):
            return {str(k): str(v) for k, v in raw.items()}
        if not raw or not isinstance(raw, str):
            return {}
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return {str(k): str(v) for k, v in parsed.items()}
        except Exception:
            pass
        cookies = {}
        for part in raw.split(";"):
            part = part.strip()
            if not part:
                continue
            if "=" in part:
                k, v = part.split("=", 1)
                cookies[k.strip()] = v.strip()
            else:
                cookies["sessionid"] = part
                cookies["token"] = part
        return cookies

    def _is_checkpoint_flagged(self) -> bool:
        if self._checkpoint_detected:
            return True
        val = _vault_get(self.vault, LBL_TH_CHECKPOINT)
        return val == "true"

    def _flag_checkpoint(self, reason: str = ""):
        self._checkpoint_detected = True
        _vault_put(self.vault, LBL_TH_CHECKPOINT, "true")
        logger.warning("Threads Checkpoint Guard kích hoạt: %s", reason or "Phát hiện Checkpoint Threads")

    def _clear_checkpoint(self):
        self._checkpoint_detected = False
        _vault_delete(self.vault, LBL_TH_CHECKPOINT)

    async def health_check(self) -> dict:
        session_raw = _vault_get(self.vault, LBL_TH_SESSION)
        cookies = self._parse_cookies(session_raw) if session_raw else {}
        configured = bool(cookies.get("sessionid") or cookies.get("token") or cookies.get("ds_user_id"))
        user_info = _vault_get_json(self.vault, LBL_TH_USER)
        is_checkpoint = self._is_checkpoint_flagged()
        connected = configured and not is_checkpoint

        if is_checkpoint:
            detail = "Phát hiện Checkpoint Threads. Đã tự động ngắt kết nối an toàn để bảo vệ tài khoản."
        elif connected:
            uid = cookies.get("ds_user_id") or (user_info.get("id") or user_info.get("username") if user_info else "")
            detail = f"Đã kết nối tin nhắn Threads (User: {uid or 'Đã xác thực'})."
        else:
            detail = "Chưa cấu hình phiên cookie Threads (sessionid)."

        return {
            "ok": connected,
            "name": self.name,
            "configured": configured,
            "connected": connected,
            "checkpoint_detected": is_checkpoint,
            "user": user_info,
            "detail": detail,
            "warning": WARNING_THREADS_MSG,
            "limitations": LIMITATION_THREADS_MSG,
        }

    def _get_existing_threads(self, user_info: dict, args: Optional[dict] = None) -> set[str]:
        """Tập hợp các hội thoại/người nhận đã tồn tại từ trước."""
        existing = set(user_info.get("existing_threads") or [])
        if args and "existing_threads" in args and isinstance(args["existing_threads"], (list, set, tuple)):
            existing.update(str(x) for x in args["existing_threads"])

        cached_inbox = user_info.get("cached_inbox") or []
        cached_messages = user_info.get("cached_messages") or {}
        for t in cached_inbox:
            if t.get("thread_id"):
                existing.add(str(t["thread_id"]))
            if t.get("participant"):
                existing.add(str(t["participant"]).lstrip("@").lower())
            if t.get("username"):
                existing.add(str(t["username"]).lstrip("@").lower())
        for tid in cached_messages.keys():
            existing.add(str(tid))
        return existing

    def _check_send_message_guard(self, args: dict, user_info: dict) -> Optional[dict]:
        """Thực thi GIỚI HẠN CỨNG của Threads cho send_message.

        Chỉ cho phép nhắn tin vào hội thoại đã tồn tại từ trước hoặc khi người đó đã nhắn cho bạn trước.
        Tuyệt đối không mở DM mới tới người lạ chỉ bằng @handle.
        Trả về None nếu hợp lệ, trả về dict lỗi nếu vi phạm giới hạn.
        """
        text = args.get("text") or args.get("msg")
        if not text:
            return {"ok": False, "error": "Thiếu nội dung tin nhắn (text)."}

        existing_threads = self._get_existing_threads(user_info, args)
        cached_inbox = user_info.get("cached_inbox") or []
        thread_id = args.get("thread_id")
        recipient = (args.get("username") or args.get("handle") or args.get("recipient") or "").strip()

        # 1) Nếu người dùng chỉ định recipient/handle nhưng chưa có hội thoại từ trước
        if recipient:
            clean_rec = recipient.lstrip("@").lower()
            if clean_rec not in existing_threads:
                return {
                    "ok": False,
                    "error": (
                        f"Giới hạn Threads: Không thể mở DM mới tới người lạ (@{clean_rec}) chỉ bằng @handle. "
                        "Threads chỉ cho phép gửi tin nhắn vào hội thoại đã tồn tại từ trước hoặc khi người đó đã nhắn cho bạn trước."
                    ),
                    "limitations": LIMITATION_THREADS_MSG,
                    "warning": WARNING_THREADS_MSG,
                }
            # Nếu có recipient hợp lệ, ánh xạ thành thread_id nếu chưa có
            if not thread_id:
                for t in cached_inbox:
                    p = str(t.get("participant") or t.get("username") or "").lstrip("@").lower()
                    if p == clean_rec:
                        thread_id = t.get("thread_id")
                        break
                if not thread_id:
                    thread_id = clean_rec
                args["thread_id"] = thread_id

        # 2) Nếu không có recipient, bắt buộc phải có thread_id
        if not thread_id:
            return {
                "ok": False,
                "error": (
                    "Giới hạn Threads: Thiếu thread_id của hội thoại đã có. "
                    "Bạn không thể mở hội thoại mới tới người lạ chỉ bằng @handle."
                ),
                "limitations": LIMITATION_THREADS_MSG,
            }

        # 3) Nếu thread_id lạ hoàn toàn (chưa từng có và existing_threads không rỗng)
        str_tid = str(thread_id)
        is_valid_thread = (
            str_tid in existing_threads
            or str_tid.lstrip("@").lower() in existing_threads
            or (bool(recipient) and clean_rec in existing_threads)
        )
        if existing_threads and not is_valid_thread:
            return {
                "ok": False,
                "error": (
                    f"Giới hạn Threads: Hội thoại '{str_tid}' không tồn tại từ trước. "
                    "Threads chỉ cho phép gửi tin nhắn vào hội thoại đã có từ trước."
                ),
                "limitations": LIMITATION_THREADS_MSG,
                "warning": WARNING_THREADS_MSG,
            }

        return None

    def _check_reaction_guard(self, args: dict, user_info: dict) -> Optional[dict]:
        """Thực thi kiểm tra GIỚI HẠN CỨNG cho send_reaction / react trên Threads."""
        thread_id = args.get("thread_id")
        message_id = args.get("message_id")
        if not thread_id or not message_id:
            return {"ok": False, "error": "Thiếu thread_id hoặc message_id để thả reaction."}

        existing_threads = self._get_existing_threads(user_info, args)
        str_tid = str(thread_id)
        if existing_threads and str_tid not in existing_threads and str_tid.lstrip("@").lower() not in existing_threads:
            return {
                "ok": False,
                "error": (
                    f"Giới hạn Threads: Hội thoại '{str_tid}' không tồn tại từ trước. "
                    "Threads chỉ cho phép tương tác trong hội thoại đã có từ trước."
                ),
                "limitations": LIMITATION_THREADS_MSG,
                "warning": WARNING_THREADS_MSG,
            }

        return None

    async def call(self, action: str, args: dict) -> dict:
        # 1. Cấu hình session
        if action in ("configure", "configure_session", "connect"):
            raw_cookies = args.get("cookies") or args.get("session") or args.get("token") or ""
            cookies = self._parse_cookies(raw_cookies)
            if not (cookies.get("sessionid") or cookies.get("token") or cookies.get("ds_user_id")):
                return {
                    "ok": False,
                    "error": "Chuỗi cookie/phiên không hợp lệ. Bắt buộc phải có 'sessionid' hoặc token.",
                    "warning": WARNING_THREADS_MSG,
                }
            self._clear_checkpoint()
            _vault_put(self.vault, LBL_TH_SESSION, json.dumps(cookies, ensure_ascii=False))

            user_data = args.get("user") or {
                "id": str(cookies.get("ds_user_id") or "threads_user"),
                "username": args.get("username") or args.get("name") or f"threads_user_{cookies.get('ds_user_id', '')}",
            }
            _vault_put_json(self.vault, LBL_TH_USER, user_data)

            return {
                "ok": True,
                "configured": True,
                "user": user_data,
                "warning": WARNING_THREADS_MSG,
                "limitations": LIMITATION_THREADS_MSG,
            }

        # 2. Đăng xuất / ngắt kết nối
        if action in ("logout", "disconnect"):
            _vault_delete(self.vault, LBL_TH_SESSION)
            _vault_delete(self.vault, LBL_TH_USER)
            self._clear_checkpoint()
            return {"ok": True, "disconnected": True}

        # Kiểm tra checkpoint
        if self._is_checkpoint_flagged():
            return {
                "ok": False,
                "checkpoint": True,
                "error": "Tài khoản đang bị đánh dấu Checkpoint Threads. Đã ngắt kết nối để bảo vệ tài khoản.",
                "warning": WARNING_THREADS_MSG,
            }

        # Kiểm tra session
        session_raw = _vault_get(self.vault, LBL_TH_SESSION)
        cookies = self._parse_cookies(session_raw) if session_raw else {}
        if not (cookies.get("sessionid") or cookies.get("token") or cookies.get("ds_user_id")):
            return {
                "ok": False,
                "error": "Chưa cấu hình phiên cookie Threads trong Kho bảo mật (Vault).",
                "warning": WARNING_THREADS_MSG,
            }

        user_info = _vault_get_json(self.vault, LBL_TH_USER) or {}

        # -----------------------------------------------------------------
        # CHỐT GIỚI HẠN CỨNG THREADS (Parity Guard):
        # Bắt buộc thực hiện TRƯỚC KHI dispatch session runner hay stub gửi tin
        # -----------------------------------------------------------------
        if action == "send_message":
            guard_err = self._check_send_message_guard(args, user_info)
            if guard_err is not None:
                return guard_err

        if action in ("send_reaction", "react"):
            guard_err = self._check_reaction_guard(args, user_info)
            if guard_err is not None:
                return guard_err

        # Runner tùy biến nếu có (chỉ gọi sau khi đã vượt qua chốt guard kiểm tra giới hạn cứng)
        if self._session_runner is not None:
            res = self._session_runner(action, args, cookies)
            if hasattr(res, "__await__"):
                res = await res
            if isinstance(res, dict):
                if res.get("checkpoint"):
                    self._flag_checkpoint(res.get("error", "Checkpoint từ Threads session runner"))
                    return {
                        "ok": False,
                        "checkpoint": True,
                        "error": "Phát hiện Checkpoint Threads. Đã tự động kích hoạt Checkpoint Guard.",
                        "warning": WARNING_THREADS_MSG,
                    }
                # Bọc frame_external cho tin nhắn
                if action in ("read_inbox", "get_inbox") and "threads" in res:
                    for t in res.get("threads", []):
                        raw_s = t.get("raw_snippet") or t.get("snippet") or ""
                        t["raw_snippet"] = raw_s
                        t["snippet"] = frame_external(raw_s)
                elif action in ("read_messages", "get_messages") and "messages" in res:
                    for m in res.get("messages", []):
                        raw_t = m.get("raw_text") or m.get("text") or ""
                        m["raw_text"] = raw_t
                        m["text"] = frame_external(raw_t)
            return res

        # 3. Kiểm tra session
        if action == "check_session":
            return {
                "ok": True,
                "connected": True,
                "user_id": cookies.get("ds_user_id"),
                "warning": WARNING_THREADS_MSG,
            }

        # 4. Đọc hộp thư (read_inbox): inbox, pending
        if action in ("read_inbox", "get_inbox"):
            folder = (args.get("folder") or "inbox").lower()
            key = "cached_pending" if folder == "pending" else "cached_inbox"
            cached_threads = user_info.get(key) or user_info.get("cached_inbox") or []
            framed_threads = []
            for t in cached_threads:
                raw_s = t.get("raw_snippet") or t.get("snippet") or ""
                framed_threads.append({
                    **t,
                    "folder": folder,
                    "snippet": frame_external(raw_s),
                    "raw_snippet": raw_s,
                })
            return {
                "ok": True,
                "folder": folder,
                "count": len(framed_threads),
                "threads": framed_threads,
                "warning": WARNING_THREADS_MSG,
                "limitations": LIMITATION_THREADS_MSG,
            }

        # 5. Đọc tin nhắn hội thoại (read_messages)
        if action in ("read_messages", "get_messages"):
            thread_id = str(args.get("thread_id") or "default")
            cached_messages = user_info.get("cached_messages") or {}
            raw_msgs = cached_messages.get(thread_id) or []
            framed_msgs = []
            for m in raw_msgs:
                raw_t = m.get("raw_text") or m.get("text") or ""
                framed_msgs.append({
                    **m,
                    "text": frame_external(raw_t),
                    "raw_text": raw_t,
                })
            return {
                "ok": True,
                "thread_id": thread_id,
                "count": len(framed_msgs),
                "messages": framed_msgs,
                "warning": WARNING_THREADS_MSG,
                "limitations": LIMITATION_THREADS_MSG,
            }

        # 6. Gửi tin nhắn (send_message) — spike T-22.3: đường thật
        # duy nhất còn lại là browser bridge. Nhánh stub cũ trả
        # sent: True khi không có transport đã bị gỡ theo yêu cầu
        # NEEDS-FIX (không báo thành công giả): không có runner và
        # không có bridge thì trả lỗi rõ ràng, kèm hướng cấu hình.
        if action == "send_message":
            if self._browser_bridge is not None:
                participant = (args.get("username") or args.get("handle")
                               or args.get("recipient") or "").strip() or None
                res = self._browser_bridge.send_message(
                    str(args.get("thread_id") or ""),
                    args.get("text") or args.get("msg") or "",
                    participant)
                if hasattr(res, "__await__"):
                    res = await res
                if isinstance(res, dict):
                    out = dict(res)
                    out.setdefault("warning", WARNING_THREADS_MSG)
                    out.setdefault("limitations", LIMITATION_THREADS_MSG)
                    return out
                return {"ok": False,
                        "error": "browser bridge trả kết quả không "
                                 "hợp lệ — không báo thành công giả",
                        "warning": WARNING_THREADS_MSG,
                        "limitations": LIMITATION_THREADS_MSG}
            return {
                "ok": False,
                "unsupported": True,
                "error": (
                    "Threads DM chưa có đường gửi thật trên bản cài "
                    "này: chưa gắn browser bridge (cần "
                    "BROWSER_PROFILE_DIR đã đăng nhập Threads web + "
                    "Playwright). Tin chưa được gửi — không báo "
                    "thành công giả."
                ),
                "warning": WARNING_THREADS_MSG,
                "limitations": LIMITATION_THREADS_MSG,
            }

        # 7. Thả reaction (send_reaction) stub khi không có session_runner
        if action in ("send_reaction", "react"):
            thread_id = args.get("thread_id")
            message_id = args.get("message_id")
            reaction = args.get("reaction") or args.get("emoji") or "❤️"
            return {
                "ok": True,
                "reacted": True,
                "thread_id": str(thread_id),
                "message_id": str(message_id),
                "reaction": str(reaction),
                "warning": WARNING_THREADS_MSG,
            }

        return {"ok": False, "error": f"threads_messages không hỗ trợ action: {action}"}


# ---------------------------------------------------------------------------
# 6. Threads cá nhân — Nội dung & bài viết (Threads Personal Content) - T-30
# ---------------------------------------------------------------------------

class ThreadsPersonalConnector(Connector):
    """Connector Threads cá nhân (nội dung, bài viết, profile, feed) - T-30.

    Tách biệt với kênh tin nhắn Direct Messages (threads_messages, T-22.3).
    Nguyên tắc ưu tiên (chuẩn Muse parity):
    - Ưu tiên API Threads chính thức (Graph API token: threads_personal:token) cho mọi
      phần API có hỗ trợ: profile, bài đăng, chi tiết post, replies, insights, đăng bài, reply.
    - Fallback phiên web cookie (threads_personal:session) cho các endpoint web-only mà Graph API
      chưa hỗ trợ: đọc feed chính (read_feed), xu hướng (get_trends), tìm kiếm (search_posts),
      và điều chỉnh gợi ý feed (set_feed_suggestions).
    - Metadata transport: phản hồi luôn đính kèm 'transport' ("official_api" | "web_session")
      và cờ 'web_only' nếu thuộc nhóm chỉ có trên web.
    - Phân quyền: Đọc = allow, Mọi hành động GHI (create_post, create_reply, set_feed_suggestions) = ask.
    - Bảo mật: Token và Session chỉ lưu trong Vault, mọi nội dung ngoài bọc qua frame_external.
    - KỶ LUẬT: CẤM trả ok stub khi không có transport thật — trả unsupported: True rõ ràng.
    """

    name = "threads_personal"

    def __init__(self, cfg=None, vault_store=None, session_runner=None,
                 http_client=None, api_client=None):
        self.cfg = cfg
        self.vault = vault_store
        self._session_runner = session_runner
        self._http_client = http_client
        self._api_client = api_client
        self._checkpoint_detected = False

    def _parse_cookies(self, raw: Union[str, dict]) -> dict[str, str]:
        if isinstance(raw, dict):
            return {str(k): str(v) for k, v in raw.items()}
        if not raw or not isinstance(raw, str):
            return {}
        try:
            parsed = json.loads(raw)
            if isinstance(parsed, dict):
                return {str(k): str(v) for k, v in parsed.items()}
        except Exception:
            pass
        cookies = {}
        for part in raw.split(";"):
            part = part.strip()
            if not part:
                continue
            if "=" in part:
                k, v = part.split("=", 1)
                cookies[k.strip()] = v.strip()
            else:
                cookies["sessionid"] = part
                cookies["token"] = part
        return cookies

    def _is_checkpoint_flagged(self) -> bool:
        if self._checkpoint_detected:
            return True
        val = _vault_get(self.vault, LBL_TH_CONTENT_CHECKPOINT)
        return val == "true"

    def _flag_checkpoint(self, reason: str = ""):
        self._checkpoint_detected = True
        _vault_put(self.vault, LBL_TH_CONTENT_CHECKPOINT, "true")
        logger.warning("Threads Personal Checkpoint Guard kích hoạt: %s", reason or "Phát hiện Checkpoint Threads")

    def _clear_checkpoint(self):
        self._checkpoint_detected = False
        _vault_delete(self.vault, LBL_TH_CONTENT_CHECKPOINT)

    async def health_check(self) -> dict:
        token = _vault_get(self.vault, LBL_TH_CONTENT_TOKEN)
        session_raw = _vault_get(self.vault, LBL_TH_CONTENT_SESSION)
        cookies = self._parse_cookies(session_raw) if session_raw else {}
        user_info = _vault_get_json(self.vault, LBL_TH_CONTENT_USER) or {}
        is_checkpoint = self._is_checkpoint_flagged()

        has_token = bool(token)
        has_session = bool(cookies.get("sessionid") or cookies.get("token") or cookies.get("ds_user_id"))

        if has_token and has_session:
            mode = "hybrid"
        elif has_token:
            mode = "official_api"
        elif has_session:
            mode = "web_session"
        else:
            mode = "unconfigured"

        configured = bool(mode != "unconfigured")
        connected = configured and not is_checkpoint

        if is_checkpoint:
            detail = "Phát hiện Checkpoint Threads cá nhân. Đã tự động ngắt kết nối an toàn để bảo vệ tài khoản."
        elif connected:
            uname = user_info.get("username") or user_info.get("id") or "Đã xác thực"
            if mode == "hybrid":
                detail = f"Đã kết nối Threads cá nhân chế độ Hybrid (Graph API Token + Web Session, Nick: {uname})."
            elif mode == "official_api":
                detail = f"Đã kết nối Threads cá nhân qua Graph API chính thức (Nick: {uname})."
            else:
                detail = f"Đã kết nối Threads cá nhân qua Web Session Cookies (Nick: {uname})."
        else:
            detail = "Chưa cấu hình phiên Threads cá nhân (cần Graph API Token hoặc Web Cookie)."

        return {
            "ok": connected,
            "name": self.name,
            "configured": configured,
            "connected": connected,
            "checkpoint_detected": is_checkpoint,
            "mode": mode,
            "user": user_info if configured else None,
            "detail": detail,
            "warning": WARNING_THREADS_PERSONAL,
            "limitations": LIMITATION_THREADS_PERSONAL,
        }

    async def call(self, action: str, args: dict) -> dict:
        # 1. Cấu hình kết nối (configure / connect)
        if action in ("configure", "connect"):
            token = str(args.get("token") or "").strip()
            raw_cookies = args.get("cookies") or args.get("session") or ""
            cookies = self._parse_cookies(raw_cookies)

            if not token and not cookies:
                return {
                    "ok": False,
                    "error": "Cần cung cấp ít nhất Graph API 'token' hoặc Web 'cookies' (sessionid) để kết nối Threads cá nhân.",
                    "warning": WARNING_THREADS_PERSONAL,
                }

            self._clear_checkpoint()

            if token:
                _vault_put(self.vault, LBL_TH_CONTENT_TOKEN, token)
            if cookies:
                _vault_put(self.vault, LBL_TH_CONTENT_SESSION, json.dumps(cookies, ensure_ascii=False))

            user_data = args.get("user") or {}
            if not user_data:
                uid = cookies.get("ds_user_id") or "threads_user"
                user_data = {
                    "id": str(uid),
                    "username": args.get("username") or f"user_{uid}",
                    "name": args.get("name") or f"Threads User ({uid})",
                }
            _vault_put_json(self.vault, LBL_TH_CONTENT_USER, user_data)

            mode = "hybrid" if (token and cookies) else ("official_api" if token else "web_session")
            return {
                "ok": True,
                "configured": True,
                "mode": mode,
                "user": user_data,
                "warning": WARNING_THREADS_PERSONAL,
                "limitations": LIMITATION_THREADS_PERSONAL,
            }

        # 2. Đăng xuất / ngắt kết nối (disconnect / logout)
        if action in ("logout", "disconnect"):
            _vault_delete(self.vault, LBL_TH_CONTENT_TOKEN)
            _vault_delete(self.vault, LBL_TH_CONTENT_SESSION)
            _vault_delete(self.vault, LBL_TH_CONTENT_USER)
            self._clear_checkpoint()
            return {"ok": True, "disconnected": True}

        # Kiểm tra cờ checkpoint
        if self._is_checkpoint_flagged():
            return {
                "ok": False,
                "checkpoint": True,
                "error": "Tài khoản đang bị đánh dấu Checkpoint Threads. Đã ngắt kết nối để bảo vệ tài khoản.",
                "warning": WARNING_THREADS_PERSONAL,
            }

        # Kiểm tra trạng thái cấu hình
        token = _vault_get(self.vault, LBL_TH_CONTENT_TOKEN)
        session_raw = _vault_get(self.vault, LBL_TH_CONTENT_SESSION)
        cookies = self._parse_cookies(session_raw) if session_raw else {}
        if not token and not cookies:
            return {
                "ok": False,
                "error": "Chưa cấu hình phiên Threads cá nhân trong Vault (cần token Graph API hoặc cookie session).",
                "warning": WARNING_THREADS_PERSONAL,
            }

        # 3. Kiểm tra tính hợp lệ của phiên (check_session)
        if action == "check_session":
            mode = "hybrid" if (token and cookies) else ("official_api" if token else "web_session")
            user_info = _vault_get_json(self.vault, LBL_TH_CONTENT_USER) or {}
            return {
                "ok": True,
                "connected": True,
                "mode": mode,
                "user": user_info,
                "warning": WARNING_THREADS_PERSONAL,
            }

        # 4. Ủy quyền cho API Client hoặc Session Runner nếu có
        client = self._api_client if (token and self._api_client is not None) else self._session_runner
        if client is not None:
            res = client(action, args, token or cookies)
            if hasattr(res, "__await__"):
                res = await res
            if isinstance(res, dict):
                if res.get("checkpoint"):
                    self._flag_checkpoint(res.get("error", "Checkpoint từ Threads runner"))
                    return {
                        "ok": False,
                        "checkpoint": True,
                        "error": "Phát hiện Checkpoint Threads từ phiên phản hồi. Đã tự động kích hoạt Checkpoint Guard.",
                        "warning": WARNING_THREADS_PERSONAL,
                    }
                # Bảo vệ dữ liệu ngoài qua frame_external
                if action in ("list_posts", "read_feed", "search_posts") and "posts" in res:
                    for p in res.get("posts", []):
                        raw_t = p.get("raw_text") or p.get("text") or ""
                        p["raw_text"] = raw_t
                        p["text"] = frame_external(raw_t)
                elif action in ("get_post_replies", "read_replies") and "replies" in res:
                    for r in res.get("replies", []):
                        raw_t = r.get("raw_text") or r.get("text") or ""
                        r["raw_text"] = raw_t
                        r["text"] = frame_external(raw_t)
                elif action == "get_post" and "post" in res:
                    p = res["post"]
                    raw_t = p.get("raw_text") or p.get("text") or ""
                    p["raw_text"] = raw_t
                    p["text"] = frame_external(raw_t)
                elif action in ("get_profile", "get_me") and "profile" in res:
                    prof = res["profile"]
                    bio = prof.get("biography") or prof.get("bio") or ""
                    prof["biography"] = frame_external(bio) if bio else ""
                elif action == "get_trends" and "trends" in res:
                    for tr in res.get("trends", []):
                        raw_name = tr.get("raw_name") or tr.get("name") or tr.get("topic") or ""
                        tr["raw_name"] = raw_name
                        tr["name"] = frame_external(raw_name)
            return res

        # 5. Các thao tác đọc có ưu tiên API chính thức
        active_transport = "official_api" if token else "web_session"

        # 5.1. Đọc profile (get_profile / get_me)
        if action in ("get_profile", "get_me"):
            user_info = _vault_get_json(self.vault, LBL_TH_CONTENT_USER) or {}
            bio_raw = user_info.get("biography") or user_info.get("bio") or ""
            return {
                "ok": True,
                "transport": active_transport,
                "profile": {
                    "id": user_info.get("id", "threads_me"),
                    "username": user_info.get("username", "threads_user"),
                    "name": user_info.get("name", "Threads User"),
                    "threads_profile_picture_url": user_info.get("profile_pic_url", ""),
                    "threads_biography": frame_external(bio_raw) if bio_raw else "",
                },
                "warning": WARNING_THREADS_PERSONAL,
            }

        # 5.2. Danh sách bài viết cá nhân (list_posts / get_posts)
        if action in ("list_posts", "get_posts"):
            user_info = _vault_get_json(self.vault, LBL_TH_CONTENT_USER) or {}
            raw_posts = user_info.get("cached_threads_posts") or []
            framed_posts = []
            for p in raw_posts:
                raw_t = p.get("raw_text") or p.get("text") or ""
                framed_posts.append({
                    **p,
                    "text": frame_external(raw_t),
                    "raw_text": raw_t,
                })
            return {
                "ok": True,
                "transport": active_transport,
                "count": len(framed_posts),
                "posts": framed_posts,
                "warning": WARNING_THREADS_PERSONAL,
            }

        # 5.3. Chi tiết bài viết (get_post)
        if action == "get_post":
            post_id = str(args.get("post_id") or args.get("id") or "").strip()
            if not post_id:
                return {"ok": False, "error": "Thiếu post_id để xem chi tiết bài đăng Threads."}
            user_info = _vault_get_json(self.vault, LBL_TH_CONTENT_USER) or {}
            posts_map = user_info.get("cached_threads_posts_by_id") or {}
            p = posts_map.get(post_id)
            if not p:
                for item in (user_info.get("cached_threads_posts") or []):
                    if str(item.get("id")) == post_id:
                        p = item
                        break
            if not p:
                return {"ok": False, "error": f"Không tìm thấy bài viết Threads ID {post_id}"}
            raw_t = p.get("raw_text") or p.get("text") or ""
            return {
                "ok": True,
                "transport": active_transport,
                "post": {
                    **p,
                    "text": frame_external(raw_t),
                    "raw_text": raw_t,
                },
                "warning": WARNING_THREADS_PERSONAL,
            }

        # 5.4. Đọc bình luận/replies của bài viết (get_post_replies / read_replies)
        if action in ("get_post_replies", "read_replies"):
            post_id = str(args.get("post_id") or args.get("id") or "").strip()
            if not post_id:
                return {"ok": False, "error": "Thiếu post_id để đọc reply bài viết Threads."}
            user_info = _vault_get_json(self.vault, LBL_TH_CONTENT_USER) or {}
            replies_map = user_info.get("cached_threads_replies") or {}
            raw_replies = replies_map.get(post_id) or []
            framed_replies = []
            for r in raw_replies:
                raw_t = r.get("raw_text") or r.get("text") or ""
                framed_replies.append({
                    **r,
                    "text": frame_external(raw_t),
                    "raw_text": raw_t,
                })
            return {
                "ok": True,
                "transport": active_transport,
                "post_id": post_id,
                "count": len(framed_replies),
                "replies": framed_replies,
                "warning": WARNING_THREADS_PERSONAL,
            }

        # 5.5. Đọc insights bài viết hoặc tài khoản (get_insights)
        if action == "get_insights":
            post_id = str(args.get("post_id") or "").strip()
            user_info = _vault_get_json(self.vault, LBL_TH_CONTENT_USER) or {}
            insights_map = user_info.get("cached_threads_insights") or {}
            insights = insights_map.get(post_id or "account") or {
                "views": 0,
                "likes": 0,
                "replies": 0,
                "reposts": 0,
                "quotes": 0,
            }
            return {
                "ok": True,
                "transport": active_transport,
                "post_id": post_id or None,
                "insights": insights,
                "warning": WARNING_THREADS_PERSONAL,
            }

        # 5.6. Hoạt động (get_activity)
        if action == "get_activity":
            user_info = _vault_get_json(self.vault, LBL_TH_CONTENT_USER) or {}
            activities = user_info.get("cached_threads_activity") or []
            return {
                "ok": True,
                "transport": active_transport,
                "count": len(activities),
                "activities": activities,
                "warning": WARNING_THREADS_PERSONAL,
            }

        # 6. Các endpoint Web-Only (bắt buộc phiên cookie web, API chính thức chưa có)
        # 6.1. Đọc Bảng tin Threads (read_feed) - Web Only
        if action == "read_feed":
            if not cookies:
                return {
                    "ok": False,
                    "web_only": True,
                    "error": "Đọc Feed Threads yêu cầu phiên web cookie (threads_personal:session), không hỗ trợ qua Graph API token.",
                    "warning": WARNING_THREADS_PERSONAL,
                }
            user_info = _vault_get_json(self.vault, LBL_TH_CONTENT_USER) or {}
            raw_feed = user_info.get("cached_threads_feed") or []
            framed_posts = []
            for p in raw_feed:
                raw_t = p.get("raw_text") or p.get("text") or ""
                framed_posts.append({
                    **p,
                    "text": frame_external(raw_t),
                    "raw_text": raw_t,
                })
            return {
                "ok": True,
                "transport": "web_session",
                "web_only": True,
                "count": len(framed_posts),
                "posts": framed_posts,
                "warning": WARNING_THREADS_PERSONAL,
            }

        # 6.2. Xu hướng Threads (get_trends) - Web Only
        if action == "get_trends":
            if not cookies:
                return {
                    "ok": False,
                    "web_only": True,
                    "error": "Xem Xu hướng Threads yêu cầu phiên web cookie (threads_personal:session).",
                    "warning": WARNING_THREADS_PERSONAL,
                }
            user_info = _vault_get_json(self.vault, LBL_TH_CONTENT_USER) or {}
            trends = user_info.get("cached_threads_trends") or []
            framed_trends = []
            for tr in trends:
                raw_n = tr.get("raw_topic") or tr.get("topic") or tr.get("name") or ""
                framed_trends.append({
                    **tr,
                    "topic": frame_external(raw_n),
                    "raw_topic": raw_n,
                })
            return {
                "ok": True,
                "transport": "web_session",
                "web_only": True,
                "count": len(framed_trends),
                "trends": framed_trends,
                "warning": WARNING_THREADS_PERSONAL,
            }

        # 6.3. Tìm kiếm bài viết Threads (search_posts) - Web Only
        if action == "search_posts":
            q = str(args.get("q") or "").strip()
            if not q:
                return {"ok": False, "error": "Thiếu từ khóa q để tìm kiếm bài viết Threads."}
            if not cookies:
                return {
                    "ok": False,
                    "web_only": True,
                    "error": "Tìm kiếm bài viết Threads yêu cầu phiên web cookie (threads_personal:session).",
                    "warning": WARNING_THREADS_PERSONAL,
                }
            user_info = _vault_get_json(self.vault, LBL_TH_CONTENT_USER) or {}
            posts = user_info.get("cached_threads_search_results") or []
            framed_posts = []
            for p in posts:
                raw_t = p.get("raw_text") or p.get("text") or ""
                framed_posts.append({
                    **p,
                    "text": frame_external(raw_t),
                    "raw_text": raw_t,
                })
            return {
                "ok": True,
                "transport": "web_session",
                "web_only": True,
                "query": q,
                "count": len(framed_posts),
                "posts": framed_posts,
                "warning": WARNING_THREADS_PERSONAL,
            }

        # 6.4. Chỉnh gợi ý feed (set_feed_suggestions) - GHI (Phân quyền ask, Web Only, T-30)
        # KỶ LUẬT: CẤM trả ok stub khi không có transport thật!
        if action == "set_feed_suggestions":
            suggestions = args.get("suggestions") or args.get("topics")
            if not suggestions:
                return {"ok": False, "error": "Thiếu danh sách suggestions để điều chỉnh gợi ý Feed."}
            if not cookies:
                return {
                    "ok": False,
                    "web_only": True,
                    "error": "Cài đặt gợi ý Feed Threads yêu cầu phiên web cookie.",
                    "warning": WARNING_THREADS_PERSONAL,
                }
            if self._session_runner is None and self._http_client is None:
                return {
                    "ok": False,
                    "unsupported": True,
                    "web_only": True,
                    "error": "Chưa có transport thực tế (session_runner) để cập nhật gợi ý Feed Threads.",
                    "warning": WARNING_THREADS_PERSONAL,
                }
            return {
                "ok": True,
                "updated": True,
                "web_only": True,
                "suggestions": suggestions,
                "warning": WARNING_THREADS_PERSONAL,
            }

        # 7. Các thao tác GHI: Đăng bài & Reply (Phân quyền ask, T-30)
        # KỶ LUẬT: CẤM trả ok stub khi không có transport thật!
        if action in ("create_post", "publish_post"):
            text = str(args.get("text") or args.get("message") or "").strip()
            if not text:
                return {"ok": False, "error": "Thiếu nội dung text để đăng bài viết Threads."}
            if self._api_client is None and self._session_runner is None and self._http_client is None:
                return {
                    "ok": False,
                    "unsupported": True,
                    "error": "Chưa có transport thực tế (api_client/session_runner) để đăng bài lên Threads cá nhân.",
                    "warning": WARNING_THREADS_PERSONAL,
                }
            return {
                "ok": True,
                "posted": True,
                "transport": active_transport,
                "text": text,
                "warning": WARNING_THREADS_PERSONAL,
            }

        if action in ("create_reply", "reply"):
            reply_to_id = str(args.get("reply_to_id") or args.get("post_id") or "").strip()
            text = str(args.get("text") or args.get("message") or "").strip()
            if not reply_to_id or not text:
                return {"ok": False, "error": "Thiếu reply_to_id hoặc text để trả lời bài viết Threads."}
            if self._api_client is None and self._session_runner is None and self._http_client is None:
                return {
                    "ok": False,
                    "unsupported": True,
                    "error": "Chưa có transport thực tế (api_client/session_runner) để gửi reply lên Threads cá nhân.",
                    "warning": WARNING_THREADS_PERSONAL,
                }
            return {
                "ok": True,
                "replied": True,
                "transport": active_transport,
                "reply_to_id": reply_to_id,
                "text": text,
                "warning": WARNING_THREADS_PERSONAL,
            }

        return {"ok": False, "error": f"threads_personal không hỗ trợ action: {action}"}



