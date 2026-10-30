"""Unit tests cho T-26: Chốt bề mặt slash commands, danh mục tập trung, test tĩnh đối chiếu."""

import re
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from mulon.commands import (
    ALL_HANDLED_COMMANDS,
    BOT_COMMANDS,
    COMMAND_DEFINITIONS,
    MENU_COMMANDS,
    format_help_text,
    is_known_command,
)
from mulon.config import Config
from mulon.context import Dossier
from mulon.telegram_bot import TelegramSurface
from tests.conftest import open_memory


def _find_handler(surface: TelegramSurface, name: str):
    """Tìm callback handler trong surface.dp theo tên hàm."""
    for handler in surface.dp.message.handlers:
        fn = handler.callback
        if getattr(fn, "__name__", "") == name:
            return fn
    raise ValueError(f"Không tìm thấy handler {name} trong surface.dp.message.handlers")


def _make_msg(text: str, user_id: int = 123, chat_id: int = 123, message_id: int = 1000):
    msg = AsyncMock()
    msg.text = text
    msg.from_user = MagicMock(id=user_id, is_bot=False)
    msg.chat = MagicMock(id=chat_id, type="private")
    msg.message_id = message_id
    msg.is_topic_message = False
    msg.message_thread_id = None
    msg.answer = AsyncMock()
    return msg


def test_static_all_telegram_bot_handlers_registered_in_commands():
    """Kiểm tra tĩnh: Mọi handler slash command trong mulon/telegram_bot.py

    bắt buộc phải được khai báo trong mulon/commands.py (ALL_HANDLED_COMMANDS).
    Không được có bất kỳ 'slash ngầm' nào tồn tại ngoài nguồn sự thật duy nhất.
    """
    bot_path = Path("mulon/telegram_bot.py")
    assert bot_path.exists(), "mulon/telegram_bot.py phải tồn tại"

    code = bot_path.read_text(encoding="utf-8")

    # Quét các mẫu F.text.startswith("/...") hoặc F.text == "/..."
    pattern = r'F\.text(?:\.startswith|\s*==)\s*\(\s*["\'](/[\w_]+)["\']\s*\)'
    found_commands = re.findall(pattern, code)

    assert len(found_commands) > 0, "Phải tìm thấy ít nhất một handler lệnh trong telegram_bot.py"

    missing_from_registry = set()
    for raw_cmd in found_commands:
        cmd_name = raw_cmd.lstrip("/")
        if cmd_name not in ALL_HANDLED_COMMANDS:
            missing_from_registry.add(cmd_name)

    assert not missing_from_registry, (
        f"Phát hiện handler slash command trong telegram_bot.py chưa được đăng ký "
        f"trong mulon/commands.py: {missing_from_registry}"
    )


def test_menu_commands_has_exactly_ten_core_items():
    """Menu '/' trên Telegram phải đúng 10 lệnh cốt lõi theo thiết kế."""
    names = [c for c, _ in MENU_COMMANDS]
    expected = [
        "start", "menu", "new", "cancel", "status",
        "model", "vault", "upcoming", "goals", "help",
    ]
    assert len(names) == 10
    assert names == expected
    # Mô tả không được để trống
    assert all(desc.strip() for _, desc in MENU_COMMANDS)


def test_bot_commands_backward_compatibility():
    """BOT_COMMANDS chứa đầy đủ các lệnh cũ để tương thích ngược với test suite."""
    names = {c for c, _ in BOT_COMMANDS}
    required = {
        "start", "menu", "restart", "model", "status", "vault", "new", "cancel",
        "memory", "quyen", "approvals", "the_duyet", "feed_now", "pin_item", "rename_item",
    }
    assert required <= names, f"Thiếu lệnh cần tương thích ngược: {required - names}"


