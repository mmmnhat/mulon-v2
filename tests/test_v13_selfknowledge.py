"""1.3.0 Gói B: bản vá tự nhận thức — khối SELF-KNOWLEDGE vào
prompt (roster tool thật + bề mặt thật + quy tắc cứng), và lệnh
/the_duyet gửi thẻ duyệt THỬ thật qua ApprovalBroker."""

import asyncio

from mulon.agent import Agent, build_self_knowledge
from mulon.context import ContextEngine, Dossier
from mulon.gateway import Completion
from mulon.policy import PolicyEngine
from mulon.tools import build_default_registry
from tests.conftest import open_memory
from tests.test_v12_surface import _cfg, _surface

OWNER = 42


async def test_self_knowledge_block_states_the_facts(cfg):
    memory = await open_memory(cfg)
    registry = build_default_registry(cfg, memory)
    block = build_self_knowledge(cfg, registry)
    # Là ai: bot Telegram đang chạy thật, Python/aiogram, chính
    # codebase này — không "bot của ai khác".
    assert "TỰ NHẬN THỨC" in block
    assert "bot Telegram" in block and "Python (aiogram" in block
    # Đường làm việc thật.
    assert str(cfg.workspace_dir) in block
    assert str(cfg.dossier_dir) in block
    # Roster: MỌI tool trong registry đều có tên trong khối, và
    # read_file có nhãn lời thường "Đọc file".
    for spec in registry.specs():
        assert f"(tool: {spec.name})" in block, spec.name
    assert "Đọc file (tool: read_file)" in block
    # Bề mặt thật: thẻ duyệt có nút thật qua broker, /the_duyet,
    # Mini App, Vault chỉ cầm ref.
    assert "ApprovalBroker" in block and "/the_duyet" in block
    assert "Mini App" in block and "vault:<uuid>" in block
    # Quy tắc cứng: không chối tool chưa đối chiếu, không bịa
    # thẻ mẫu, không hỏi ngược "bot chạy bằng gì".
    assert "Không bao giờ tuyên bố" in block
    assert "Không bịa giao diện" in block
    assert "chính bạn là bot đó" in block
    await memory.close()


class _RecordingGateway:
    """Gateway ghi lại messages của fast path để kiểm khối tự
    nhận thức đã vào prompt thật."""

    def __init__(self):
        self.seen = []

    async def stream(self, messages, model=None, purpose="",
                     on_delta=None):
        self.seen = list(messages)
        return Completion(text="chào ní")

    async def complete(self, messages, model=None, tools=None,
                       purpose="", temperature=None):
        return Completion(text="{}")


async def test_agent_injects_self_knowledge_after_dossier(cfg):
    memory = await open_memory(cfg)
    dossier = Dossier.load(cfg.dossier_dir)
    gateway = _RecordingGateway()
    ctx = ContextEngine(cfg, dossier, memory, gateway)
    registry = build_default_registry(cfg, memory)
    policy = PolicyEngine(cfg.policy_path, memory=memory)
    agent = Agent(cfg, gateway, memory, ctx, registry, policy)
    result = await agent.handle(
        "agent:main:telegram:dm:1:topic:0", "chào buổi sáng")
    assert result.text == "chào ní"
    assert gateway.seen[0]["role"] == "system"
    block = gateway.seen[1]
    assert block["role"] == "system"
    assert "TỰ NHẬN THỨC" in block["content"]
    assert "read_file" in block["content"]
    await memory.close()


async def test_the_duyet_command_registered():
    from mulon.telegram_bot import BOT_COMMANDS

    names = [c for c, _ in BOT_COMMANDS]
    assert "the_duyet" in names
    desc = dict(BOT_COMMANDS)["the_duyet"]
    assert "thử" in desc.lower()


async def test_the_duyet_opens_real_pending_and_callback_settles(cfg):
    surface, broker, memory, bot = await _surface(_cfg(cfg))
    aid = await surface.send_test_approval_card(777)
    assert aid and broker.is_pending(aid)
    # Pending thật ở broker, đúng danh tính thẻ thử.
    pend = broker.pending()
    assert len(pend) == 1
    assert pend[0]["tool"] == "the_duyet"
    assert pend[0]["kind"] == "test"
    # Thẻ thật đã gửi kèm bàn phím có callback appr:* THẬT.
    card = bot.sent[-1]
    kb = card["reply_markup"]
    datas = [b.callback_data for row in kb.inline_keyboard
             for b in row if getattr(b, "callback_data", None)]
    assert f"appr:1:{aid}" in datas
    assert f"appr:0:{aid}" in datas
    # Bấm Duyệt qua đúng đường callback -> quyết toán đúng.
    ok, note = await surface.handle_approval_callback(
        f"appr:1:{aid}", OWNER)
    assert ok and "duyệt" in note.lower()
    rows = []
    for _ in range(60):
        rows = await memory.recent_trajectory(
            kind="approval_decision", limit=5)
        if rows:
            break
        await asyncio.sleep(0.05)
    assert rows, "chưa thấy vết quyết định thẻ thử"
    payload = rows[0]["payload"]
    assert payload["tool"] == "the_duyet"
    assert payload["outcome"] == "approved"
    assert payload["approved"] is True
    assert payload["test"] is True
    # Nhắn xác nhận đã gửi, nói rõ không thực thi gì.
    assert any("thẻ thử" in s["text"] and "không có hành động" in
               s["text"] for s in bot.sent)
    # Thẻ được gỡ khỏi chat bởi listener như thẻ thường.
    assert bot.deleted, "thẻ thử phải được gỡ sau quyết định"
    await memory.close()


async def test_the_duyet_without_broker_degrades_clean(cfg):
    surface, broker, memory, bot = await _surface(_cfg(cfg))
    surface.broker = None
    assert await surface.send_test_approval_card(777) is None
    await memory.close()
