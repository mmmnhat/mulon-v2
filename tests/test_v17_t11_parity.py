"""Kiểm thử tính năng Parity hệ thống theo T-11 (v1.7.32):
- Slash command audit: /help phân nhóm, /help <cmd>, từ chối lệnh lạ ngay lập tức.
- /the_duyet chỉ cho phép khi dev_mode=True.
- /memory tóm tắt có cấu trúc thay vì dump thô.
- /model 3 tiers (brain/cheap/escalated), ghi đè theo phiên (/model session), reset.
- Tích hợp model session override vào Agent.handle.
- Mini App API /api/model (GET và POST).
- /setup api <endpoint> <key> kiểm tra kết nối sống trước khi lưu.
- Tool self_verify_and_restart đăng ký trong ToolRegistry.
"""

import json
import os
import tempfile
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from mulon.agent import Agent
from mulon.approvals import ApprovalBroker
from mulon.config import Config
from mulon.connectors import build_default_connectors
from mulon.context import ContextEngine, Dossier
from mulon.gateway import Completion, ModelGateway
from mulon.policy import PolicyEngine
from mulon.telegram_bot import (
    BOT_COMMANDS,
    MENU_COMMANDS,
    TelegramSurface,
)
from mulon.tools import build_default_registry
from mulon.vault import VaultStore
from mulon.webapp_server import WebAppServer
from tests.conftest import open_memory

OWNER = 42


class DummyBot:
    id = 999
    username = "mulon_test_bot"

    def __init__(self):
        self.sent = []
        self._next_id = 100

    async def send_message(self, chat_id, text, **kw):
        self._next_id += 1
        msg = SimpleNamespace(message_id=self._next_id, chat=SimpleNamespace(id=chat_id), text=text)
        self.sent.append({"chat_id": chat_id, "text": text, **kw})
        return msg

    async def set_my_commands(self, commands):
        pass


def _make_msg(text: str, user_id: int = OWNER, chat_id: int = OWNER, thread_id: int | None = None) -> SimpleNamespace:
    msg = SimpleNamespace(
        text=text,
        from_user=SimpleNamespace(id=user_id, username="tester"),
        chat=SimpleNamespace(id=chat_id, type="private"),
        message_id=123,
        message_thread_id=thread_id,
        is_topic_message=bool(thread_id),
        date=1700000000,
        reply_to_message=None,
    )
    msg.answer = AsyncMock()
    return msg


def test_command_registry_integrity():
    """Kiểm tra tính toàn vẹn danh sách lệnh: không trùng lặp, mô tả đầy đủ."""
    menu_names = [c for c, _ in MENU_COMMANDS]
    bot_names = [c for c, _ in BOT_COMMANDS]

    # Menu phải có 10 lệnh cốt lõi
    assert len(menu_names) == 10
    assert len(menu_names) == len(set(menu_names))
    assert "start" in menu_names
    assert "help" in menu_names
    assert "menu" in menu_names
    assert "model" in menu_names
    assert "upcoming" in menu_names

    # BOT_COMMANDS chứa toàn bộ lệnh
    assert len(bot_names) == len(set(bot_names))
    for c in ("help", "model", "upcoming", "restart", "memory", "vault"):
        assert c in bot_names

    for _, desc in BOT_COMMANDS:
        assert desc and len(desc.strip()) > 3


async def test_help_command_categorized(cfg: Config):
    """Lệnh /help trả về danh sách phân nhóm rõ ràng; /help <cmd> trả về chi tiết."""
    cfg = replace(cfg, allowed_user_id=OWNER)
    memory = await open_memory(cfg)
    policy = PolicyEngine(cfg.policy_path, memory=memory)
    broker = ApprovalBroker(policy=policy, timeout_s=10)
    surface = TelegramSurface(
        cfg, agent=None, memory=memory,
        dossier=Dossier.load(cfg.dossier_dir), policy=policy, broker=broker
    )
    bot = DummyBot()
    surface.bot = bot

    # Test /help chung
    msg = _make_msg("/help", user_id=OWNER)
    await surface._handle_help_command(msg)
    assert msg.answer.called
    ans_text = msg.answer.call_args[0][0]
    assert "DANH SÁCH LỆNH MULON" in ans_text
    assert "/model" in ans_text
    assert "/upcoming" in ans_text

    # Test /help model
    msg_model = _make_msg("/help model", user_id=OWNER)
    await surface._handle_help_command(msg_model)
    assert msg_model.answer.called
    model_help = msg_model.answer.call_args[0][0]
    assert "/model session" in model_help
    assert "/model tier" in model_help
    await memory.close()


async def test_unknown_command_rejected_immediately(cfg: Config):
    """Lệnh lạ (ví dụ /xyz123khongco) bị từ chối ngay lập tức, không đưa vào agent."""
    cfg = replace(cfg, allowed_user_id=OWNER)
    memory = await open_memory(cfg)
    policy = PolicyEngine(cfg.policy_path, memory=memory)
    broker = ApprovalBroker(policy=policy, timeout_s=10)
    surface = TelegramSurface(
        cfg, agent=None, memory=memory,
        dossier=Dossier.load(cfg.dossier_dir), policy=policy, broker=broker
    )
    bot = DummyBot()
    surface.bot = bot

    msg = _make_msg("/xyz123khongco", user_id=OWNER)
    with patch.object(surface.batcher, "add", new_callable=AsyncMock) as mock_add:
        await surface._handle_text_message(msg)
        assert not mock_add.called
        assert msg.answer.called
        reply = msg.answer.call_args[0][0]
        assert "Không có lệnh" in reply
    await memory.close()


