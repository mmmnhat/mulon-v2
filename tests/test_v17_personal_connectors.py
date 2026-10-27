"""Test cho T-22.1 — Connector tài khoản cá nhân (Zalo cá nhân + Telegram cá nhân).

Kiểm chứng toàn diện:
1. Telegram cá nhân (Telethon MTProto userbot):
   - Trạng thái chưa cấu hình / chưa kết nối kèm cảnh báo rủi ro userbot.
   - Luồng đăng nhập QR code -> lưu StringSession an toàn vào Vault.
   - Đọc tin nhắn: bảo vệ toàn diện dữ liệu ngoài qua frame_external.
   - Gửi tin nhắn / tệp và đối chiếu policy (đọc = allow, gửi = ask).
   - Danh sách hội thoại (list_dialogs).
   - Ngắt kết nối / dọn dẹp sạch sẽ Vault.

2. Zalo cá nhân (zca-js bridge):
   - Trạng thái chưa kết nối kèm cảnh báo giới hạn (không đăng nhật ký).
   - Luồng đăng nhập QR code & tái sử dụng session qua Vault.
   - Đọc tin nhắn: bảo vệ toàn diện dữ liệu ngoài qua frame_external.
   - Tìm người dùng theo số điện thoại (find_user).
   - Gửi tin nhắn và tệp (send_message / send_file).
   - Ngắt kết nối / dọn dẹp sạch sẽ Vault.

3. Tích hợp WebApp & REST API:
   - Endpoint /api/personal-connector/status, /qr, /disconnect.
   - Dữ liệu /api/state chứa đầy đủ thông tin zalo và telegram_personal.
"""

from __future__ import annotations

import asyncio
import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from mulon.connectors import build_default_connectors
from mulon.personal_connectors import (
    TelegramPersonalConnector,
    ZaloPersonalConnector,
    LBL_TG_SESSION,
    LBL_TG_USER,
    LBL_ZALO_SESSION,
    LBL_ZALO_USER,
    LIMITATION_ZALO,
    WARNING_TELEGRAM,
    _vault_get,
    _vault_put,
)
from mulon.policy import (
    PolicyEngine,
    VERDICT_ALLOW,
    VERDICT_ASK,
)
from mulon.vault import VaultStore


# ---------------------------------------------------------------------------
# Mocks & Stubs cho Telethon
# ---------------------------------------------------------------------------

class FakeQRLogin:
    def __init__(self):
        self.url = "tg://login?token=fake_token_12345"
        self.expires = 300
        self.is_done = False

    async def wait(self, timeout=None):
        return True

    async def recreate(self):
        self.url = "tg://login?token=fake_token_recreated"


class FakeTelethonUser:
    def __init__(self, uid=987654321, first_name="Nhat", username="mmmnhat"):
        self.id = uid
        self.first_name = first_name
        self.last_name = ""
        self.username = username
        self.phone = "+84900000000"


class FakeTelethonMessage:
    def __init__(self, mid, text, sender_id=111):
        self.id = mid
        self.text = text
        self.sender_id = sender_id
        self.date = MagicMock()
        self.date.isoformat.return_value = "2026-10-27T09:00:00+07:00"


class FakeTelethonDialog:
    def __init__(self, did, title, unread=0, is_user=True, is_group=False):
        self.id = did
        self.title = title
        self.unread_count = unread
        self.is_user = is_user
        self.is_group = is_group
        self.is_channel = False


class FakeTelethonClient:
    def __init__(self, authorized=False):
        self._authorized = authorized
        self.session = MagicMock()
        self.session.save.return_value = "1BVtsOMQBu..."
        self._me = FakeTelethonUser()
        self.disconnected = False

    async def is_user_authorized(self):
        return self._authorized

    async def connect(self):
        pass

    async def disconnect(self):
        self.disconnected = True

    async def qr_login(self):
        return FakeQRLogin()

    async def get_me(self):
        return self._me

    async def get_messages(self, entity, limit=10):
        return [
            FakeTelethonMessage(1, "Chào bạn, hôm nay có lịch họp không?"),
            FakeTelethonMessage(2, "Báo giá dự án đã gửi qua email nha."),
        ]

    async def get_dialogs(self, limit=20):
        return [
            FakeTelethonDialog(101, "Nhóm Dự án MuLon", unread=2, is_group=True),
            FakeTelethonDialog(102, "Nguyễn Văn A", unread=0, is_user=True),
        ]

    async def send_message(self, entity, text):
        return FakeTelethonMessage(1001, text)

    async def send_file(self, entity, file_path, caption=""):
        return FakeTelethonMessage(1002, caption)


