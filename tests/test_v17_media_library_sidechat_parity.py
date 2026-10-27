"""Tests for [T-10.5] Parity: Gửi/nhận mọi loại nội dung + Thư viện + Chat phụ & Routing R15."""

import asyncio
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest
from aiogram.enums import ChatType

from mulon.config import Config
from mulon.context import ContextEngine, Dossier
from mulon.library import LibraryService, register_library_tools
from mulon.memory import Memory
from mulon.telegram_bot import (TelegramSurface, parse_session_key,
                                session_key_for)
from mulon.tools import ToolRegistry
from tests.conftest import open_memory


class DummyAnchorMessage:
    def __init__(self, chat_id: int = 12345, thread_id: int | None = None):
        self.chat = SimpleNamespace(id=chat_id, type=ChatType.PRIVATE)
        self.message_thread_id = thread_id
        self.is_topic_message = thread_id is not None
        self.message_id = 999
        self.photos_sent = []
        self.videos_sent = []
        self.audios_sent = []
        self.voices_sent = []
        self.documents_sent = []
        self.text_answers = []

    async def answer(self, text: str, **kwargs):
        self.text_answers.append(text)

    async def answer_photo(self, photo, caption: str = "", **kwargs):
        self.photos_sent.append((photo, caption))

    async def answer_video(self, video, caption: str = "", **kwargs):
        self.videos_sent.append((video, caption))

    async def answer_audio(self, audio, caption: str = "", **kwargs):
        self.audios_sent.append((audio, caption))

    async def answer_voice(self, voice, caption: str = "", **kwargs):
        self.voices_sent.append((voice, caption))

    async def answer_document(self, document, caption: str = "", **kwargs):
        self.documents_sent.append((document, caption))


class DummyBot:
    def __init__(self):
        self.sent_messages = []
        self.downloaded_files = []

    async def send_message(self, chat_id: int, text: str, **kwargs):
        self.sent_messages.append((chat_id, text, kwargs))
        return SimpleNamespace(message_id=101)

    async def send_photo(self, chat_id: int, photo, caption: str = "", **kwargs):
        self.sent_messages.append((chat_id, f"[photo]{caption}", kwargs))

    async def send_video(self, chat_id: int, video, caption: str = "", **kwargs):
        self.sent_messages.append((chat_id, f"[video]{caption}", kwargs))

    async def send_audio(self, chat_id: int, audio, caption: str = "", **kwargs):
        self.sent_messages.append((chat_id, f"[audio]{caption}", kwargs))

    async def send_document(self, chat_id: int, document, caption: str = "", **kwargs):
        self.sent_messages.append((chat_id, f"[doc]{caption}", kwargs))

    async def get_file(self, file_id: str):
        return SimpleNamespace(file_path=f"path/{file_id}")

    async def download_file(self, file_path: str, destination: str):
        self.downloaded_files.append((file_path, destination))
        dest_path = Path(destination)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        dest_path.write_bytes(b"downloaded-file-content")


@pytest.mark.asyncio
async def test_send_all_5_media_types_outgoing(cfg, tmp_path):
    """Gửi đi: bot nhận biết và gửi ảnh, video, voice, audio, tài liệu qua đúng hàm aiogram."""
    memory = await open_memory(cfg)
    ws = Path(cfg.workspace_dir)
    ws.mkdir(parents=True, exist_ok=True)

    img_file = ws / "chart.png"
    img_file.write_bytes(b"fake-png-image")

    vid_file = ws / "demo.mp4"
    vid_file.write_bytes(b"fake-mp4-video")

    voice_file = ws / "speech.ogg"
    voice_file.write_bytes(b"fake-ogg-voice")

    audio_file = ws / "music.mp3"
    audio_file.write_bytes(b"fake-mp3-audio")

    doc_file = ws / "report.pdf"
    doc_file.write_bytes(b"fake-pdf-doc")

    lib = LibraryService(cfg, memory)
    bot = DummyBot()
    surface = TelegramSurface(
        cfg, agent=None, memory=memory, dossier=Dossier.load(cfg.dossier_dir),
        surfaces={"library": lib}
    )
    surface.bot = bot

    # 1. Ảnh
    anchor1 = DummyAnchorMessage()
    await surface._maybe_send_media_outputs(anchor1, f"Kết quả tạo ảnh tại: {img_file}")
    assert len(anchor1.photos_sent) == 1
    assert "chart.png" in anchor1.photos_sent[0][1]

    # 2. Video
    anchor2 = DummyAnchorMessage()
    await surface._maybe_send_media_outputs(anchor2, f"Đã xuất video: {vid_file}")
    assert len(anchor2.videos_sent) == 1
    assert "demo.mp4" in anchor2.videos_sent[0][1]

    # 3. Voice (ogg)
    anchor3 = DummyAnchorMessage()
    await surface._maybe_send_media_outputs(anchor3, f"Bản ghi âm: {voice_file}")
    assert len(anchor3.voices_sent) == 1
    assert "speech.ogg" in anchor3.voices_sent[0][1]

    # 4. Audio (mp3)
    anchor4 = DummyAnchorMessage()
    await surface._maybe_send_media_outputs(anchor4, f"Bản nhạc nền: {audio_file}")
    assert len(anchor4.audios_sent) == 1
    assert "music.mp3" in anchor4.audios_sent[0][1]

    # 5. Tài liệu (pdf)
    anchor5 = DummyAnchorMessage()
    await surface._maybe_send_media_outputs(anchor5, f"Báo cáo phân tích: {doc_file}")
    assert len(anchor5.documents_sent) == 1
    assert "report.pdf" in anchor5.documents_sent[0][1]

    # Kiểm tra tất cả đã vào Thư viện tự động
    items = await lib.list_items()
    item_names = {it["name"] for it in items}
    assert {"chart.png", "demo.mp4", "speech.ogg", "music.mp3", "report.pdf"}.issubset(item_names)
    await memory.close()


