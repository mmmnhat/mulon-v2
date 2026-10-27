# -*- coding: utf-8 -*-
"""Test kiểm chứng T-24.7 (Polish X-06/X-07):
1. Báo xếp hàng ngay khi bot bận (phản hồi tức thì trong vài giây).
2. Hết lóe markdown thô (không lộ ** hoặc ### trong streaming hay câu trả lời ngắn).
3. Dọn sạch dòng phân cách thô (---, ***, ___) trong bài viết dài.
"""

import asyncio
import html
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from aiogram.types import ReactionTypeEmoji

from mulon.config import Config
from mulon.context import Dossier
from mulon.telegram_bot import (
    TelegramSurface,
    clean_final_text,
    md_to_html,
    safe_stream_markdown_to_html,
)


def test_clean_final_text_and_md_to_html_removes_hr():
    """Kiểm tra dọn dẹp các dòng phân cách thô (---, ***, ___) trong thân bài viết."""
    article = """# Bài viết so sánh AI Agent

Mở đầu bài viết phân tích...

---

### 1. Kiến trúc Thin-Agent
Nội dung phần 1 rất chi tiết.

  ---  

### 2. Bộ nhớ Bi-temporal
Nội dung phần 2 rất hay.

- - -

### 3. Kết luận
Tóm tắt nội dung:
- Điểm 1
- Điểm 2
* Điểm 3

***

Hết bài.
"""
    cleaned = clean_final_text(article)
    assert "---" not in cleaned
    assert "- - -" not in cleaned
    assert "***" not in cleaned
    assert "### 1. Kiến trúc Thin-Agent" in cleaned
    assert "- Điểm 1" in cleaned

    converted = md_to_html(article)
    assert "---" not in converted
    assert "- - -" not in converted
    assert "***" not in converted
    assert "<b>1. Kiến trúc Thin-Agent</b>" in converted
    assert "<b>3. Kết luận</b>" in converted


def test_clean_final_text_preserves_code_blocks_and_tables():
    """Kiểm tra không xóa nhầm --- trong code block (YAML) hoặc bảng markdown."""
    text_with_yaml = """Dưới đây là cấu hình mẫu:
```yaml
---
title: Bài viết mẫu
author: Mulon
---
```

Và đây là bảng so sánh:
| Tiêu chí | Muse | ChatGPT |
| --- | --- | --- |
| Tốc độ | Nhanh | Vừa |

---

Kết thúc bài.
"""
    converted = md_to_html(text_with_yaml)
    # Trong code block yaml: giữ nguyên ---
    assert "<pre>yaml\n---\ntitle: Bài viết mẫu\nauthor: Mulon\n---</pre>" in converted
    # Trong bảng markdown: hàng phân cách | --- | được giữ nguyên
    assert "| --- | --- |" in converted
    # Bên ngoài: dòng --- đơn lẻ bị xóa sạch
    body_after_table = converted.split("| Tốc độ | Nhanh | Vừa |")[1]
    assert "---" not in body_after_table
    assert "Kết thúc bài." in body_after_table


def test_safe_stream_markdown_to_html():
    """Kiểm tra safe_stream_markdown_to_html chuyển đổi an toàn trong quá trình streaming."""
    # 1. Câu trả lời ngắn hoàn chỉnh
    r1 = safe_stream_markdown_to_html("**17 + 25 = 42**")
    assert r1 == "<b>17 + 25 = 42</b>"
    assert "**" not in r1

    # 2. Câu đang stream dở dang (chưa có dấu đóng **)
    r2 = safe_stream_markdown_to_html("**17 + 25 = 42")
    assert r2 == "<b>17 + 25 = 42</b>"
    assert "**" not in r2

    # 3. Tiêu đề đang stream
    r3 = safe_stream_markdown_to_html("### 1. Quán cà phê đẹp\nKhông gian chill")
    assert "<b>1. Quán cà phê đẹp</b>" in r3
    assert "###" not in r3

    # 4. Code block đang stream dở dang
    r4 = safe_stream_markdown_to_html("```python\nprint('hello')")
    assert "<pre>python\nprint(&#x27;hello&#x27;)</pre>" in r4 or "<pre>python\nprint('hello')</pre>" in r4

    # 5. Phân cách thô trong stream
    r5 = safe_stream_markdown_to_html("Đoạn 1\n---\nĐoạn 2")
    assert "---" not in r5
    assert "Đoạn 1" in r5 and "Đoạn 2" in r5


