"""1.2.0 Khối 2: ApprovalBroker — resolve/timeout/remember + tóm
tắt args an toàn (che khóa nhạy cảm)."""

import asyncio

from mulon.approvals import ApprovalBroker, summarize_args
from mulon.policy import PolicyEngine


def _payload(tool="run_command"):
    return {"approval_id": "x", "tool": tool, "group": "shell",
            "summary": "cmd=ls", "session_key": "sk", "task_id": "t1"}


async def test_resolve_approve():
    broker = ApprovalBroker(timeout_s=5)
    broker.open("a1", _payload())
    assert broker.is_pending("a1")
    assert broker.resolve("a1", True) is True
    record = await broker.wait("a1")
    assert record["approved"] is True and record["outcome"] == "approved"
    assert not broker.is_pending("a1")
    assert broker.recent()[0]["outcome"] == "approved"


async def test_resolve_deny_and_double_resolve():
    broker = ApprovalBroker(timeout_s=5)
    broker.open("a2", _payload())
    assert broker.resolve("a2", False) is True
    record = await broker.wait("a2")
    assert record["approved"] is False and record["outcome"] == "denied"
    # Quyết lần 2: không còn chờ nữa.
    assert broker.resolve("a2", True) is False


async def test_timeout_expires():
    broker = ApprovalBroker(timeout_s=0.05)
    broker.open("a3", _payload())
    record = await broker.wait("a3")
    assert record["approved"] is False and record["outcome"] == "expired"
    assert broker.resolve("a3", True) is False


async def test_remember_writes_session_rule(cfg):
    policy = PolicyEngine(cfg.policy_path)
    broker = ApprovalBroker(policy=policy, timeout_s=5)
    broker.open("a4", _payload("run_command"))
    broker.resolve("a4", True, remember=True)
    record = await broker.wait("a4")
    assert record["remember"] is True
    assert policy.session_tools.get("run_command") == "allow"
    # Lần sau trong phiên: decide ra allow, không hỏi lại.
    assert policy.decide("run_command", "shell").verdict == "allow"


async def test_listener_notified_with_card():
    broker = ApprovalBroker(timeout_s=5)
    seen = []
    broker.on_decided(lambda rec: seen.append(rec))
    broker.open("a5", _payload())
    broker.attach("a5", {"chat_id": 1, "message_id": 9})
    broker.resolve("a5", True)
    await broker.wait("a5")
    assert seen and seen[0]["card"] == {"chat_id": 1, "message_id": 9}


def test_summarize_args_redacts_secrets():
    out = summarize_args({
        "command": "ls -la",
        "api_key": "sk-secret-123",
        "password": "hunter2",
        "path": "/tmp/x",
    })
    assert "ls -la" in out
    assert "sk-secret-123" not in out and "hunter2" not in out
    assert "***" in out
    assert summarize_args({}) == "(không có tham số)"
    long_out = summarize_args({"text": "x" * 500})
    assert len(long_out) <= 245
