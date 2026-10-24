"""1.2.0 bổ sung thẻ duyệt: DÒNG PHẠM VI (suy từ tool/nhóm thật +
cơ chế nhớ session) và LÝ DO của agent (lời dẫn của model ở lượt
gọi tool) — trên thẻ chat, payload broker và /api/state. Không có
lý do thì thẻ vẫn dựng bình thường, không bịa."""

import asyncio
import json

from aiohttp import ClientSession

from mulon.agent import Agent
from mulon.approvals import ApprovalBroker, approval_scope, \
    normalize_reason
from mulon.context import ContextEngine, Dossier
from mulon.gateway import Completion, ToolCall
from mulon.policy import PolicyEngine
from mulon.tools import build_default_registry
from tests.conftest import open_memory
from tests.test_v12_surface import _PAYLOAD, _cfg, _surface
from tests.test_v12_webapp_api import _start, _stop, _url
from tests.test_v12_webapp_auth import make_init_data

SESSION = "agent:main:telegram:dm:1:topic:0"


# ---------- approval_scope / normalize_reason ----------

def test_scope_shell_group_from_real_data():
    scope = approval_scope({"tool": "run_command", "group": "shell"})
    assert "chỉ áp cho lần này" in scope["once"]
    rem = scope["remember"]
    assert "run_command" in rem            # đúng công cụ được nhớ
    assert "chạy lệnh hệ thống" in rem     # nhãn nhóm thật
    assert "hết phiên" in rem              # lớp session, không bền
    assert "không áp cho" in rem           # không lan sang việc khác


def test_scope_other_group_not_hardcoded():
    scope = approval_scope({"tool": "web_fetch", "group": "web"})
    assert "web_fetch" in scope["remember"]
    assert "đọc web" in scope["remember"]
    assert "chạy lệnh hệ thống" not in scope["remember"]


def test_normalize_reason_collapses_and_caps():
    assert normalize_reason("  Cần kiểm tra\n\n  log  giúp em ") == \
        "Cần kiểm tra log giúp em"
    assert normalize_reason("") == ""
    assert normalize_reason(None) == ""
    long = normalize_reason("a " * 300)
    assert len(long) <= 282 and long.endswith("…")


# ---------- broker.pending(): payload cho Mini App ----------

async def test_pending_carries_scope_and_reason():
    broker = ApprovalBroker(timeout_s=5)
    broker.open("s1", {"approval_id": "s1", "tool": "run_command",
                       "group": "shell", "summary": "cmd=ls",
                       "reason": "Cần  xem log\nđể biết lỗi ở đâu",
                       "session_key": "sk", "task_id": "t1"})
    item = broker.pending()[0]
    assert item["reason"] == "Cần xem log để biết lỗi ở đâu"
    assert "chỉ áp cho lần này" in item["scope_once"]
    assert "run_command" in item["scope_remember"]
    assert "hết phiên" in item["scope_remember"]
    broker.resolve("s1", False)
    await broker.wait("s1")


async def test_pending_without_reason_still_has_scope():
    broker = ApprovalBroker(timeout_s=5)
    broker.open("s2", {"approval_id": "s2", "tool": "web_fetch",
                       "group": "web", "summary": "url=x",
                       "session_key": "sk", "task_id": "t1"})
    item = broker.pending()[0]
    assert item["reason"] == ""
    assert item["scope_once"] and item["scope_remember"]
    broker.resolve("s2", False)
    await broker.wait("s2")


# ---------- thẻ chat: phạm vi + lý do cắt gọn ----------

async def test_chat_card_has_scope_and_reason(cfg):
    surface, broker, memory, bot = await _surface(_cfg(cfg))
    payload = dict(_PAYLOAD, approval_id="c7",
                   reason="Cần dọn thư mục tạm trước khi xuất bản.")
    broker.open("c7", payload)
    waiter = asyncio.create_task(broker.wait("c7"))
    mid = await surface.send_approval_card(777, None, payload)
    assert mid is not None
    text = bot.sent[0]["text"]
    assert "Phạm vi:" in text
    assert "chỉ áp cho lần này" in text
    assert "tới hết phiên này" in text
    assert "không áp cho" in text
    assert "Lý do: Cần dọn thư mục tạm" in text
    broker.resolve("c7", False)
    await waiter
    await memory.close()