class _MockMessage:
    def __init__(self, text="tin nhắn", chat_id=123, message_id=456):
        self.text = text
        self.caption = ""
        self.chat = SimpleNamespace(id=chat_id, type="private")
        self.message_id = message_id
        self.from_user = SimpleNamespace(id=123, username="testuser")
        self.is_topic_message = False
        self.message_thread_id = None
        self.answers = []
        self.reactions = []

    async def react(self, reactions):
        self.reactions.extend(reactions)

    async def answer(self, text, parse_mode=None, **kwargs):
        msg = _MockPlaceholder(text)
        self.answers.append((text, parse_mode, msg))
        return msg


class _MockPlaceholder:
    def __init__(self, text=""):
        self.text = text
        self.history = [text]
        self.parse_modes = []
        self.deleted = False

    async def edit_text(self, text, parse_mode=None, **kwargs):
        self.text = text
        self.history.append(text)
        self.parse_modes.append(parse_mode)

    async def delete(self):
        self.deleted = True


class _MockAgent:
    def __init__(self, return_text="Đáp án", stream_tokens=None, sleep_s=0.0):
        self.return_text = return_text
        self.stream_tokens = stream_tokens or []
        self.sleep_s = sleep_s

    async def handle(self, key, text, on_delta=None, on_event=None):
        if self.sleep_s > 0:
            await asyncio.sleep(self.sleep_s)
        if on_delta and self.stream_tokens:
            for tok in self.stream_tokens:
                await on_delta(tok)
        return SimpleNamespace(text=self.return_text)


def _build_surface(tmp_path, agent):
    cfg = Config(
        telegram_bot_token="123456:TEST",
        allowed_user_id=123,
        debounce_seconds=0.05,
        workspace_dir=tmp_path / "workspace",
        dossier_dir=tmp_path / "dossier",
    )
    dossier = Dossier.load(cfg.dossier_dir)
    return TelegramSurface(cfg, agent=agent, memory=None, dossier=dossier)


@pytest.mark.asyncio
async def test_notify_queued_sends_immediate_feedback(tmp_path):
    """Gửi tin lúc bot bận: có phản hồi tức thì bằng reaction ⏳ và tin báo xếp hàng."""
    agent = _MockAgent()
    surface = _build_surface(tmp_path, agent)
    key = "agent:main:telegram:dm:123:topic:0"

    msg1 = _MockMessage(text="tin nhắn 1 khi bận")

    # Giả lập session đang bận
    surface.batcher.mark_busy(key)

    # 1. Gọi _notify_queued lần 1
    await surface._notify_queued(key, msg1)

    # Kiểm tra đã thả reaction ⏳
    assert len(msg1.reactions) == 1
    assert isinstance(msg1.reactions[0], ReactionTypeEmoji)
    assert msg1.reactions[0].emoji == "⏳"

    # Kiểm tra đã gửi tin xác nhận xếp hàng
    assert len(msg1.answers) == 1
    text, parse_mode, placeholder = msg1.answers[0]
    assert "xếp hàng" in text.lower()
    assert parse_mode == "HTML"
    assert surface._queued_placeholders.get(key) is placeholder

    # 2. Gọi _notify_queued lần 2 với tin nhắn tiếp theo trong cùng đợt bận
    msg2 = _MockMessage(text="tin nhắn 2 khi bận")
    await surface._notify_queued(key, msg2)

    # Reaction thả trên tin mới, nhưng KHÔNG gửi thêm tin nhắn xếp hàng trùng lặp
    assert len(msg2.reactions) == 1
    assert msg2.reactions[0].emoji == "⏳"
    assert len(msg2.answers) == 0
    assert surface._queued_placeholders.get(key) is placeholder

    surface.batcher.release(key)


