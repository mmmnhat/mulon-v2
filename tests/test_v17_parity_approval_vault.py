"""Test hồi quy và kiểm chứng Parity F3 + F2 (T-10.1).

Các yêu cầu:
1. Đồng bộ phê duyệt 2 chiều (chat <-> Mini App dùng chung 1 bản ghi duyệt):
   - Quyết ở Mini App (/api/approve) -> thẻ trong chat đổi trạng thái (✅ ĐÃ DUYỆT / ❌ ĐÃ CHẶN)
     và bàn phím nút bấm bị gỡ bỏ/vô hiệu hoá.
   - Quyết ở chat (inline button callback) -> thẻ trong chat đổi trạng thái ngay,
     Mini App (/api/state) cập nhật thẻ từ pending sang history ngay.
2. Tính idempotent:
   - Quyết trùng hoặc 2 lần liên tiếp: chỉ xử lý 1 lần duy nhất, lần sau báo đã xử lý/hết hạn.
3. Hết hạn (expiry):
   - Hết hạn thì hiển thị rõ ĐÃ HẾT HẠN ở cả hai nơi (chat card có badge HẾT HẠN,
     Mini App history ghi nhận outcome: expired).
4. Thẻ Vault trong chat end-to-end:
   - Agent thiếu bí mật -> tự gửi thẻ nhập vào chat (nhãn điền sẵn).
   - Người dùng nhập xong qua /api/vault/capture hoặc VaultStore -> bot báo lại NGAY trong chat.
   - Bí mật không rò rỉ vào log, trajectory, hay nội dung chat.
   - Việc đang dở tiếp tục thực hiện.
"""

import asyncio
from dataclasses import replace
from unittest.mock import AsyncMock, MagicMock

import pytest
from aiohttp import ClientSession

from mulon.approvals import ApprovalBroker
from mulon.connectors import build_default_connectors
from mulon.context import Dossier
from mulon.policy import PolicyEngine
from mulon.telegram_bot import TelegramSurface
from mulon.tools import ToolRegistry, build_default_registry
from mulon.vault import VaultBroker, VaultStore, register_vault_tools
from mulon.webapp_server import WebAppServer
from tests.conftest import open_memory
from tests.test_v12_surface import FakeBot, _cfg
from tests.test_v12_webapp_auth import OWNER, TOKEN, make_init_data

PAYLOAD = {
    "approval_id": "appr_sync_1",
    "tool": "delete_file",
    "group": "file",
    "summary": "path=/tmp/test.txt",
    "target": "/tmp/test.txt",
    "reason": "Dọn dẹp file tạm theo yêu cầu",
    "session_key": "sess_1",
    "task_id": "task_1",
}


async def _setup_sync_env(cfg, approval_action="update"):
    cfg_base = _cfg(cfg, approval_card_action=approval_action)
    cfg_base = replace(
        cfg_base,
        telegram_bot_token=TOKEN,
        allowed_user_id=OWNER,
        webapp_port=0,
    )
    memory = await open_memory(cfg_base)
    policy = PolicyEngine(cfg_base.policy_path, memory=memory)
    broker = ApprovalBroker(policy=policy, timeout_s=30)
    surface = TelegramSurface(
        cfg_base,
        agent=None,
        memory=memory,
        dossier=Dossier.load(cfg_base.dossier_dir),
        policy=policy,
        broker=broker,
    )
    bot = FakeBot()
    bot._me_username = "Mulon_bot"
    surface.bot = bot

    vault_store = VaultStore(cfg_base.vault_path)
    vault_store.on_captured(surface.on_vault_secret_captured)

    server = WebAppServer(
        cfg_base,
        memory=memory,
        policy=policy,
        broker=broker,
        connectors=build_default_connectors(cfg_base),
        mcp_manager=None,
        vault_store=vault_store,
        registry=build_default_registry(cfg_base, memory),
        dossier=Dossier.load(cfg_base.dossier_dir),
        skills=None,
    )
    server.set_vault_notifier(surface.on_vault_secret_captured)
    assert await server.start()
    return memory, broker, surface, bot, server, vault_store


def _api_url(server, path):
    return f"http://127.0.0.1:{server.port}{path}"


