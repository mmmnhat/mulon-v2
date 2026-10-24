"""1.2.0 vá nhãn lời thường cho Mini App: render thật cho thấy
app còn lộ tên thô tiếng Anh ở 3 chỗ trong khi bề mặt chat đã
có nhãn tiếng Việt. Vá: /api/state gắn `action_label` cho thẻ
chờ duyệt (cùng `tool_action_label` của thẻ chat) + lịch sử
phê duyệt, và `group_labels` cho màn Quyền; frontend ưu tiên
nhãn, không có nhãn thì fallback giữ tên thô. Jargon
"lớp phiên/lớp host" ở màn Quyền cũng bỏ, thay lời thường."""

from pathlib import Path

from aiohttp import ClientSession

from mulon.webapp_server import known_action_label, \
    policy_group_label, tool_action_label
from tests.test_v12_webapp_api import _start, _stop, _url
from tests.test_v12_webapp_auth import make_init_data

HTML = (Path(__file__).resolve().parent.parent / "mulon" / "webapp"
        / "index.html").read_text(encoding="utf-8")


# ---------- helper nhãn (unit) ----------

def test_known_action_label_by_tool():
    assert known_action_label("run_command", "shell") == \
        "Chạy lệnh hệ thống"
    assert known_action_label("send_message", "connector") == \
        "Gửi tin nhắn"
    assert known_action_label("github_push", "connector") == \
        "Đẩy lên GitHub"


def test_known_action_label_by_group_and_unknown_empty():
    assert known_action_label("tool_bat_ky", "shell") == \
        "Chạy lệnh hệ thống"
    assert known_action_label("tool_bat_ky", "web") == "Đọc trang web"
    # Không có nhãn -> "" để frontend fallback tên thô, không bịa.
    assert known_action_label("tool_la_99", "la") == ""


def test_tool_action_label_chat_fallback_unchanged():
    # Hàm của thẻ chat giữ nguyên hành vi cũ cho tool lạ.
    assert tool_action_label("run_command", "shell") == \
        "Chạy lệnh hệ thống"
    assert tool_action_label("tool_la_99", "la") == \
        "Dùng công cụ tool_la_99"


def test_policy_group_labels_vietnamese():
    assert policy_group_label("file") == "Thao tác file"
    assert policy_group_label("memory") == "Tra ký ức"
    assert policy_group_label("shell") == "Chạy lệnh hệ thống"
    assert policy_group_label("system") == "Thông tin hệ thống"
    assert policy_group_label("web") == "Đọc web"
    assert policy_group_label("mcp:foo") == ""  # lạ -> fallback key


# ---------- /api/state: pending + history + policy ----------

async def _get_state(server):
    headers = {"X-Telegram-Init-Data": make_init_data()}
    async with ClientSession() as s:
        async with s.get(_url(server, "/api/state"),
                         headers=headers) as r:
            assert r.status == 200
            return await r.json()


async def test_api_state_pending_has_action_label(cfg):
    _, memory, broker, server = await _start(cfg)
    try:
        broker.open("pl1", {"approval_id": "pl1",
                            "tool": "run_command", "group": "shell",
                            "summary": "cmd=ls",
                            "session_key": "sk", "task_id": "t"})
        data = await _get_state(server)
        item = data["approvals"]["pending"][0]
        assert item["action_label"] == "Chạy lệnh hệ thống"
        assert item["group_label"] == "Chạy lệnh hệ thống"
        # Tên thô vẫn còn trong payload cho dòng chi tiết của thẻ.
        assert item["tool"] == "run_command"
        broker.resolve("pl1", False)
        await broker.wait("pl1")
    finally:
        await _stop(memory, server)


async def test_api_state_history_has_action_labels(cfg):
    _, memory, broker, server = await _start(cfg)
    try:
        for tool, group, outcome in (
                ("send_message", "connector", "approved"),
                ("github_push", "connector", "approved"),
                ("tool_la_99", "la", "denied")):
            await memory.log_trajectory(
                "sk", "approval_decision",
                {"tool": tool, "group": group, "outcome": outcome,
                 "approved": outcome == "approved", "remember": False})
        data = await _get_state(server)
        hist = {h["tool"]: h for h in data["approvals"]["history"]}
        assert hist["send_message"]["action_label"] == "Gửi tin nhắn"
        assert hist["github_push"]["action_label"] == "Đẩy lên GitHub"
        assert hist["send_message"]["group_label"] == \
            "Gọi dịch vụ ngoài"
        # Tool lạ: không bịa nhãn — frontend sẽ fallback tên thô.
        assert hist["tool_la_99"]["action_label"] == ""
        assert hist["tool_la_99"]["group_label"] == ""
    finally:
        await _stop(memory, server)


async def test_api_state_policy_group_labels(cfg):
    _, memory, broker, server = await _start(cfg)
    try:
        data = await _get_state(server)
        labels = data["policy"]["group_labels"]
        assert labels["file"] == "Thao tác file"
        assert labels["memory"] == "Tra ký ức"
        assert labels["shell"] == "Chạy lệnh hệ thống"
        assert labels["system"] == "Thông tin hệ thống"
        assert labels["web"] == "Đọc web"
        # Tương thích ngược: groups vẫn là map key -> verdict.
        assert data["policy"]["groups"]["shell"] in (
            "allow", "ask", "deny")
    finally:
        await _stop(memory, server)


# ---------- frontend: ưu tiên nhãn + hết jargon màn Quyền ----------

def test_frontend_prefers_labels_with_raw_fallback():
    assert "p.action_label || p.tool" in HTML      # thẻ chờ duyệt
    assert "h.action_label || h.tool" in HTML      # lịch sử duyệt
    assert "pol.group_labels" in HTML              # nhóm ở màn Quyền
    assert "p.group_label || p.group" in HTML
    assert "h.group_label || h.group" in HTML


def test_frontend_policy_screen_no_layer_jargon():
    flat = " ".join(HTML.split())
    assert "persist = lớp host" not in flat
    assert "lớp host" not in flat
    assert "lớp phiên" not in flat
    # Câu thay thế giữ đúng nghĩa bằng lời thường.
    assert "Ghi vào file cấu hình trên máy — áp cho mọi phiên " \
           "sau, không mất khi hết phiên." in flat
    assert "chỉ áp cho phiên hiện tại" in flat
