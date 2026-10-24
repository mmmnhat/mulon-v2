"""1.3.0 Gói A: atlas sprite states của avatar Mini App —
route tĩnh danh sách trắng phục vụ atlas + manifest đúng hình
học v0, index.html phát atlas thật (hết CSS keyframes)."""

from dataclasses import replace

import pytest
from aiohttp import ClientSession

from mulon.approvals import ApprovalBroker
from mulon.connectors import build_default_connectors
from mulon.context import Dossier
from mulon.policy import PolicyEngine
from mulon.tools import build_default_registry
from mulon.vault import VaultStore
from mulon.webapp_server import INDEX_HTML, WebAppServer
from tests.conftest import open_memory
from tests.test_v12_webapp_auth import TOKEN as _TOK, OWNER, make_init_data


async def _start(cfg):
    cfg2 = replace(cfg, telegram_bot_token=_TOK,
                   allowed_user_id=OWNER, webapp_port=0)
    memory = await open_memory(cfg2)
    policy = PolicyEngine(cfg2.policy_path, memory=memory)
    server = WebAppServer(
        cfg2, memory=memory, policy=policy,
        broker=ApprovalBroker(policy=policy, timeout_s=30),
        connectors=build_default_connectors(cfg2), mcp_manager=None,
        vault_store=VaultStore(cfg2.vault_path),
        registry=build_default_registry(cfg2, memory),
        dossier=Dossier.load(cfg2.dossier_dir), skills=None)
    assert await server.start()
    return memory, server


@pytest.fixture
async def app(cfg):
    memory, server = await _start(cfg)
    yield server
    await server.stop()
    await memory.close()


def _url(server, path):
    return f"http://127.0.0.1:{server.port}{path}"


async def test_atlas_served_with_png_bytes(app):
    async with ClientSession() as s:
        async with s.get(_url(app, "/app/assets/"
                                   "sprite-sheet-alpha.png")) as r:
            assert r.status == 200
            assert r.content_type == "image/png"
            body = await r.read()
    assert body[:8] == b"\x89PNG\r\n\x1a\n"
    assert len(body) > 100_000  # atlas thật 1280x1280, không stub


async def test_manifest_served_and_geometry_matches_v0(app):
    async with ClientSession() as s:
        async with s.get(_url(app, "/app/assets/"
                                   "mulon-states-manifest.json")) as r:
            assert r.status == 200
            data = await r.json()
    anim = data["animation"]
    assert anim["cellWidth"] == 256 and anim["cellHeight"] == 256
    rows = anim["rows"]
    assert rows["done"] == {**rows["done"], "row": 0,
                            "frames": 5, "fps": 8, "loop": False}
    assert rows["error"]["row"] == 1 and rows["error"]["frames"] == 4
    assert rows["error"]["fps"] == 6 and rows["error"]["loop"] is False
    assert rows["idle"]["row"] == 2 and rows["idle"]["frames"] == 4
    assert rows["idle"]["fps"] == 4 and rows["idle"]["loop"] is True
    assert rows["waiting"]["row"] == 3
    assert rows["waiting"]["loop"] is True
    assert rows["working"]["row"] == 4
    assert rows["working"]["fps"] == 6
    assert rows["working"]["loop"] is True


async def test_unknown_asset_404_and_no_dir_traversal(app):
    headers = {"X-Telegram-Init-Data": make_init_data()}
    async with ClientSession() as s:
        for path in ("/app/assets/nope.png",
                     "/app/assets/../index.html",
                     "/app/assets/%2e%2e%2findex.html"):
            async with s.get(_url(app, path), headers=headers) as r:
                assert r.status == 404, path


def test_frontend_plays_real_atlas_not_css_keyframes():
    html = INDEX_HTML.read_text(encoding="utf-8")
    # Cơ chế sprite thật: nạp atlas + manifest, player theo fps.
    assert "/app/assets/sprite-sheet-alpha.png" in html
    assert "/app/assets/mulon-states-manifest.json" in html
    assert "SPRITE_FALLBACK" in html and "spritePlay" in html
    assert 'id="avatar-sprite"' in html
    # Cơ chế cũ đã gỡ hẳn: không còn keyframes giả trạng thái.
    for gone in ("av-breathe", "av-work", "av-wait", "av-done",
                 "av-err", "st-working", "st-idle"):
        assert gone not in html, gone
    # Fallback họ tím theo theme vẫn còn (chữ cái trên tint).
    assert "--tint-lav" in html and 'id="avatar-letter"' in html
    # Vị trí frame tính theo hình học lưới (cột), không theo số
    # frame của hàng — chia (frames-1) từng làm frame cuối nhảy
    # sang ô trống thứ 5, avatar mất 1 nhịp (render kiểm 1.3.0).
    assert "(cols - 1)" in html
    assert "sprite.frame / (c.frames - 1)" not in html
    # Chữ cái dự phòng ẩn hẳn khi sprite bật (nó từng ló qua
    # phần trong suốt của frame).
    assert ".avatar.sprite-on #avatar-letter" in html