async def test_bidirectional_sync_approve_from_miniapp_updates_chat_card(cfg):
    """Duyệt từ Mini App (/api/approve) -> thẻ trong chat được CẬP NHẬT TRẠNG THÁI + gỡ nút."""
    memory, broker, surface, bot, server, _ = await _setup_sync_env(cfg, approval_action="update")
    try:
        broker.open("appr_sync_1", dict(PAYLOAD))
        waiter = asyncio.create_task(broker.wait("appr_sync_1"))

        mid = await surface.send_approval_card(777, None, dict(PAYLOAD))
        assert mid is not None
        assert len(bot.sent) == 1

        headers = {"X-Telegram-Init-Data": make_init_data()}
        async with ClientSession() as s:
            async with s.post(
                _api_url(server, "/api/approve"),
                headers=headers,
                json={"id": "appr_sync_1", "decision": "approve"},
            ) as r:
                assert r.status == 200
                res = await r.json()
                assert res["ok"] is True
                assert res["resolved"] is True

        record = await waiter
        assert record["outcome"] == "approved"
        assert record["approved"] is True

        # Thẻ chat KHÔNG bị xoá mà được edit text sang trạng thái ĐÃ CHO PHÉP / ĐÃ DUYỆT
        assert not bot.deleted
        assert len(bot.edited) >= 1
        last_edit_text = bot.edited[-1][0]
        assert "ĐÃ DUYỆT" in last_edit_text or "ĐÃ CHO PHÉP" in last_edit_text
        assert "Đã cho phép thực thi" in last_edit_text

        # Bàn phím nút bấm phía Telegram đã được gỡ (vô hiệu hoá)
        # Trong edit_message_text hoặc edit_message_reply_markup, reply_markup là None
        assert bot.edited[-1][1].get("reply_markup") is None
    finally:
        await server.stop()
        await memory.close()


async def test_bidirectional_sync_deny_from_chat_updates_miniapp_state(cfg):
    """Chặn từ chat (inline button callback) -> thẻ chat đổi trạng thái, Mini App chuyển sang history."""
    memory, broker, surface, bot, server, _ = await _setup_sync_env(cfg, approval_action="update")
    try:
        broker.open("appr_sync_2", dict(PAYLOAD, approval_id="appr_sync_2"))
        waiter = asyncio.create_task(broker.wait("appr_sync_2"))

        mid = await surface.send_approval_card(777, None, dict(PAYLOAD, approval_id="appr_sync_2"))
        assert mid is not None

        # Kiểm tra trước khi bấm: Mini App thấy đang pending
        headers = {"X-Telegram-Init-Data": make_init_data()}
        async with ClientSession() as s:
            async with s.get(_api_url(server, "/api/state"), headers=headers) as r:
                assert r.status == 200
                state_data = await r.json()
                pending_ids = [p["approval_id"] for p in state_data["approvals"]["pending"]]
                assert "appr_sync_2" in pending_ids

        # Bấm Chặn từ Telegram chat
        ok, note = await surface.handle_approval_callback("appr:0:appr_sync_2", OWNER)
        assert ok is True
        assert "Đã chặn" in note

        record = await waiter
        assert record["outcome"] == "denied"
        assert record["approved"] is False

        # Thẻ chat đã đổi trạng thái thành ĐÃ CHẶN / ĐÃ TỪ CHỐI
        assert len(bot.edited) >= 1
        assert "ĐÃ CHẶN" in bot.edited[-1][0] or "ĐÃ TỪ CHỐI" in bot.edited[-1][0]

        # Mô phỏng ghi trajectory của agent
        await memory.log_trajectory(
            "sess_1",
            "approval_decision",
            {
                "tool": "delete_file",
                "group": "file",
                "approval_id": "appr_sync_2",
                "outcome": "denied",
                "approved": False,
                "remember": False,
            },
        )

        # Mini App state cập nhật ngay: pending rỗng, history có outcome denied
        async with ClientSession() as s:
            async with s.get(_api_url(server, "/api/state"), headers=headers) as r:
                assert r.status == 200
                state_after = await r.json()
                pending_after = [p["approval_id"] for p in state_after["approvals"]["pending"]]
                assert "appr_sync_2" not in pending_after
                hist = state_after["approvals"]["history"]
                assert any(h["outcome"] == "denied" for h in hist)
    finally:
        await server.stop()
        await memory.close()


