"""Test cho browser bridge Instagram DM — T-22.3.

Phạm vi:
- Khớp hội thoại theo thread_id / participant.
- Bridge: chưa có profile/driver thì báo unsupported rõ ràng;
  driver báo ok nhưng không xác minh thì KHÔNG được tính là gửi;
  driver lỗi thì lỗi đi qua nguyên vẹn, không biến thành sent True.
- Connector: không có runner lẫn bridge thì trả lỗi unsupported thay cho stub cũ
  sent: True (chống báo thành công giả theo audit T-22.3).
- Có bridge hoặc session runner thì gửi tin và xác minh thật.
"""

from __future__ import annotations

from types import SimpleNamespace
import pytest

from mulon.instagram_browser_bridge import (
    InstagramBrowserBridge,
    _match_conversation,
)
from mulon.personal_connectors import (
    LIMITATION_INSTAGRAM_MSG,
    WARNING_INSTAGRAM_MSG,
    InstagramMessagesConnector,
)
from mulon.vault import VaultStore


class FakeInstagramDriver:
    """Driver giả cho test Instagram DM: ghi lại lệnh, trả kết quả do test đặt."""

    def __init__(self, result=None, react_result=None):
        self.calls = []
        self.react_calls = []
        self.result = result if result is not None else {
            "ok": True, "sent": True, "verified": True,
            "thread_id": "ig_thread_01",
        }
        self.react_result = react_result if react_result is not None else {
            "ok": True, "reacted": True,
            "thread_id": "ig_thread_01", "message_id": "m1", "emoji": "❤️",
        }

    async def send(self, thread_id, text, participant=None):
        self.calls.append({
            "thread_id": thread_id, "text": text,
            "participant": participant,
        })
        out = dict(self.result)
        out.setdefault("thread_id", thread_id)
        return out

    async def react(self, thread_id, message_id, emoji="❤️"):
        self.react_calls.append({
            "thread_id": thread_id, "message_id": message_id,
            "emoji": emoji,
        })
        out = dict(self.react_result)
        out.setdefault("thread_id", thread_id)
        out.setdefault("message_id", message_id)
        return out


def test_match_conversation_by_thread_id_and_participant():
    assert _match_conversation(
        "https://www.instagram.com/direct/t/17841400012345678/", "Alice", "17841400012345678", None)
    assert _match_conversation(
        "https://www.instagram.com/direct/t/998877/", "Known Friend",
        "other", "@known_friend")
    assert not _match_conversation(
        "https://www.instagram.com/direct/t/998877/", "Someone Else",
        "nope", "@stranger")
    assert not _match_conversation("", "", "", None)


@pytest.mark.asyncio
async def test_bridge_without_profile_or_driver_is_unsupported():
    bridge = InstagramBrowserBridge(cfg=SimpleNamespace(
        browser_profile_dir=None, browser_timeout_s=30.0,
        instagram_web_base_url="https://www.instagram.com"))
    res = await bridge.send_message("ig_thread_01", "xin chào")
    assert res["ok"] is False
    assert res.get("unsupported") is True
    assert "BROWSER_PROFILE_DIR" in res["error"]
    assert res.get("sent") is not True


@pytest.mark.asyncio
async def test_bridge_fake_driver_verified_success():
    driver = FakeInstagramDriver()
    bridge = InstagramBrowserBridge(cfg=None, driver=driver)
    res = await bridge.send_message("ig_thread_01", "xin chào",
                                    participant="known_friend")
    assert res["ok"] is True
    assert res["sent"] is True
    assert res["verified"] is True
    assert driver.calls[0]["thread_id"] == "ig_thread_01"
    assert driver.calls[0]["text"] == "xin chào"


@pytest.mark.asyncio
async def test_bridge_unverified_ok_is_not_counted_as_sent():
    driver = FakeInstagramDriver(result={"ok": True, "sent": True})
    bridge = InstagramBrowserBridge(cfg=None, driver=driver)
    res = await bridge.send_message("ig_thread_01", "xin chào")
    assert res["ok"] is False
    assert res.get("sent") is not True
    assert "không xác minh" in res["error"]