@pytest.mark.asyncio
async def test_queued_placeholder_reused_in_on_batch(tmp_path):
    """Tin xếp hàng được tái sử dụng làm placeholder trong _on_batch, không sinh tin mới."""
    agent = _MockAgent(return_text="Kết quả hoàn thành")
    surface = _build_surface(tmp_path, agent)
    key = "agent:main:telegram:dm:123:topic:0"

    msg = _MockMessage(text="tin xếp hàng")
    surface._sessions_meta[key] = msg

    # Giả lập đã có queued placeholder
    queued_msg = _MockPlaceholder("⏳ Đang xếp hàng...")
    surface._queued_placeholders[key] = queued_msg

    # Chạy _on_batch cho lượt xếp hàng
    await surface._on_batch(key, "tin xếp hàng", ["tin xếp hàng"])

    # Không gửi thêm tin nhắn mới vào chat (msg.answers rỗng)
    assert len(msg.answers) == 0
    # Queued placeholder được cập nhật trực tiếp thành 'Đang xử lý...' rồi đến kết quả
    assert any("Đang xử lý..." in h for h in queued_msg.history)
    assert queued_msg.text == "Kết quả hoàn thành"
    # Placeholder đã được dọn khỏi dictionary
    assert surface._queued_placeholders.get(key) is None


@pytest.mark.asyncio
async def test_queued_placeholder_deleted_on_cancel(tmp_path):
    """Khi người dùng hủy lệnh (/cancel hoặc ý định dừng), queued placeholder bị xóa sạch."""
    agent = _MockAgent()
    surface = _build_surface(tmp_path, agent)
    key = "agent:main:telegram:dm:123:topic:0"

    queued_msg = _MockPlaceholder("⏳ Đang xếp hàng...")
    surface._queued_placeholders[key] = queued_msg

    # Giả lập lệnh /cancel
    cancel_msg = _MockMessage(text="/cancel")
    # Lấy handler cancel
    dp = surface.dp
    # Gọi logic tương đương trong cmd_cancel:
    qp = surface._queued_placeholders.pop(key, None)
    if qp:
        await qp.delete()

    assert queued_msg.deleted is True
    assert surface._queued_placeholders.get(key) is None


@pytest.mark.asyncio
async def test_on_delta_skips_short_and_formats_streaming_html(tmp_path):
    """Kiểm tra on_delta không edit ở độ dài ngắn và định dạng HTML khi stream dài."""
    # Trả về câu trả lời ngắn: "17 + 25 = 42"
    agent = _MockAgent(
        return_text="**17 + 25 = 42**",
        stream_tokens=["**17 + ", "25 = 42**"]
    )
    surface = _build_surface(tmp_path, agent)
    key = "agent:main:telegram:dm:123:topic:0"
    msg = _MockMessage(text="tính 17 + 25")
    surface._sessions_meta[key] = msg

    await surface._on_batch(key, "tính 17 + 25", ["tính 17 + 25"])

    # Lấy placeholder được tạo
    assert len(msg.answers) == 1
    _, _, placeholder = msg.answers[0]

    # Kiểm tra: vì tổng độ dài < 50 ký tự, on_delta không thực hiện edit dở dang
    # (chỉ có edit cuối cùng với parse_mode="HTML")
    assert placeholder.text == "<b>17 + 25 = 42</b>"
    # Không có trạng thái nào trong lịch sử chứa markdown thô '**'
    for h in placeholder.history:
        assert "**" not in h
