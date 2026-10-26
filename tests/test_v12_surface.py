"""1.2.0 Khối 1+3: menu lệnh, Direct Link trong group, thẻ duyệt
tự gỡ (resolve qua inline + hết hạn), người lạ không resolve được."""

import asyncio
from dataclasses import replace
from types import SimpleNamespace

from mulon.approvals import ApprovalBroker
from mulon.context import Dossier
from mulon.policy import PolicyEngine
from mulon.telegram_bot import BOT_COMMANDS, TelegramSurface, \
    webapp_direct_link
from tests.conftest import open_memory

OWNER = 42


class FakeBot:
    id = 999
    username = "mulon_bot"

    def __init__(self):
        self.sent = []
        self.deleted = []
        self.edited = []
        self.commands = None
        self._next_id = 500

    async def send_message(self, chat_id, text, **kw):
        self._next_id += 1
        self.sent.append({"chat_id": chat_id, "text": text, **kw})
        return SimpleNamespace(message_id=self._next_id)

    async def delete_message(self, chat_id, message_id):
        self.deleted.append((chat_id, message_id))

    async def edit_message_text(self, text, **kw):
        self.edited.append((text, kw))

    async def edit_message_reply_markup(self, **kw):
        pass

    async def set_my_commands(self, commands):
        self.commands = commands


def _cfg(cfg, **kw):
    base = dict(allowed_user_id=OWNER, telegram_bot_token="t",
                webapp_url="https://tunnel.example",
                webapp_app_name="panel",
                approval_card_action="delete")
    base.update(kw)
    return replace(cfg, **base)


async def _surface(cfg, timeout=30.0):
    memory = await open_memory(cfg)
    policy = PolicyEngine(cfg.policy_path, memory=memory)
    broker = ApprovalBroker(policy=policy, timeout_s=timeout)
    surface = TelegramSurface(
        cfg, agent=None, memory=memory,
        dossier=Dossier.load(cfg.dossier_dir), policy=policy,
        broker=broker)
    bot = FakeBot()
    bot._me_username = "mulon_bot"
    surface.bot = bot
    return surface, broker, memory, bot


def test_commands_registered_include_menu():
    names = [c for c, _ in BOT_COMMANDS]
    assert "menu" in names
    for expected in ("start", "status", "new", "memory", "quyen",
                     "approvals", "vault", "setup_topics", "chatphu"):
        assert expected in names
    assert len(names) == len(set(names))  # không trùng
    assert all(desc for _, desc in BOT_COMMANDS)


def test_direct_link_shape():
    cfg = SimpleNamespace(webapp_url="https://t.example",
                          webapp_app_name="panel")
    link = webapp_direct_link(cfg, "mulon_bot", "approve_ab12")
    assert link == ("https://t.me/mulon_bot/panel"
                    "?startapp=approve_ab12&mode=compact")
    assert webapp_direct_link(cfg, None, "panel") is None
    empty = SimpleNamespace(webapp_url="", webapp_app_name="panel")
    assert webapp_direct_link(empty, "mulon_bot", "panel") is None


async def test_menu_payload_with_and_without_config(cfg):
    surface, broker, memory, bot = await _surface(_cfg(cfg))
    text, kb = surface.menu_payload()
    assert kb is not None
    btn = kb.inline_keyboard[0][0]
    assert btn.url == ("https://t.me/mulon_bot/panel"
                       "?startapp=panel&mode=compact")
    # Thiếu cấu hình -> hướng dẫn + không nút.
    surface2, _, memory2, _ = await _surface(
        replace(cfg, allowed_user_id=OWNER))
    text2, kb2 = surface2.menu_payload()
    assert kb2 is None and "BotFather" in text2
    await memory.close()
    await memory2.close()


def _all_buttons(kb):
    return [b for row in kb.inline_keyboard for b in row]


async def test_approval_keyboard_group_uses_direct_link(cfg):
    surface, broker, memory, bot = await _surface(_cfg(cfg))
    kb = surface.approval_keyboard("ab12")
    urls = [b.url for b in _all_buttons(kb) if getattr(b, "url", None)]
    assert urls == ["https://t.me/mulon_bot/panel"
                    "?startapp=approve_ab12&mode=compact"]
    callbacks = [b.callback_data for b in _all_buttons(kb)
                 if getattr(b, "callback_data", None)]
    assert callbacks == ["appr:1:ab12", "appr:0:ab12", "appr:2:ab12"]
    await memory.close()


