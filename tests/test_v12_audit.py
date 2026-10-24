"""Hồi quy theo audit bề mặt (audit-be-mat-tuong-tac-mulon.md):
DUY-1 (/approvals đúng outcome của thẻ), DUY-2 (/quyen đúng 3
nấc), NC-1 (converter Markdown->HTML an toàn), nhãn trạng thái
lời thường dùng chung."""

import json

from mulon import surfaces as surf
from mulon.policy import PolicyEngine
from mulon.telegram_bot import md_to_html
from mulon.webapp_server import plain_step_label, tool_action_label


# ---------------- DUY-1 ----------------

def test_format_approvals_distinguishes_ask_outcomes():
    rows = [
        {"created_at": "t3", "payload": {
            "tool": "run_command", "group": "shell", "layer": "ask",
            "outcome": "approved", "approved": True,
            "allowed": False}},  # policy.check ghi allowed=False
        {"created_at": "t2", "payload": {
            "tool": "run_command", "group": "shell", "layer": "ask",
            "outcome": "denied", "approved": False}},
        {"created_at": "t1", "payload": {
            "tool": "read_file", "group": "file",
            "layer": "host-tool", "allowed": False}},
    ]
    out = surf.format_approvals(rows)
    # Việc ĐÃ ĐƯỢC DUYỆT qua thẻ không được hiện thành CHẶN.
    assert "CHO (đã duyệt qua thẻ)" in out
    assert "CHẶN (user từ chối qua thẻ)" in out
    # Hàng policy thuần vẫn CHO/CHẶN như cũ.
    assert "CHẶN tool read_file" in out
    assert "**" not in out  # NC-1: không còn ký tự markdown thô


# ---------------- DUY-2 ----------------

def test_summarize_policy_three_verdicts(cfg):
    cfg.policy_path.write_text(json.dumps({
        "default": "allow",
        "tools": {"run_command": "ask", "read_file": "allow",
                  "write_file": "deny"},
        "groups": {},
    }), encoding="utf-8")
    text = surf.summarize_policy(PolicyEngine(cfg.policy_path))
    assert "run_command" in text and "phải hỏi trước" in text
    assert "write_file" in text and "bị chặn" in text
    assert "được tự làm" in text  # read_file
    # Dòng cuối: Mini App sửa được policy — hết khẳng định sai.
    assert "không có đường tắt" not in text
    assert "/menu" in text and "policy.json" in text
    assert "**" not in text


def test_summarize_policy_default_ask(cfg):
    cfg.policy_path.write_text(json.dumps({"default": "ask"}),
                               encoding="utf-8")
    text = surf.summarize_policy(PolicyEngine(cfg.policy_path))
    assert "phải hỏi trước" in text
    assert "full-auto" not in text


# ---------------- NC-1: converter ----------------

def test_md_to_html_converts_and_escapes():
    out = md_to_html("Kết quả **quan trọng** và `code<x>` đây")
    assert "<b>quan trọng</b>" in out
    assert "<code>code&lt;x&gt;</code>" in out
    assert "**" not in out
    # HTML thô trong nội dung bị escape, không thành thẻ thật.
    out2 = md_to_html("chèn <script>alert(1)</script> vào")
    assert "<script>" not in out2 and "&lt;script&gt;" in out2
    # Link markdown -> thẻ a; heading -> b.
    out3 = md_to_html("## Tiêu đề\nXem [docs](https://e.x/d)")
    assert "<b>Tiêu đề</b>" in out3
    assert '<a href="https://e.x/d">docs</a>' in out3
    # Code block giữ nguyên + escape.
    out4 = md_to_html("```\na < b\n```")
    assert "<pre>a &lt; b</pre>" in out4


# ---------------- nhãn lời thường ----------------

def test_plain_step_labels_hide_raw_tool_names():
    assert plain_step_label(
        "tool_start", {"tool": "run_command"}) == "Đang chạy lệnh"
    assert plain_step_label(
        "tool_start", {"tool": "web_fetch"}) == "Đang đọc web"
    assert plain_step_label(
        "tool_start", {"tool": "read_file"}) == "Đang đọc file"
    assert plain_step_label("verify") == "Đang kiểm chứng"
    assert plain_step_label(
        "approval_requested") == "Đang chờ duyệt"
    # Tool lạ: fallback theo nhóm, vẫn không lộ tên thô.
    label = plain_step_label(
        "tool_start", {"tool": "xyz_bi_mat", "group": "shell"})
    assert label == "Đang chạy lệnh" and "xyz" not in label


def test_tool_action_labels_for_card():
    assert tool_action_label("run_command", "shell") == \
        "Chạy lệnh hệ thống"
    assert tool_action_label("web_fetch", "web") == "Đọc trang web"
    assert tool_action_label("read_file", "file") == "Đọc file"