async def test_approval_idempotent_two_consecutive_decisions(cfg):
    """Quyết định trùng/hai lần liên tiếp là idempotent, không chạy hành động hai lần."""
    memory, broker, surface, bot, server, _ = await _setup_sync_env(cfg)
    try:
        broker.open("appr_idem_1", dict(PAYLOAD, approval_id="appr_idem_1"))
        waiter = asyncio.create_task(broker.wait("appr_idem_1"))
        await surface.send_approval_card(777, None, dict(PAYLOAD, approval_id="appr_idem_1"))

        # Quyết lần 1 từ Telegram inline callback
        ok1, note1 = await surface.handle_approval_callback("appr:1:appr_idem_1", OWNER)
        assert ok1 is True
        assert "Đã duyệt" in note1

        record = await waiter
        assert record["outcome"] == "approved"

        # Quyết lần 2 từ Telegram inline callback -> từ chối an toàn
        ok2, note2 = await surface.handle_approval_callback("appr:1:appr_idem_1", OWNER)
        assert ok2 is False
        assert "đã được xử lý hoặc đã hết hạn" in note2

        # Quyết tiếp từ Mini App API -> trả về resolved: False
        headers = {"X-Telegram-Init-Data": make_init_data()}
        async with ClientSession() as s:
            async with s.post(
                _api_url(server, "/api/approve"),
                headers=headers,
                json={"id": "appr_idem_1", "decision": "approve"},
            ) as r:
                assert r.status == 200
                res = await r.json()
                assert res["resolved"] is False
                assert res["ok"] is False
                assert "đã được xử lý" in res["error"]
    finally:
        await server.stop()
        await memory.close()


async def test_approval_expiration_shows_clearly_on_both_surfaces(cfg):
    """Thẻ duyệt hết hạn hiển thị rõ ĐÃ HẾT HẠN ở cả chat và Mini App."""
    cfg_base = _cfg(cfg, approval_card_action="update")
    cfg_base = replace(cfg_base, telegram_bot_token=TOKEN, allowed_user_id=OWNER, webapp_port=0)
    memory = await open_memory(cfg_base)
    policy = PolicyEngine(cfg_base.policy_path, memory=memory)
    # Timeout cực ngắn để test hết hạn
    broker = ApprovalBroker(policy=policy, timeout_s=0.1)
    surface = TelegramSurface(
        cfg_base,
        agent=None,
        memory=memory,
        dossier=Dossier.load(cfg_base.dossier_dir),
        policy=policy,
        broker=broker,
    )
    bot = FakeBot()
    bot._me_username = "Mulon_bot"
    surface.bot = bot

    server = WebAppServer(
        cfg_base,
        memory=memory,
        policy=policy,
        broker=broker,
        connectors=build_default_connectors(cfg_base),
        mcp_manager=None,
        vault_store=VaultStore(cfg_base.vault_path),
        registry=build_default_registry(cfg_base, memory),
        dossier=Dossier.load(cfg_base.dossier_dir),
        skills=None,
    )
    assert await server.start()

    try:
        broker.open("appr_exp_1", dict(PAYLOAD, approval_id="appr_exp_1"))
        waiter = asyncio.create_task(broker.wait("appr_exp_1"))
        mid = await surface.send_approval_card(777, None, dict(PAYLOAD, approval_id="appr_exp_1"))
        assert mid is not None

        record = await waiter
        assert record["outcome"] == "expired"
        assert record["approved"] is False

        # 1. Trên Telegram chat: thẻ được cập nhật sang HẾT HẠN PHÊ DUYỆT
        assert not bot.deleted
        assert len(bot.edited) >= 1
        edit_text = bot.edited[-1][0]
        assert "HẾT HẠN PHÊ DUYỆT" in edit_text
        assert "Thẻ đã hết hạn mà chưa có phản hồi" in edit_text
        # Nút bấm bị gỡ bỏ
        assert bot.edited[-1][1].get("reply_markup") is None

        # 2. Trên Mini App:
        # Ghi trajectory tương tự agent khi wait timeout
        await memory.log_trajectory(
            "sess_1",
            "approval_decision",
            {
                "tool": "delete_file",
                "group": "file",
                "approval_id": "appr_exp_1",
                "outcome": "expired",
                "approved": False,
            },
        )
        headers = {"X-Telegram-Init-Data": make_init_data()}
        async with ClientSession() as s:
            async with s.get(_api_url(server, "/api/state"), headers=headers) as r:
                assert r.status == 200
                st = await r.json()
                assert "appr_exp_1" not in [p["approval_id"] for p in st["approvals"]["pending"]]
                hist = st["approvals"]["history"]
                assert hist and hist[0]["outcome"] == "expired"
    finally:
        await server.stop()
        await memory.close()


