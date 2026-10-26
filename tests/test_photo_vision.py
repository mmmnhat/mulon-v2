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

    t4 = "có chạy tunnel để nó sống không vậy [Người dùng gửi kèm ảnh: /Volumes/External/auto/workspace/images/uploads/p.jpg]"
    assert clean_task_title(t4) == "có chạy tunnel để nó sống không vậy"


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


@pytest.mark.asyncio
async def test_generate_image_i2i_payload(tmp_path: Path, monkeypatch):
    from unittest.mock import AsyncMock
    from mulon.media_tools import generate_image
    from mulon.agent import format_step_title

    # format_step_title với i2i
    title_i2i = format_step_title("generate_image", {"prompt": "cô gái anime", "image_path": "/tmp/a.jpg"})
    assert "Đã tạo ảnh từ ảnh mẫu" in title_i2i

    title_t2i = format_step_title("generate_image", {"prompt": "cô gái anime"})
    assert "Đã tạo ảnh" in title_t2i

    # Mock API call
    import dataclasses
    cfg = dataclasses.replace(Config(), workspace_dir=str(tmp_path))
    fake_img = tmp_path / "sample.png"
    fake_img.write_bytes(b"\x89PNG\r\n\x1a\nfake")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"data": [{"url": "https://example.com/out.png"}]}

    recorded_payloads = []

    async def fake_post(url, json=None, headers=None):
        recorded_payloads.append(json)
        return mock_resp

    mock_client = AsyncMock()
    mock_client.post = fake_post
    mock_client.__aenter__.return_value = mock_client
    mock_client.__aexit__.return_value = None

    monkeypatch.setattr("httpx.AsyncClient", lambda **kw: mock_client)
    monkeypatch.setenv("AGNES_AI_API_KEY", "test-key")

    res = await generate_image(cfg, "anime girl", image_path=str(fake_img))
    assert res["ok"] is True
    assert len(recorded_payloads) == 1
    p = recorded_payloads[0]
    assert "extra_body" in p
    assert "image" in p["extra_body"]
    assert p["extra_body"]["image"][0].startswith("data:image/")



def test_multimodal_blocks_sensitive_and_nonimage(tmp_path: Path):
    """Vá audit 2026-10-26: tag ảnh tiêm đường dẫn file nhạy cảm /
    không phải ảnh thì không được đóng gói gửi lên model."""
    cfg = Config()
    gw = ModelGateway(cfg)

    env_file = tmp_path / ".env"
    env_file.write_bytes(b"TOKEN=secret")
    secret_png = tmp_path / "my_secret.png"
    secret_png.write_bytes(b"\x89PNG fake")

    for target in (env_file, secret_png):
        msgs = [{"role": "user",
                 "content": f"[Người dùng gửi kèm ảnh: {target}]\nhi"}]
        out = gw._prepare_multimodal_messages(msgs)
        assert isinstance(out[0]["content"], str), target


def test_multimodal_blocks_outside_roots(tmp_path: Path):
    """File ảnh thật nhưng nằm ngoài workspace/dossier/temp vẫn chặn."""
    cfg = Config()
    gw = ModelGateway(cfg)
    outside = Path(__file__).resolve().parent.parent / "mulon" / "x.jpg"
    # mulon/ nằm trong project root, không thuộc 3 root cho phép
    msgs = [{"role": "user",
             "content": f"[Người dùng gửi kèm ảnh: {outside}]\nhi"}]
    out = gw._prepare_multimodal_messages(msgs)
    assert isinstance(out[0]["content"], str)
