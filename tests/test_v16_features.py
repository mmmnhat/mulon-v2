"""Bộ kiểm thử cho các tính năng phiên bản 1.6:
1. Action-level Connector Policy (quyền chi tiết từng hành động).
2. Thẻ nhập bí mật Vault an toàn tương tác trong chat (request_vault_secret).
3. Cài đặt MCP 1-Click từ Mini App (bỏ qua thẻ duyệt kép).
4. Thư viện Artifacts + Link chia sẻ thật công khai (/share/{token}).
5. Ghim (pin) và đổi tên (rename) tài liệu trong Thư viện.
"""

import dataclasses
import json
from pathlib import Path
import pytest
from aiohttp.test_utils import TestClient, TestServer
from aiohttp import web

from mulon.policy import PolicyEngine, VERDICT_ALLOW, VERDICT_ASK, VERDICT_DENY
from mulon.vault import register_vault_tools, VaultStore
from mulon.tools import ToolRegistry
from mulon.library import LibraryService
from mulon.webapp_server import WebAppServer
from mulon.marketplace import MarketplaceService
from mulon.approvals import ApprovalBroker
from tests.test_v13_service import FakeMCP, write_bundle, listing
from tests.conftest import open_memory


# ---------------- 1. Action-Level Connector Policy ----------------
def test_action_level_policy_hierarchy(tmp_path):
    policy_file = tmp_path / "policy.json"
    engine = PolicyEngine(policy_file)

    # Mặc định theo CONNECTOR_ACTION_DEFAULTS
    dec_send = engine.decide("", "connector:gmail:send")
    assert dec_send.verdict == VERDICT_ASK

    dec_search = engine.decide("", "connector:gmail:search")
    assert dec_search.verdict == VERDICT_ALLOW

    dec_cal_create = engine.decide("", "connector:gcalendar:create_event")
    assert dec_cal_create.verdict == VERDICT_ASK

    dec_cal_list = engine.decide("", "connector:gcalendar:list_events")
    assert dec_cal_list.verdict == VERDICT_ALLOW

    # Ghi đè cấp hành động cụ thể
    engine.set_host_rule("group", "connector:gmail:send", VERDICT_ALLOW)
    assert engine.decide("", "connector:gmail:send").verdict == VERDICT_ALLOW

    # Hành động khác vẫn giữ nguyên
    assert engine.decide("", "connector:gcalendar:create_event").verdict == VERDICT_ASK

    # Ghi đè cấp connector chung: nếu hành động chưa có rule riêng, nhận theo connector chung
    engine.set_host_rule("group", "connector:gcalendar", VERDICT_DENY)
    assert engine.decide("", "connector:gcalendar:delete_event").verdict == VERDICT_DENY


# ---------------- 2. In-Chat Interactive Vault Cards ----------------
async def test_request_vault_secret_tool(cfg):
    reg = ToolRegistry()
    cfg_test = dataclasses.replace(
        cfg,
        webapp_url="https://bot.example.com",
        webapp_app_name="app",
    )
    object.__setattr__(cfg_test, "_bot_username", "Mulon_bot")

    notified = []

    def fake_notifier(info):
        notified.append(info)

    register_vault_tools(reg, cfg_test, notifier=fake_notifier)

    tool = reg.get("request_vault_secret")
    assert tool is not None

    res = await tool.handler(label="google:client_id", description="Nhập Client ID Google")
    assert res["ok"] is True
    assert res["label"] == "google:client_id"
    assert res["card_sent"] is True
    assert "startapp=vault_google__client_id" in res["direct_url"]

    assert len(notified) == 1
    assert notified[0]["startapp_param"] == "vault_google__client_id"
    assert notified[0]["description"] == "Nhập Client ID Google"


