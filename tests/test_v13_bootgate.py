"""1.3.0: boot gate + reconciliation + tự rollback + catalog tự
cập nhật (spec marketplace mục 9.7, 10.4, 10.6 + quyết định
owner: bot tự restart, tự khôi phục cấu hình khi áp dụng lỗi,
catalog chỉ cập nhật dữ kiện — không bao giờ tự cài)."""

import json
from dataclasses import replace
from pathlib import Path

import pytest

from mulon.approvals import ApprovalBroker
from mulon.marketplace import MarketplaceService, tool_fingerprint
from mulon.marketplace_providers import bundle_content_hash
from mulon.policy import PolicyEngine
from mulon.vault import VaultStore
from tests.test_v13_service import ECHO_TOOLS, FakeMCP, listing, \
    write_bundle


class BootMCP(FakeMCP):
    """FakeMCP + snapshot tool như manager sau khi start()."""

    def __init__(self, snapshot=None, **kw):
        super().__init__(**kw)
        self._snapshot = snapshot or {}

    def tool_snapshot(self):
        return self._snapshot


@pytest.fixture
def env13(cfg, tmp_path):
    mcp_file = tmp_path / "mcp_servers.json"
    mcp_file.write_text(json.dumps({"servers": [
        {"name": "manual-one", "command": "python3",
         "args": ["-m", "old"], "enabled": False}]}),
        encoding="utf-8")
    cfg2 = replace(
        cfg, mcp_config_path=mcp_file,
        marketplace_store_path=tmp_path / "marketplace.json",
        marketplace_curated_path=tmp_path / "curated.json",
        marketplace_catalog_path=tmp_path / "catalog_dl.json")
    write_bundle(cfg2.marketplace_curated_path, [listing()])
    policy = PolicyEngine(cfg2.policy_path)
    broker = ApprovalBroker(policy=policy, timeout_s=5)
    vault = VaultStore(cfg2.vault_path)
    entry = {"name": "echo-test", "command": "python3",
             "args": ["-m", "echo_server"], "enabled": True,
             "timeout_s": 20, "call_timeout_s": 60}
    from mulon.marketplace import config_fingerprint
    record = {
        "local_name": "echo-test",
        "canonical_id": "mulon-curated:echo-test",
        "provider_id": "mulon-curated", "slug": "echo-test",
        "name": "Server echo-test", "source_kind": "mulon-curated",
        "source_url": None, "desired_state": "enabled",
        "lifecycle_state": "pending_restart",
        "health_state": "unknown", "health_detail": "",
        "health_checked_at": None,
        "manifest_fingerprint": "mf",
        "config_fingerprint": config_fingerprint(entry),
        "approved_tool_fingerprint": tool_fingerprint(ECHO_TOOLS),
        "tool_count": 2,
        "policy": {"group": "mcp:echo-test",
                   "managed_verdict": "ask",
                   "origin": "marketplace_default"},
        "bindings": [], "installed_revision": "2026.10.24-1",
        "available_revision": None,
        "rollback_snapshot": {
            "local_name": "echo-test", "previous_entry": None,
            "previous_policy_verdict": None,
            "previous_installed": None},
        "created_at": "2026-10-24T00:00:00+00:00",
        "updated_at": "2026-10-24T00:00:00+00:00",
    }
    svc = MarketplaceService(
        cfg2, policy=policy, broker=broker, vault_store=vault,
        mcp_manager=BootMCP(snapshot={"echo-test": ECHO_TOOLS}))
    svc.store.put_installed(record)
    svc.store.put_operation({
        "id": "op_boot", "type": "install",
        "stage": "pending_restart", "local_name": "echo-test",
        "subject_name": "Server echo-test", "plan": {},
        "plan_fingerprint": "", "probe_result": None,
        "probe_plan_fingerprint": "", "approvals": [],
        "error": None, "last_note": "",
        "created_at": "2026-10-24T00:00:00+00:00",
        "created_ts": 0, "updated_at": "2026-10-24T00:00:00+00:00",
        "expires_at": "2026-10-24T00:00:00+00:00", "journal": []})
    svc.store.set_restart_pending({
        "operation_id": "op_boot", "generation": 1,
        "kind": "install", "local_names": ["echo-test"],
        "rollback_attempted": False, "at": "2026-10-24"})
    # Entry đã được commit vào file từ tiến trình trước.
    data = json.loads(mcp_file.read_text())
    data["servers"].append(entry)
    mcp_file.write_text(json.dumps(data), encoding="utf-8")
    return cfg2, svc


async def test_boot_gate_activates_matching_server(env13):
    cfg2, svc = env13
    excluded = await svc.boot_gate()
    assert excluded == set()
    record = svc.store.get_installed("echo-test")
    assert record["lifecycle_state"] == "active"
    assert record["health_state"] == "healthy"
    assert svc.store.get_operation("op_boot")["stage"] == "done"
    assert svc.store.restart_pending() is None
    notes = svc.store.pop_notifications()
    assert any("echo-test" in n["text"] for n in notes)


