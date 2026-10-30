"""Test chuẩn hóa mã phản hồi lỗi RFC 7807 (Problem Details for HTTP APIs - T-39.5).

Xác thực:
1. 100% phản hồi lỗi trên /api/* đều chứa đủ các trường chuẩn RFC 7807:
   - status (int)
   - title (str)
   - detail (str)
   - error_code (str)
   - type (URN)
   - instance (URI)
2. Bảo toàn 100% tính tương thích ngược (Điều kiện 4 của Muse):
   - ok: False
   - error: message cũ
"""

import json
import pytest
from aiohttp import ClientSession

from mulon.webapp_server import problem_json_response
from tests.test_v12_webapp_api import _start, _stop, _url, make_init_data


@pytest.fixture
async def api_app(cfg):
    parts = await _start(cfg)
    yield parts
    await _stop(parts[1], parts[3])


@pytest.mark.asyncio
async def test_rfc7807_error_auth_forbidden(api_app):
    """Xác thực lỗi 403 khi thiếu initData có đầy đủ trường RFC 7807 và ok: False."""
    _, _, _, server = api_app
    async with ClientSession() as s:
        async with s.get(_url(server, "/api/state")) as r:
            assert r.status == 403
            assert r.content_type == "application/json"
            data = await r.json()

            # 1. Ràng buộc tương thích ngược (Điều kiện 4)
            assert data["ok"] is False
            assert "initData không hợp lệ" in data["error"]

            # 2. Ràng buộc chuẩn RFC 7807
            assert data["status"] == 403
            assert data["title"] == "Forbidden"
            assert data["error_code"] == "invalid_init_data"
            assert data["code"] == "invalid_init_data"
            assert data["type"] == "urn:mulon:error:invalid_init_data"
            assert data["instance"] == "/api/state"
            assert "initData" in data["detail"]


@pytest.mark.asyncio
async def test_rfc7807_error_bad_request(api_app):
    """Xác thực lỗi 400 khi truyền tham số sai có đầy đủ trường RFC 7807."""
    _, _, _, server = api_app
    headers = {"X-Telegram-Init-Data": make_init_data()}
    async with ClientSession() as s:
        async with s.post(
            _url(server, "/api/policy"),
            headers=headers,
            json={"scope": "group", "name": "shell", "verdict": "gia_tri_sai_hoan_toan"},
        ) as r:
            assert r.status == 400
            assert r.content_type == "application/json"
            data = await r.json()

            # 1. Tương thích ngược
            assert data["ok"] is False
            assert "error" in data

            # 2. RFC 7807
            assert data["status"] == 400
            assert data["title"] == "Bad Request"
            assert "error_code" in data
            assert data["code"] == data["error_code"]
            assert data["type"] == f"urn:mulon:error:{data['error_code']}"
            assert data["instance"] == "/api/policy"
            assert len(data["detail"]) > 0


@pytest.mark.asyncio
async def test_rfc7807_error_not_found(api_app):
    """Xác thực lỗi 404 khi truy vấn ID không tồn tại có đầy đủ trường RFC 7807."""
    _, _, _, server = api_app
    headers = {"X-Telegram-Init-Data": make_init_data()}
    async with ClientSession() as s:
        async with s.get(
            _url(server, "/api/profile/facts/999999"),
            headers=headers,
        ) as r:
            assert r.status in (400, 404)
            assert r.content_type == "application/json"
            data = await r.json()

            assert data["ok"] is False
            assert data["status"] == r.status
            assert data["title"] in ("Not Found", "Bad Request")
            assert "error_code" in data
            assert data["instance"] == "/api/profile/facts/999999"
            assert data["type"].startswith("urn:mulon:error:")


@pytest.mark.asyncio
async def test_problem_json_response_helper():
    """Kiểm tra trực tiếp hàm helper problem_json_response."""
    resp = problem_json_response(
        status=422,
        error="Dữ liệu payload không thể xử lý",
        error_code="unprocessable_entity",
        instance="/api/custom",
        extra_key="extra_value",
    )
    assert resp.status == 422
    body = json.loads(resp.body.decode("utf-8"))
    assert body["ok"] is False
    assert body["error"] == "Dữ liệu payload không thể xử lý"
    assert body["status"] == 422
    assert body["title"] == "Unprocessable Entity"
    assert body["error_code"] == "unprocessable_entity"
    assert body["instance"] == "/api/custom"
    assert body["extra_key"] == "extra_value"
    assert body["type"] == "urn:mulon:error:unprocessable_entity"