async def test_the_duyet_guard_in_production(cfg: Config):
    """Lệnh /the_duyet bị chặn khi dev_mode=False."""
    cfg_prod = replace(cfg, allowed_user_id=OWNER, dev_mode=False)
    memory = await open_memory(cfg_prod)
    policy = PolicyEngine(cfg_prod.policy_path, memory=memory)
    broker = ApprovalBroker(policy=policy, timeout_s=10)
    surface = TelegramSurface(
        cfg_prod, agent=None, memory=memory,
        dossier=Dossier.load(cfg_prod.dossier_dir), policy=policy, broker=broker
    )
    bot = DummyBot()
    surface.bot = bot

    with patch.dict(os.environ, {"MULON_DEV_MODE": "0"}):
        msg = _make_msg("/the_duyet", user_id=OWNER)
        await surface._handle_the_duyet_command(msg)
        assert msg.answer.called
        assert "đang tắt" in msg.answer.call_args[0][0]
    await memory.close()


async def test_memory_structured_summary(cfg: Config):
    """Lệnh /memory tóm tắt có cấu trúc thay vì dump dossier thô."""
    cfg = replace(cfg, allowed_user_id=OWNER)
    memory = await open_memory(cfg)
    await memory.add_fact("Chủ dự án thích cà phê đen đá", subject="so_thich")
    await memory.add_fact("Chủ dự án dùng Mac mini M4", subject="thiet_bi")

    policy = PolicyEngine(cfg.policy_path, memory=memory)
    broker = ApprovalBroker(policy=policy, timeout_s=10)
    surface = TelegramSurface(
        cfg, agent=None, memory=memory,
        dossier=Dossier.load(cfg.dossier_dir), policy=policy, broker=broker
    )
    bot = DummyBot()
    surface.bot = bot

    msg = _make_msg("/memory", user_id=OWNER)
    await surface._handle_memory_command(msg)
    assert msg.answer.called
    text = msg.answer.call_args[0][0]
    assert "TỔNG QUAN BỘ NHỚ" in text
    assert "cà phê đen đá" in text
    assert "Chủ đề chính" in text
    await memory.close()


async def test_model_command_tiers_and_session(cfg: Config):
    """Lệnh /model hỗ trợ 3 tiers, session override và reset."""
    cfg2 = replace(
        cfg,
        allowed_user_id=OWNER,
        model_brain="gemini-3.8-flash",
        model_cheap="gemini-3.5-flash-lite",
        model_escalated="grok-4.20-0309-reasoning",
    )
    memory = await open_memory(cfg2)
    policy = PolicyEngine(cfg2.policy_path, memory=memory)
    broker = ApprovalBroker(policy=policy, timeout_s=10)
    surface = TelegramSurface(
        cfg2, agent=None, memory=memory,
        dossier=Dossier.load(cfg2.dossier_dir), policy=policy, broker=broker
    )
    bot = DummyBot()
    surface.bot = bot

    # 1. /model không tham số: hiện 3 tiers
    msg1 = _make_msg("/model", user_id=OWNER)
    await surface._handle_model_command(msg1)
    assert msg1.answer.called
    ans1 = msg1.answer.call_args[0][0]
    assert "CẤU HÌNH MODEL AI" in ans1
    assert "Brain (chính)" in ans1
    assert "Cheap" in ans1
    assert "Escalated" in ans1

    # 2. /model session claude-3-7-sonnet: ghi đè cho phiên
    msg2 = _make_msg("/model session claude-3-7-sonnet", user_id=OWNER, chat_id=123)
    await surface._handle_model_command(msg2)
    assert "Đã đổi model cho riêng phiên này" in msg2.answer.call_args[0][0]
    stored = await memory.kv_get("session_model:agent:main:telegram:dm:123:topic:0")
    assert stored == "claude-3-7-sonnet"

    # 3. /model tier cheap gemini-2.0-flash: đổi tier
    msg3 = _make_msg("/model tier cheap gemini-2.0-flash", user_id=OWNER)
    await surface._handle_model_command(msg3)
    assert "Đã cập nhật tầng <b>Cheap</b>" in msg3.answer.call_args[0][0]
    assert cfg2.model_cheap == "gemini-2.0-flash"

    # 4. /model reset: xóa session override
    msg4 = _make_msg("/model reset", user_id=OWNER, chat_id=123)
    await surface._handle_model_command(msg4)
    assert "Đã xóa ghi đè model phiên này" in msg4.answer.call_args[0][0]
    assert await memory.kv_get("session_model:agent:main:telegram:dm:123:topic:0") is None

    await memory.close()


