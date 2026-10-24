"""Gom tin liên tiếp: cả chùm tin trong cửa sổ debounce thành 1 lượt,
nội dung nối theo thứ tự; chunk HTML không làm vỡ thẻ.

Phần sau (vá 1.1.1): tin tới TRONG LÚC một lượt đang chạy hoặc
đang chờ lock phải bị giữ (hold) rồi drain/gộp — không nứt thành
lượt riêng lẻ như cảnh thật user gặp: gửi "Bạn làm được gì" rồi
gõ tiếp "List ra" trong lúc bot đang xử lý, nhận 2 câu trả lời
đầy đủ chồng nhau thay vì 1 lượt gộp + 1 lượt tiếp nối.
"""

import asyncio
import dataclasses
from types import SimpleNamespace

import pytest

from mulon.context import Dossier
from mulon.telegram_bot import MessageBatcher, TelegramSurface, \
    chunk_html


async def test_batcher_merges_burst_into_one_turn():
    flushed = []

    async def on_flush(key, joined, parts):
        flushed.append((key, joined, parts))

    batcher = MessageBatcher(debounce_s=0.05, on_flush=on_flush)
    await batcher.add("s1", "tin một")
    await batcher.add("s1", "tin hai")
    await batcher.add("s1", "tin ba")
    await asyncio.sleep(0.2)
    assert len(flushed) == 1
    key, joined, parts = flushed[0]
    assert key == "s1"
    assert parts == ["tin một", "tin hai", "tin ba"]
    assert joined == "tin một\ntin hai\ntin ba"


async def test_batcher_separate_sessions_stay_separate():
    flushed = []

    async def on_flush(key, joined, parts):
        flushed.append(key)

    batcher = MessageBatcher(debounce_s=0.05, on_flush=on_flush)
    await batcher.add("s1", "a")
    await batcher.add("s2", "b")
    await asyncio.sleep(0.2)
    assert sorted(flushed) == ["s1", "s2"]


async def test_batcher_flush_now():
    flushed = []

    async def on_flush(key, joined, parts):
        flushed.append(joined)

    batcher = MessageBatcher(debounce_s=60, on_flush=on_flush)
    await batcher.add("s1", "gửi ngay")
    await batcher.flush_now("s1")
    assert flushed == ["gửi ngay"]


def test_chunk_html_keeps_tags_balanced():
    text = ("<b>đoạn in đậm rất dài</b> " * 60) + " phần cuối <i>nghiêng</i>"
    chunks = chunk_html(text, max_chars=500)
    assert len(chunks) > 1
    for chunk in chunks:
        assert len(chunk) <= 500 + 20
        assert chunk.count("<b>") == chunk.count("</b>")
        assert chunk.count("<i>") == chunk.count("</i>")


def test_chunk_html_short_text_single_chunk():
    assert chunk_html("xin chào", max_chars=500) == ["xin chào"]


# ----------------- vá 1.1.1: giữ tin khi session bận -----------------

async def test_batcher_holds_messages_while_busy_until_release():
    flushed = []

    async def on_flush(key, joined, parts):
        flushed.append((joined, parts))

    batcher = MessageBatcher(debounce_s=0.05, on_flush=on_flush)
    batcher.mark_busy("s1")
    await batcher.add("s1", "tin B")
    await batcher.add("s1", "tin C")
    await asyncio.sleep(0.2)  # quá cửa sổ debounce mà vẫn chưa flush
    assert flushed == []
    assert batcher.is_busy("s1")
    batcher.release("s1")  # kick: hẹn giờ debounce cho phần bị giữ
    await asyncio.sleep(0.2)
    assert flushed == [("tin B\ntin C", ["tin B", "tin C"])]
    assert not batcher.is_busy("s1")


async def test_batcher_drain_takes_buffer_and_cancels_timer():
    flushed = []

    async def on_flush(key, joined, parts):
        flushed.append(joined)

    batcher = MessageBatcher(debounce_s=0.05, on_flush=on_flush)
    await batcher.add("s1", "một")
    await batcher.add("s1", "hai")
    assert batcher.drain("s1") == ["một", "hai"]
    await asyncio.sleep(0.2)
    assert flushed == []  # timer đã bị hủy: không flush thêm lần nữa
    assert batcher.drain("s1") == []


class _FakeAnchor:
    """Neo tin nhắn giả cho _on_batch: react + answer -> placeholder
    (cùng khuôn với _FakeAnchor ở test_bootstrap_flow)."""

    def __init__(self):
        self.answers = []
        self.placeholders = []

    async def react(self, reactions):
        pass

    async def answer(self, text, **kw):
        self.answers.append(text)
        placeholder = SimpleNamespace(text=None)

        async def edit_text(t, **kw2):
            placeholder.text = t

        placeholder.edit_text = edit_text
        self.placeholders.append(placeholder)
        return placeholder


