import base64
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mulon.agent import clean_task_title
from mulon.config import Config
from mulon.gateway import ModelGateway
from mulon.telegram_bot import TelegramSurface, format_reply_context


def test_clean_task_title_with_photo():
    t1 = "[Người dùng gửi kèm ảnh: /tmp/p.jpg]\ntạo ảnh character sheets mẫu nữ"
    assert clean_task_title(t1) == "tạo ảnh character sheets mẫu nữ"

    t2 = "[Người dùng gửi một tấm ảnh: /tmp/p.jpg]"
    assert clean_task_title(t2) == "Xử lý hình ảnh gửi kèm"

    t3 = "[Đang trả lời tin của ní: \"tạo ảnh\"]\n[Người dùng gửi kèm ảnh: /tmp/p.jpg]\ntạo ảnh character sheets"
    assert clean_task_title(t3) == "tạo ảnh character sheets"


def test_format_reply_context_photo():
    msg = MagicMock()
    rep = MagicMock()
    rep.text = None
    rep.caption = None
    rep.document = None
    rep.photo = [MagicMock()]
    rep.from_user.first_name = "Ní"
    msg.reply_to_message = rep

    res = format_reply_context(msg, "tạo ảnh tương tự")
    assert '[Đang trả lời tin của Ní: "[Hình ảnh]"]' in res
    assert "tạo ảnh tương tự" in res


def test_multimodal_expansion(tmp_path: Path):
    cfg = Config()
    gw = ModelGateway(cfg)

    # Tạo một file ảnh giả lập
    fake_img = tmp_path / "test.jpg"
    fake_img.write_bytes(b"\xff\xd8\xff\xe0fakejpeg")

    msgs = [
        {"role": "system", "content": "You are Mulon"},
        {"role": "user", "content": f"[Người dùng gửi kèm ảnh: {fake_img}]\ntạo ảnh character sheet"},
    ]

    expanded = gw._prepare_multimodal_messages(msgs)
    assert len(expanded) == 2
    user_msg = expanded[1]
    assert user_msg["role"] == "user"
    assert isinstance(user_msg["content"], list)
    assert user_msg["content"][0]["type"] == "text"
    assert user_msg["content"][1]["type"] == "image_url"
    assert user_msg["content"][1]["image_url"]["url"].startswith("data:image/jpeg;base64,")


def test_telegram_bot_has_photo_handler():
    cfg = Config()
    memory = MagicMock()
    agent = MagicMock()
    dossier = MagicMock()
    bot = TelegramSurface(cfg, memory, agent, dossier)
    # Kiểm tra router của dp có handler photo
    handlers = bot.dp.message.handlers
    assert len(handlers) > 0
    # Phải có ít nhất 1 handler cho photo
    has_photo = any(
        "on_photo" in str(getattr(h.callback, "__name__", ""))
        for h in handlers
    )
    assert has_photo, "Bot phải đăng ký on_photo handler"
