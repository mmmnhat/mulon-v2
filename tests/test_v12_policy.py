"""1.2.0 Khối 2: policy 3 nấc (allow/ask/deny) + tương thích file cũ."""

import json

from mulon.policy import PolicyEngine, parse_verdict
from tests.conftest import open_memory


def _write(cfg, data):
    cfg.policy_path.write_text(json.dumps(data), encoding="utf-8")


def test_parse_verdict_words():
    assert parse_verdict("ask") == "ask"
    assert parse_verdict("prompt") == "ask"
    assert parse_verdict("CONFIRM") == "ask"
    assert parse_verdict("deny") == "deny"
    assert parse_verdict("block") == "deny"
    assert parse_verdict("allow") == "allow"
    assert parse_verdict("yes") == "allow"
    assert parse_verdict(None) is None


def test_ask_from_host_file(cfg):
    _write(cfg, {
        "default": "confirm",
        "tools": {"run_command": "ask"},
        "groups": {"web": "prompt", "shell": "deny"},
    })
    policy = PolicyEngine(cfg.policy_path)
    d = policy.decide("run_command", "shell")
    assert d.verdict == "ask" and d.needs_ask and d.allowed is False
    assert d.layer == "host-tool"
    d2 = policy.decide("web_fetch", "web")
    assert d2.verdict == "ask" and d2.layer == "host-group"
    d3 = policy.decide("read_file", "file")  # rơi xuống default
    assert d3.verdict == "ask" and d3.layer == "host-default"


def test_backward_compat_allow_deny_only(cfg):
    _write(cfg, {"default": "allow",
                 "tools": {"run_command": "deny"}})
    policy = PolicyEngine(cfg.policy_path)
    d = policy.decide("run_command", "shell")
    assert d.verdict == "deny" and d.allowed is False
    d2 = policy.decide("read_file", "file")
    assert d2.verdict == "allow" and d2.allowed is True
    # Không có file policy -> builtin full-auto như cũ.
    empty = PolicyEngine(cfg.policy_path.parent / "khong_co.json")
    d3 = empty.decide("run_command", "shell")
    assert d3.verdict == "allow" and d3.layer == "builtin"


async def test_check_logs_verdict(cfg):
    _write(cfg, {"tools": {"run_command": "ask"}})
    memory = await open_memory(cfg)
    policy = PolicyEngine(cfg.policy_path, memory=memory)
    await policy.check("run_command", "shell", session_key="sk")
    rows = await memory.recent_trajectory(kind="policy_decision",
                                          limit=5)
    assert rows[0]["payload"]["verdict"] == "ask"
    await memory.close()


def test_session_and_host_rules(cfg):
    policy = PolicyEngine(cfg.policy_path)
    policy.set_session_rule("tool", "run_command", "ask")
    assert policy.decide("run_command", "shell").verdict == "ask"
    # Host thắng session:
    policy.set_host_rule("tool", "run_command", "deny")
    assert policy.decide("run_command", "shell").verdict == "deny"
    # File đã ghi thật — engine mới đọc lại vẫn thấy.
    fresh = PolicyEngine(cfg.policy_path)
    assert fresh.decide("run_command", "shell").verdict == "deny"
    desc = policy.describe()
    assert desc["tools"]["run_command"] == "deny"
    assert desc["session_tools"]["run_command"] == "ask"