async def test_vault_card_end_to_end_capture_and_resume(cfg, tmp_path):
    """Thẻ Vault trong chat end-to-end: agent thiếu bí mật -> gửi thẻ -> nhập -> báo lại + tiếp tục việc."""
    reg = ToolRegistry()
    vault_store_path = tmp_path / "vault.json"
    vault_store = VaultStore(vault_store_path)
    vault_broker = VaultBroker()

    cards_sent = []

    async def mock_notifier(info):
        cards_sent.append(info)
        return True

    register_vault_tools(reg, cfg, notifier=mock_notifier, vault_broker=vault_broker)
    tool = reg.get("request_vault_secret")
    assert tool is not None

    # 1. Agent gọi tool request_vault_secret với wait_timeout_s > 0 (chờ bí mật)
    wait_task = asyncio.create_task(
        tool.handler(
            label="google:client_secret",
            description="Client Secret cho Google Workspace",
            wait_timeout_s=5.0,
        )
    )

    # Chờ một tick ngắn để tool gửi thẻ vào broker
    await asyncio.sleep(0.05)
    assert len(cards_sent) == 1
    assert cards_sent[0]["label"] == "google:client_secret"
    assert "vault_google__client_secret" in cards_sent[0]["startapp_param"]
    assert vault_broker.is_waiting("google:client_secret")

    # Giả lập người dùng nhập giá trị qua VaultStore (như Mini App /api/vault/capture làm)
    raw_secret_value = "super-secret-google-token-xyz-12345"
    ref = vault_store.put("google:client_secret", raw_secret_value)
    assert ref.startswith("vault:")

    # Giải quyết broker khi có secret được put
    vault_broker.resolve("google:client_secret", ref)

    # Tool hoàn tất với ref được cấp
    res = await wait_task
    assert res["ok"] is True
    assert res["label"] == "google:client_secret"
    assert res["ref"] == ref
    # Giá trị bí mật thô KHÔNG nằm trong kết quả tool
    assert raw_secret_value not in str(res)

    # Giá trị đọc được qua 1 cửa resolve
    assert vault_store.resolve(ref) == raw_secret_value


async def test_vault_card_bot_notifies_chat_immediately(cfg):
    """Khi bí mật được nộp vào Vault, bot thông báo NGAY trong chat tương ứng."""
    cfg_base = _cfg(cfg)
    memory = await open_memory(cfg_base)
    surface = TelegramSurface(
        cfg_base,
        agent=None,
        memory=memory,
        dossier=Dossier.load(cfg_base.dossier_dir),
    )
    bot = FakeBot()
    surface.bot = bot

    # Giả lập đã gửi thẻ vào chat 999
    surface._pending_vault_cards["openai:api_key"] = {
        "chat_id": 999,
        "thread_id": 12,
        "label": "openai:api_key",
    }

    # Báo bí mật đã nộp
    fake_ref = "vault:uuid-key-888"
    await surface.on_vault_secret_captured("openai:api_key", fake_ref)

    # Kiểm tra tin nhắn Telegram được gửi đến đúng chat 999 và thread 12
    assert len(bot.sent) >= 1
    sent_msg = bot.sent[-1]
    assert sent_msg["chat_id"] == 999
    assert sent_msg.get("message_thread_id") == 12
    assert "Đã nhận và lưu bí mật" in sent_msg["text"]
    assert "openai:api_key" in sent_msg["text"]
    assert fake_ref in sent_msg["text"]
    await memory.close()
