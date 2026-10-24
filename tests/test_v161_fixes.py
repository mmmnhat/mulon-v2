"""Kiểm thử cho các sửa 1.6.1 (audit trước 1.6).

1. "Duyệt và nhớ" ghi theo group, không theo tool connector_call.
2. VaultStore.put khử trùng theo label.
3. Library unshare + get_item_by_token chỉ chấp nhận share_status=active.
"""

import asyncio
import dataclasses

import pytest

from mulon.approvals import ApprovalBroker, approval_scope
from mulon.policy import PolicyEngine, VERDICT_ALLOW, VERDICT_ASK
from mulon.vault import VaultStore, register_vault_tools
from mulon.tools import ToolRegistry
from mulon.library import LibraryService
from tests.conftest import open_memory


async def _remember_flow(policy):
    broker = ApprovalBroker(policy=policy)
    payload = {
        "tool": "connector_call",
        "group": "connector:gmail:send",
        "summary": "send",
    }
    broker.open("abc123", payload)

    async def _decide():
        await asyncio.sleep(0)
        broker.resolve("abc123", True, remember=True)

    task = asyncio.create_task(_decide())
    record = await broker.wait("abc123")
    await task
    return record


async def test_remember_records_group_not_tool(tmp_path):
    policy = PolicyEngine(tmp_path / "policy.json")
    # Trước sửa: gmail:send = ask.
    assert policy.decide("connector_call", "connector:gmail:send").verdict == VERDICT_ASK
    record = await _remember_flow(policy)
    assert record["approved"] is True
    assert record["remember"] is True
    # Sau nhớ: chỉ đúng action đó được allow.
    assert policy.decide("connector_call", "connector:gmail:send").verdict == VERDICT_ALLOW
    # Action khác vẫn ask — đây chính là lỗi cũ (trước đây cả hai đều allow
    # vì rule session-tool "connector_call" thắng action-default).
    assert policy.decide("connector_call", "connector:gcalendar:delete_event").verdict == VERDICT_ASK
    assert policy.decide("connector_call", "connector:gmail:search").verdict == VERDICT_ALLOW


def test_approval_scope_says_group():
    scope = approval_scope({"tool": "connector_call", "group": "connector:gmail:send"})
    assert "connector:gmail:send" in scope["remember"]


def test_vault_put_dedupes_by_label(tmp_path):
    store = VaultStore(tmp_path / "vault.json")
    store.put("google:client_secret", "ban-cu-sai")
    store.put("google:client_secret", "ban-moi-dung")
    labels = store.labels()
    assert len(labels) == 1
    assert labels[0]["label"] == "google:client_secret"
    assert store.resolve(labels[0]["ref"]) == "ban-moi-dung"


async def test_request_vault_secret_no_notifier_is_not_ok(cfg):
    reg = ToolRegistry()
    register_vault_tools(reg, cfg, notifier=None)
    tool = reg.get("request_vault_secret")
    res = await tool.handler(label="test:key", description="test")
    assert res["card_sent"] is False
    assert res["ok"] is False


async def test_request_vault_secret_notifier_false_is_not_sent(cfg):
    reg = ToolRegistry()

    def failing_notifier(info):
        return False

    register_vault_tools(reg, cfg, notifier=failing_notifier)
    tool = reg.get("request_vault_secret")
    res = await tool.handler(label="test:key", description="test")
    assert res["card_sent"] is False
    assert res["ok"] is False


async def test_library_unshare_revokes_link(cfg):
    memory = await open_memory(cfg)
    lib = LibraryService(cfg, memory)
    doc_path = cfg.workspace_dir / "doc.md"
    doc_path.write_text("# Doc\nNội dung.", encoding="utf-8")
    # scan() lập chỉ mục file trong workspace; lấy item vừa scan.
    await lib.scan()
    items = await lib.list_items()
    assert items, "scan phải thấy doc.md trong workspace"
    item = items[0]
    shared = await lib.share_item(item["id"], hours=1, base_url="https://bot.example.com")
    assert shared["ok"] is True
    assert shared["share_status"] == "active"
    token = shared["share_token"]
    got = await lib.get_item_by_token(token)
    assert got["ok"] is True
    revoked = await lib.unshare_item(item["id"])
    assert revoked["ok"] is True
    assert revoked["share_status"] == "revoked"
    gone = await lib.get_item_by_token(token)
    assert gone["ok"] is False