# ---------------------------------------------------------------------------
# Tests: TelegramPersonalConnector
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_telegram_personal_unconfigured(tmp_path):
    vault = VaultStore(tmp_path / "vault.json")
    conn = TelegramPersonalConnector(vault_store=vault)

    # Khi chưa cấu hình API ID / Hash
    health = await conn.health_check()
    assert health["ok"] is False
    assert health["connected"] is False
    assert WARNING_TELEGRAM in health["warning"]


@pytest.mark.asyncio
async def test_telegram_personal_qr_login_and_auth(tmp_path):
    vault = VaultStore(tmp_path / "vault.json")
    fake_client = FakeTelethonClient(authorized=False)
    conn = TelegramPersonalConnector(vault_store=vault, client=fake_client)

    # 1. Bắt đầu QR login
    res = await conn.call("qr_login", {"step": "start"})
    assert res["ok"] is True
    assert "tg://login?token=" in res["qr_url"]
    assert WARNING_TELEGRAM in res["warning"]

    # 2. Sau khi người dùng quét mã thành công
    fake_client._authorized = True
    status_res = await conn.call("qr_login", {"step": "status"})
    assert status_res["ok"] is True
    assert status_res["connected"] is True
    assert status_res["user"]["username"] == "mmmnhat"

    # Phiên phải được lưu an toàn vào Vault
    saved_session = _vault_get(vault, LBL_TG_SESSION)
    assert saved_session == "1BVtsOMQBu..."

    # 3. Health check sau khi đã kết nối
    health = await conn.health_check()
    assert health["ok"] is True
    assert health["connected"] is True
    assert health["user"]["id"] == 987654321


@pytest.mark.asyncio
async def test_telegram_personal_read_messages_frame_external(tmp_path):
    vault = VaultStore(tmp_path / "vault.json")
    fake_client = FakeTelethonClient(authorized=True)
    conn = TelegramPersonalConnector(vault_store=vault, client=fake_client)

    res = await conn.call("read_messages", {"chat_id": 101, "limit": 5})
    assert res["ok"] is True
    assert res["count"] == 2
    for msg in res["messages"]:
        # Dữ liệu ngoài bắt buộc phải đi qua frame_external
        assert "<external_data" in msg["text"]
        assert "</external_data>" in msg["text"]
        assert msg["raw_text"] != ""


@pytest.mark.asyncio
async def test_telegram_personal_send_message_and_file(tmp_path):
    vault = VaultStore(tmp_path / "vault.json")
    fake_client = FakeTelethonClient(authorized=True)
    conn = TelegramPersonalConnector(vault_store=vault, client=fake_client)

    # Gửi tin nhắn
    res_msg = await conn.call("send_message", {"chat_id": 101, "text": "Tin nhắn thử nghiệm"})
    assert res_msg["ok"] is True
    assert res_msg["message_id"] == 1001

    # Gửi file
    res_file = await conn.call("send_file", {"chat_id": 101, "file_path": "/tmp/test.pdf", "caption": "Tài liệu"})
    assert res_file["ok"] is True
    assert res_file["message_id"] == 1002


@pytest.mark.asyncio
async def test_telegram_personal_dialogs_and_disconnect(tmp_path):
    vault = VaultStore(tmp_path / "vault.json")
    _vault_put(vault, LBL_TG_SESSION, "valid_session")
    fake_client = FakeTelethonClient(authorized=True)
    conn = TelegramPersonalConnector(vault_store=vault, client=fake_client)

    # Danh sách hội thoại
    res_d = await conn.call("list_dialogs", {"limit": 10})
    assert res_d["ok"] is True
    assert res_d["count"] == 2
    assert res_d["dialogs"][0]["title"] == "Nhóm Dự án MuLon"

    # Ngắt kết nối
    res_dc = await conn.call("disconnect", {})
    assert res_dc["ok"] is True
    assert fake_client.disconnected is True
    # Session trong Vault phải bị dọn dẹp sạch
    assert _vault_get(vault, LBL_TG_SESSION) is None


# ---------------------------------------------------------------------------
# Tests: ZaloPersonalConnector
# ---------------------------------------------------------------------------

class FakeZaloRunner:
    def __init__(self):
        self.connected = False
        self.sent_messages = []
        self.sent_files = []

    async def __call__(self, cmd: str, args: dict) -> dict:
        if cmd == "login_qr":
            self.connected = True
            return {
                "ok": True,
                "qr_path": "/tmp/zalo_qr_test.png",
                "user": {"id": "zalo_u123", "name": "Nguyễn Văn Test"},
                "session": {"cookie": "zcookie_xyz", "imei": "imei_123", "userAgent": "Mozilla/5.0"},
            }
        if cmd == "login_session":
            self.connected = True
            return {"ok": True, "user": {"id": "zalo_u123", "name": "Nguyễn Văn Test"}}
        if cmd == "get_messages":
            return {
                "ok": True,
                "messages": [
                    {"msgId": "m1", "content": "Tin nhắn Zalo cá nhân 1", "from": "u1"},
                    {"msgId": "m2", "content": "File hợp đồng gửi kèm nhé", "from": "u2"},
                ]
            }
        if cmd == "send_message":
            self.sent_messages.append(args)
            return {"ok": True, "msgId": "sent_z_1"}
        if cmd == "send_file":
            self.sent_files.append(args)
            return {"ok": True, "msgId": "sent_zf_1"}
        if cmd == "find_user":
            return {"ok": True, "user": {"userId": "zalo_found_1", "name": "Trần Thị B", "phone": args.get("phone")}}
        if cmd == "logout":
            self.connected = False
            return {"ok": True}
        return {"ok": False, "error": f"Unknown cmd: {cmd}"}


