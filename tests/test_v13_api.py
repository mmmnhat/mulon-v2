"""1.3.0: API /api/marketplace/* của Mini App — auth initData
owner-only như mọi /api/*, không lộ giá trị Vault trong bất kỳ
response nào, prepare theo Idempotency-Key không tạo 2 operation,
toggle connector của server managed route qua MarketplaceService
(spec marketplace mục 11)."""

import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest
from aiohttp import ClientSession

from mulon.approvals import ApprovalBroker
from mulon.connectors import build_default_connectors
from mulon.context import Dossier
from mulon.marketplace import MarketplaceService
from mulon.policy import PolicyEngine
from mulon.tools import build_default_registry
from mulon.vault import VaultStore
from mulon.webapp_server import WebAppServer
from tests.conftest import open_memory
from tests.test_v12_webapp_auth import TOKEN, OWNER, make_init_data
from tests.test_v13_service import FakeMCP, listing, write_bundle

SENTINEL = "GIA-TRI-VAULT-KHONG-DUOC-LO-456"


@pytest.fixture
async def app13(cfg, tmp_path):
    mcp_file = tmp_path / "mcp_servers.json"
    mcp_file.write_text(json.dumps({"servers": []}),
                        encoding="utf-8")
    cfg2 = replace(
        cfg, **{"telegram_bot_token": TOKEN},
        allowed_user_id=OWNER,
        webapp_port=0, mcp_config_path=mcp_file,
        marketplace_store_path=tmp_path / "marketplace.json",
        marketplace_curated_path=tmp_path / "curated.json",
        marketplace_catalog_path=tmp_path / "catalog_dl.json")
    write_bundle(cfg2.marketplace_curated_path, [listing()])
    memory = await open_memory(cfg2)
    policy = PolicyEngine(cfg2.policy_path, memory=memory)
    broker = ApprovalBroker(policy=policy, timeout_s=30)
    vault = VaultStore(cfg2.vault_path)
    ref = vault.put("api-key", SENTINEL)
    fake_mcp = FakeMCP()
    fake_mcp.config_path = cfg2.mcp_config_path
    svc = MarketplaceService(
        cfg2, policy=policy, broker=broker, vault_store=vault,
        mcp_manager=fake_mcp)
    server = WebAppServer(
        cfg2, memory=memory, policy=policy, broker=broker,
        connectors=build_default_connectors(cfg2),
        mcp_manager=fake_mcp,
        vault_store=vault,
        registry=build_default_registry(cfg2, memory),
        dossier=Dossier.load(cfg2.dossier_dir), skills=None,
        marketplace=svc)
    assert await server.start()
    yield cfg2, memory, broker, server, svc, ref
    await server.stop()
    await memory.close()


def _url(server, path):
    return f"http://127.0.0.1:{server.port}{path}"


def _h():
    return {"X-Telegram-Init-Data": make_init_data()}


async def test_marketplace_requires_owner_initdata(app13):
    *_, server, _svc, _ref = app13
    async with ClientSession() as s:
        async with s.get(_url(server, "/api/marketplace/summary")) \
                as r:
            assert r.status == 403
        async with s.get(_url(server, "/api/marketplace/catalog"),
                         headers={"X-Telegram-Init-Data": "gia"}) \
                as r:
            assert r.status == 403


async def test_catalog_and_listing_detail(app13):
    *_, server, _svc, _ref = app13
    async with ClientSession() as s:
        async with s.get(_url(server, "/api/marketplace/catalog"),
                         headers=_h()) as r:
            assert r.status == 200
            data = await r.json()
        assert data["items"][0]["slug"] == "echo-test"
        assert data["items"][0]["pricing"]["label"] == "Miễn phí"
        async with s.get(_url(
                server,
                "/api/marketplace/listings/mulon-curated/echo-test"),
                headers=_h()) as r:
            detail = (await r.json())["listing"]
        assert detail["manifest"]["command"] == sys.executable
        assert detail["security"]["score"] == 9.0


async def test_import_parse_errors_carry_codes(app13):
    *_, server, _svc, _ref = app13
    payload = {"text": json.dumps({"mcpServers": {"s": {
        "command": "python3", "env": {"API_KEY": SENTINEL}}}})}
    async with ClientSession() as s:
        async with s.post(_url(server,
                               "/api/marketplace/import/parse"),
                          headers=_h(), json=payload) as r:
            assert r.status == 400
            body = await r.json()
            text = await r.text()
    assert body["code"] == "secret_literal_rejected"
    assert SENTINEL not in text


async def test_prepare_idempotent_and_no_secret_leak(app13):
    *_, server, _svc, ref = app13
    headers = {**_h(), "Idempotency-Key": "req-1"}
    body = {"provider_id": "mulon-curated", "slug": "echo-test"}
    async with ClientSession() as s:
        async with s.post(_url(server,
                               "/api/marketplace/install/prepare"),
                          headers=headers, json=body) as r:
            first = await r.json()
        async with s.post(_url(server,
                               "/api/marketplace/install/prepare"),
                          headers=headers, json=body) as r:
            second = await r.json()
            raw = await r.text()
    assert first["operation"]["id"] == second["operation"]["id"]
    assert SENTINEL not in raw
    # Gắn Vault ref qua API: chỉ ref đi qua, giá trị không trở lại.
    op_id = first["operation"]["id"]
    svc = _svc
    assert svc.store.get_operation(op_id) is not None


async def test_state_has_marketplace_summary(app13):
    *_, server, _svc, _ref = app13
    async with ClientSession() as s:
        async with s.get(_url(server, "/api/state"),
                         headers=_h()) as r:
            data = await r.json()
    assert data["marketplace_summary"]["installed_count"] == 0
    assert data["marketplace_summary"]["catalog"]["provider_id"] \
        == "mulon-curated"


async def test_connector_toggle_routes_to_service(app13):
    cfg2, _memory, _broker, server, svc, _ref = app13
    # Gắn 1 record managed + entry tương ứng.
    from mulon.marketplace import config_fingerprint
    entry = {"name": "echo-test", "command": sys.executable,
             "args": ["-m", "echo_server"], "enabled": True}
    record = {
        "local_name": "echo-test",
        "canonical_id": "mulon-curated:echo-test",
        "provider_id": "mulon-curated", "slug": "echo-test",
        "name": "Server echo-test", "desired_state": "enabled",
        "lifecycle_state": "active", "health_state": "healthy",
        "config_fingerprint": config_fingerprint(entry),
        "approved_tool_fingerprint": "x", "tool_count": 2,
        "policy": {"group": "mcp:echo-test",
                   "managed_verdict": "ask",
                   "origin": "marketplace_default"},
        "bindings": [], "manifest_fingerprint": "m",
        "installed_revision": "1", "available_revision": None,
        "source_kind": "mulon-curated", "source_url": None,
        "health_detail": "", "health_checked_at": None,
        "created_at": "t", "updated_at": "t"}
    svc.store.put_installed(record)
    Path(cfg2.mcp_config_path).write_text(
        json.dumps({"servers": [entry]}), encoding="utf-8")
    async with ClientSession() as s:
        async with s.post(_url(server, "/api/connector"),
                          headers=_h(),
                          json={"name": "mcp:echo-test",
                                "enabled": False}) as r:
            body = await r.json()
    assert body["ok"] is True
    assert body["operation_id"]
    # Qua service: policy group bị deny ngay, entry enabled=false.
    assert svc.policy.get_host_verdict(
        "group", "mcp:echo-test") == "deny"
    data = json.loads(Path(cfg2.mcp_config_path).read_text(encoding="utf-8"))
    assert data["servers"][0]["enabled"] is False