@pytest.mark.asyncio
async def test_bridge_driver_error_passes_through():
    driver = FakeInstagramDriver(result={"ok": False,
                                         "error": "không thấy ô soạn tin"})
    bridge = InstagramBrowserBridge(cfg=None, driver=driver)
    res = await bridge.send_message("ig_thread_01", "xin chào")
    assert res["ok"] is False
    assert "không thấy ô soạn tin" in res["error"]


@pytest.mark.asyncio
async def test_bridge_validation_rejects_empty_thread_or_text():
    bridge = InstagramBrowserBridge(cfg=None, driver=FakeInstagramDriver())
    assert (await bridge.send_message("", "xin chào"))["ok"] is False
    assert (await bridge.send_message("ig_thread_01", "   "))["ok"] is False


@pytest.mark.asyncio
async def test_bridge_send_reaction_success():
    driver = FakeInstagramDriver()
    bridge = InstagramBrowserBridge(cfg=None, driver=driver)
    res = await bridge.send_reaction("ig_thread_01", "msg_123", "🔥")
    assert res["ok"] is True
    assert res["reacted"] is True
    assert driver.react_calls[0]["message_id"] == "msg_123"
    assert driver.react_calls[0]["emoji"] == "🔥"


async def _configured_instagram_connector(tmp_path, bridge=None):
    vault = VaultStore(tmp_path / "vault.json")
    conn = InstagramMessagesConnector(vault_store=vault,
                                      browser_bridge=bridge)
    await conn.call("configure", {
        "cookies": "sessionid=ig_valid_session; ds_user_id=12345678;",
        "user": {
            "cached_messages": {
                "ig_thread_01": [
                    {"id": "m1", "text": "Tin nhắn cũ"},
                ],
            },
        },
    })
    return conn


@pytest.mark.asyncio
async def test_connector_without_transport_no_longer_fakes_sent(tmp_path):
    conn = await _configured_instagram_connector(tmp_path)
    res = await conn.call("send_message", {
        "thread_id": "ig_thread_01", "text": "Chào bạn!",
    })
    assert res["ok"] is False
    assert res.get("unsupported") is True
    assert res.get("sent") is not True
    assert "chưa có đường gửi thật" in res["error"]
    assert LIMITATION_INSTAGRAM_MSG in res["limitations"]

    # Reaction cũng unsupported khi không có bridge/runner
    react = await conn.call("send_reaction", {
        "thread_id": "ig_thread_01", "message_id": "m1", "reaction": "❤️",
    })
    assert react["ok"] is False
    assert react.get("unsupported") is True
    assert react.get("reacted") is not True


@pytest.mark.asyncio
async def test_connector_with_bridge_send_message_and_reaction(tmp_path):
    driver = FakeInstagramDriver()
    bridge = InstagramBrowserBridge(cfg=None, driver=driver)
    conn = await _configured_instagram_connector(tmp_path, bridge=bridge)

    valid = await conn.call("send_message", {
        "thread_id": "ig_thread_01", "text": "Tin nhắn mới qua bridge",
        "username": "@alice",
    })
    assert valid["ok"] is True
    assert valid["sent"] is True
    assert valid["verified"] is True
    assert driver.calls[0]["thread_id"] == "ig_thread_01"
    assert driver.calls[0]["text"] == "Tin nhắn mới qua bridge"

    react = await conn.call("send_reaction", {
        "thread_id": "ig_thread_01", "message_id": "m1", "reaction": "🎉",
    })
    assert react["ok"] is True
    assert react["reacted"] is True
    assert driver.react_calls[0]["emoji"] == "🎉"


@pytest.mark.asyncio
async def test_connector_allows_bridge_without_vault_session(tmp_path):
    vault = VaultStore(tmp_path / "vault.json")
    driver = FakeInstagramDriver()
    bridge = InstagramBrowserBridge(cfg=None, driver=driver)
    # Connector hoàn toàn chưa có cookie trong Vault
    conn = InstagramMessagesConnector(vault_store=vault, browser_bridge=bridge)

    res = await conn.call("send_message", {
        "thread_id": "ig_thread_01", "text": "Tin gửi khi chỉ có browser profile",
    })
    assert res["ok"] is True
    assert res["sent"] is True
    assert res["verified"] is True
