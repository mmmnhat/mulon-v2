"""Kiểm thử tầng Presentation & Delivery Telegram (ADR-001 / T-39.6).

Kiểm thử độc lập các hàm formatting, chunking, tag balancing và progress rendering
mà KHÔNG phụ thuộc vào aiogram Bot / polling loop.
"""
from __future__ import annotations

import pytest

from mulon.telegram_delivery import (
    clean_final_text,
    md_to_html,
    safe_stream_markdown_to_html,
    chunk_html,
    format_progress_lines,
    _open_tags,
)
import mulon.telegram_bot as tb


def test_reexport_backward_compatibility():
    """Kiểm tra toàn bộ các hàm và hằng số presenter vẫn được re-export qua mulon.telegram_bot."""
    assert tb.clean_final_text is clean_final_text
    assert tb.md_to_html is md_to_html
    assert tb.safe_stream_markdown_to_html is safe_stream_markdown_to_html
    assert tb.chunk_html is chunk_html
    assert tb.format_progress_lines is format_progress_lines
    assert tb._open_tags is _open_tags


def test_clean_final_text():
    """Kiểm tra loại bỏ dòng phân cách thô (---, ***, ___) và chuẩn hóa khoảng cách dòng."""
    raw = "Phần 1\n\n---\n\nPhần 2\n\n***\n\n\n\nPhần 3"
    cleaned = clean_final_text(raw)
    assert "---" not in cleaned
    assert "***" not in cleaned
    assert "\n\n\n" not in cleaned
    assert "Phần 1" in cleaned and "Phần 2" in cleaned and "Phần 3" in cleaned


def test_md_to_html_safety_and_formatting():
    """Kiểm tra chuyển đổi markdown sang HTML an toàn, chống injection."""
    # 1. Bold và Header
    text = "### Tiêu đề\nĐây là **chữ đậm** và `code`."
    res = md_to_html(text)
    assert "<b>Tiêu đề</b>" in res
    assert "<b>chữ đậm</b>" in res
    assert "<code>code</code>" in res

    # 2. Xử lý thẻ HTML thô chèn vào (phải bị escape, không được thành thẻ thật)
    malicious = "<script>alert(1)</script> và <img src=x onerror=alert(1)>"
    res_mal = md_to_html(malicious)
    assert "<script>" not in res_mal
    assert "&lt;script&gt;" in res_mal
    assert "<img" not in res_mal

    # 3. Code block nhiều dòng
    code_block = "Code:\n```python\nprint('hello')\n```"
    res_code = md_to_html(code_block)
    assert "<pre>python\nprint(&#x27;hello&#x27;)</pre>" in res_code


def test_safe_stream_markdown_to_html():
    """Kiểm tra khả năng tự đóng thẻ dở dang khi đang stream."""
    # Dở dang code block ```
    partial_code = "Đang viết code:\n```python\ndef foo():"
    streamed = safe_stream_markdown_to_html(partial_code)
    assert "<pre>" in streamed and "</pre>" in streamed

    # Dở dang bold **
    partial_bold = "Đang nói **rất quan trọng"
    streamed_bold = safe_stream_markdown_to_html(partial_bold)
    assert "<b>" in streamed_bold and "</b>" in streamed_bold


def test_chunk_html_balances_tags():
    """Kiểm tra việc chia nhỏ khối HTML không làm vỡ thẻ mở/đóng."""
    long_html = "<b>" + ("Tin tức quan trọng. " * 300) + "</b>"
    chunks = chunk_html(long_html, max_chars=400)
    assert len(chunks) > 1

    for c in chunks:
        # Mỗi chunk phải đóng đủ thẻ đã mở
        stack = _open_tags(c)
        assert len(stack) == 0, f"Chunk bị rò thẻ chưa đóng: {c}"


def test_format_progress_lines():
    """Kiểm tra format danh sách bước tiến trình trực quan chuẩn Muse."""
    steps = [
        {"icon": "✓", "text": "Bước 1 xong"},
        {"icon": "⏳", "text": "Bước 2 đang chạy"},
    ]
    out = format_progress_lines(steps)
    assert "<b>⏳ Đang xử lý:</b>" in out
    assert "✓ Bước 1 xong" in out
    assert "⏳ Bước 2 đang chạy" in out
