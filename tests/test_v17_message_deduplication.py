"""Test kiểm chứng toàn diện cơ chế chống nhân đôi tin nhắn (T-24.4).

Bao gồm 4 điểm bằng chứng:
(1) Câu trả lời ở group/chat chỉ có đúng một bản cập nhật trên placeholder, không gửi thêm tin mới trùng lặp khi edit_text gặp 'message is not modified'.
(2) Thông báo dừng việc: chỉ cập nhật trên placeholder đang chạy, không vừa sửa tin cũ vừa gửi thêm tin mới cùng nội dung.
(3) Xác nhận lưu Vault: chỉ gửi đúng một tin xác nhận vào chat ngay cả khi được gọi đồng thời từ cả listener kho và notifier webapp.
(4) Thẻ yêu cầu bí mật Vault: cùng một nhãn (label) chỉ phát một thẻ duy nhất, cập nhật tại chỗ khi đổi mục đích; khôi phục trạng thái đã phát sau restart qua KV để chống phát lặp.
(5) Khử trùng tin nhắn đến (inbound Telegram update de-duplication) bảo vệ chống getUpdates re-delivery.
"""

import asyncio
import json
import time
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from mulon.approvals import ApprovalBroker
from mulon.context import Dossier
from mulon.policy import PolicyEngine
from mulon.telegram_bot import MessageBatcher, TelegramSurface
from mulon.vault import VaultBroker, VaultStore, register_vault_tools
from tests.conftest import open_memory
from tests.test_v12_surface import FakeBot, _cfg


class MockMessage:
    def __init__(self, chat_id=100, message_id=1, text="", is_topic=False, thread_id=None):
        self.chat = SimpleNamespace(id=chat_id, type="group")
        self.message_id = message_id
        self.text = text
        self.caption = ""
        self.is_topic_message = is_topic
        self.message_thread_id = thread_id
        self.from_user = SimpleNamespace(id=42, username="owner")
        self.sent_answers = []
        self.reactions = []

    async def answer(self, text, parse_mode=None, **kw):
        mock_msg = MockPlaceholder(self.chat.id, len(self.sent_answers) + 500, text)
        self.sent_answers.append(mock_msg)
        return mock_msg

    async def react(self, reaction):
        self.reactions.append(reaction)


class MockPlaceholder:
    def __init__(self, chat_id, message_id, text=""):
        self.chat = SimpleNamespace(id=chat_id)
        self.message_id = message_id
        self.text = text
        self.edit_history = [text]
        self.fail_with_not_modified = False

    async def edit_text(self, text, parse_mode=None, **kw):
        if self.fail_with_not_modified:
            from aiogram.exceptions import TelegramBadRequest
            raise TelegramBadRequest(
                method=MagicMock(),
                message="Bad Request: message is not modified: specified new message content and reply markup are exactly the same as a current content and reply markup of the message"
            )
        self.text = text
        self.edit_history.append(text)
        return self


@pytest.mark.asyncio
async def test_group_reply_does_not_send_duplicate_on_message_not_modified(cfg):
    """(1) Câu '2 cộng 2' không bị gửi 2 lần (một bản sửa cuối + một tin mới) khi edit_text báo 'message is not modified'."""
    cfg_base = _cfg(cfg)
    memory = await open_memory(cfg_base)
    policy = PolicyEngine(cfg_base.policy_path, memory=memory)
    broker = ApprovalBroker(policy=policy, timeout_s=30)
    surface = TelegramSurface(
        cfg_base, agent=None, memory=memory,
        dossier=Dossier.load(cfg_base.dossier_dir),
        policy=policy, broker=broker
    )
    bot = FakeBot()
    surface.bot = bot

    # Giả lập agent trả lời "2 + 2 = 4"
    surface.agent = SimpleNamespace(
        handle=AsyncMock(return_value=SimpleNamespace(text="2 + 2 = 4"))
    )

    anchor = MockMessage(chat_id=12345, message_id=10, text="2 cộng 2")
    surface._sessions_meta["key_1"] = anchor

    # Mock placeholder có cờ fail_with_not_modified = True (giả lập Telegram báo tin nhắn đã có đúng nội dung đó)
    orig_answer = anchor.answer
    created_placeholder = None

    async def answer_with_placeholder(text, **kw):
        nonlocal created_placeholder
        created_placeholder = MockPlaceholder(anchor.chat.id, 999, text)
        created_placeholder.fail_with_not_modified = True
        anchor.sent_answers.append(created_placeholder)
        return created_placeholder

    anchor.answer = answer_with_placeholder

    await surface._on_batch("key_1", "2 cộng 2", ["2 cộng 2"])

    # Chỉ có duy nhất 1 tin nhắn (placeholder) được tạo ra lúc đầu, KHÔNG có tin nhắn answer thứ hai
    assert len(anchor.sent_answers) == 1
    assert created_placeholder is not None
    await memory.close()


