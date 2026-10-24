"""1.2.0 Khối 4: API Mini App chạy thật trên cổng tạm — /api/state
không lộ bí mật Vault, /api/approve resolve broker, /api/policy
đổi verdict, thiếu initData -> 403."""

import asyncio
import json
from dataclasses import replace

import pytest
from aiohttp import ClientSession

from mulon.approvals import ApprovalBroker
from mulon.connectors import build_default_connectors
from mulon.context import Dossier
from mulon.policy import PolicyEngine
from mulon.tools import build_default_registry
from mulon.vault import VaultStore
from mulon.webapp_server import WebAppServer
from tests.conftest import open_memory
from tests.test_v12_webapp_auth import TOKEN, OWNER, make_init_data

SECRET_MARKER = "GIA-TRI-BI-MAT-KHONG-DUOC-LO-123"


async def _start(cfg):
    cfg2 = replace(cfg, telegram_bot_token=TOKEN,
                   allowed_user_id=OWNER, webapp_port=0)
    memory = await open_memory(cfg2)
    policy = PolicyEngine(cfg2.policy_path, memory=memory)
    broker = ApprovalBroker(policy=policy, timeout_s=30)
    vault = VaultStore(cfg2.vault_path)
    vault.put("nhan-test", SECRET_MARKER)
    server = WebAppServer(
        cfg2, memory=memory, policy=policy, broker=broker,
        connectors=build_default_connectors(cfg2), mcp_manager=None,
        vault_store=vault,
        registry=build_default_registry(cfg2, memory),
        dossier=Dossier.load(cfg2.dossier_dir), skills=None)
    assert await server.start()
    return cfg2, memory, broker, server


async def _stop(memory, server):
    await server.stop()
    await memory.close()


@pytest.fixture
async def app(cfg):
    parts = await _start(cfg)
    yield parts
    await _stop(parts[1], parts[3])


def _url(server, path):
    return f"http://127.0.0.1:{server.port}{path}"


async def test_state_requires_valid_initdata(app):
    _, _, _, server = app
    async with ClientSession() as s:
        async with s.get(_url(server, "/api/state")) as r:
            assert r.status == 403
        async with s.get(_url(server, "/api/state"),
                         headers={"X-Telegram-Init-Data":
                                  "gia-mao"}) as r:
            assert r.status == 403


async def test_state_ok_and_no_secret_leak(app):
    _, _, _, server = app
    headers = {"X-Telegram-Init-Data": make_init_data()}
    async with ClientSession() as s:
        async with s.get(_url(server, "/api/state"),
                         headers=headers) as r:
            assert r.status == 200
            text = await r.text()
            data = await r.json()
    assert SECRET_MARKER not in text
    assert data["vault"][0]["label"] == "nhan-test"
    assert data["vault"][0]["ref"].startswith("vault:")
    assert data["status"]["busy"] is False
    assert "groups" in data["policy"] and "tools" in data["policy"]
    assert data["approvals"]["pending"] == []
    assert "items" in data["schedule"]
    assert data["profile"]["facts_active"] >= 0


async def test_api_approve_resolves_broker(app):
    _, _, broker, server = app
    broker.open("zz9", {"approval_id": "zz9", "tool": "run_command",
                        "group": "shell", "summary": "cmd=ls",
                        "session_key": "sk", "task_id": "t"})
    waiter = asyncio.create_task(broker.wait("zz9"))
    headers = {"X-Telegram-Init-Data": make_init_data()}
    async with ClientSession() as s:
        async with s.post(_url(server, "/api/approve"),
                          headers=headers,
                          json={"id": "zz9",
                                "decision": "approve_remember"}) as r:
            assert r.status == 200
            assert (await r.json())["ok"] is True
    record = await waiter
    assert record["approved"] is True and record["remember"] is True


async def test_api_policy_changes_verdict(app):
    _, _, _, server = app
    headers = {"X-Telegram-Init-Data": make_init_data()}
    async with ClientSession() as s:
        async with s.post(_url(server, "/api/policy"),
                          headers=headers,
                          json={"scope": "group", "name": "shell",
                                "verdict": "ask"}) as r:
            assert r.status == 200
            data = await r.json()
    assert data["policy"]["groups"]["shell"] == "ask"
    async with ClientSession() as s:
        async with s.post(_url(server, "/api/policy"),
                          headers=headers,
                          json={"scope": "group", "name": "shell",
                                "verdict": "bậy"}) as r:
            assert r.status == 400


async def test_index_served_without_auth(app):
    _, _, _, server = app
    async with ClientSession() as s:
        async with s.get(_url(server, "/app")) as r:
            assert r.status == 200
            text = await r.text()
    assert "Phê duyệt" in text and "Hồ sơ" in text


async def test_api_vault_update_and_delete(app):
    _, _, _, server = app
    headers = {"X-Telegram-Init-Data": make_init_data()}
    async with ClientSession() as s:
        # Create
        async with s.post(_url(server, "/api/vault/capture"),
                          headers=headers,
                          json={"label": "init_label", "value": "init_val"}) as r:
            assert r.status == 200
            ref = (await r.json())["ref"]

        # Update label and value
        async with s.post(_url(server, "/api/vault/update"),
                          headers=headers,
                          json={"ref": ref, "label": "updated_label", "value": "new_secret"}) as r:
            assert r.status == 200
            assert (await r.json())["ok"] is True

        # Check state has updated label (never value)
        async with s.get(_url(server, "/api/state"), headers=headers) as r:
            st = await r.json()
            found = [x for x in st["vault"] if x["ref"] == ref]
            assert found and found[0]["label"] == "updated_label"
            assert "new_secret" not in json.dumps(st)

        # Delete
        async with s.post(_url(server, "/api/vault/delete"),
                          headers=headers,
                          json={"ref": ref}) as r:
            assert r.status == 200
            assert (await r.json())["ok"] is True

        # Check state no longer has ref
        async with s.get(_url(server, "/api/state"), headers=headers) as r:
            st = await r.json()
            assert not any(x["ref"] == ref for x in st["vault"])