async def test_agent_uses_session_model_override(cfg: Config):
    """Agent tự động nhận diện và áp dụng model ghi đè theo session."""
    memory = await open_memory(cfg)
    session_key = "agent:main:telegram:dm:999:topic:0"
    await memory.kv_set(f"session_model:{session_key}", "custom-model-override")

    gateway = MagicMock(spec=ModelGateway)
    gateway.stream = AsyncMock(return_value=Completion(text="Chào bạn!"))
    gateway.complete = AsyncMock(return_value=Completion(text="Chào bạn!"))

    dossier = Dossier.load(cfg.dossier_dir)
    ctx = ContextEngine(cfg, dossier, memory, gateway)
    registry = build_default_registry(cfg, memory)
    policy = PolicyEngine(cfg.policy_path, memory=memory)
    agent = Agent(cfg, gateway, memory, ctx, registry, policy)

    res = await agent.handle(session_key, "Alo")
    assert res.text == "Chào bạn!"
    assert gateway.stream.called
    called_model = gateway.stream.call_args[1].get("model")
    assert called_model == "custom-model-override"
    await memory.close()


async def test_webapp_model_api(cfg: Config):
    """Kiểm thử Mini App endpoints /api/model GET và POST."""
    memory = await open_memory(cfg)
    policy = PolicyEngine(cfg.policy_path, memory=memory)
    srv = WebAppServer(
        cfg,
        memory=memory,
        policy=policy,
        broker=ApprovalBroker(policy=policy, timeout_s=10),
        connectors=build_default_connectors(cfg),
        mcp_manager=None,
        vault_store=VaultStore(cfg.vault_path),
        registry=build_default_registry(cfg, memory),
        dossier=Dossier.load(cfg.dossier_dir),
    )

    # 1. GET /api/model
    req_get = MagicMock()
    resp_get = await srv._handle_model_get(req_get)
    data_get = json.loads(resp_get.text)
    assert data_get["ok"] is True
    assert "brain" in data_get["tiers"]
    assert "cheap" in data_get["tiers"]
    assert "popular_models" in data_get

    # 2. POST /api/model tier
    req_post = MagicMock()
    req_post.json = AsyncMock(return_value={"tier": "brain", "model": "gemini-exp-custom"})
    resp_post = await srv._handle_model_post(req_post)
    data_post = json.loads(resp_post.text)
    assert data_post["ok"] is True
    assert data_post["tier"] == "brain"
    assert data_post["model"] == "gemini-exp-custom"
    assert cfg.model_brain == "gemini-exp-custom"

    # 3. POST /api/model session override
    req_sess = MagicMock()
    req_sess.json = AsyncMock(return_value={"session_key": "sess_123", "model": "session-special"})
    resp_sess = await srv._handle_model_post(req_sess)
    data_sess = json.loads(resp_sess.text)
    assert data_sess["ok"] is True
    assert data_sess["scope"] == "session"
    assert await memory.kv_get("session_model:sess_123") == "session-special"

    await memory.close()


async def test_setup_api_command_live_test(cfg: Config):
    """Kiểm thử /setup api <endpoint> <key> từ chối endpoint hỏng và lưu khi kết nối thành công."""
    cfg = replace(cfg, allowed_user_id=OWNER)
    memory = await open_memory(cfg)
    policy = PolicyEngine(cfg.policy_path, memory=memory)
    vstore = VaultStore(cfg.vault_path)
    surface = TelegramSurface(
        cfg, agent=None, memory=memory,
        dossier=Dossier.load(cfg.dossier_dir), policy=policy,
        surfaces={"vault_store": vstore},
    )
    bot = DummyBot()
    surface.bot = bot

    # Test với endpoint chết -> từ chối lưu
    msg_fail = _make_msg("/setup api http://127.0.0.1:54321/v1 bad-key", user_id=OWNER)
    await surface._handle_setup_command(msg_fail)
    assert msg_fail.answer.called
    assert "Không thể kết nối" in msg_fail.answer.call_args[0][0]
    assert vstore.resolve("proxy:api_key") is None

    # Test với endpoint thành công (mock httpx)
    with patch("httpx.AsyncClient.get") as mock_get:
        mock_get.return_value = SimpleNamespace(status_code=200)
        msg_ok = _make_msg("/setup api http://127.0.0.1:8317/v1 my-valid-key", user_id=OWNER)
        await surface._handle_setup_command(msg_ok)
        assert "Kết nối API sống!" in msg_ok.answer.call_args[0][0]
        assert vstore.resolve("proxy:api_key") == "my-valid-key"
        assert cfg.proxy_base_url == "http://127.0.0.1:8317/v1"

    await memory.close()


def test_self_evolution_tool_registered(cfg: Config):
    """Tool self_verify_and_restart được đăng ký trong ToolRegistry."""
    from mulon.evolution import register_evolution_tools
    reg = build_default_registry(cfg, memory=MagicMock())
    register_evolution_tools(reg, cfg, memory=MagicMock())
    tool = reg.get("self_verify_and_restart")
    assert tool is not None
    assert tool.group == "system"
    assert "reason" in tool.parameters["properties"]