@pytest.mark.asyncio
async def test_zalo_personal_health_check_and_limitations(tmp_path):
    vault = VaultStore(tmp_path / "vault.json")
    conn = ZaloPersonalConnector(vault_store=vault)

    health = await conn.health_check()
    assert health["connected"] is False
    assert LIMITATION_ZALO in health["limitations"]


@pytest.mark.asyncio
async def test_zalo_personal_qr_login_and_session(tmp_path):
    vault = VaultStore(tmp_path / "vault.json")
    runner = FakeZaloRunner()
    conn = ZaloPersonalConnector(vault_store=vault, bridge_runner=runner)

    # 1. Đăng nhập QR
    res = await conn.call("qr_login", {"step": "start"})
    assert res["ok"] is True
    assert res["user"]["id"] == "zalo_u123"
    assert LIMITATION_ZALO in res["limitations"]

    # Session phải được lưu an toàn vào Vault
    saved_session = _vault_get(vault, LBL_ZALO_SESSION)
    assert saved_session is not None
    assert "zcookie_xyz" in saved_session

    # 2. Health check sau khi đã đăng nhập
    health = await conn.health_check()
    assert health["ok"] is True
    assert health["connected"] is True
    assert health["user"]["name"] == "Nguyễn Văn Test"


@pytest.mark.asyncio
async def test_zalo_personal_read_messages_frame_external(tmp_path):
    vault = VaultStore(tmp_path / "vault.json")
    runner = FakeZaloRunner()
    conn = ZaloPersonalConnector(vault_store=vault, bridge_runner=runner)

    res = await conn.call("read_messages", {"thread_id": "thread_123"})
    assert res["ok"] is True
    assert res["count"] == 2
    for msg in res["messages"]:
        assert "<external_data" in msg["text"]
        assert "</external_data>" in msg["text"]
        assert "Tin nhắn Zalo cá nhân" in msg["raw_text"] or "File hợp đồng" in msg["raw_text"]


@pytest.mark.asyncio
async def test_zalo_personal_send_find_and_disconnect(tmp_path):
    vault = VaultStore(tmp_path / "vault.json")
    runner = FakeZaloRunner()
    conn = ZaloPersonalConnector(vault_store=vault, bridge_runner=runner)

    # Gửi tin nhắn
    send_res = await conn.call("send_message", {"thread_id": "thread_group_1", "msg": "Alo cả nhà", "type": "group"})
    assert send_res["ok"] is True
    assert len(runner.sent_messages) == 1

    # Gửi file
    file_res = await conn.call("send_file", {"thread_id": "thread_user_1", "file_path": "/tmp/tailieu.docx"})
    assert file_res["ok"] is True
    assert len(runner.sent_files) == 1

    # Tìm user theo số điện thoại
    find_res = await conn.call("find_user", {"phone": "0912345678"})
    assert find_res["ok"] is True
    assert find_res["user"]["name"] == "Trần Thị B"

    # Ngắt kết nối
    dc_res = await conn.call("disconnect", {})
    assert dc_res["ok"] is True
    assert _vault_get(vault, LBL_ZALO_SESSION) is None


# ---------------------------------------------------------------------------
# Tests: Policy Enforcement (Đọc = Cho phép, Gửi = Hỏi trước)
# ---------------------------------------------------------------------------

def test_personal_connectors_policy_rules(tmp_path):
    policy = PolicyEngine(tmp_path / "policy.json")

    # Zalo cá nhân: đọc = allow, gửi = ask
    assert policy.decide("connector_call", "connector:zalo_personal:read_messages").verdict == VERDICT_ALLOW
    assert policy.decide("connector_call", "connector:zalo_personal:get_messages").verdict == VERDICT_ALLOW
    assert policy.decide("connector_call", "connector:zalo_personal:find_user").verdict == VERDICT_ALLOW
    assert policy.decide("connector_call", "connector:zalo_personal:send_message").verdict == VERDICT_ASK
    assert policy.decide("connector_call", "connector:zalo_personal:send_file").verdict == VERDICT_ASK

    # Telegram cá nhân: đọc = allow, gửi = ask
    assert policy.decide("connector_call", "connector:telegram_personal:read_messages").verdict == VERDICT_ALLOW
    assert policy.decide("connector_call", "connector:telegram_personal:list_dialogs").verdict == VERDICT_ALLOW
    assert policy.decide("connector_call", "connector:telegram_personal:find_dialog").verdict == VERDICT_ALLOW
    assert policy.decide("connector_call", "connector:telegram_personal:send_message").verdict == VERDICT_ASK
    assert policy.decide("connector_call", "connector:telegram_personal:send_file").verdict == VERDICT_ASK


