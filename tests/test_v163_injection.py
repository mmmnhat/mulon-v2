"""Kiểm thử thuần cho sửa 1.6.3 (injection/SSRF/proxy).

Không cần mạng, không cần pytest-asyncio: chỉ vòng tĩnh của SSRF
guard (không DNS) và khóa proxy. Kiểm tra DNS/redirect thật nằm
ở mục test cần chạy trên Mac mini trong báo cáo mảng.
"""

import os

import pytest

from mulon.config import validate_proxy_base_url
from mulon.tools import ssrf_error_for_url


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8317/v1",
    "http://localhost/admin",
    "http://foo.localhost/",
    "http://10.0.0.5/",
    "http://172.16.0.9/",
    "http://172.31.255.255/",
    "http://192.168.1.1/",
    "http://169.254.169.254/latest/meta-data/",
    "http://[::1]/",
    "http://[::ffff:127.0.0.1]/",
    "http://0.0.0.0/",
    "ftp://example.com/",
])
def test_ssrf_blocks_private_urls(url):
    assert ssrf_error_for_url(url) is not None


@pytest.mark.parametrize("url", [
    "https://example.com/x",
    "http://172.32.0.9/",  # ngoài 172.16/12
    "http://8.8.8.8/",
])
def test_ssrf_allows_public_urls(url):
    assert ssrf_error_for_url(url) is None


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8317/v1",
    "http://localhost:8317/v1",
    "http://[::1]:8317/v1",
])
def test_proxy_local_allowed(url):
    validate_proxy_base_url(url)


@pytest.mark.parametrize("url", [
    "http://127.0.0.1:8080/v1",
    "http://127.0.0.1/v1",
    "https://example.com:8317/v1",
    "http://192.168.1.1:8317/v1",
    "",
])
def test_proxy_remote_rejected(url, monkeypatch):
    monkeypatch.delenv("MULON_ALLOW_REMOTE_PROXY", raising=False)
    with pytest.raises(ValueError):
        validate_proxy_base_url(url)


def test_proxy_remote_allowed_only_with_explicit_env(monkeypatch):
    monkeypatch.setenv("MULON_ALLOW_REMOTE_PROXY", "1")
    validate_proxy_base_url("https://example.com:8317/v1")
