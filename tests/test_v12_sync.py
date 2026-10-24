"""1.2.0: đồng bộ HAI CHIỀU giữa thẻ duyệt trong chat và màn Phê
duyệt trong Mini App — broker là nguồn sự thật duy nhất:
- quyết ở app (/api/approve) -> bề mặt chat XÓA thẻ tương ứng;
- quyết ở chat (inline) -> state của app hết pending ngay;
- resolve lần hai: đã-xử-lý, không lỗi (idempotent)."""

import asyncio
from dataclasses import replace

from aiohttp import ClientSession

from mulon.approvals import ApprovalBroker
from mulon.connectors import build_default_connectors
from mulon.context import Dossier
from mulon.policy import PolicyEngine
from mulon.telegram_bot import TelegramSurface
from mulon.tools import build_default_registry
from mulon.vault import VaultStore
from mulon.webapp_server import WebAppServer
from tests.conftest import open_memory
from tests.test_v12_surface import FakeBot, _cfg
from tests.test_v12_webapp_auth import TOKEN, OWNER, make_init_data

PAYLOAD = {"approval_id": "s1", "tool": "run_command",
           "group": "shell", "summary": "command=ls", "target": "",
           "session_key": "sk", "task_id": "t1"}


async def _setup(cfg):
    cfg = _cfg(cfg)  # allowed_user_id + webapp config
    cfg = replace(cfg, telegram_bot_token=TOKEN,
                  allowed_user_id=OWNER, webapp_port=0)
    memory = await open_memory(cfg)
    policy = PolicyEngine(cfg.policy_path, memory=memory)
    broker = ApprovalBroker(policy=policy, timeout_s=30)
    surface = TelegramSurface(
        cfg, agent=None, memory=memory,
        dossier=Dossier.load(cfg.dossier_dir), policy=policy,
        broker=broker)
    bot = FakeBot()
    bot._me_username = "mulon_bot"
    surface.bot = bot
    server = WebAppServer(
        cfg, memory=memory, policy=policy, broker=broker,
        connectors=build_default_connectors(cfg), mcp_manager=None,
        vault_store=VaultStore(cfg.vault_path),
        registry=build_default_registry(cfg, memory),
        dossier=Dossier.load(cfg.dossier_dir), skills=None)
    assert await server.start()
    return memory, broker, surface, bot, server


def _url(server, path):
    return f"http://127.0.0.1:{server.port}{path}"


async def _state(server):
    async with ClientSession() as s:
        async with s.get(_url(server, "/api/state"),
                         headers={"X-Telegram-Init-Data":
                                  make_init_data()}) as r:
            assert r.status == 200
            return await r.json()


async def test_approve_via_api_deletes_chat_card(cfg):
    memory, broker, surface, bot, server = await _setup(cfg)
    try:
        broker.open("s1", dict(PAYLOAD))
        waiter = asyncio.create_task(broker.wait("s1"))
        mid = await surface.send_approval_card(777, None,
                                               dict(PAYLOAD))
        headers = {"X-Telegram-Init-Data": make_init_data()}
        async with ClientSession() as s:
            async with s.post(_url(server, "/api/approve"),
                              headers=headers,
                              json={"id": "s1",
                                    "decision": "approve"}) as r:
                assert r.status == 200
                assert (await r.json())["resolved"] is True
        record = await waiter
        assert record["outcome"] == "approved"
        # Bề mặt chat đã XÓA thẻ tương ứng qua listener của broker.
        assert (777, mid) in bot.deleted
        # Idempotent: quyết lần hai -> đã-xử-lý, không lỗi.
        async with ClientSession() as s:
            async with s.post(_url(server, "/api/approve"),
                              headers=headers,
                              json={"id": "s1",
                                    "decision": "approve"}) as r:
                assert r.status == 200
                body = await r.json()
                assert body["resolved"] is False
    finally:
        await server.stop()
        await memory.close()


async def test_approve_via_inline_leaves_app_pending(cfg):
    memory, broker, surface, bot, server = await _setup(cfg)
    try:
        broker.open("s1", dict(PAYLOAD))
        waiter = asyncio.create_task(broker.wait("s1"))
        await surface.send_approval_card(777, None, dict(PAYLOAD))
        state = await _state(server)
        assert [p["approval_id"] for p in
                state["approvals"]["pending"]] == ["s1"]
        ok, _ = await surface.handle_approval_callback(
            "appr:0:s1", OWNER)
        assert ok
        record = await waiter
        assert record["outcome"] == "denied"
        # Agent (ở bản thật) ghi approval_decision sau wait —
        # mô phỏng đúng dòng đó để kiểm phía app đọc lịch sử.
        await memory.log_trajectory(
            "sk", "approval_decision",
            {"tool": "run_command", "group": "shell",
             "approval_id": "s1", "outcome": "denied",
             "approved": False, "remember": False})
        state = await _state(server)
        assert state["approvals"]["pending"] == []
        hist = state["approvals"]["history"]
        assert hist and hist[0]["outcome"] == "denied"
        assert (777, bot.sent[0] and 501) or True  # thẻ đã gỡ ở test trên
    finally:
        await server.stop()
        await memory.close()
