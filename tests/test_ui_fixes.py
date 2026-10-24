"""Kiểm thử cho các sửa UI (không phải so sánh model).

1. Rename Library: backend chấp nhận cả {name} và {title} cũ.
2. /api/state có "library" và schedule có mục "ideas_auto".
3. Trash/restore qua Mini App route.
4. BOT_COMMANDS có 3 lệnh từng bị ẩn: feed_now, pin_item, rename_item.
5. GoogleAuth.revoke() gọi đúng endpoint revoke trước khi xóa local.
"""
from dataclasses import replace
from pathlib import Path

import pytest
from aiohttp import ClientSession

from mulon.approvals import ApprovalBroker
from mulon.connectors import build_default_connectors
from mulon.context import Dossier
from mulon.google_conn import GoogleAuth
from mulon.library import LibraryService
from mulon.policy import PolicyEngine
from mulon.telegram_bot import BOT_COMMANDS
from mulon.tools import build_default_registry
from mulon.vault import VaultStore
from mulon.webapp_server import WebAppServer
from tests.conftest import open_memory
from tests.test_v12_webapp_auth import OWNER, TOKEN, make_init_data


async def _start(cfg):
    cfg2 = replace(cfg, telegram_bot_token=TOKEN,
                   allowed_user_id=OWNER, webapp_port=0)
    memory = await open_memory(cfg2)
    policy = PolicyEngine(cfg2.policy_path, memory=memory)
    broker = ApprovalBroker(policy=policy, timeout_s=30)
    vault = VaultStore(cfg2.vault_path)
    lib = LibraryService(cfg2, memory)
    server = WebAppServer(
        cfg2, memory=memory, policy=policy, broker=broker,
        connectors=build_default_connectors(cfg2), mcp_manager=None,
        vault_store=vault, registry=build_default_registry(cfg2, memory),
        dossier=Dossier.load(cfg2.dossier_dir), skills=None, library=lib)
    assert await server.start()
    return cfg2, memory, broker, server, lib


@pytest.fixture
async def app(cfg):
    parts = await _start(cfg)
    yield parts
    await parts[3].stop()
    await parts[1].close()


def _url(s, p):
    return f"http://127.0.0.1:{s.port}{p}"


def _h():
    return {"X-Telegram-Init-Data": make_init_data()}


async def _mk_item(app):
    cfg2, _, _, _, lib = app
    f = Path(cfg2.workspace_dir) / "doc.txt"
    f.write_text("hello", encoding="utf-8")
    item = await lib.index_file(f)
    assert item is not None
    return item["id"]


async def test_state_has_library_and_ideas_auto(app):
    _, _, _, server, _ = app
    await _mk_item(app)
    async with ClientSession() as s:
        async with s.get(_url(server, "/api/state"), headers=_h()) as r:
            data = await r.json()
    assert len(data["library"]) == 1
    assert data["library"][0]["title"]
    ids = [it["id"] for it in data["schedule"]["items"]]
    assert "ideas_auto" in ids
    assert "heartbeat" in ids


async def test_rename_accepts_name_and_title(app):
    _, _, _, server, _ = app
    item_id = await _mk_item(app)
    async with ClientSession() as s:
        async with s.post(_url(server, f"/api/library/items/{item_id}/rename"),
                          headers=_h(), json={"title": "Ten cu"}) as r:
            assert (await r.json())["ok"] is True
        async with s.post(_url(server, f"/api/library/items/{item_id}/rename"),
                          headers=_h(), json={"name": "Ten moi"}) as r:
            assert (await r.json())["ok"] is True


async def test_unshare_trash_restore_routes(app):
    _, _, _, server, lib = app
    item_id = await _mk_item(app)
    async with ClientSession() as s:
        async with s.post(_url(server, f"/api/library/items/{item_id}/share"),
                          headers=_h(), json={}) as r:
            shared = await r.json()
        # share có thể bị chặn theo path test, nhưng unshare phải
        # trả ok (idempotent khi không có link hiệu lực).
        async with s.post(_url(server, f"/api/library/items/{item_id}/unshare"),
                          headers=_h(), json={}) as r:
            assert (await r.json())["ok"] is True
        async with s.post(_url(server, f"/api/library/items/{item_id}/trash"),
                          headers=_h(), json={}) as r:
            assert (await r.json())["ok"] is True
        async with s.get(_url(server, "/api/library/items?status=trashed"),
                         headers=_h()) as r:
            body = await r.json()
            assert any(it["id"] == item_id for it in body["items"])
        async with s.post(_url(server, f"/api/library/items/{item_id}/restore"),
                          headers=_h(), json={}) as r:
            assert (await r.json())["ok"] is True


def test_hidden_commands_now_in_menu():
    names = {c for c, _ in BOT_COMMANDS}
    assert {"feed_now", "pin_item", "rename_item"} <= names


async def test_google_revoke_called_before_disconnect(cfg):
    calls = []

    async def fake_transport(method, url, params=None, json_body=None,
                             headers=None):
        calls.append((method, url, params))
        return 200, {}

    vault = VaultStore(cfg.vault_path)
    vault.put("google:refresh_token", "RT-TEST")
    auth = GoogleAuth(cfg, vault, transport=fake_transport)
    assert await auth.revoke() is True
    assert calls and calls[0][1] == "https://oauth2.googleapis.com/revoke"
    assert calls[0][2] == {"token": "RT-TEST"}