@pytest.mark.asyncio
async def test_stop_cancellation_single_notification(cfg):
    """(2) Thông báo dừng việc: chỉ cập nhật trên placeholder đang chạy, không vừa sửa tin cũ vừa gửi tin mới."""
    cfg_base = _cfg(cfg)
    memory = await open_memory(cfg_base)
    policy = PolicyEngine(cfg_base.policy_path, memory=memory)
    broker = ApprovalBroker(policy=policy, timeout_s=30)
    surface = TelegramSurface(
        cfg_base, agent=None, memory=memory,
        dossier=Dossier.load(cfg_base.dossier_dir),
        policy=policy, broker=broker
    )
    bot = FakeBot()
    surface.bot = bot

    anchor = MockMessage(chat_id=12345, message_id=20, text="việc dài")
    session_key = "agent:main:telegram:group:12345:topic:0"
    surface._sessions_meta[session_key] = anchor

    # Giả lập một tác vụ đang chạy trong _on_batch
    stop_called = asyncio.Event()

    async def slow_handle(*args, **kwargs):
        try:
            await asyncio.sleep(10.0)
        except asyncio.CancelledError:
            stop_called.set()
            raise

    surface.agent = SimpleNamespace(handle=slow_handle)

    batch_task = asyncio.create_task(surface._on_batch(session_key, "việc dài", ["việc dài"]))
    await asyncio.sleep(0.05)  # Chờ _on_batch chạy và gán running_task + placeholder

    assert surface.batcher.is_busy(session_key)
    placeholder = anchor.sent_answers[0]
    assert placeholder is not None

    # Người dùng gửi /stop
    stop_message = MockMessage(chat_id=12345, message_id=21, text="/stop")
    # Giả lập handler cmd_cancel xử lý
    running_task = surface._active_tasks.get(session_key)
    had_running_task = bool(running_task and not running_task.done())
    assert had_running_task is True
    running_task.cancel()
    surface.batcher.drain(session_key)
    if not had_running_task:
        await stop_message.answer("Đã dừng tác vụ đang chạy theo yêu cầu.")

    try:
        await batch_task
    except asyncio.CancelledError:
        pass

    assert stop_called.is_set()
    # Kiểm tra: placeholder đã được cập nhật thông báo dừng
    assert any("Đã dừng tác vụ theo yêu cầu" in h for h in placeholder.edit_history)
    # Và KHÔNG có tin nhắn mới nào được gửi vào stop_message
    assert len(stop_message.sent_answers) == 0
    await memory.close()


@pytest.mark.asyncio
async def test_vault_capture_single_confirmation_message(cfg):
    """(3) Xác nhận lưu Vault thành công chỉ gửi đúng 1 tin vào chat ngay cả khi listener và notifier cùng gọi."""
    cfg_base = _cfg(cfg)
    memory = await open_memory(cfg_base)
    surface = TelegramSurface(
        cfg_base, agent=None, memory=memory,
        dossier=Dossier.load(cfg_base.dossier_dir),
    )
    bot = FakeBot()
    surface.bot = bot

    surface._pending_vault_cards["gmail:token"] = {
        "chat_id": 777,
        "thread_id": None,
        "label": "gmail:token",
    }

    # Giả lập gọi đồng thời từ cả 2 nguồn (vault_store callback và webapp notifier)
    ref = "vault:uuid-gmail-123"
    await surface.on_vault_secret_captured("gmail:token", ref)
    await surface.on_vault_secret_captured("gmail:token", ref)  # Lần gọi thứ 2 liên tiếp

    # Bot chỉ gửi đúng 1 tin nhắn vào chat 777
    assert len(bot.sent) == 1
    assert bot.sent[0]["chat_id"] == 777
    assert "Đã nhận và lưu bí mật vào Kho an toàn" in bot.sent[0]["text"]
    assert "gmail:token" in bot.sent[0]["text"]
    await memory.close()


