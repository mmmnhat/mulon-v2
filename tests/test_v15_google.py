"""1.5.0 — Google connectors (Gmail + Google Calendar).

Transport HTTP giả lập toàn bộ bề mặt Google: token endpoint,
Gmail API, Calendar API. Kiểm: ủy quyền (auth-url, callback
state 1 lần), refresh token vào Vault, search/read/send,
list/create/delete sự kiện, health 3 trạng thái, state cho
Mini App (nút Kết nối + mục quyền connector:gmail).
"""

import base64
import json
from dataclasses import replace

import pytest
from aiohttp import ClientSession

from mulon.approvals import ApprovalBroker
from mulon.connectors import build_default_connectors
from mulon.context import Dossier
from mulon.google_conn import (GMAIL_API, LBL_EMAIL, LBL_REFRESH,
                               TOKEN_URL, GoogleAuth, _vault_get)
from mulon.policy import PolicyEngine
from mulon.tools import build_default_registry
from mulon.vault import VaultStore
from mulon.webapp_server import WebAppServer
from tests.conftest import open_memory
from tests.test_v12_webapp_auth import TOKEN as _TOK, OWNER, make_init_data


def b64(text: str) -> str:
    return base64.urlsafe_b64encode(text.encode()).decode()


class FakeGoogle:
    """Transport giả: khớp URL theo hậu tố, ghi lại mọi call."""

    def __init__(self):
        self.calls = []
        self.refresh_count = 0

    async def __call__(self, method, url, params=None,
                       json_body=None, headers=None):
        self.calls.append({"method": method, "url": url,
                           "params": params, "json": json_body,
                           "headers": headers or {}})
        if url == TOKEN_URL:
            if (json_body or {}).get("grant_type") == "refresh_token":
                self.refresh_count += 1
                return 200, {"access_token": "AT-FAKE",
                             "expires_in": 3600}
            return 200, {"refresh_token": "RT-FAKE",
                         "access_token": "AT-FAKE",
                         "expires_in": 3600}
        if url.endswith("/profile"):
            return 200, {"emailAddress": "owner@example.com",
                         "messagesTotal": 42}
        if url.endswith("/messages") and method == "GET":
            return 200, {"messages": [{"id": "m1"}, {"id": "m2"}]}
        if "/messages/" in url and method == "GET":
            mid = url.rsplit("/", 1)[1]
            if (params or {}).get("format") == "metadata":
                return 200, {
                    "id": mid, "snippet": "trích đoạn",
                    "payload": {"headers": [
                        {"name": "Subject", "value": "Hóa đơn"},
                        {"name": "From",
                         "value": "bank@example.com"},
                        {"name": "Date",
                         "value": "Fri, 24 Oct 2026 09:00:00 +0700"},
                    ]}}
            return 200, {
                "id": mid,
                "payload": {
                    "headers": [
                        {"name": "Subject", "value": "Hóa đơn"},
                        {"name": "From",
                         "value": "bank@example.com"},
                        {"name": "To", "value": "owner@example.com"},
                        {"name": "Date", "value": "Fri, 24 Oct 2026"},
                    ],
                    "mimeType": "multipart/alternative",
                    "parts": [
                        {"mimeType": "text/plain",
                         "body": {"data": b64("Nội dung thư mẫu")}},
                        {"mimeType": "text/html",
                         "body": {"data": b64("<p>bản html</p>")}},
                    ]}}
        if url.endswith("/messages/send"):
            return 200, {"id": "sent-1", "threadId": "th-1"}
        if "/events" in url and method == "GET":
            return 200, {"items": [{
                "id": "ev1", "summary": "Họp đội",
                "start": {"dateTime": "2026-10-25T09:00:00+07:00"},
                "end": {"dateTime": "2026-10-25T10:00:00+07:00"},
                "location": "Online", "description": "họp tuần"}]}
        if "/events" in url and method == "POST":
            return 200, {"id": "ev-new",
                         "htmlLink": "https://calendar.google.com/ev"}
        if "/events/" in url and method == "DELETE":
            return 204, {}
        return 404, {"error": {"message": "không khớp fake"}}


def _auth(cfg, tmp_path, fake, connected=True):
    cfg2 = replace(cfg, google_client_id="CID",
                   google_client_secret="CSEC",
                   webapp_url="https://tunnel.example")
    vault = VaultStore(tmp_path / "vault.json")
    if connected:
        vault.put(LBL_REFRESH, "RT-FAKE")
    return GoogleAuth(cfg2, vault, transport=fake), vault


# ---------- auth / vault ----------

