"""Vá 1.4.1 — đợt vá theo phản ánh thật của owner sau 1.4:

- Công tắc heartbeat THẬT trong Mini App (kv thắng env, áp
  dụng ngay ở engine + API lịch + trạng thái hệ thống).
- Quyền riêng từng connector (policy group connector:<tên>,
  rơi về nhóm "connector"; mục riêng ở màn Quyền).
- Frontend: chợ mở màn con theo danh mục, bỏ ô tìm MCP, bỏ
  card Giá, nhãn capability tiếng Việt, theme nhuộm 60/30/10,
  .field-input đầy bề ngang (Kho responsive).
"""

from dataclasses import replace
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from aiohttp import ClientSession

from mulon.approvals import GROUP_SCOPE_LABELS, ApprovalBroker
from mulon.connectors import build_default_connectors
from mulon.context import Dossier
from mulon.policy import PolicyEngine
from mulon.proactivity import (PROACTIVITY_KV_KEY,
                               ProactivityEngine, effective_enabled)
from mulon.tools import build_default_registry
from mulon.vault import VaultStore
from mulon.webapp_server import INDEX_HTML, WebAppServer
from tests.conftest import open_memory
from tests.test_v12_webapp_auth import TOKEN as _TOK, OWNER, make_init_data

TZ = ZoneInfo("Asia/Ho_Chi_Minh")
IN_HOURS = datetime(2026, 10, 24, 10, 0, tzinfo=TZ)


class _NullGateway:
    calls = 0

    async def complete(self, *a, **k):
        type(self).calls += 1
        raise AssertionError("không được gọi model")


async def _start(cfg, tmp_path):
    cfg2 = replace(cfg, telegram_bot_token=_TOK, allowed_user_id=OWNER, webapp_port=0)
    memory = await open_memory(cfg2)
    policy = PolicyEngine(cfg2.policy_path, memory=memory)
    server = WebAppServer(
        cfg2, memory=memory, policy=policy,
        broker=ApprovalBroker(policy=policy, timeout_s=30),
        connectors=build_default_connectors(cfg2), mcp_manager=None,
        vault_store=VaultStore(cfg2.vault_path),
        registry=build_default_registry(cfg2, memory),
        dossier=Dossier.load(cfg2.dossier_dir))
    assert await server.start()
    return cfg2, memory, server


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


# ---------- heartbeat: công tắc hiệu lực ----------

async def test_heartbeat_kv_override_beats_env(cfg):
    cfg_on = replace(cfg, proactivity_enabled=True)
    cfg_off = replace(cfg, proactivity_enabled=False)
    memory = await open_memory(cfg_on)
    assert await effective_enabled(memory, cfg_on) is True
    await memory.kv_set(PROACTIVITY_KV_KEY, "0")
    assert await effective_enabled(memory, cfg_on) is False
    await memory.kv_set(PROACTIVITY_KV_KEY, "1")
    assert await effective_enabled(memory, cfg_off) is True
    await memory.close()


async def test_heartbeat_engine_skips_when_toggled_off(cfg):
    cfg = replace(cfg, proactivity_enabled=True)
    (cfg.dossier_dir / "HEARTBEAT.md").write_text(
        "# HEARTBEAT\n\n- [ ] Việc mẫu\n", encoding="utf-8")
    memory = await open_memory(cfg)
    await memory.kv_set(PROACTIVITY_KV_KEY, "0")
    engine = ProactivityEngine(cfg, memory, _NullGateway())
    stats = await engine.run_once(now=IN_HOURS)
    assert stats["skipped"] == "disabled"
    assert stats["notes"] == 0
    await memory.close()


async def test_heartbeat_toggle_via_schedule_api(app):
    _, memory, server = app
    async with ClientSession() as s:
        async with s.get(_url(server, "/api/state"),
                         headers=_headers()) as r:
            data = await r.json()
        hb = [i for i in data["schedule"]["items"]
              if i["id"] == "heartbeat"]
        assert hb and hb[0]["toggleable"] is True
        assert hb[0]["enabled"] is False  # env mặc định tắt
        async with s.post(_url(server, "/api/schedule"),
                          headers=_headers(),
                          json={"id": "heartbeat",
                                "enabled": True}) as r:
            assert r.status == 200
            body = await r.json()
        assert body["ok"] is True and body["enabled"] is True
        assert await memory.kv_get(PROACTIVITY_KV_KEY) == "1"
        async with s.get(_url(server, "/api/state"),
                         headers=_headers()) as r:
            data = await r.json()
        hb = [i for i in data["schedule"]["items"]
              if i["id"] == "heartbeat"]
        assert hb[0]["enabled"] is True
        assert data["system"]["heartbeat_enabled"] is True


# ---------- quyền connector ----------

def test_policy_group_prefix_fallback(cfg):
    policy = PolicyEngine(cfg.policy_path)
    policy.set_session_rule("group", "connector", "ask")
    d = policy.decide("connector_call", "connector:gmail")
    assert d.verdict == "ask"  # rơi về nhóm gốc
    policy.set_session_rule("group", "connector:gmail", "deny")
    d = policy.decide("connector_call", "connector:gmail")
    assert d.verdict == "deny"  # rule riêng thắng
    d = policy.decide("connector_call", "connector:drive")
    assert d.verdict == "ask"


async def test_policy_state_has_connector_section(app):
    _, _, server = app
    # "goals" là group lạ từng hiện thô trên máy owner (rule
    # lưu bền) — có nhãn thì hết thô.
    server.policy.set_session_rule("group", "goals", "ask")
    async with ClientSession() as s:
        async with s.get(_url(server, "/api/state"),
                         headers=_headers()) as r:
            data = await r.json()
    pol = data["policy"]
    assert "connector:system" in pol["connectors"]
    assert pol["connector_labels"]["connector:system"] == "system"
    assert all(not g.startswith(("mcp:", "connector:"))
               for g in pol["groups"])
    assert pol["group_labels"].get("goals") == "Quản lý mục tiêu"


def test_goals_group_label_exists():
    assert GROUP_SCOPE_LABELS["goals"] == "quản lý mục tiêu"


# ---------- frontend wiring ----------

def test_frontend_patch_pack_wired():
    html = INDEX_HTML.read_text(encoding="utf-8")
    # Chợ: màn con danh mục + bỏ ô tìm + bỏ card Giá
    assert 'id="screen-mktcat"' in html
    assert '"screen-mktcat":"caidat"' in html  # showSub mới mở được
    assert 'id="mkt-q"' not in html
    assert "Tìm MCP" not in html
    assert '<div class="r-title">Giá</div>' not in html
    # Nhãn capability tiếng Việt
    assert "download_and_run" in html  # key trong bảng nhãn
    assert "Tải về và chạy mã" in html
    # Theme nhuộm cả 3 tầng + thẻ hồ sơ theo theme
    assert '"--paper"' in html and '"--surface2"' in html
    assert "var(--bc1)" in html and "deep2" in html
    # Kho responsive: field-input đầy bề ngang
    assert "display:block; width:100%" in html
    # Việc: câu trống mới nói rõ hỏi đáp không tính là việc
    assert "không tính là việc" in html