# ---------------- 3. One-Click MCP Install from Mini App ----------------
async def test_install_one_click_bypass_approvals(tmp_path, cfg):
    pe = PolicyEngine(tmp_path / "policy.json")
    broker = ApprovalBroker(policy=pe)
    vault = VaultStore(tmp_path / "vault.json")
    mcp = FakeMCP()

    curated_path = tmp_path / "curated.json"
    catalog_path = tmp_path / "catalog.json"
    mcp_file = tmp_path / "mcp_servers.json"
    mcp_file.write_text(json.dumps({"servers": []}), encoding="utf-8")
    write_bundle(curated_path, [listing("mytool")])

    cfg_mkt = dataclasses.replace(
        cfg,
        mcp_config_path=mcp_file,
        marketplace_store_path=tmp_path / "mkt.json",
        marketplace_curated_path=curated_path,
        marketplace_catalog_path=catalog_path,
    )

    mkt = MarketplaceService(
        cfg_mkt,
        policy=pe,
        broker=broker,
        vault_store=vault,
        mcp_manager=mcp,
    )

    # Chuẩn bị một install draft từ catalog
    op = mkt.prepare_install(
        {"kind": "catalog", "provider_id": "mulon-curated", "slug": "mytool"}
    )
    assert op["stage"] == "awaiting_probe_approval"

    # One-click install: probe -> commit tự động không cần tạo thẻ broker
    done_op = await mkt.install_one_click(op["id"])
    assert done_op["stage"] == "pending_restart"
    assert done_op["local_name"] == "mytool"


# ---------------- 4. Library Sharing & Public Route ----------------
async def test_library_share_and_public_viewer(cfg):
    cfg_test = dataclasses.replace(
        cfg,
        webapp_url="https://bot.example.com",
    )
    memory = await open_memory(cfg_test)

    lib = LibraryService(cfg_test, memory)
    doc_path = cfg_test.workspace_dir / "test_report.md"
    doc_path.write_text("# Báo cáo tiến độ 1.6\nMọi thứ chạy rất mượt mà.", encoding="utf-8")

    item = await lib.index_file(doc_path)
    assert item is not None

    # Chia sẻ tạo token thật và link công khai
    shared = await lib.share_item(item["id"], hours=24)
    assert shared["ok"] is True
    assert shared["share_status"] == "active"
    token = shared["share_token"]
    assert token != ""
    assert shared["url"] == f"https://bot.example.com/share/{token}"

    # Kiểm tra routing của WebAppServer
    server = WebAppServer(
        cfg=cfg_test,
        memory=memory,
        registry=ToolRegistry(),
        connectors=None,
        broker=None,
        mcp_manager=None,
        vault_store=None,
        policy=PolicyEngine(cfg_test.policy_path),
        library=lib,
    )
    app = server.build_app()
    client = TestClient(TestServer(app))
    await client.start_server()

    try:
        # Truy cập công khai không cần Telegram initData
        resp = await client.get(f"/share/{token}")
        assert resp.status == 200
        html_text = await resp.text()
        assert "test_report.md" in html_text
        assert "Báo cáo tiến độ 1.6" in html_text
        assert "Sao chép" in html_text

        # Token không tồn tại
        resp_bad = await client.get("/share/non_existent_token_1234")
        assert resp_bad.status == 404
    finally:
        await client.close()
        await memory.close()


# ---------------- 5. Library Pin & Rename ----------------
async def test_library_pin_and_rename(cfg):
    memory = await open_memory(cfg)
    lib = LibraryService(cfg, memory)

    f1 = cfg.workspace_dir / "doc1.md"
    f1.write_text("doc 1", encoding="utf-8")
    it1 = await lib.index_file(f1)

    f2 = cfg.workspace_dir / "doc2.md"
    f2.write_text("doc 2", encoding="utf-8")
    it2 = await lib.index_file(f2)

    # Ghim it1
    res_pin = await lib.pin_item(it1["id"], True)
    assert res_pin["ok"] is True
    assert res_pin["pinned"] == 1

    # it1 phải đứng đầu danh sách
    items = await lib.list_items()
    assert items[0]["id"] == it1["id"]

    # Đổi tên it2
    res_ren = await lib.rename_item(it2["id"], "Tài liệu số 2 mới")
    assert res_ren["ok"] is True
    assert res_ren["title"] == "Tài liệu số 2 mới"
    assert res_ren["name"] == "Tài liệu số 2 mới"

    items_after = await lib.list_items()
    it2_updated = next(x for x in items_after if x["id"] == it2["id"])
    assert it2_updated["name"] == "Tài liệu số 2 mới"

    await memory.close()
