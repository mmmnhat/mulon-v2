"""1.3.0: MarketplaceService — prepare/bind/2 lần duyệt/probe/
commit/rollback/gỡ (spec marketplace mục 8, 9). MCP được thay
bằng FakeMCP xác định; luồng đầu-cuối thật nằm ở test_v13_e2e."""

import asyncio
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from mulon.approvals import ApprovalBroker
from mulon.marketplace import MarketplaceError, MarketplaceService
from mulon.marketplace_providers import bundle_content_hash
from mulon.policy import PolicyEngine
from mulon.vault import VaultStore

ECHO_TOOLS = [
    {"name": "echo", "description": "Trả lại nguyên văn",
     "inputSchema": {"type": "object",
                     "properties": {"text": {"type": "string"}},
                     "required": ["text"]}},
    {"name": "add", "description": "Cộng hai số",
     "inputSchema": {"type": "object",
                     "properties": {"a": {"type": "number"},
                                    "b": {"type": "number"}},
                     "required": ["a", "b"]}},
]


class FakeMCP:
    """Đứng thay MCPManager: probe trả tool cố định, không spawn
    tiến trình. Ghi lại entry đã probe để test soi binding."""

    def __init__(self, tools=None, fail=False):
        self._tools = ECHO_TOOLS if tools is None else tools
        self.fail = fail
        self.resolver = None
        self.probed: list[dict] = []

    def set_secret_resolver(self, fn):
        self.resolver = fn

    async def probe_entry(self, entry, timeout_s=None):
        self.probed.append(entry)
        if self.fail:
            return {"ok": False, "error_code": "probe_failed",
                    "error": "không chạy được", "tools": [],
                    "latency_ms": 1}
        return {"ok": True, "latency_ms": 7, "tools": self._tools,
                "error_code": "", "error": ""}

    def tool_snapshot(self):
        return {}

    def status(self):
        return {}


def write_bundle(path: Path, listings: list[dict],
                 version: str = "2026.10.24-1") -> None:
    bundle = {"schema_version": 1, "provider_id": "mulon-curated",
              "bundle_version": version,
              "reviewed_at": "2026-10-24", "listings": listings}
    bundle["content_sha256"] = bundle_content_hash(bundle)
    path.write_text(json.dumps(bundle, ensure_ascii=False),
                    encoding="utf-8")


def listing(slug="echo-test", score=9.0, critical=0, env=None,
            command=None, args=None):
    return {
        "slug": slug, "name": f"Server {slug}",
        "creator_name": "Mulon tuyển chọn",
        "source_url": "https://example.com/src",
        "summary": "Server kiểm thử.",
        "description": "Mô tả dài.",
        "categories": ["developer-tools"],
        "locality": "local_process", "transport": "stdio",
        "pricing": {"model": "free"},
        "security": {"score": score, "risk_label": "Thấp",
                     "critical_findings_count": critical,
                     "findings": [], "scanned_at": "2026-10-24",
                     "scan_source": "test"},
        "permissions": ["Chạy tiến trình local"],
        "tool_count_known": 2,
        "tool_names_known": ["echo", "add"],
        "install": {"command": command or sys.executable,
                    "args": args or ["-m", "echo_server"],
                    "env": env or {}},
    }


@pytest.fixture
def env13(cfg, tmp_path):
    mcp_file = tmp_path / "mcp_servers.json"
    mcp_file.write_text(json.dumps({
        "_comment": "giữ nguyên trường lạ",
        "servers": [{"name": "manual-one", "command": "python3",
                     "args": ["-m", "old"], "enabled": False,
                     "custom_field": "keep-me"}],
    }), encoding="utf-8")
    cfg2 = replace(
        cfg, mcp_config_path=mcp_file,
        marketplace_store_path=tmp_path / "marketplace.json",
        marketplace_curated_path=tmp_path / "curated.json",
        marketplace_catalog_path=tmp_path / "catalog_dl.json")
    write_bundle(cfg2.marketplace_curated_path,
                 [listing(),
                  listing(slug="needs-key", env={"API_KEY": ""}),
                  listing(slug="low-score", score=5.0),
                  listing(slug="critical-one", critical=1)])
    return cfg2


def make_service(cfg2, mcp=None, restarter=None, fetcher=None):
    policy = PolicyEngine(cfg2.policy_path)
    broker = ApprovalBroker(policy=policy, timeout_s=5)
    vault = VaultStore(cfg2.vault_path)
    svc = MarketplaceService(
        cfg2, policy=policy, broker=broker, vault_store=vault,
        mcp_manager=mcp or FakeMCP(), restarter=restarter,
        fetcher=fetcher)
    return svc, policy, broker, vault