async def test_approval_keyboard_fallback_inline_only(cfg):
    surface, broker, memory, bot = await _surface(
        replace(cfg, allowed_user_id=OWNER))
    kb = surface.approval_keyboard("ab12")
    assert all(not getattr(b, "url", None)
               for b in _all_buttons(kb))
    assert len(_all_buttons(kb)) == 3  # chỉ inline dự phòng
    await memory.close()


_PAYLOAD = {"approval_id": "c1", "tool": "run_command",
            "group": "shell", "summary": "command=ls",
            "session_key": "sk", "task_id": "t1"}


async def test_card_lifecycle_resolve_via_inline_deletes(cfg):
    surface, broker, memory, bot = await _surface(_cfg(cfg))
    broker.open("c1", dict(_PAYLOAD))
    waiter = asyncio.create_task(broker.wait("c1"))
    mid = await surface.send_approval_card(777, None, dict(_PAYLOAD))
    assert mid is not None and len(bot.sent) == 1
    ok, note = await surface.handle_approval_callback(
        "appr:1:c1", OWNER)
    assert ok and "Đã duyệt" in note
    record = await waiter
    assert record["outcome"] == "approved"
    assert (777, mid) in bot.deleted  # thẻ TỰ GỠ sau quyết định
    await memory.close()


async def test_card_lifecycle_expiry_deletes(cfg):
    surface, broker, memory, bot = await _surface(
        _cfg(cfg), timeout=0.05)
    payload = dict(_PAYLOAD, approval_id="c2")
    broker.open("c2", payload)
    waiter = asyncio.create_task(broker.wait("c2"))
    mid = await surface.send_approval_card(777, 12, payload)
    record = await waiter
    assert record["outcome"] == "expired"
    assert (777, mid) in bot.deleted  # hết hạn cũng gỡ thẻ
    await memory.close()


async def test_card_structure_rich_and_chat_first(cfg):
    """Thẻ duyệt là card trong chat: dòng 1 hành động lời thường,
    bảng trường Hành động/Đích/Chi tiết, hạn thẻ; hàng nút chính
    là 3 nút inline; nút app chỉ là phụ hàng dưới."""
    surface, broker, memory, bot = await _surface(_cfg(cfg))
    payload = dict(_PAYLOAD, approval_id="c9",
                   target="workspace/tmp/*")
    broker.open("c9", payload)
    waiter = asyncio.create_task(broker.wait("c9"))
    await surface.send_approval_card(777, None, payload)
    sent = bot.sent[0]
    text = sent["text"]
    assert "Chạy lệnh hệ thống" in text      # dòng 1 lời thường
    assert "Hành động:" in text
    assert "Đích:" in text and "workspace/tmp" in text
    assert "Chi tiết:" in text and "command=ls" in text
    assert "hết hạn" in text and "Chặn" in text
    kb = sent["reply_markup"]
    row1 = kb.inline_keyboard[0]
    assert [b.callback_data for b in row1] == [
        "appr:1:c9", "appr:0:c9", "appr:2:c9"]  # quyết ngay tại thẻ
    row2 = kb.inline_keyboard[1]
    assert len(row2) == 1 and row2[0].text == "Xem chi tiết"
    assert "startapp=approve_c9" in row2[0].url
    broker.resolve("c9", False)
    await waiter
    await memory.close()


async def test_stranger_cannot_resolve(cfg):
    surface, broker, memory, bot = await _surface(_cfg(cfg))
    payload = dict(_PAYLOAD, approval_id="c3")
    broker.open("c3", payload)
    ok, note = await surface.handle_approval_callback(
        "appr:1:c3", 999999)
    assert not ok and "Chỉ chủ nhân" in note
    assert broker.is_pending("c3")  # vẫn chờ — chưa bị resolve
    assert broker.resolve("c3", False) is True  # dọn dẹp
    await broker.wait("c3")
    await memory.close()
