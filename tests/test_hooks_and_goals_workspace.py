"""Test Hook Subsystem và Goal Workspace theo chuẩn kiến trúc Muse."""

import pytest
from pathlib import Path
from mulon.hooks import HookManager
from mulon.memory import ensure_goal_workspace


def test_ensure_goal_workspace(tmp_path):
    class Cfg:
        workspace_dir = tmp_path

    res = ensure_goal_workspace(Cfg(), 42)
    assert res["files"].is_dir()
    assert res["hidden_files"].is_dir()
    assert res["files"].name == "files"
    assert res["hidden_files"].name == "hidden_files"


def test_hook_lifecycle(tmp_path):
    hm = HookManager(tmp_path / "hooks")

    # 1. Đăng ký hook mới
    script_content = """#!/usr/bin/env bash
echo '{"decision": "wake", "reason": "Có flash sale 50%", "payload": {"discount": 50}}'
"""
    manifest = hm.register_hook(
        "test_hook",
        "Test Hook Sale",
        script_content,
        "# Instruction",
        interval_s=30,
    )
    assert manifest["id"] == "test_hook"
    assert manifest["enabled"] is False
    assert manifest["dry_run_passed"] is False

    # 2. Không cho phép enable khi chưa dry_run
    en_res = hm.enable("test_hook", True)
    assert en_res["ok"] is False

    # 3. Dry run
    dry = hm.dry_run("test_hook")
    if dry.get("skipped"):
        pytest.skip(f"Môi trường thiếu shell bash để chạy hook: {dry.get('reason')}")
    assert dry["ok"] is True
    assert dry["decision"] == "wake"
    assert dry["payload"]["discount"] == 50

    # 4. Giờ có thể enable
    en_res2 = hm.enable("test_hook", True)
    assert en_res2["ok"] is True
    assert en_res2["hook"]["enabled"] is True

    # 5. Poll thật
    poll_res = hm.poll("test_hook")
    assert poll_res["ok"] is True
    assert poll_res["decision"] == "wake"
    assert poll_res["payload"]["discount"] == 50


def test_hook_degrade_when_no_bash(tmp_path, monkeypatch):
    monkeypatch.setattr("mulon.hooks._find_bash", lambda: None)
    hm = HookManager(tmp_path / "hooks")
    hm.register_hook("no_bash_hook", "Test", "echo 1", "# Doc")
    res = hm.dry_run("no_bash_hook")
    assert res["ok"] is False
    assert res.get("skipped") is True
    assert "bash_not_available_on_system" in res.get("reason", "")