async def test_boot_gate_blocks_tool_drift(env13):
    cfg2, svc = env13
    drifted = [dict(ECHO_TOOLS[0], description="đã bị sửa"),
               ECHO_TOOLS[1]]
    svc.mcp._snapshot = {"echo-test": drifted}
    # Tiến trình này không có restart pending: chỉ xét gate.
    svc.store.set_restart_pending(None)
    excluded = await svc.boot_gate()
    assert excluded == {"echo-test"}
    record = svc.store.get_installed("echo-test")
    assert record["health_state"] == "blocked_tool_drift"


async def test_boot_gate_blocks_config_drift(env13):
    cfg2, svc = env13
    data = json.loads(Path(cfg2.mcp_config_path).read_text())
    for e in data["servers"]:
        if e["name"] == "echo-test":
            e["args"] = ["-m", "server_khac"]
    Path(cfg2.mcp_config_path).write_text(json.dumps(data))
    svc.store.set_restart_pending(None)
    excluded = await svc.boot_gate()
    assert excluded == {"echo-test"}
    record = svc.store.get_installed("echo-test")
    assert record["lifecycle_state"] == "config_drift"


async def test_boot_apply_failure_auto_rollback(env13):
    cfg2, svc = env13
    # Áp dụng thất bại: server không nối được lúc boot (snapshot
    # rỗng) -> reconciliation tự rollback cấu hình trước đó.
    svc.mcp._snapshot = {}
    await svc.boot_gate()
    # Entry bị gỡ khỏi file, record biến mất (trạng thái trước đó
    # là chưa cài), policy rule bị dọn.
    data = json.loads(Path(cfg2.mcp_config_path).read_text())
    assert [e["name"] for e in data["servers"]] == ["manual-one"]
    assert svc.store.get_installed("echo-test") is None
    pending = svc.store.restart_pending()
    assert pending["kind"] == "rollback"
    assert pending["rollback_attempted"] is True
    assert svc._boot_needs_restart is True
    op = svc.store.get_operation("op_boot")
    assert op["stage"] == "failed"
    assert op["error"]["code"] == "apply_rolled_back"
    # Boot lần 2 (sau restart khôi phục): quyết toán xong.
    svc2 = MarketplaceService(
        cfg2, policy=svc.policy, broker=svc.broker,
        vault_store=svc.vault,
        mcp_manager=BootMCP(snapshot={}))
    await svc2.boot_gate()
    assert svc2.store.restart_pending() is None
    notes = svc2.store.pop_notifications()
    assert any("khôi phục" in n["text"] for n in notes)


async def test_boot_aborts_stale_operations(env13):
    cfg2, svc = env13
    svc.store.put_operation({
        "id": "op_stale", "type": "install", "stage": "probing",
        "local_name": "x", "subject_name": "x", "plan": {},
        "plan_fingerprint": "", "probe_result": None,
        "probe_plan_fingerprint": "", "approvals": [],
        "error": None, "last_note": "",
        "created_at": "2026-10-24T00:00:00+00:00", "created_ts": 0,
        "updated_at": "2026-10-24T00:00:00+00:00",
        "expires_at": "2026-10-24T00:00:00+00:00", "journal": []})
    svc.store.set_restart_pending(None)
    await svc.boot_gate()
    op = svc.store.get_operation("op_stale")
    assert op["stage"] == "failed"
    assert op["error"]["code"] == "aborted_restart"


# ---------------- catalog tự cập nhật ----------------

def _bundle_bytes(version, listings):
    bundle = {"schema_version": 1, "provider_id": "mulon-curated",
              "bundle_version": version,
              "reviewed_at": "2026-10-25", "listings": listings}
    bundle["content_sha256"] = bundle_content_hash(bundle)
    return json.dumps(bundle, ensure_ascii=False).encode()


async def test_catalog_update_only_data_never_installs(env13):
    cfg2, svc = env13
    new_listing = listing(slug="moi-toanh")

    async def fetcher(url, timeout):
        return _bundle_bytes("2026.10.25-1", [listing(),
                                              new_listing])

    svc._fetcher = fetcher
    result = await svc.maybe_update_catalog(force=True)
    assert result["result"] == "updated"
    slugs = [i["slug"] for i in svc.provider.listings()]
    assert "moi-toanh" in slugs
    # Chỉ dữ kiện: không có server nào bị cài.
    assert svc.store.all_installed().keys() == {"echo-test"}
    assert svc.summary()["installed_count"] == 1


async def test_catalog_update_bad_checksum_keeps_old(env13):
    cfg2, svc = env13
    raw = bytearray(_bundle_bytes("2026.10.25-1", [listing()]))
    # Phá nội dung nhưng giữ nguyên checksum khai báo.
    text = raw.decode().replace("Server echo-test", "Server bi sua")
    svc._fetcher = lambda url, timeout: text.encode()
    result = await svc.maybe_update_catalog(force=True)
    assert result["result"] == "error"
    state = svc.store.catalog_update_state()
    assert state["last_result"] == "error"
    assert not Path(cfg2.marketplace_catalog_path).exists()


async def test_catalog_update_no_change_when_older(env13):
    cfg2, svc = env13

    async def fetcher(url, timeout):
        return _bundle_bytes("2026.10.20-1", [listing()])

    svc._fetcher = fetcher
    result = await svc.maybe_update_catalog(force=True)
    assert result["result"] == "no_change"
