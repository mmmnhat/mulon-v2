"""1.2.0 bổ sung: chọn màu chủ đề (Cài đặt → Giao diện) + thẻ
"Thiết bị & hệ thống". Theme chỉ đổi họ hue nhận diện, lưu kv
phía server và phản ánh qua /api/state.profile.theme; system
lấy dữ kiện thật của máy chạy (hostname/uptime), proxy kiểm
bằng TCP — không bịa danh sách thiết bị."""

import socket
from dataclasses import replace
from pathlib import Path

import pytest
from aiohttp import ClientSession

import mulon
from mulon.approvals import ApprovalBroker
from mulon.connectors import build_default_connectors
from mulon.context import Dossier
from mulon.policy import PolicyEngine
from mulon.tools import build_default_registry
from mulon.vault import VaultStore
from mulon.webapp_server import THEME_KEYS, WebAppServer
from tests.conftest import open_memory
from tests.test_v12_webapp_auth import TOKEN, OWNER, make_init_data

HTML = (Path(__file__).resolve().parent.parent / "mulon" / "webapp"
        / "index.html").read_text(encoding="utf-8")
HEADERS = {"X-Telegram-Init-Data": make_init_data()}


async def _start(cfg):
    cfg2 = replace(cfg, telegram_bot_token=TOKEN,
                   allowed_user_id=OWNER, webapp_port=0)
    memory = await open_memory(cfg2)
    policy = PolicyEngine(cfg2.policy_path, memory=memory)
    broker = ApprovalBroker(policy=policy, timeout_s=30)
    server = WebAppServer(
        cfg2, memory=memory, policy=policy, broker=broker,
        connectors=build_default_connectors(cfg2), mcp_manager=None,
        vault_store=VaultStore(cfg2.vault_path),
        registry=build_default_registry(cfg2, memory),
        dossier=Dossier.load(cfg2.dossier_dir), skills=None)
    assert await server.start()
    return memory, server


@pytest.fixture
async def app(cfg):
    memory, server = await _start(cfg)
    yield memory, server
    await server.stop()
    await memory.close()


def _url(server, path):
    return f"http://127.0.0.1:{server.port}{path}"


async def _get_state(server):
    async with ClientSession() as s:
        async with s.get(_url(server, "/api/state"),
                         headers=HEADERS) as r:
            assert r.status == 200
            return await r.json()


# ---------------- theme ----------------

async def test_theme_defaults_to_lavender(app):
    _, server = app
    state = await _get_state(server)
    assert state["profile"]["theme"] == "lavender"


async def test_theme_post_persists_and_state_reflects(app):
    memory, server = app
    async with ClientSession() as s:
        async with s.post(_url(server, "/api/profile/theme"),
                          headers=HEADERS,
                          json={"theme": "blue"}) as r:
            assert r.status == 200
            data = await r.json()
    assert data == {"ok": True, "theme": "blue"}
    assert await memory.kv_get("webapp_theme") == "blue"
    state = await _get_state(server)
    assert state["profile"]["theme"] == "blue"


async def test_theme_all_allowed_keys_accepted(app):
    _, server = app
    async with ClientSession() as s:
        for key in THEME_KEYS:
            async with s.post(_url(server, "/api/profile/theme"),
                              headers=HEADERS,
                              json={"theme": key}) as r:
                assert r.status == 200, key


async def test_theme_invalid_rejected_400(app):
    _, server = app
    async with ClientSession() as s:
        for bad in ("neon", "", "LAVENDER"):
            async with s.post(_url(server, "/api/profile/theme"),
                              headers=HEADERS,
                              json={"theme": bad}) as r:
                assert r.status == 400, bad
        async with s.post(_url(server, "/api/profile/theme"),
                          headers=HEADERS, json={}) as r:
            assert r.status == 400


async def test_theme_requires_auth(app):
    _, server = app
    async with ClientSession() as s:
        async with s.post(_url(server, "/api/profile/theme"),
                          json={"theme": "blue"}) as r:
            assert r.status == 403


# ---------------- system ----------------

async def test_state_system_fields_real(app):
    _, server = app
    state = await _get_state(server)
    sysinfo = state["system"]
    # hostname/uptime lấy thật từ chính máy đang chạy test.
    assert sysinfo["hostname"] == socket.gethostname()
    assert sysinfo["os"]
    assert sysinfo["version"] == mulon.__version__
    assert isinstance(sysinfo["uptime_s"], int)
    assert sysinfo["uptime_s"] >= 0
    # Proxy: trạng thái thuộc tập trung thực, không khẳng định bừa.
    assert sysinfo["proxy"]["status"] in ("ok", "down", "unknown")
    assert "detail" in sysinfo["proxy"]
    assert isinstance(sysinfo["scheduler_enabled"], bool)
    assert isinstance(sysinfo["heartbeat_enabled"], bool)


async def test_state_system_viewer_from_initdata(app):
    _, server = app
    state = await _get_state(server)
    viewer = state["system"]["viewer"]
    # make_init_data ký user id=OWNER, first_name="Chủ".
    assert viewer["id"] == OWNER
    assert viewer["name"] == "Chủ"


# ---------------- frontend ----------------

def test_frontend_theme_swatches():
    assert "Màu chủ đề" in HTML
    assert 'id="theme-swatches"' in HTML
    assert 'class="swatch"' in HTML or '"swatch"' in HTML
    # Đủ 6 họ màu + nhãn tiếng Việt. (Theme "Đất nung" đã gỡ
    # cùng đợt bỏ clay khỏi app — user chốt 2026-10-24.)
    for label in ("Tím Mulon", "Xanh dương", "Hồng", "Đào",
                  "Xanh lá", "Chì"):
        assert label in HTML
    for key in ("lavender", "blue", "pink", "peach", "green",
                "graphite"):
        assert key in HTML
    # Mặc định tím Mulon + áp ngay bằng localStorage + đồng bộ API.
    assert "localStorage" in HTML
    assert "mulon-theme" in HTML
    assert "/api/profile/theme" in HTML


def test_frontend_system_screen():
    assert 'id="screen-system"' in HTML
    assert "Thiết bị &amp; hệ thống" in HTML or \
        "Thiết bị & hệ thống" in HTML
    assert "Máy đang chạy Mulon" in HTML
    assert "Phiên này" in HTML
    # Trung thực: nói rõ không ghép thiết bị.
    assert "không ghép nối thiết bị" in HTML
