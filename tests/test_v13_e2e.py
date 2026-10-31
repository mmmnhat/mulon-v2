"""1.3.0 kiểm đầu-cuối THẬT (spec marketplace mục 13.4 + hợp
đồng build): một MCP stdio server vô hại (tests/mcp_echo_server)
đi trọn đường import -> probe -> duyệt 2 lần -> commit ->
(restart mô phỏng) boot gate -> đăng ký tool đúng tên -> gọi
được tool. Thêm case cấu hình bị phá sau commit để rollback tự
kích hoạt ở lần boot mô phỏng."""

import asyncio
import json
import sys
from dataclasses import replace
from pathlib import Path

import pytest

from mulon.approvals import ApprovalBroker
from mulon.marketplace import MarketplaceService
from mulon.mcp_client import MCPManager
from mulon.policy import PolicyEngine
from mulon.tools import ToolRegistry
from mulon.vault import VaultStore
from tests.test_v13_service import until

ECHO_SERVER = Path(__file__).with_name("mcp_echo_server.py")


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
    return cfg2


def make_stack(cfg2):
    policy = PolicyEngine(cfg2.policy_path)
    broker = ApprovalBroker(policy=policy, timeout_s=10)
    vault = VaultStore(cfg2.vault_path)
    manager = MCPManager(cfg2, cfg2.mcp_config_path)
    svc = MarketplaceService(
        cfg2, policy=policy, broker=broker, vault_store=vault,
        mcp_manager=manager, restarter=lambda: None)
    return svc, policy, broker, manager


async def install_echo(svc, broker):
    text = json.dumps({"mcpServers": {"echo": {
        "command": sys.executable, "args": [str(ECHO_SERVER)]}}})
    parsed = svc.parse_import(text=text)
    assert parsed["ok"] is True
    op = svc.prepare_install({"draft_id": parsed["draft_id"]})
    op_id = op["id"]
    req = svc.request_stage_approval(op_id, "probe")
    broker.resolve(req["approval_id"], True)
    assert await until(lambda: svc.store.get_operation(op_id)
                       ["stage"] == "awaiting_commit_approval")
    req = svc.request_stage_approval(op_id, "commit")
    broker.resolve(req["approval_id"], True)
    assert await until(lambda: svc.store.get_operation(op_id)
                       ["stage"] == "pending_restart")
    return op_id


@pytest.mark.asyncio
async def test_end_to_end_import_install_boot_register(env13):
    svc, policy, broker, _manager = make_stack(env13)
    op_id = await install_echo(svc, broker)
    probe = svc.store.get_operation(op_id)["probe_result"]
    assert {t["name"] for t in probe["tools"]} == {"echo", "add"}

    # --- mô phỏng restart: manager + service mới trên cùng dữ
    # kiện bền; boot gate chạy giữa start() và register_into().
    svc2, _p2, _b2, manager2 = make_stack(env13)
    await manager2.start()
    excluded = await svc2.boot_gate()
    assert excluded == set()
    record = svc2.store.get_installed("echo")
    assert record["lifecycle_state"] == "active"
    assert svc2.store.get_operation(op_id)["stage"] == "done"
    registry = ToolRegistry()
    registered = manager2.register_into(registry, exclude=excluded)
    assert "mcp_echo_echo" in registered
    assert "mcp_echo_add" in registered
    tool = registry.get("mcp_echo_echo")
    assert tool.group == "mcp:echo"
    result = await manager2.call_tool("echo", "echo",
                                      {"text": "xin chào"})
    assert "xin chào" in str(result)
    await manager2.close()


@pytest.mark.asyncio
async def test_broken_config_after_commit_auto_rolls_back(env13):
    svc, policy, broker, _manager = make_stack(env13)
    await install_echo(svc, broker)
    # Phá entry sau commit (đổi command sang thứ không tồn tại)
    # trước lần boot áp dụng.
    data = json.loads(Path(env13.mcp_config_path).read_text(encoding="utf-8"))
    for entry in data["servers"]:
        if entry["name"] == "echo":
            entry["command"] = "/khong/ton/tai/server"
    Path(env13.mcp_config_path).write_text(json.dumps(data), encoding="utf-8")
    svc2, _p2, _b2, manager2 = make_stack(env13)
    await manager2.start()
    excluded = await svc2.boot_gate()
    # Đối chiếu thất bại -> tự rollback: entry bị gỡ, record mất,
    # chờ restart lần 2 để hoàn tất khôi phục.
    data = json.loads(Path(env13.mcp_config_path).read_text(encoding="utf-8"))
    assert [e["name"] for e in data["servers"]] == ["manual-one"]
    assert svc2.store.get_installed("echo") is None
    pending = svc2.store.restart_pending()
    assert pending["kind"] == "rollback"
    assert svc2._boot_needs_restart is True
    # Đọc bằng engine mới (tiến trình thật chỉ có 1 instance).
    fresh_policy = PolicyEngine(env13.policy_path)
    assert fresh_policy.get_host_verdict(
        "group", "mcp:echo") is None
    await manager2.close()
    # Boot lần 2: quyết toán khôi phục xong, không restart nữa.
    svc3, _p3, _b3, manager3 = make_stack(env13)
    await manager3.start()
    await svc3.boot_gate()
    assert svc3.store.restart_pending() is None
    assert svc3._boot_needs_restart is False
    await manager3.close()
