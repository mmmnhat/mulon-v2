"""Unit & regression tests cho đợt vá lỗi trải nghiệm Telegram T-21 (X-01..X-09)."""

import asyncio
from unittest.mock import MagicMock
import pytest

from mulon.config import Config, DEFAULT_TIMEZONE
from mulon.context import ContextEngine, Dossier
from tests.conftest import open_memory
from mulon.agent import classify_intent, Intent
from mulon.telegram_bot import is_cancellation_intent, md_to_html, MessageBatcher, TelegramSurface


@pytest.mark.asyncio
async def test_group_recall_does_not_leak_dm_messages(tmp_path):
    cfg = Config(
        db_path=tmp_path / "test.db",
        dossier_dir=tmp_path / "dossier",
        workspace_dir=tmp_path / "workspace",
        artifact_dir=tmp_path / "artifacts",
        policy_path=tmp_path / "policy.json",
    )
    memory = await open_memory(cfg)

    # 1. Ghi tin nhắn nhạy cảm trong phiên DM riêng tư
    dm_session = "agent:main:telegram:dm:6174671348:topic:0"
    await memory.get_or_create_session(dm_session)
    await memory.append_message(
        dm_session, "user", "Kịch bản bài đăng: vụ add nick FB cá nhân vào Meta popup"
    )
    await memory.append_message(
        dm_session, "assistant", "Đã chốt xong 3 ảnh và kịch bản che mờ thông tin"
    )

    # 2. Recall với exclude_dm=True (chế độ trong nhóm) -> không được ra kết quả DM
    hits_group = await memory.recall("kịch bản bài đăng", exclude_dm=True)
    assert len(hits_group) == 0

    # Recall thông thường trong DM (exclude_dm=False) -> tìm thấy bình thường
    hits_dm = await memory.recall("kịch bản bài đăng", exclude_dm=False)
    assert len(hits_dm) > 0
    assert any("FB cá nhân" in h["text"] for h in hits_dm)

    # 3. ContextEngine.build cho group session -> có GROUP PRIVACY GUARD và exclude_dm
    dossier = Dossier.load(tmp_path / "dossier")
    ctx = ContextEngine(cfg, dossier, memory, MagicMock())
    group_session = "agent:main:telegram:group:-1004486430474:topic:0"
    built = await ctx.build(group_session, "nãy tui nhắn riêng gì nhớ không")

    # Kiểm tra không có hit nào từ DM bị lọt vào recall_hits
    for hit in built.recall_hits:
        assert ":dm:" not in str(hit.get("session_key", ""))

    # Kiểm tra rào chắn group privacy trong system prompt
    system_prompts = [m["content"] for m in built.messages if m["role"] == "system"]
    assert any("GROUP PRIVACY GUARD" in p for p in system_prompts)
    assert any("TUYỆT ĐỐI KHÔNG tiết lộ" in p for p in system_prompts)


@pytest.mark.asyncio
async def test_accurate_system_time_injection(tmp_path):
    cfg = Config(
        db_path=tmp_path / "test.db",
        dossier_dir=tmp_path / "dossier",
        workspace_dir=tmp_path / "workspace",
        artifact_dir=tmp_path / "artifacts",
        policy_path=tmp_path / "policy.json",
        default_timezone=DEFAULT_TIMEZONE,
    )
    memory = await open_memory(cfg)
    dossier = Dossier.load(tmp_path / "dossier")
    ctx = ContextEngine(cfg, dossier, memory, MagicMock())

    built = await ctx.build("agent:main:telegram:dm:1:topic:0", "bây giờ mấy giờ")
    system_prompts = [m["content"] for m in built.messages if m["role"] == "system"]

    # Kiểm tra khối thời gian chuẩn xác
    time_prompt = next((p for p in system_prompts if "THỜI GIAN HỆ THỐNG HIỆN TẠI" in p), "")
    assert time_prompt != ""
    assert "Múi giờ Asia/Ho_Chi_Minh" in time_prompt
    assert "Bây giờ là:" in time_prompt