class _GatedAgent:
    """Agent giả ghi lại mọi lượt; lượt đầu tiên chặn ở `gate` để
    giả cảnh bot đang xử lý lâu trong lúc user gõ tiếp, hoặc ném
    lỗi ngay (fail_first) để kiểm tra session không kẹt bận."""

    def __init__(self, fail_first: bool = False):
        self.calls: list[str] = []
        self.started = asyncio.Event()
        self.gate = asyncio.Event()
        self.fail_first = fail_first

    async def handle(self, key, text, on_delta=None, on_event=None):
        self.calls.append(text)
        if len(self.calls) == 1:
            self.started.set()
            if self.fail_first:
                raise RuntimeError("agent giả vờ sập")
            await self.gate.wait()
        return SimpleNamespace(text=f"đã xử: {text}")


def _fast_surface(cfg, agent) -> TelegramSurface:
    cfg = dataclasses.replace(cfg, debounce_seconds=0.05)
    dossier = Dossier.load(cfg.dossier_dir)
    surface = TelegramSurface(cfg, agent=agent, memory=None,
                              dossier=dossier)
    key = "agent:main:telegram:dm:42:topic:0"
    surface._sessions_meta[key] = _FakeAnchor()
    return surface


async def _wait_calls(agent: _GatedAgent, n: int, timeout: float = 3.0):
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while len(agent.calls) < n:
        if loop.time() > deadline:
            raise AssertionError(
                f"chờ {n} lượt mà agent mới nhận {agent.calls}")
        await asyncio.sleep(0.01)


async def test_messages_during_active_turn_merge_into_one_followup(cfg):
    """Tái hiện cảnh thật: tin A đang được xử lý (agent bị chặn),
    user gõ tiếp B và C -> tổng cộng đúng 2 lượt, lượt 2 chứa cả
    B và C theo thứ tự."""
    agent = _GatedAgent()
    surface = _fast_surface(cfg, agent)
    key = "agent:main:telegram:dm:42:topic:0"

    await surface.batcher.add(key, "Bạn làm được gì")
    await asyncio.wait_for(agent.started.wait(), timeout=2)
    await surface.batcher.add(key, "List ra")
    await surface.batcher.add(key, "cụ thể đi")
    await asyncio.sleep(0.2)  # quá vài cửa sổ debounce
    # Lượt 1 còn chạy: B/C bị giữ, không nứt thành lượt riêng.
    assert agent.calls == ["Bạn làm được gì"]
    agent.gate.set()
    await _wait_calls(agent, 2)
    assert agent.calls[1] == "List ra\ncụ thể đi"
    await asyncio.sleep(0.2)
    assert len(agent.calls) == 2


async def test_message_while_waiting_for_lock_is_drained(cfg):
    """Lượt 2 đã flush và đang chờ lock; tin C tới lúc đó phải bị
    drain vào chính lượt 2 — không sinh lượt thứ ba."""
    agent = _GatedAgent()
    surface = _fast_surface(cfg, agent)
    key = "agent:main:telegram:dm:42:topic:0"

    first = asyncio.create_task(surface._on_batch(key, "A", ["A"]))
    await asyncio.wait_for(agent.started.wait(), timeout=2)
    second = asyncio.create_task(surface._on_batch(key, "B", ["B"]))
    await asyncio.sleep(0.05)  # cho lượt 2 kịp xếp hàng chờ lock
    await surface.batcher.add(key, "C")
    await asyncio.sleep(0.2)
    assert agent.calls == ["A"]
    agent.gate.set()
    await asyncio.wait_for(first, timeout=2)
    await asyncio.wait_for(second, timeout=2)
    assert agent.calls == ["A", "B\nC"]
    await asyncio.sleep(0.2)
    assert len(agent.calls) == 2


async def test_agent_error_does_not_wedge_session_busy(cfg):
    """HT-1: agent.handle ném lỗi ở lượt 1 -> bề mặt KHÔNG văng
    lỗi ra ngoài và KHÔNG treo placeholder: user nhận tin lỗi lời
    thường ngay trên placeholder, session nhả bận, tin sau được
    xử lý bình thường."""
    agent = _GatedAgent(fail_first=True)
    surface = _fast_surface(cfg, agent)
    key = "agent:main:telegram:dm:42:topic:0"

    await surface._on_batch(key, "tin đầu", ["tin đầu"])  # không raise
    assert not surface.batcher.is_busy(key)
    anchor = surface._sessions_meta[key]
    shown = " ".join(
        [a for a in anchor.answers]
        + [p.text or "" for p in anchor.placeholders])
    assert "đang lỗi" in shown and "thử lại" in shown
    await surface.batcher.add(key, "tin sau")
    await _wait_calls(agent, 2)
    assert agent.calls == ["tin đầu", "tin sau"]