@pytest.mark.asyncio
async def test_large_file_degrades_gracefully(cfg, tmp_path):
    """File > 50MB bị degrade có thông báo rõ, không nuốt lỗi im lặng và không crash."""
    memory = await open_memory(cfg)
    ws = Path(cfg.workspace_dir)
    ws.mkdir(parents=True, exist_ok=True)

    big_file = ws / "huge_database.zip"
    big_file.write_bytes(b"x")  # Tạo file

    lib = LibraryService(cfg, memory)
    # Cấu hình giới hạn nhỏ 10 bytes để test vượt ngưỡng
    cfg_custom = Config(
        workspace_dir=str(ws),
        telegram_max_file_size_bytes=10,
    )
    surface = TelegramSurface(
        cfg_custom, agent=None, memory=memory, dossier=Dossier.load(cfg.dossier_dir),
        surfaces={"library": lib}
    )
    anchor = DummyAnchorMessage()
    # Ghi file 20 bytes (> 10 bytes)
    big_file.write_bytes(b"01234567890123456789")
    await surface._maybe_send_media_outputs(anchor, f"Tệp sao lưu: {big_file}")

    assert len(anchor.documents_sent) == 0
    assert len(anchor.text_answers) == 1
    assert "vượt quá giới hạn" in anchor.text_answers[0]
    assert "huge_database.zip" in anchor.text_answers[0]
    await memory.close()


@pytest.mark.asyncio
async def test_natural_language_search_and_tools(cfg):
    """LibraryService tìm kiếm bằng ngôn ngữ tự nhiên không dấu (fold_vi) và tool Agent."""
    memory = await open_memory(cfg)
    ws = Path(cfg.workspace_dir)
    ws.mkdir(parents=True, exist_ok=True)

    f1 = ws / "hop_dong_thue_nha_2026.pdf"
    f1.write_bytes(b"hop dong")
    f2 = ws / "anh_chup_sinh_nhat.jpg"
    f2.write_bytes(b"anh sinh nhat")
    f3 = ws / "huong_dan_cai_dat.md"
    f3.write_bytes(b"huong dan")

    lib = LibraryService(cfg, memory)
    it1 = await lib.index_file(f1, source="user_upload", caption="Hợp đồng thuê căn hộ năm 2026")
    it2 = await lib.index_file(f2, source="user_upload", caption="Tiệc sinh nhật cùng bạn bè")
    it3 = await lib.index_file(f3, source="agent", caption="Tài liệu Markdown kỹ thuật")

    # 1. Tìm theo từ khóa có dấu / không dấu
    res1 = await lib.search("hợp đồng")
    assert len(res1) >= 1
    assert res1[0]["name"] == "hop_dong_thue_nha_2026.pdf"

    res2 = await lib.search("sinh nhat")
    assert len(res2) >= 1
    assert res2[0]["name"] == "anh_chup_sinh_nhat.jpg"

    # 2. Tìm theo caption
    res3 = await lib.search("kỹ thuật")
    assert len(res3) >= 1
    assert res3[0]["name"] == "huong_dan_cai_dat.md"

    # 3. Tìm theo loại (kind)
    res4 = await lib.search("sinh nhật", kind="image")
    assert len(res4) == 1
    assert res4[0]["kind"] == "image"

    # 4. Kiểm tra các tool đăng ký cho Agent
    registry = ToolRegistry()
    tool_names = register_library_tools(registry, lib)
    assert "search_library" in tool_names
    assert "get_library_item" in tool_names
    assert "share_library_item" in tool_names

    tool_res = await registry.execute("search_library", {"query": "thuê nhà"})
    assert tool_res["ok"] is True
    assert tool_res["count"] >= 1
    assert tool_res["items"][0]["name"] == "hop_dong_thue_nha_2026.pdf"

    detail_res = await registry.execute("get_library_item", {"item_id": it1["id"]})
    assert detail_res["ok"] is True
    assert detail_res["item"]["name"] == "hop_dong_thue_nha_2026.pdf"
    await memory.close()