async def test_chat_card_reason_truncated_one_line(cfg):
    surface, broker, memory, bot = await _surface(_cfg(cfg))
    payload = dict(_PAYLOAD, approval_id="c8",
                   reason="lý do rất dài " * 40)
    broker.open("c8", payload)
    waiter = asyncio.create_task(broker.wait("c8"))
    await surface.send_approval_card(777, None, payload)
    text = bot.sent[0]["text"]
    line = [ln for ln in text.split("\n")
            if ln.startswith("Lý do:")][0]
    assert len(line) <= 150 and line.endswith("…")
    broker.resolve("c8", False)
    await waiter
    await memory.close()


async def test_chat_card_without_reason_still_builds(cfg):
    surface, broker, memory, bot = await _surface(_cfg(cfg))
    payload = dict(_PAYLOAD, approval_id="c10")  # không có reason
    broker.open("c10", payload)
    waiter = asyncio.create_task(broker.wait("c10"))
    mid = await surface.send_approval_card(777, None, payload)
    assert mid is not None
    text = bot.sent[0]["text"]
    assert "Phạm vi:" in text          # phạm vi vẫn luôn có
    assert "Lý do:" not in text        # không bịa dòng lý do
    broker.resolve("c10", False)
    await waiter
    await memory.close()


# ---------- /api/state: pending chứa scope + reason ----------

async def test_api_state_pending_has_scope_and_reason(cfg):
    _, memory, broker, server = await _start(cfg)
    try:
        broker.open("sr1", {"approval_id": "sr1",
                            "tool": "run_command", "group": "shell",
                            "summary": "cmd=ls",
                            "reason": "Cần xem log để chẩn đoán lỗi",
                            "session_key": "sk", "task_id": "t"})
        headers = {"X-Telegram-Init-Data": make_init_data()}
        async with ClientSession() as s:
            async with s.get(_url(server, "/api/state"),
                             headers=headers) as r:
                assert r.status == 200
                data = await r.json()
        pending = data["approvals"]["pending"]
        assert len(pending) == 1
        item = pending[0]
        assert item["reason"] == "Cần xem log để chẩn đoán lỗi"
        assert "chỉ áp cho lần này" in item["scope_once"]
        assert "run_command" in item["scope_remember"]
        assert "hết phiên" in item["scope_remember"]
        broker.resolve("sr1", False)
        await broker.wait("sr1")
    finally:
        await _stop(memory, server)


# ---------- agent: lời dẫn của model thành reason trên thẻ ----

class _Gateway:
    """Act 1: text dẫn + gọi tool `now`. Act 2: trả text."""

    def __init__(self, preamble):
        self.preamble = preamble
        self.act_calls = 0

    async def complete(self, messages, model=None, tools=None,
                       purpose="", temperature=None):
        if purpose == "verify":
            return Completion(text=json.dumps(
                {"ok": True, "diagnosis": ""}))
        if purpose == "plan":
            return Completion(text=json.dumps({"steps": ["Việc"]}))
        if tools is None:
            return Completion(text="{}")
        self.act_calls += 1
        if self.act_calls == 1:
            return Completion(text=self.preamble, tool_calls=[
                ToolCall(id="c1", name="now", arguments="{}")])
        return Completion(text="Xong.")

    async def stream(self, messages, model=None, purpose="",
                     on_delta=None):
        return Completion(text="chào")


async def _run_agent_with_preamble(cfg, preamble):
    cfg.policy_path.write_text(json.dumps(
        {"tools": {"now": "ask"}}), encoding="utf-8")
    memory = await open_memory(cfg)
    dossier = Dossier.load(cfg.dossier_dir)
    gateway = _Gateway(preamble)
    ctx = ContextEngine(cfg, dossier, memory, gateway)
    registry = build_default_registry(cfg, memory)
    policy = PolicyEngine(cfg.policy_path, memory=memory)
    broker = ApprovalBroker(policy=policy, timeout_s=10)
    seen = {}

    async def on_event(kind, payload):
        if kind == "approval_requested":
            seen.update(payload)

            async def _decide():
                await asyncio.sleep(0.05)
                broker.resolve(payload["approval_id"], True)

            asyncio.create_task(_decide())

    agent = Agent(cfg, gateway, memory, ctx, registry, policy,
                  broker=broker)
    result = await agent.handle(SESSION, "chạy lệnh xem giờ giúp tui",
                                on_event=on_event)
    assert result.text == "Xong."
    await memory.close()
    return seen


async def test_agent_reason_flows_from_model_preamble(cfg):
    seen = await _run_agent_with_preamble(
        cfg, "Em xem giờ hệ thống để lên lịch cho đúng.")
    assert seen.get("reason") == \
        "Em xem giờ hệ thống để lên lịch cho đúng."


async def test_agent_without_preamble_reason_empty(cfg):
    seen = await _run_agent_with_preamble(cfg, "")
    assert seen.get("reason") == ""