async def test_auth_url_scopes_and_redirect(cfg, tmp_path):
    auth, _ = _auth(cfg, tmp_path, FakeGoogle(), connected=False)
    url = auth.build_auth_url("STATE123")
    assert "accounts.google.com" in url
    assert "state=STATE123" in url
    assert "gmail.send" in url and "calendar.events" in url
    assert "redirect_uri=https%3A%2F%2Ftunnel.example" in url
    assert auth.configured() is True
    assert auth.connected() is False


async def test_exchange_code_stores_refresh_and_email(cfg,
                                                      tmp_path):
    fake = FakeGoogle()
    auth, vault = _auth(cfg, tmp_path, fake, connected=False)
    res = await auth.exchange_code("CODE-1")
    assert res["ok"] is True
    assert _vault_get(vault, LBL_REFRESH) == "RT-FAKE"
    assert _vault_get(vault, LBL_EMAIL) == "owner@example.com"
    assert auth.connected() is True
    # không rò rỉ secret vào kết quả
    assert "RT-FAKE" not in json.dumps(res)


async def test_disconnect_clears_vault(cfg, tmp_path):
    auth, vault = _auth(cfg, tmp_path, FakeGoogle())
    auth.disconnect()
    assert _vault_get(vault, LBL_REFRESH) is None
    assert auth.connected() is False


# ---------- gmail ----------

async def test_gmail_search_read_send(cfg, tmp_path):
    fake = FakeGoogle()
    auth, _ = _auth(cfg, tmp_path, fake)
    from mulon.google_conn import GmailConnector

    conn = GmailConnector(auth)
    out = await conn.call("search", {"query": "hóa đơn",
                                     "max_results": 5})
    assert out["ok"] and out["count"] == 2
    assert out["messages"][0]["subject"] == "Hóa đơn"
    assert out["messages"][0]["from"] == "bank@example.com"

    msg = await conn.call("read", {"id": "m1"})
    assert msg["ok"] and msg["body"] == "Nội dung thư mẫu"

    sent = await conn.call("send", {"to": "a@b.c",
                                    "subject": "Chào",
                                    "body": "thân thư"})
    assert sent["ok"] and sent["id"] == "sent-1"
    send_call = [c for c in fake.calls
                 if c["url"].endswith("/messages/send")][0]
    raw = base64.urlsafe_b64decode(
        send_call["json"]["raw"]).decode()
    assert "Subject: =?" in raw or "Chào" in raw
    assert fake.refresh_count >= 1  # đã qua refresh token


async def test_gmail_health_states(cfg, tmp_path):
    from mulon.google_conn import GmailConnector

    fake = FakeGoogle()
    # chưa cấu hình
    vault = VaultStore(tmp_path / "v1.json")
    auth0 = GoogleAuth(replace(cfg, google_client_id="",
                               google_client_secret=""),
                       vault, transport=fake)
    h = await GmailConnector(auth0).health_check()
    assert h["ok"] is False and h["configured"] is False
    # có client, chưa kết nối
    auth1, _ = _auth(cfg, tmp_path, fake, connected=False)
    h = await GmailConnector(auth1).health_check()
    assert h["ok"] is False and h["connected"] is False
    # đã kết nối
    auth2, _ = _auth(cfg, tmp_path, fake, connected=True)
    h = await GmailConnector(auth2).health_check()
    assert h["ok"] is True


# ---------- calendar ----------

async def test_calendar_list_create_delete(cfg, tmp_path):
    from mulon.google_conn import GCalendarConnector

    fake = FakeGoogle()
    auth, _ = _auth(cfg, tmp_path, fake)
    conn = GCalendarConnector(auth, default_tz="Asia/Ho_Chi_Minh")
    out = await conn.call("list_events", {"days": 7})
    assert out["ok"] and out["count"] == 1
    assert out["events"][0]["summary"] == "Họp đội"
    made = await conn.call("create_event", {
        "summary": "Đi khám", "start": "2026-10-26T08:00:00",
        "end": "2026-10-26T09:00:00"})
    assert made["ok"] and made["id"] == "ev-new"
    post = [c for c in fake.calls
            if "/events" in c["url"] and c["method"] == "POST"][0]
    assert post["json"]["start"]["timeZone"] == "Asia/Ho_Chi_Minh"
    gone = await conn.call("delete_event", {"event_id": "ev1"})
    assert gone["ok"]


# ---------- webapp: OAuth flow + state ----------