@pytest.mark.asyncio
async def test_share_library_item_max_48h(cfg):
    """Link chia sẻ luôn được clamp <= 48h theo checklist E2."""
    memory = await open_memory(cfg)
    ws = Path(cfg.workspace_dir)
    ws.mkdir(parents=True, exist_ok=True)
    f = ws / "share_test.md"
    f.write_text("chia se noi dung", encoding="utf-8")

    lib = LibraryService(cfg, memory)
    it = await lib.index_file(f)

    # Thử yêu cầu 100 giờ -> phải clamp về 48 giờ
    res = await lib.share_item(it["id"], hours=100.0, base_url="https://mulon.test")
    assert res["ok"] is True
    assert res["share_status"] == "active"
    exp = datetime.fromisoformat(res["share_expires_at"])
    now = datetime.now(timezone.utc)
    delta = exp - now
    assert timedelta(hours=47) <= delta <= timedelta(hours=48, minutes=5)
    await memory.close()


@pytest.mark.asyncio
async def test_sidechat_history_isolation_and_shared_user_memory(cfg):
    """Chat phụ (E3 + R15): transcript độc lập, không lẫn history, nhưng dùng chung ký ức bền của user."""
    memory = await open_memory(cfg)
    dossier = Dossier.load(cfg.dossier_dir)
    ctx_engine = ContextEngine(cfg, dossier, memory, gateway=None)

    main_session = "agent:main:telegram:group:-100999:topic:1"
    sidechat_session = "agent:main:telegram:group:-100999:topic:42"

    # Main chat: thêm 2 tin nhắn và ghi 1 sự thật về user
    await memory.append_message(main_session, "user", "Chào bot, tôi là kỹ sư phần mềm tại Hà Nội.")
    await memory.append_message(main_session, "assistant", "Chào bạn, mình đã ghi nhớ bạn là kỹ sư tại Hà Nội.")
    await memory.add_fact("Người dùng là kỹ sư phần mềm sống tại Hà Nội", subject="nghề nghiệp", source="main_chat")

    # Sidechat: thêm 1 tin nhắn
    await memory.append_message(sidechat_session, "user", "Đây là cuộc trò chuyện trong chat phụ về dự án X.")
    await memory.append_message(sidechat_session, "assistant", "Rõ rồi, chúng ta sẽ tập trung vào dự án X tại đây.")

    # 1. Kiểm chứng cô lập history
    main_msgs = await memory.recent_messages(main_session)
    side_msgs = await memory.recent_messages(sidechat_session)

    main_contents = [m["content"] for m in main_msgs]
    side_contents = [m["content"] for m in side_msgs]

    assert any("Hà Nội" in c for c in main_contents)
    assert not any("dự án X" in c for c in main_contents)

    assert any("dự án X" in c for c in side_contents)
    assert not any("Chào bạn, mình đã ghi nhớ bạn là kỹ sư tại Hà Nội" in c for c in side_contents)

    # 2. Kiểm chứng ký ức dùng chung (recall fact từ chat chính vào chat phụ)
    recalled_facts = await memory.recall("nghề nghiệp kỹ sư")
    assert any("kỹ sư phần mềm" in f.get("text", "") for f in recalled_facts)

    await memory.close()


def test_r15_routing_session_key():
    """Kiểm tra tách chat_id và thread_id từ session_key chuẩn R15."""
    # DM
    c1, t1 = parse_session_key("agent:main:telegram:dm:123456:topic:0")
    assert c1 == 123456
    assert t1 is None

    # Group forum topic
    c2, t2 = parse_session_key("agent:main:telegram:group:-100123456789:topic:88")
    assert c2 == -100123456789
    assert t2 == 88

    # Group topic 0
    c3, t3 = parse_session_key("agent:main:telegram:group:-100123456789:topic:0")
    assert c3 == -100123456789
    assert t3 is None

    # Invalid
    c4, t4 = parse_session_key("invalid_session_key")
    assert c4 is None
    assert t4 is None
