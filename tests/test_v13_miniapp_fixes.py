"""1.3.0 Gói C: vá Mini App theo phản ánh thật của owner —
Vault nhập ngay trong app (không echo/log giá trị), màn Kỹ
năng đọc được nội dung, tab Việc hiện cả lượt chat."""

from dataclasses import replace

import pytest
from aiohttp import ClientSession

from mulon.approvals import ApprovalBroker
from mulon.connectors import build_default_connectors
from mulon.context import Dossier
from mulon.policy import PolicyEngine
from mulon.skills import SkillCatalog
from mulon.tools import build_default_registry
from mulon.vault import VaultStore
from mulon.webapp_server import INDEX_HTML, WebAppServer
from tests.conftest import open_memory
from tests.test_v12_webapp_auth import TOKEN as _TOK, OWNER, make_init_data

SENTINEL = "SENTINEL-GIA-TRI-VAULT-KHONG-DUOC-LO-987"

SKILL_MD = """---
name: ky-nang-mau
description: Kỹ năng mẫu để kiểm tra màn đọc kỹ năng.
requires:
  env: []
  tools: []
---

# Kỹ năng mẫu

Nội dung thân kỹ năng: làm đúng 2 bước, bước một là ĐỌC KỸ.
"""


async def _start(cfg, tmp_path):
    cfg2 = replace(cfg, telegram_bot_token=_TOK,
                   allowed_user_id=OWNER, webapp_port=0)
    memory = await open_memory(cfg2)
    policy = PolicyEngine(cfg2.policy_path, memory=memory)
    registry = build_default_registry(cfg2, memory)
    skills_dir = tmp_path / "skills"
    (skills_dir / "ky-nang-mau").mkdir(parents=True)
    (skills_dir / "ky-nang-mau" / "SKILL.md").write_text(
        SKILL_MD, encoding="utf-8")
    catalog = SkillCatalog.load(skills_dir,
                                tool_names=registry.names())
    server = WebAppServer(
        cfg2, memory=memory, policy=policy,
        broker=ApprovalBroker(policy=policy, timeout_s=30),
        connectors=build_default_connectors(cfg2), mcp_manager=None,
        vault_store=VaultStore(cfg2.vault_path),
        registry=registry,
        dossier=Dossier.load(cfg2.dossier_dir), skills=catalog)
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


# ---------- C1: Vault nhập ngay trong app ----------
async def test_vault_capture_stores_and_returns_only_ref(app):
    cfg2, memory, server = app
    async with ClientSession() as s:
        async with s.post(_url(server, "/api/vault/capture"),
                          headers=_headers(),
                          json={"label": "api-key-mau",
                                "value": SENTINEL}) as r:
            assert r.status == 200
            text = await r.text()
            data = await r.json()
    assert data["ok"] is True
    ref = data["ref"]
    assert ref.startswith("vault:")
    # Giá trị KHÔNG echo trong response...
    assert SENTINEL not in text
    # ...nhưng đã vào kho thật, resolve đúng qua cửa duy nhất.
    store = VaultStore(cfg2.vault_path)
    assert store.resolve(ref) == SENTINEL
    assert store.labels()[0]["label"] == "api-key-mau"
    # Vết trajectory chỉ có nhãn + ref, không giá trị.
    rows = await memory.recent_trajectory(kind="vault_captured",
                                          limit=5)
    assert rows and SENTINEL not in str(rows[0]["payload"])
    assert rows[0]["payload"]["ref"] == ref


async def test_vault_capture_requires_auth_and_input(app):
    _, _, server = app
    async with ClientSession() as s:
        async with s.post(_url(server, "/api/vault/capture"),
                          json={"label": "x", "value": "y"}) as r:
            assert r.status == 403
        async with s.post(_url(server, "/api/vault/capture"),
                          headers=_headers(),
                          json={"label": "", "value": "y"}) as r:
            assert r.status == 400
        async with s.post(_url(server, "/api/vault/capture"),
                          headers=_headers(),
                          json={"label": "x", "value": ""}) as r:
            assert r.status == 400


# ---------- C2: Kỹ năng đọc được ----------
async def test_skills_list_and_detail(app):
    _, _, server = app
    async with ClientSession() as s:
        async with s.get(_url(server, "/api/skills"),
                         headers=_headers()) as r:
            assert r.status == 200
            data = await r.json()
        assert data["available"] is True
        items = data["skills"]
        assert [i["name"] for i in items] == ["ky-nang-mau"]
        assert "mẫu để kiểm tra" in items[0]["description"]
        assert items[0]["source"].endswith("SKILL.md")
        async with s.get(_url(server, "/api/skills/ky-nang-mau"),
                         headers=_headers()) as r:
            assert r.status == 200
            detail = await r.json()
        assert "ĐỌC KỸ" in detail["content"]
        assert detail["source"].endswith("SKILL.md")
        async with s.get(_url(server, "/api/skills/khong-co"),
                         headers=_headers()) as r:
            assert r.status == 404
        async with s.get(_url(server, "/api/skills")) as r:
            assert r.status == 403  # vẫn qua auth như mọi /api/*


# ---------- C5: tab Việc hiện lượt chat ----------
async def test_state_includes_chat_turns_not_only_tasks(app):
    _, memory, server = app
    key = "agent:main:telegram:dm:42:topic:0"
    await memory.get_or_create_session(key)
    umid = await memory.append_message(
        key, "user", "Chào Mulon, hôm nay khỏe không")
    await memory.append_message(key, "assistant", "Khỏe ní.")
    await memory.log_trajectory(
        key, "turn_done",
        {"intent": "chat", "verified": None, "llm_calls": 1,
         "user_msg_id": umid})
    async with ClientSession() as s:
        async with s.get(_url(server, "/api/state"),
                         headers=_headers()) as r:
            assert r.status == 200
            data = await r.json()
    turns = [t for t in data["tasks"] if t["kind"] == "turn"]
    assert len(turns) == 1
    turn = turns[0]
    assert turn["title"] == "Chào Mulon, hôm nay khỏe không"
    assert turn["status"] == "done"
    assert turn["intent"] == "chat"


def test_frontend_fix_pack_wired():
    html = INDEX_HTML.read_text(encoding="utf-8")
    # C1: form Vault trong app + endpoint capture; nút "qua
    # form trong chat" đã bỏ.
    assert 'id="vault-value"' in html and 'id="vault-save"' in html
    assert "/api/vault/capture" in html
    assert 'id="vault-add"' not in html
    # C2: màn chi tiết kỹ năng + gọi /api/skills.
    assert 'id="screen-skill"' in html and "/api/skills" in html
    assert "openSkill" in html
    # C3: không còn công tắc disabled trang trí ở Lịch/Kết nối —
    # mục không đổi được hiện trạng thái bằng chữ.
    assert "data-sched" in html and "Đang bật" in html
    assert 'disabled") + \'><span class="tr">' not in html
    # C4: lỗi lưu theme phải toast, không còn catch nuốt im lặng
    # ở đường này.
    assert "chưa lưu được lên" in html
    assert 'catch (e) { /* thiếu API cũ' not in html
    # Điều hướng startapp=vault vào thẳng màn Kho.
    assert 'START_PARAM === "vault"' in html
