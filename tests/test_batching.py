"""Gom tin liên tiếp: cả chùm tin trong cửa sổ debounce thành 1 lượt,
nội dung nối theo thứ tự; chunk HTML không làm vỡ thẻ."""

import asyncio

from mulon.telegram_bot import MessageBatcher, chunk_html


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