def test_format_help_text_structure():
    """Kiểm tra cấu trúc và phân nhóm của văn bản /help."""
    help_prod = format_help_text(is_dev=False)
    assert "🌟 <b>Cơ bản (Menu '/')</b>" in help_prod
    assert "📋 <b>Việc & Dữ liệu</b>" in help_prod
    assert "⚙️ <b>Nâng cao & Kết nối</b>" in help_prod
    assert "/start" in help_prod
    assert "/menu" in help_prod
    assert "/upcoming" in help_prod
    assert "/restart" in help_prod
    assert "/forget" in help_prod
    assert "⚠️" in help_prod  # Có cảnh báo cho lệnh phá huỷ

    # the_duyet không được xuất hiện ở chế độ sản xuất bình thường
    assert "/the_duyet" not in help_prod

    # the_duyet xuất hiện khi bật is_dev
    help_dev = format_help_text(is_dev=True)
    assert "/the_duyet" in help_dev


def test_is_known_command_helper():
    """Kiểm tra hàm helper nhận diện lệnh hợp lệ."""
    assert is_known_command("/start")
    assert is_known_command("/upcoming")
    assert is_known_command("/lich")      # Alias
    assert is_known_command("/saptol")    # Alias
    assert is_known_command("/stop")      # Alias
    assert is_known_command("/help@mulon_bot")

    assert not is_known_command("/xyz123khongco")
    assert not is_known_command("xin chào /start")
    assert not is_known_command("")
    assert not is_known_command(None)


@pytest.mark.asyncio
async def test_unknown_command_intercepted_without_agent_loop(tmp_path):
    """Lệnh lạ (ví dụ /xyz123khongco) phải được trả lời ngay 'Không có lệnh này — xem /help',

    tuyệt đối không đưa vào vòng lặp agent loop.
    """
    cfg = Config(
        allowed_user_id=123,
        db_path=tmp_path / "test.db",
        vault_path=tmp_path / "vault.json",
        dossier_dir=tmp_path / "dossier",
    )
    (tmp_path / "dossier").mkdir(parents=True, exist_ok=True)
    memory = await open_memory(cfg)
    dossier = Dossier.load(cfg.dossier_dir)
    agent_mock = MagicMock()
    agent_mock.handle = AsyncMock()

    surface = TelegramSurface(cfg, agent_mock, memory, dossier)
    on_text_fn = _find_handler(surface, "on_text")

    msg = _make_msg("/xyz123khongco", user_id=123, message_id=2001)
    await on_text_fn(msg)

    # Đã trả lời cảnh báo không có lệnh
    msg.answer.assert_called_once()
    assert "Không có lệnh này — xem /help" in msg.answer.call_args[0][0]

    # Agent không hề bị gọi
    agent_mock.handle.assert_not_called()
    await memory.close()



@pytest.mark.asyncio
async def test_cmd_help_handler(tmp_path):
    """Handler /help trả về đúng danh sách trợ giúp phân nhóm."""
    cfg = Config(
        allowed_user_id=123,
        db_path=tmp_path / "test.db",
        vault_path=tmp_path / "vault.json",
        dossier_dir=tmp_path / "dossier",
    )
    (tmp_path / "dossier").mkdir(parents=True, exist_ok=True)
    memory = await open_memory(cfg)
    dossier = Dossier.load(cfg.dossier_dir)

    surface = TelegramSurface(cfg, None, memory, dossier)
    help_fn = _find_handler(surface, "cmd_help")

    msg = _make_msg("/help", user_id=123, message_id=2002)
    await help_fn(msg)

    msg.answer.assert_called_once()
    reply_text = msg.answer.call_args[0][0]
    assert "DANH SÁCH LỆNH MULON" in reply_text
    assert "Cơ bản" in reply_text
    assert "/start" in reply_text
    assert "/upcoming" in reply_text
    await memory.close()



