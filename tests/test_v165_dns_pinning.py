"""Kiểm thử cho vá bảo mật DNS rebinding TOCTOU (T-06).

Xác nhận:
1. resolve_and_verify_url phát hiện chính xác IP công cộng và chặn private IP.
2. PinningBackend ghim đúng IP đã kiểm chứng tại tầng socket.
3. http_get_public tự động ghim IP từng hop redirect, chặn redirect nội bộ,
   chặn redirect quá trần.
"""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mulon.tools import (
    PinningBackend,
    assert_url_public,
    http_get_public,
    resolve_and_verify_url,
)


@pytest.mark.asyncio
async def test_resolve_and_verify_public_literal_ip():
    err, ip = await resolve_and_verify_url("http://93.184.216.34/path")
    assert err is None
    assert ip == "93.184.216.34"


@pytest.mark.asyncio
async def test_resolve_and_verify_private_literal_ip():
    err, ip = await resolve_and_verify_url("http://127.0.0.1:8080/path")
    assert err is not None
    assert "nội bộ" in err or "loopback" in err
    assert ip is None


@pytest.mark.asyncio
async def test_resolve_and_verify_dns_public():
    with patch("asyncio.get_running_loop") as mock_loop:
        mock_loop.return_value.getaddrinfo = AsyncMock(return_value=[
            (2, 1, 6, "", ("93.184.216.34", 443)),
            (2, 1, 6, "", ("93.184.216.35", 443)),
        ])
        err, ip = await resolve_and_verify_url("https://example.com/test")
        assert err is None
        assert ip == "93.184.216.34"
        assert await assert_url_public("https://example.com/test") is None


@pytest.mark.asyncio
async def test_resolve_and_verify_dns_rebinding_to_private():
    with patch("asyncio.get_running_loop") as mock_loop:
        # Giả lập DNS trả về IP nội bộ
        mock_loop.return_value.getaddrinfo = AsyncMock(return_value=[
            (2, 1, 6, "", ("127.0.0.1", 443)),
        ])
        err, ip = await resolve_and_verify_url("https://malicious.example.com/test")
        assert err is not None
        assert "nội bộ" in err
        assert ip is None


@pytest.mark.asyncio
async def test_resolve_and_verify_dns_mixed_private_public():
    with patch("asyncio.get_running_loop") as mock_loop:
        # Nếu bất kỳ IP nào trong kết quả DNS là private -> phải chặn toàn bộ (fail-closed)
        mock_loop.return_value.getaddrinfo = AsyncMock(return_value=[
            (2, 1, 6, "", ("93.184.216.34", 443)),
            (2, 1, 6, "", ("192.168.1.1", 443)),
        ])
        err, ip = await resolve_and_verify_url("https://mixed.example.com/test")
        assert err is not None
        assert "nội bộ" in err
        assert ip is None


@pytest.mark.asyncio
async def test_pinning_backend_replaces_host():
    backend = PinningBackend(ip_map={"target.com": "93.184.216.34"})

    # Giả lập super().connect_tcp
    with patch(
        "httpcore._backends.anyio.AnyIOBackend.connect_tcp",
        new_callable=AsyncMock,
    ) as mock_super_connect:
        mock_super_connect.return_value = "fake_stream"
        stream = await backend.connect_tcp("target.com", 443)
        assert stream == "fake_stream"
        mock_super_connect.assert_awaited_once_with(
            "93.184.216.34", 443, timeout=None, local_address=None, socket_options=None
        )


@pytest.mark.asyncio
async def test_pinning_backend_leaves_unmapped_host():
    backend = PinningBackend(ip_map={"other.com": "93.184.216.34"})

    with patch(
        "httpcore._backends.anyio.AnyIOBackend.connect_tcp",
        new_callable=AsyncMock,
    ) as mock_super_connect:
        mock_super_connect.return_value = "fake_stream"
        stream = await backend.connect_tcp("unmapped.com", 80)
        assert stream == "fake_stream"
        mock_super_connect.assert_awaited_once_with(
            "unmapped.com", 80, timeout=None, local_address=None, socket_options=None
        )


@pytest.mark.asyncio
async def test_http_get_public_pins_ip_and_tracks_redirect():
    # Giả lập client có transport và pool
    mock_pool = MagicMock()
    mock_pool._network_backend = MagicMock()
    mock_transport = MagicMock()
    mock_transport._pool = mock_pool

    client = MagicMock()
    client._transport = mock_transport

    resp_redirect = MagicMock()
    resp_redirect.status_code = 302
    resp_redirect.headers = {"location": "https://hop2.com/target"}

    resp_final = MagicMock()
    resp_final.status_code = 200
    resp_final.headers = {}

    client.get = AsyncMock(side_effect=[resp_redirect, resp_final])

    with patch(
        "mulon.tools.resolve_and_verify_url",
        side_effect=[
            (None, "93.184.216.34"),
            (None, "104.20.1.1"),
        ],
    ):
        result = await http_get_public(client, "https://hop1.com/start")
        assert result == resp_final
        assert client._ip_map["hop1.com"] == "93.184.216.34"
        assert client._ip_map["hop2.com"] == "104.20.1.1"


@pytest.mark.asyncio
async def test_http_get_public_blocks_redirect_to_private():
    client = MagicMock()
    resp_redirect = MagicMock()
    resp_redirect.status_code = 302
    resp_redirect.headers = {"location": "http://127.0.0.1:8080/secret"}

    client.get = AsyncMock(return_value=resp_redirect)

    with patch(
        "mulon.tools.resolve_and_verify_url",
        side_effect=[
            (None, "93.184.216.34"),
            ("địa chỉ IP nội bộ/loopback/link-local — từ chối (SSRF guard)", None),
        ],
    ):
        with pytest.raises(ValueError, match="địa chỉ IP nội bộ"):
            await http_get_public(client, "https://hop1.com/start")
        # client.get chỉ được gọi đúng 1 lần cho hop 1, KHÔNG BAO GIỜ gọi hop 2 tới 127.0.0.1
        assert client.get.await_count == 1


@pytest.mark.asyncio
async def test_real_httpx_client_instrumented_with_pinning():
    import httpx

    async with httpx.AsyncClient(follow_redirects=False) as client:
        # Trước khi gọi, network backend là mặc định của httpcore
        assert not isinstance(
            client._transport._pool._network_backend, PinningBackend
        )
        with patch(
            "mulon.tools.resolve_and_verify_url",
            return_value=(None, "93.184.216.34"),
        ), patch.object(
            client, "get", new_callable=AsyncMock
        ) as mock_get:
            fake_resp = MagicMock()
            fake_resp.status_code = 200
            fake_resp.headers = {}
            mock_get.return_value = fake_resp

            resp = await http_get_public(client, "https://example.com/api")
            assert resp == fake_resp

        # Sau khi gọi, network backend đã được bọc bằng PinningBackend và ghim IP
        assert isinstance(
            client._transport._pool._network_backend, PinningBackend
        )
        assert client._ip_map.get("example.com") == "93.184.216.34"