def test_correction_marker_redirects_and_multiline_cancellation():
    # Sửa ý với marker "á nhầm"
    is_c1, rest1 = is_cancellation_intent("á nhầm, bài hồi sáng á")
    assert is_c1 is True
    assert rest1 == "bài hồi sáng á"

    # Sửa ý với "ý là"
    is_c2, rest2 = is_cancellation_intent("ý là làm bài thơ ngắn thôi")
    assert is_c2 is True
    assert rest2 == "làm bài thơ ngắn thôi"

    # Sửa ý với "không phải"
    is_c3, rest3 = is_cancellation_intent("không phải, check bài đăng hôm qua")
    assert is_c3 is True
    assert rest3 == "check bài đăng hôm qua"

    # Nhiều dòng kèm hủy / đổi ý ở dòng 2 (tái hiện ca thực tế X-04 / X-07)
    multiline = (
        "Viết cho tui một bài dài phân tích xu hướng AI agent năm nay, thật chi tiết.\n"
        "Thôi khỏi viết nữa, đổi ý: kể tui 1 câu chuyện cười ngắn thôi."
    )
    is_c4, rest4 = is_cancellation_intent(multiline)
    assert is_c4 is True
    assert "kể tui 1 câu chuyện cười ngắn thôi" in rest4


def test_group_session_burst_without_repeating_mention():
    flushed = []

    async def on_flush(key, joined, parts):
        flushed.append((key, joined, parts))

    batcher = MessageBatcher(debounce_s=0.05, on_flush=on_flush)
    cfg = MagicMock()
    cfg.group_mention_only = True
    surface = TelegramSurface(
        cfg=cfg, agent=None, memory=None, dossier=None
    )
    surface.batcher = batcher
    surface.bot = MagicMock()
    surface.bot._me_username = "Mulon_bot"

    # Tin 1: Có mention bot trong group -> should_respond = True
    msg1 = MagicMock()
    msg1.chat.type = "group"
    msg1.chat.id = -100123
    msg1.text = "@Mulon_bot ơi cho hỏi"
    msg1.caption = None
    msg1.is_topic_message = False
    msg1.reply_to_message = None

    assert surface._should_respond(msg1) is True

    # Giả lập msg1 được thêm vào batcher
    key = "agent:main:telegram:group:-100123:topic:0"
    asyncio.run(batcher.add(key, msg1.text))
    assert batcher.has_pending(key) is True

    # Tin 2: Cùng user gõ tiếp ý vụn không lặp lại mention -> should_respond vẫn True nhờ has_pending
    msg2 = MagicMock()
    msg2.chat.type = "group"
    msg2.chat.id = -100123
    msg2.text = "nay có gì hot không"
    msg2.caption = None
    msg2.is_topic_message = False
    msg2.reply_to_message = None

    assert surface._should_respond(msg2) is True


def test_intent_classification_for_time_and_search_queries():
    # Hỏi thời gian -> Intent.CHAT (có thời gian sẵn trong prompt, trả lời ngay tức thì)
    assert classify_intent("mấy giờ rồi") == Intent.CHAT
    assert classify_intent("bây giờ là mấy giờ") == Intent.CHAT
    assert classify_intent("hôm nay thứ mấy vậy") == Intent.CHAT

    # Tìm kiếm tin tức / tài liệu -> Intent.TOOL
    assert classify_intent("Tìm giúp tui 3 tin AI nổi bật nhất hôm nay, nhớ kèm nguồn hẳn hoi.") == Intent.TOOL
    assert classify_intent("tìm tin tức công nghệ mới") == Intent.TOOL


def test_md_to_html_preserves_heading_separation():
    raw = "### 1. Báo cáo kiểm tra\nNội dung chi tiết ở đây."
    converted = md_to_html(raw)
    assert "<b>1. Báo cáo kiểm tra</b>" in converted
    # Phải có ngắt dòng để không dính chùm vào đoạn văn tiếp theo
    assert "\n" in converted