async def until(predicate, timeout=3.0):
    waited = 0.0
    while waited < timeout:
        if predicate():
            return True
        await asyncio.sleep(0.05)
        waited += 0.05
    return predicate()


def stage_of(svc, op_id):
    return svc.store.get_operation(op_id)["stage"]


async def approve_stage(svc, broker, op_id, stage):
    result = svc.request_stage_approval(op_id, stage)
    broker.resolve(result["approval_id"], True)
    return result["approval_id"]


# ---------------- prepare ----------------

async def test_prepare_curated_and_idempotency(env13):
    svc, *_ = make_service(env13)
    op = svc.prepare_install(
        {"provider_id": "mulon-curated", "slug": "echo-test"},
        idempotency_key="k1")
    assert op["stage"] == "awaiting_probe_approval"
    assert op["local_name"] == "echo-test"
    again = svc.prepare_install(
        {"provider_id": "mulon-curated", "slug": "echo-test"},
        idempotency_key="k1")
    assert again["id"] == op["id"]


async def test_prepare_name_collision_and_alias(env13):
    svc, *_ = make_service(env13)
    with pytest.raises(MarketplaceError) as ei:
        svc.prepare_install(
            {"provider_id": "mulon-curated", "slug": "echo-test"},
            alias="manual-one")
    assert ei.value.code == "name_collision"
    op = svc.prepare_install(
        {"provider_id": "mulon-curated", "slug": "echo-test"},
        alias="echo-alias")
    assert op["local_name"] == "echo-alias"


async def test_prepare_security_gates(env13):
    svc, *_ = make_service(env13)
    with pytest.raises(MarketplaceError) as ei:
        svc.prepare_install(
            {"provider_id": "mulon-curated", "slug": "low-score"})
    assert ei.value.code == "security_below_threshold"
    with pytest.raises(MarketplaceError) as ei:
        svc.prepare_install(
            {"provider_id": "mulon-curated", "slug": "critical-one"})
    assert ei.value.code == "security_critical_blocked"


# ---------------- import thủ công ----------------

async def test_parse_import_variants(env13):
    svc, *_ = make_service(env13)
    multi = svc.parse_import(text=json.dumps({"mcpServers": {
        "a": {"command": "python3"}, "b": {"command": "python3"}}}))
    assert multi["ok"] is False
    assert multi["candidates"] == ["a", "b"]
    out = svc.parse_import(text=json.dumps({"mcpServers": {
        "mine": {"command": "python3", "args": ["-m", "x"]}}}))
    assert out["ok"] is True
    assert out["listing"]["provider_id"] == "manual"
    remote = svc.parse_import(
        text=json.dumps({"url": "https://x.test/mcp"}))
    assert remote["support_state"] == "supported"
    assert remote["listing"]["transport"] == "http"


async def test_parse_import_secret_literal_rejected(env13):
    svc, *_ = make_service(env13)
    with pytest.raises(MarketplaceError) as ei:
        svc.parse_import(text=json.dumps({"mcpServers": {
            "s": {"command": "python3",
                  "env": {"API_KEY": "sk-that-must-not-pass"}}}}))
    assert ei.value.code == "secret_literal_rejected"


# ---------------- bind secrets ----------------

async def test_bind_secrets_flow(env13):
    svc, _, _, vault = make_service(env13)
    op = svc.prepare_install(
        {"provider_id": "mulon-curated", "slug": "needs-key"})
    assert op["stage"] == "awaiting_secret"
    with pytest.raises(MarketplaceError) as ei:
        svc.bind_secrets(op["id"], {"API_KEY": "plaintext-value"})
    assert ei.value.code == "secret_literal_rejected"
    with pytest.raises(MarketplaceError) as ei:
        svc.bind_secrets(op["id"], {"API_KEY": "vault:missing"})
    assert ei.value.code == "secret_missing"
    ref = vault.put("api-key-test", "gia-tri-that-123")
    view = svc.bind_secrets(op["id"], {"API_KEY": ref})
    assert view["stage"] == "awaiting_probe_approval"
    assert "gia-tri-that-123" not in json.dumps(
        svc.store.data, ensure_ascii=False)


# ---------------- luồng 2 duyệt trọn gói ----------------