@pytest.mark.asyncio
async def test_vault_request_card_idempotent_and_restart_recovery(cfg):
    """(4) Thẻ yêu cầu bí mật Vault không phát 2 lần; cập nhật tại chỗ khi đổi mô tả; phục hồi qua KV sau restart."""
    cfg_base = _cfg(cfg)
    memory = await open_memory(cfg_base)
    surface = TelegramSurface(
        cfg_base, agent=None, memory=memory,
        dossier=Dossier.load(cfg_base.dossier_dir),
    )
    bot = FakeBot()
    surface.bot = bot

    # 1. Phát thẻ lần đầu (02:22)
    info1 = {
        "label": "google:client_secret",
        "description": "Cần để kết nối Gmail",
        "chat_id": 888,
    }
    sent1 = await surface.send_vault_card_to_owner(info1)
    assert sent1 is True
    assert len(bot.sent) == 1
    assert "Cần để kết nối Gmail" in bot.sent[0]["text"]

    # 2. Phát lại cùng yêu cầu sau đó (02:24, lệch nhẹ mô tả)
    info2 = {
        "label": "google:client_secret",
        "description": "Cần Client Secret để lấy refresh token Gmail",
        "chat_id": 888,
    }
    sent2 = await surface.send_vault_card_to_owner(info2)
    assert sent2 is True
    # Không gửi thêm tin nhắn mới (vẫn chỉ 1 tin trong bot.sent)
    assert len(bot.sent) == 1
    # Thẻ cũ đã được sửa tại chỗ với mô tả mới
    assert len(bot.edited) == 1
    assert "Cần Client Secret để lấy refresh token Gmail" in bot.edited[0][0]

    # 3. Giả lập bot bị restart: khởi tạo instance surface mới với cùng memory DB
    surface_after_restart = TelegramSurface(
        cfg_base, agent=None, memory=memory,
        dossier=Dossier.load(cfg_base.dossier_dir),
    )
    bot2 = FakeBot()
    surface_after_restart.bot = bot2

    # Agent trong phiên mới cố gắng phát lại thẻ cho google:client_secret
    sent3 = await surface_after_restart.send_vault_card_to_owner(info2)
    assert sent3 is True
    # Nhờ kiểm tra trạng thái đã phát qua KV store, KHÔNG gửi thêm thẻ mới nào
    assert len(bot2.sent) == 0

    await memory.close()


@pytest.mark.asyncio
async def test_telegram_incoming_message_deduplication(cfg):
    """(5) Khử trùng tin nhắn đến: update lặp từ Telegram bị bỏ qua."""
    cfg_base = _cfg(cfg)
    memory = await open_memory(cfg_base)
    surface = TelegramSurface(
        cfg_base, agent=None, memory=memory,
        dossier=Dossier.load(cfg_base.dossier_dir),
    )

    msg = MockMessage(chat_id=100, message_id=555, text="Hello")
    assert surface._is_duplicate_message(msg) is False
    # Cùng tin nhắn gửi lại lần 2
    assert surface._is_duplicate_message(msg) is True

    # Tin nhắn khác thì nhận bình thường
    msg2 = MockMessage(chat_id=100, message_id=556, text="Hello 2")
    assert surface._is_duplicate_message(msg2) is False

    await memory.close()


@pytest.mark.asyncio
async def test_approval_card_deduplication(cfg):
    """Thẻ phê duyệt: không phát trùng lặp cho cùng một approval_id."""
    cfg_base = _cfg(cfg)
    memory = await open_memory(cfg_base)
    policy = PolicyEngine(cfg_base.policy_path, memory=memory)
    broker = ApprovalBroker(policy=policy, timeout_s=30)
    surface = TelegramSurface(
        cfg_base, agent=None, memory=memory,
        dossier=Dossier.load(cfg_base.dossier_dir),
        policy=policy, broker=broker
    )
    bot = FakeBot()
    surface.bot = bot

    payload = {
        "approval_id": "appr_dedup_1",
        "tool": "run_command",
        "group": "shell",
        "summary": "ls -la",
        "target": "ls",
    }
    broker.open("appr_dedup_1", payload)

    # Gửi lần 1
    msg_id_1 = await surface.send_approval_card(555, None, payload)
    assert msg_id_1 is not None
    assert len(bot.sent) == 1

    # Gửi lần 2 cho cùng approval_id
    msg_id_2 = await surface.send_approval_card(555, None, payload)
    assert msg_id_2 == msg_id_1
    assert len(bot.sent) == 1  # Vẫn chỉ có 1 thẻ duy nhất

    await memory.close()