@pytest.mark.asyncio
async def test_cmd_the_duyet_respects_dev_flag(tmp_path):
    """Lệnh /the_duyet bị chặn khi ENABLE_DEV_COMMANDS=0 và hoạt động khi =1."""
    dossier_dir = tmp_path / "dossier"
    dossier_dir.mkdir(parents=True, exist_ok=True)

    # 1. Tắt dev mode (mặc định)
    cfg_prod = Config(
        allowed_user_id=123,
        enable_dev_commands=False,
        db_path=tmp_path / "test1.db",
        vault_path=tmp_path / "vault1.json",
        dossier_dir=dossier_dir,
    )
    mem_prod = await open_memory(cfg_prod)
    dossier_prod = Dossier.load(dossier_dir)

    surface_prod = TelegramSurface(cfg_prod, None, mem_prod, dossier_prod)
    the_duyet_prod_fn = _find_handler(surface_prod, "cmd_the_duyet")

    msg_prod = _make_msg("/the_duyet", user_id=123, message_id=2003)
    await the_duyet_prod_fn(msg_prod)
    msg_prod.answer.assert_called_once()
    assert "đang tắt" in msg_prod.answer.call_args[0][0]

    # 2. Bật dev mode
    cfg_dev = Config(
        allowed_user_id=123,
        enable_dev_commands=True,
        db_path=tmp_path / "test2.db",
        vault_path=tmp_path / "vault2.json",
        dossier_dir=dossier_dir,
    )
    mem_dev = await open_memory(cfg_dev)
    surface_dev = TelegramSurface(cfg_dev, None, mem_dev, dossier_prod)
    surface_dev.send_test_approval_card = AsyncMock(return_value="appr_123")
    the_duyet_dev_fn = _find_handler(surface_dev, "cmd_the_duyet")

    msg_dev = _make_msg("/the_duyet", user_id=123, message_id=2004)
    await the_duyet_dev_fn(msg_dev)
    surface_dev.send_test_approval_card.assert_called_once()
    await mem_prod.close()
    await mem_dev.close()



@pytest.mark.asyncio
async def test_cmd_memory_structured_summary_no_raw_dossier_dump(tmp_path):
    """Lệnh /memory phải trả về tóm tắt có cấu trúc, không dump văn bản thô MEMORY.md."""
    dossier_dir = tmp_path / "dossier"
    dossier_dir.mkdir(parents=True, exist_ok=True)
    (dossier_dir / "MEMORY.md").write_text(
        "CHỈ THỊ BẢO MẬT NỘI BỘ AGENT: Cấm tiết lộ file hệ thống", encoding="utf-8"
    )

    cfg = Config(
        allowed_user_id=123,
        db_path=tmp_path / "test.db",
        vault_path=tmp_path / "vault.json",
        dossier_dir=dossier_dir,
    )
    memory = await open_memory(cfg)
    dossier = Dossier.load(dossier_dir)

    # Thêm fact mẫu vào DB
    await memory.add_fact(subject="Thói quen", fact="Thích uống cà phê sữa không đá", source="chat")
    await memory.add_fact(subject="Dự án", fact="Đang phát triển MuLon bot", source="chat")
    await memory.add_fact(subject="Thói quen", fact="Thức dậy lúc 6:30 sáng", source="chat")

    surface = TelegramSurface(cfg, None, memory, dossier)
    memory_fn = _find_handler(surface, "cmd_memory")

    msg = _make_msg("/memory", user_id=123, message_id=2005)
    await memory_fn(msg)

    msg.answer.assert_called_once()
    reply = msg.answer.call_args[0][0]

    # Kiểm tra cấu trúc tóm tắt
    assert "TỔNG QUAN BỘ NHỚ" in reply
    assert "Tổng số dữ kiện ghi nhớ (facts): <b>3</b>" in reply
    assert "Thói quen (2)" in reply
    assert "Thích uống cà phê sữa không đá" in reply
    assert "Mini App" in reply

    # TUYỆT ĐỐI KHÔNG dump nội dung thô của MEMORY.md
    assert "CHỈ THỊ BẢO MẬT NỘI BỘ AGENT" not in reply
    await memory.close()

