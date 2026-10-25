"""Kiểm thử tính năng xác thực Google Workspace tự động qua Telegram chat."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch
import pytest

from mulon.telegram_bot import TelegramSurface


@pytest.fixture
def dummy_surface():
    cfg = MagicMock()
    cfg.allowed_user_id = 12345
    cfg.telegram_bot_token = "dummy:token"
    cfg.debounce_seconds = 0.1
    cfg.dossier_dir = "/tmp"
    cfg.workspace_dir = "/tmp"
    cfg.group_mention_only = False

    agent = MagicMock()
    agent.registry = MagicMock()
    agent.cfg = cfg

    memory = MagicMock()
    dossier = MagicMock()
    dossier.bootstrap_pending.return_value = False
    dossier.files = {}

    surf = TelegramSurface(
        cfg, agent, memory, dossier
    )
    return surf


@pytest.mark.asyncio
async def test_handle_oauth_callback_ignores_irrelevant_messages(dummy_surface):
    msg = MagicMock()
    msg.text = "Chào Mulon hôm nay thế nào?"
    handled = await dummy_surface._handle_oauth_callback(msg)
    assert handled is False
    msg.answer.assert_not_called()


@pytest.mark.asyncio
async def test_handle_oauth_callback_success(dummy_surface):
    msg = MagicMock()
    msg.text = "http://localhost:8001/oauth2callback?state=xyz123&code=4/0Atestcode"
    msg.answer = AsyncMock()

    mock_resp = MagicMock()
    mock_resp.status = 200
    mock_resp.read.return_value = b"<html><body>Authentication Successful for user: <strong>test@gmail.com</strong></body></html>"
    mock_resp.__enter__.return_value = mock_resp

    with patch("urllib.request.urlopen", return_value=mock_resp) as mock_urlopen:
        handled = await dummy_surface._handle_oauth_callback(msg)
        assert handled is True
        mock_urlopen.assert_called_once()
        req = mock_urlopen.call_args[0][0]
        assert "http://127.0.0.1:8001/oauth2callback?state=xyz123&code=4/0Atestcode" == req.full_url
        msg.answer.assert_called_once()
        assert "Xác thực Google Workspace thành công" in msg.answer.call_args[0][0]
        assert "test@gmail.com" in msg.answer.call_args[0][0]


@pytest.mark.asyncio
async def test_handle_oauth_callback_expired(dummy_surface):
    import urllib.error
    msg = MagicMock()
    msg.text = "http://localhost:8001/oauth2callback?state=expired_state&code=4/0Atest"
    msg.answer = AsyncMock()

    err = urllib.error.HTTPError("http://127.0.0.1:8001", 500, "Error", {}, MagicMock(read=lambda: b"<p>Invalid or expired OAuth state parameter</p>"))

    with patch("urllib.request.urlopen", side_effect=err):
        handled = await dummy_surface._handle_oauth_callback(msg)
        assert handled is True
        msg.answer.assert_called_once()
        assert "Chưa hoàn tất xác thực" in msg.answer.call_args[0][0]
        assert "/google_auth" in msg.answer.call_args[0][0]


@pytest.mark.asyncio
async def test_get_google_auth_url(dummy_surface):
    dummy_surface.agent.registry.has.return_value = True
    dummy_surface.agent.registry.execute = AsyncMock(return_value={
        "result": "Action required: Authorization URL: https://accounts.google.com/o/oauth2/auth?response_type=code&client_id=123&state=abc Please open."
    })

    url = await dummy_surface._get_google_auth_url()
    assert url == "https://accounts.google.com/o/oauth2/auth?response_type=code&client_id=123&state=abc"