async def _start(cfg, tmp_path):
    fake = FakeGoogle()
    cfg2 = replace(cfg, telegram_bot_token=_TOK,
                   allowed_user_id=OWNER, webapp_port=0,
                   google_client_id="CID",
                   google_client_secret="CSEC",
                   webapp_url="https://tunnel.example")
    memory = await open_memory(cfg2)
    policy = PolicyEngine(cfg2.policy_path, memory=memory)
    vault = VaultStore(cfg2.vault_path)
    auth = GoogleAuth(cfg2, vault, transport=fake)
    server = WebAppServer(
        cfg2, memory=memory, policy=policy,
        broker=ApprovalBroker(policy=policy, timeout_s=30),
        connectors=build_default_connectors(cfg2, google_auth=auth),
        mcp_manager=None, vault_store=vault,
        registry=build_default_registry(cfg2, memory),
        dossier=Dossier.load(cfg2.dossier_dir), google_auth=auth)
    assert await server.start()
    return cfg2, memory, server, vault


@pytest.fixture
async def app(cfg, tmp_path):
    parts = await _start(cfg, tmp_path)
    yield parts
    await parts[2].stop()
    await parts[1].close()


def _url(server, path):
    return f"http://127.0.0.1:{server.port}{path}"


def _headers():
    return {"X-Telegram-Init-Data": make_init_data()}


async def test_oauth_flow_end_to_end(app):
    _, memory, server, vault = app
    async with ClientSession() as s:
        async with s.get(_url(server, "/api/google/auth-url"),
                         headers=_headers()) as r:
            assert r.status == 200
            body = await r.json()
        assert body["url"].startswith(
            "https://accounts.google.com/")
        saved = json.loads(
            await memory.kv_get("google_oauth_state"))
        # callback sai state -> trang báo lỗi, không token
        async with s.get(_url(
                server,
                "/google/callback?code=X&state=SAI")) as r:
            text = await r.text()
        assert "không hợp lệ" in text
        assert _vault_get(vault, LBL_REFRESH) is None
        # lấy state mới (state cũ đã bị xoá sau callback đầu)
        async with s.get(_url(server, "/api/google/auth-url"),
                         headers=_headers()) as r:
            await r.json()
        saved = json.loads(
            await memory.kv_get("google_oauth_state"))
        async with s.get(_url(
                server,
                "/google/callback?code=CODE-9&state="
                + saved["state"])) as r:
            text = await r.text()
        assert "Đã kết nối Google" in text
        assert _vault_get(vault, LBL_REFRESH) == "RT-FAKE"
        # state dùng 1 lần: gọi lại đúng state đó vẫn bị từ chối
        async with s.get(_url(
                server,
                "/google/callback?code=CODE-9&state="
                + saved["state"])) as r:
            text = await r.text()
        assert "không hợp lệ" in text
        # state app: connector gmail có block google + quyền riêng
        async with s.get(_url(server, "/api/state"),
                         headers=_headers()) as r:
            data = await r.json()
        gmail = [c for c in data["connectors"]
                 if c["name"] == "gmail"][0]
        assert gmail["google"]["connected"] is True
        assert gmail["google"]["email"] == "owner@example.com"
        assert "connector:gmail" in data["policy"]["connectors"]
        # ngắt kết nối
        async with s.post(_url(server, "/api/google/disconnect"),
                          headers=_headers(), json={}) as r:
            assert (await r.json())["ok"] is True
        assert _vault_get(vault, LBL_REFRESH) is None


async def test_google_config_api(app):
    _, memory, server, vault = app
    async with ClientSession() as s:
        # GET config ban đầu
        async with s.get(_url(server, "/api/google/config"),
                         headers=_headers()) as r:
            assert r.status == 200
            data = await r.json()
            assert data["ok"] is True
            assert "redirect_uri" in data
            assert data["configured"] is True

        # POST config thiếu client_id -> 400
        async with s.post(_url(server, "/api/google/config"),
                          headers=_headers(),
                          json={"client_id": ""}) as r:
            assert r.status == 400

        # POST lưu client_id và client_secret mới
        async with s.post(_url(server, "/api/google/config"),
                          headers=_headers(),
                          json={"client_id": "NEW-CLIENT-ID.apps.googleusercontent.com",
                                "client_secret": "NEW-SECRET"}) as r:
            assert r.status == 200
            res = await r.json()
            assert res["ok"] is True
            assert res["configured"] is True
            assert res["client_id"] == "NEW-CLIENT-ID.apps.googleusercontent.com"
            assert res["has_client_secret"] is True

        # Kiểm tra GET phản ánh đúng
        async with s.get(_url(server, "/api/google/config"),
                         headers=_headers()) as r:
            assert r.status == 200
            data = await r.json()
            assert data["client_id"] == "NEW-CLIENT-ID.apps.googleusercontent.com"
            assert data["has_client_secret"] is True
