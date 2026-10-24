"""Kiểm thử cho các sửa 1.6.2 (mảng tính năng còn mở).

1. Browser tương tác: validator selector/text (thuần, không cần
   Playwright) — click/fill thật cần Playwright + duyệt, test tay
   trên Mac mini theo features.md.
2. Ideas tự sinh opt-in: mặc định tắt, kv thắng env, lượt tắt
   không gọi model/không ghi thẻ.
3. Policy fallback action-level cho mọi connector: ghi/xoá -> ask,
   đọc -> allow; bảng 6 action Google thắng; tool không phải
   connector và token lạ vẫn builtin allow như cũ.
"""

import asyncio

import pytest

from mulon.browser_worker import (
    MAX_FILL_TEXT_LEN,
    MAX_SELECTOR_LEN,
    validate_fill_text,
    validate_selector,
)
from mulon.ideas import (
    IDEAS_AUTO_KV_KEY,
    IdeaEngine,
    effective_auto_enabled,
)
from mulon.policy import (
    PolicyEngine,
    VERDICT_ALLOW,
    VERDICT_ASK,
    connector_fallback_verdict,
)


# ---------------------------------------------------------------------------
# (a) Browser validators
# ---------------------------------------------------------------------------

def test_selector_ok():
    assert validate_selector("#search-btn") is None
    assert validate_selector("form input[name='q']") is None
    assert validate_selector("div > button.next") is None


def test_selector_rejects():
    assert validate_selector("") is not None
    assert validate_selector("x" * (MAX_SELECTOR_LEN + 1)) is not None
    assert validate_selector("xpath=//button") is not None
    assert validate_selector("text=Delete") is not None
    assert validate_selector("div >> text=hi") is not None
    assert validate_selector("input#password") is not None
    assert validate_selector("a\nb") is not None


def test_fill_text_limits():
    assert validate_fill_text("hello") is None
    assert validate_fill_text("") is not None
    assert validate_fill_text("x" * (MAX_FILL_TEXT_LEN + 1)) is not None


# ---------------------------------------------------------------------------
# (b) Ideas auto opt-in
# ---------------------------------------------------------------------------

class _FakeMemory:
    def __init__(self, kv=None):
        self.kv = kv or {}

    async def kv_get(self, key):
        return self.kv.get(key)


class _FakeCfg:
    def __init__(self, enabled=False):
        self.ideas_auto_enabled = enabled


def test_ideas_auto_default_off():
    assert asyncio.run(effective_auto_enabled(
        _FakeMemory(), _FakeCfg(False))) is False
    assert asyncio.run(effective_auto_enabled(
        _FakeMemory(), _FakeCfg(True))) is True


def test_ideas_auto_kv_beats_env():
    assert asyncio.run(effective_auto_enabled(
        _FakeMemory({IDEAS_AUTO_KV_KEY: "1"}),
        _FakeCfg(False))) is True
    assert asyncio.run(effective_auto_enabled(
        _FakeMemory({IDEAS_AUTO_KV_KEY: "0"}),
        _FakeCfg(True))) is False


def test_generate_auto_skipped_when_disabled():
    engine = IdeaEngine(_FakeCfg(False), _FakeMemory(), None)
    stats = asyncio.run(engine.generate_auto())
    assert stats["skipped"] == "disabled"
    assert stats["cards"] == 0


# ---------------------------------------------------------------------------
# (c) Policy fallback cho mọi connector
# ---------------------------------------------------------------------------

@pytest.fixture
def policy(tmp_path):
    return PolicyEngine(tmp_path / "policy.json")


def test_tool_default_web_interact_is_ask(policy):
    for tool in ("web_click", "web_fill"):
        dec = policy.decide(tool, "web:interact")
        assert dec.verdict == VERDICT_ASK
        assert dec.layer == "tool-default"


def test_host_rule_beats_tool_default(policy):
    policy.set_host_rule("tool", "web_click", "allow")
    dec = policy.decide("web_click", "web:interact")
    assert dec.verdict == VERDICT_ALLOW
    assert dec.layer == "host-tool"


def test_connector_fallback_write_is_ask(policy):
    for group in ("connector:slack:send_message",
                  "connector:drive:create_file",
                  "connector:drive:delete_file",
                  "connector:drive:update_file",
                  "connector:drive:trash_item",
                  "connector:drive:remove_member",
                  "connector:drive:edit_doc"):
        dec = policy.decide("connector_call", group)
        assert dec.verdict == VERDICT_ASK, group
        assert dec.layer == "connector-action-fallback", group


def test_connector_fallback_read_is_allow(policy):
    for group in ("connector:drive:list_files",
                  "connector:drive:list_events",
                  "connector:drive:search",
                  "connector:drive:read_doc",
                  "connector:drive:get_file",
                  "connector:drive:view_page"):
        dec = policy.decide("connector_call", group)
        assert dec.verdict == VERDICT_ALLOW, group
        assert dec.layer == "connector-action-fallback", group


def test_google_table_beats_fallback(policy):
    # Bảng 1.6 đã có vẫn thắng: gmail:send là ask qua
    # connector-action-default, không phải qua fallback.
    dec = policy.decide("connector_call", "connector:gmail:send")
    assert dec.verdict == VERDICT_ASK
    assert dec.layer == "connector-action-default"
    dec = policy.decide("connector_call", "connector:gmail:search")
    assert dec.verdict == VERDICT_ALLOW
    assert dec.layer == "connector-action-default"


def test_fallback_does_not_touch_others(policy):
    # Call thiếu action, token lạ, tool không phải connector:
    # vẫn builtin allow như cũ.
    assert connector_fallback_verdict("connector:drive") is None
    assert connector_fallback_verdict("connector:drive:archive") is None
    assert connector_fallback_verdict("shell") is None
    assert policy.decide("connector_call",
                         "connector:drive").layer == "builtin"
    assert policy.decide("connector_call",
                         "connector:drive:archive").layer == "builtin"
    assert policy.decide("run_command", "shell").layer == "builtin"
    assert policy.decide("web_read", "web").verdict == VERDICT_ALLOW