async def test_full_two_approval_install(env13):
    restarts = []
    svc, policy, broker, _ = make_service(
        env13, restarter=lambda: restarts.append(1))
    op = svc.prepare_install(
        {"provider_id": "mulon-curated", "slug": "echo-test"})
    op_id = op["id"]
    # Chưa probe mà xin duyệt commit -> conflict.
    with pytest.raises(MarketplaceError) as ei:
        svc.request_stage_approval(op_id, "commit")
    assert ei.value.code == "operation_conflict"
    await approve_stage(svc, broker, op_id, "probe")
    assert await until(
        lambda: stage_of(svc, op_id) == "awaiting_commit_approval")
    probe = svc.store.get_operation(op_id)["probe_result"]
    assert probe["tool_count"] == 2
    assert probe["tool_fingerprint"]
    await approve_stage(svc, broker, op_id, "commit")
    assert await until(
        lambda: stage_of(svc, op_id) == "pending_restart")
    # File cấu hình: entry mới + entry thủ công nguyên vẹn.
    data = json.loads(Path(env13.mcp_config_path).read_text())
    names = [e["name"] for e in data["servers"]]
    assert "echo-test" in names and "manual-one" in names
    assert data["_comment"] == "giữ nguyên trường lạ"
    manual = next(e for e in data["servers"]
                  if e["name"] == "manual-one")
    assert manual["custom_field"] == "keep-me"
    # Policy: group mcp:echo-test ở nấc ask.
    assert policy.get_host_verdict("group", "mcp:echo-test") == "ask"
    # Bot tự restart được yêu cầu đúng 1 lần + record chờ áp dụng.
    assert restarts == [1]
    record = svc.store.get_installed("echo-test")
    assert record["lifecycle_state"] == "pending_restart"
    assert svc.store.restart_pending()["kind"] == "install"


async def test_probe_failure_and_denial(env13):
    svc, _, broker, _ = make_service(env13, mcp=FakeMCP(fail=True))
    op = svc.prepare_install(
        {"provider_id": "mulon-curated", "slug": "echo-test"})
    await approve_stage(svc, broker, op["id"], "probe")
    assert await until(lambda: stage_of(svc, op["id"]) == "failed")
    assert svc.store.get_operation(op["id"])["error"]["code"] == \
        "probe_failed"

    svc2, _, broker2, _ = make_service(env13)
    op2 = svc2.prepare_install(
        {"provider_id": "mulon-curated", "slug": "echo-test"})
    req = svc2.request_stage_approval(op2["id"], "probe")
    broker2.resolve(req["approval_id"], False)
    assert await until(lambda: stage_of(svc2, op2["id"])
                       == "cancelled")


async def test_commit_failure_rolls_back(env13, monkeypatch):
    svc, policy, broker, _ = make_service(env13)
    op = svc.prepare_install(
        {"provider_id": "mulon-curated", "slug": "echo-test"})
    await approve_stage(svc, broker, op["id"], "probe")
    assert await until(lambda: stage_of(svc, op["id"])
                       == "awaiting_commit_approval")

    original_write = svc._write_entry
    calls = {"n": 0}

    def boom(local_name, entry):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("đĩa đầy")
        return original_write(local_name, entry)

    monkeypatch.setattr(svc, "_write_entry", boom)
    await approve_stage(svc, broker, op["id"], "commit")
    assert await until(lambda: stage_of(svc, op["id"]) == "failed")
    final = svc.store.get_operation(op["id"])
    assert final["error"]["code"] == "commit_failed"
    # Rollback: không entry mới, không rule policy, record giữ.
    data = json.loads(Path(env13.mcp_config_path).read_text())
    assert [e["name"] for e in data["servers"]] == ["manual-one"]
    assert policy.get_host_verdict("group", "mcp:echo-test") is None
    record = svc.store.get_installed("echo-test")
    assert record["lifecycle_state"] == "quarantined"


# ---------------- gỡ ----------------

async def _install_echo(env13):
    svc, policy, broker, vault = make_service(env13)
    op = svc.prepare_install(
        {"provider_id": "mulon-curated", "slug": "echo-test"})
    await approve_stage(svc, broker, op["id"], "probe")
    assert await until(lambda: stage_of(svc, op["id"])
                       == "awaiting_commit_approval")
    await approve_stage(svc, broker, op["id"], "commit")
    assert await until(lambda: stage_of(svc, op["id"])
                       == "pending_restart")
    record = svc.store.get_installed("echo-test")
    record["lifecycle_state"] = "active"
    svc.store.put_installed(record)
    svc.store.set_restart_pending(None)
    return svc, policy, broker, vault


async def test_uninstall_flow_blocks_then_removes(env13):
    svc, policy, broker, _ = await _install_echo(env13)
    op = svc.prepare_uninstall("echo-test")
    assert op["stage"] == "awaiting_commit_approval"
    await approve_stage(svc, broker, op["id"], "commit")
    assert await until(lambda: stage_of(svc, op["id"])
                       == "pending_restart")
    # Tool bị chặn ngay bằng policy deny + entry đã khỏi file.
    assert policy.get_host_verdict("group", "mcp:echo-test") == \
        "deny"
    data = json.loads(Path(env13.mcp_config_path).read_text())
    assert [e["name"] for e in data["servers"]] == ["manual-one"]
    record = svc.store.get_installed("echo-test")
    assert record["lifecycle_state"] == "uninstall_pending_restart"