# ---------------------------------------------------------------------------
# Tests: build_default_connectors & Mini App State
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_build_default_connectors_integration(tmp_path):
    vault = VaultStore(tmp_path / "vault.json")
    cfg = MagicMock()
    cfg.default_timezone = "Asia/Ho_Chi_Minh"
    cfg.telegram_user_api_id = "12345"
    cfg.telegram_user_api_hash = "abcdef"

    registry = build_default_connectors(cfg, vault_store=vault)
    names = registry.names()

    assert "system" in names
    assert "zalo_personal" in names
    assert "telegram_personal" in names

    # Kiểm tra health_all tổng hợp
    health = await registry.health_all()
    assert "zalo_personal" in health
    assert "telegram_personal" in health
    assert LIMITATION_ZALO in health["zalo_personal"]["limitations"]
    assert WARNING_TELEGRAM in health["telegram_personal"]["warning"]


@pytest.mark.asyncio
async def test_webapp_personal_connectors_api_endpoints(cfg, tmp_path):
    from dataclasses import replace
    from aiohttp import ClientSession
    from mulon.approvals import ApprovalBroker
    from mulon.context import Dossier
    from mulon.tools import build_default_registry
    from mulon.memory import Memory
    from mulon.webapp_server import WebAppServer
    from tests.test_v12_webapp_auth import TOKEN, OWNER, make_init_data

    cfg2 = replace(
        cfg,
        telegram_bot_token=TOKEN,
        allowed_user_id=OWNER,
        allowed_user_ids=[OWNER],
        webapp_port=0,
    )
    memory = await Memory.open(tmp_path / "mem.db")
    vault = VaultStore(tmp_path / "vault.json")
    policy = PolicyEngine(tmp_path / "policy.json", memory=memory)

    registry = build_default_connectors(cfg2, vault_store=vault)
    # Inject fake runner vào zalo_personal
    zalo_conn = await registry.get("zalo_personal")
    zalo_conn._bridge_runner = FakeZaloRunner()

    server = WebAppServer(
        cfg2,
        memory=memory,
        policy=policy,
        broker=ApprovalBroker(policy=policy, timeout_s=30),
        connectors=registry,
        mcp_manager=None,
        vault_store=vault,
        registry=build_default_registry(cfg2, memory),
        dossier=Dossier.load(cfg2.dossier_dir),
    )
    assert await server.start()

    url_base = f"http://127.0.0.1:{server.port}"
    headers = {"X-Telegram-Init-Data": make_init_data()}

    try:
        async with ClientSession() as s:
            # 1. GET /api/personal-connector/status
            async with s.get(f"{url_base}/api/personal-connector/status?name=zalo_personal", headers=headers) as r:
                assert r.status == 200
                data = await r.json()
                assert data["ok"] is True
                assert data["health"]["name"] == "zalo_personal"
                assert LIMITATION_ZALO in data["health"]["limitations"]

            # 2. POST /api/personal-connector/qr
            async with s.post(f"{url_base}/api/personal-connector/qr", json={"name": "zalo_personal", "step": "start"}, headers=headers) as r:
                assert r.status == 200
                data = await r.json()
                assert data["ok"] is True
                assert data["user"]["id"] == "zalo_u123"

            # 3. GET /api/state: chứa thông tin zalo & telegram_personal
            async with s.get(f"{url_base}/api/state", headers=headers) as r:
                assert r.status == 200
                state = await r.json()
                conns = state.get("connectors", [])
                zalo_entry = next((c for c in conns if c["id"] == "zalo_personal"), None)
                tg_entry = next((c for c in conns if c["id"] == "telegram_personal"), None)
                assert zalo_entry is not None
                assert "zalo" in zalo_entry
                assert zalo_entry["zalo"]["connected"] is True
                assert tg_entry is not None
                assert "telegram_personal" in tg_entry
                assert WARNING_TELEGRAM in tg_entry["telegram_personal"]["warning"]

            # 4. POST /api/personal-connector/disconnect
            async with s.post(f"{url_base}/api/personal-connector/disconnect", json={"name": "zalo_personal"}, headers=headers) as r:
                assert r.status == 200
                data = await r.json()
                assert data["ok"] is True
                assert data["disconnected"] is True
    finally:
        await server.stop()
        await memory.close()

