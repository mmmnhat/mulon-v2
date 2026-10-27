"""Test cho spike browser bridge T-22.3 — gửi DM Threads thật qua web.

Phạm vi (không cần Playwright, không cần tài khoản thật):
- Khớp hội thoại (hàm thuần) theo thread_id / participant.
- Bridge: chưa có profile/driver thì báo unsupported rõ ràng;
  driver báo ok nhưng không xác minh thì KHÔNG được tính là gửi;
  driver lỗi thì lỗi đi qua nguyên vẹn, không biến thành sent True.
- Connector: guard giới hạn cứng vẫn chạy TRƯỚC bridge (người lạ
  bị chặn, bridge không được gọi); hội thoại hợp lệ qua fake
  bridge thì gửi thật (theo driver) và trả verified; không có
  runner lẫn bridge thì trả lỗi unsupported thay cho stub cũ
  sent: True (yêu cầu NEEDS-FIX của T-22.3).
"""

from __future__ import annotations

import pytest
from types import SimpleNamespace

from mulon.personal_connectors import (
    LIMITATION_THREADS_MSG,
    ThreadsMessagesConnector,
)
from mulon.threads_browser_bridge import (
    ThreadsBrowserBridge,
    _match_conversation,
)
from mulon.vault import VaultStore


class FakeDriver:
    """Driver giả cho test: ghi lại lệnh, trả kết quả do test đặt."""

    def __init__(self, result=None):
        self.calls = []
        self.result = result if result is not None else {
            "ok": True, "sent": True, "verified": True,
            "thread_id": "th_valid_1",
        }

    async def send(self, thread_id, text, participant=None):
        self.calls.append({
            "thread_id": thread_id, "text": text,
            "participant": participant,
        })
        out = dict(self.result)
        out.setdefault("thread_id", thread_id)
        return out


def test_match_conversation_by_thread_id_and_participant():
    assert _match_conversation(
        "https://www.threads.net/messages/abc123", "Alice", "abc123", None)
    assert _match_conversation(
        "https://www.threads.net/messages/xyz", "Known Friend",
        "other", "@known_friend")
    assert not _match_conversation(
        "https://www.threads.net/messages/xyz", "Someone Else",
        "nope", "@stranger")
    assert not _match_conversation("", "", "", None)


@pytest.mark.asyncio
async def test_bridge_without_profile_or_driver_is_unsupported():
    bridge = ThreadsBrowserBridge(cfg=SimpleNamespace(
        browser_profile_dir=None, browser_timeout_s=30.0,
        threads_web_base_url="https://www.threads.net"))
    res = await bridge.send_message("th_valid_1", "xin chào")
    assert res["ok"] is False
    assert res.get("unsupported") is True
    assert "BROWSER_PROFILE_DIR" in res["error"]
    assert res.get("sent") is not True


@pytest.mark.asyncio
async def test_bridge_fake_driver_verified_success():
    driver = FakeDriver()
    bridge = ThreadsBrowserBridge(cfg=None, driver=driver)
    res = await bridge.send_message("th_valid_1", "xin chào",
                                    participant="known_friend")
    assert res["ok"] is True
    assert res["sent"] is True
    assert res["verified"] is True
    assert driver.calls[0]["thread_id"] == "th_valid_1"
    assert driver.calls[0]["text"] == "xin chào"


@pytest.mark.asyncio
async def test_bridge_unverified_ok_is_not_counted_as_sent():
    driver = FakeDriver(result={"ok": True, "sent": True})
    bridge = ThreadsBrowserBridge(cfg=None, driver=driver)
    res = await bridge.send_message("th_valid_1", "xin chào")
    assert res["ok"] is False
    assert res.get("sent") is not True
    assert "không xác minh" in res["error"]


@pytest.mark.asyncio
async def test_bridge_driver_error_passes_through():
    driver = FakeDriver(result={"ok": False,
                                "error": "không thấy ô soạn tin"})
    bridge = ThreadsBrowserBridge(cfg=None, driver=driver)
    res = await bridge.send_message("th_valid_1", "xin chào")
    assert res["ok"] is False
    assert "không thấy ô soạn tin" in res["error"]


@pytest.mark.asyncio
async def test_bridge_validation_rejects_empty_thread_or_text():
    bridge = ThreadsBrowserBridge(cfg=None, driver=FakeDriver())
    assert (await bridge.send_message("", "xin chào"))["ok"] is False
    assert (await bridge.send_message("th_valid_1", "   "))["ok"] is False


async def _configured_connector(tmp_path, bridge=None):
    vault = VaultStore(tmp_path / "vault.json")
    conn = ThreadsMessagesConnector(vault_store=vault,
                                    browser_bridge=bridge)
    await conn.call("configure", {
        "cookies": "sessionid=threads_valid_session;",
        "user": {
            "existing_threads": ["th_valid_1", "known_friend"],
            "cached_inbox": [
                {"thread_id": "th_valid_1",
                 "participant": "known_friend", "snippet": "Hey"},
            ],
        },
    })
    return conn


@pytest.mark.asyncio
async def test_connector_without_transport_no_longer_fakes_sent(tmp_path):
    conn = await _configured_connector(tmp_path)
    res = await conn.call("send_message", {
        "thread_id": "th_valid_1", "text": "Chào bạn!",
    })
    assert res["ok"] is False
    assert res.get("unsupported") is True
    assert res.get("sent") is not True
    assert "chưa có đường gửi thật" in res["error"]
    assert LIMITATION_THREADS_MSG in res["limitations"]


@pytest.mark.asyncio
async def test_connector_guard_runs_before_bridge(tmp_path):
    driver = FakeDriver()
    bridge = ThreadsBrowserBridge(cfg=None, driver=driver)
    conn = await _configured_connector(tmp_path, bridge=bridge)
    stranger = await conn.call("send_message", {
        "username": "@stranger_user_99", "text": "Hello stranger!",
    })
    assert stranger["ok"] is False
    assert "người lạ" in stranger["error"]
    assert driver.calls == []

    valid = await conn.call("send_message", {
        "username": "@known_friend", "text": "Chào bạn cũ",
    })
    assert valid["ok"] is True
    assert valid["sent"] is True
    assert valid["verified"] is True
    # Guard đã map participant hợp lệ về thread_id có sẵn.
    assert driver.calls[0]["thread_id"] == "th_valid_1"


@pytest.mark.asyncio
async def test_connector_bridge_failure_is_not_success(tmp_path):
    driver = FakeDriver(result={"ok": False,
                                "error": "không xác minh được tin"})
    bridge = ThreadsBrowserBridge(cfg=None, driver=driver)
    conn = await _configured_connector(tmp_path, bridge=bridge)
    res = await conn.call("send_message", {
        "thread_id": "th_valid_1", "text": "Chào bạn!",
    })
    assert res["ok"] is False
    assert res.get("sent") is not True
