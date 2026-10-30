"""Mulon — Telegram Presentation & Delivery Layer (ADR-001 / T-39.6).

Phân tầng Presentation tách biệt khỏi Ingress & Agent Loop:
- Xử lý định dạng HTML Telegram an toàn (md_to_html, safe_stream_markdown_to_html).
- Cắt khối tin nhắn an toàn (chunk_html < 4096 ký tự) tự cân bằng thẻ mở/đóng.
- Làm sạch đầu ra văn bản (clean_final_text).
- Format tiến trình trực quan chuẩn Muse.
"""
from __future__ import annotations

import html
import re
from typing import Optional

_VOID_TAGS = {"br", "hr"}
_KNOWN_TAGS = {
    "b", "strong", "i", "em", "u", "s", "code", "pre", "a",
    "blockquote", "tg-spoiler"
}
_TAG_RE = re.compile(r"<(/?)([a-zA-Z][\w-]*)((?:\s[^<>]*)?)>")

_CODE_OR_LINK_RE = re.compile(
    r"```([\s\S]*?)```|`([^`\n]+)`|\[([^\]]+)\]\((https?://[^\s)]+)\)"
)
_BOLD_RE = re.compile(r"\*\*([^*\n]+)\*\*")
_HEADING_RE = re.compile(r"^#{1,6}\s+(.+)$", flags=re.MULTILINE)
_HR_RE = re.compile(r"^[ \t]*([-*_][ \t]*){3,}$", flags=re.MULTILINE)


def _open_tags(text: str) -> list[tuple[str, str]]:
    """Xác định các thẻ HTML chưa đóng trong chuỗi văn bản."""
    stack: list[tuple[str, str]] = []
    for m in _TAG_RE.finditer(text):
        closing, name, attrs = m.group(1), m.group(2).lower(), m.group(3) or ""
        if name in _VOID_TAGS:
            continue
        if closing:
            for i in range(len(stack) - 1, -1, -1):
                if stack[i][0] == name:
                    del stack[i:]
                    break
        else:
            stack.append((name, attrs))
    return stack


def clean_final_text(text: str) -> str:
    """Làm sạch văn bản đầu ra: loại bỏ các dòng phân cách thô (---, ***, ___) và chuẩn hóa dòng trống thừa (T-24.7)."""
    if not text:
        return ""
    cleaned = _HR_RE.sub("", text)
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    return cleaned


def safe_stream_markdown_to_html(text: str) -> str:
    """Chuyển đổi markdown đang stream thành HTML an toàn, tự đóng các thẻ dở dang để không bao giờ lộ markdown thô trên Telegram (T-24.7)."""
    if not text:
        return ""
    # Tự đóng code block dở dang (số lượng ``` lẻ)
    if text.count("```") % 2 == 1:
        text = text + "\n```"
    elif text.count("`") % 2 == 1:
        text = text + "`"
    if text.count("**") % 2 == 1:
        text = text + "**"
    html_text = md_to_html(text)
    chunks = chunk_html(html_text)
    return chunks[0] if chunks else ""


def md_to_html(text: str) -> str:
    """Converter Markdown -> HTML TỐI THIỂU và AN TOÀN cho câu trả lời của model (NC-1).

    Code block/inline + link được trích ra và escape riêng trước, phần còn lại escape toàn bộ
    rồi mới áp **bold** và heading -> <b>. Nhờ escape trước, HTML thô do model (hoặc nội dung web)
    chèn vào không bao giờ thành thẻ thật — hết cảnh `**`/`##`/`[chữ](link)` hiện nguyên văn mà
    cũng không vỡ định dạng vì nội dung lạ.
    """
    stash: list[str] = []

    def _keep(m: re.Match) -> str:
        if m.group(1) is not None:
            part = "<pre>" + html.escape(m.group(1).strip("\n")) + "</pre>"
        elif m.group(2) is not None:
            part = "<code>" + html.escape(m.group(2)) + "</code>"
        else:
            part = (
                '<a href="' + html.escape(m.group(4), quote=True) + '">'
                + html.escape(m.group(3)) + "</a>"
            )
        stash.append(part)
        return f"\x00{len(stash) - 1}\x00"

    out = _CODE_OR_LINK_RE.sub(_keep, text or "")
    out = _HR_RE.sub("", out)
    out = re.sub(r"\n{3,}", "\n\n", out)
    out = html.escape(out, quote=False)
    out = _BOLD_RE.sub(r"<b>\1</b>", out)
    out = _HEADING_RE.sub(r"\n<b>\1</b>\n", out)
    return re.sub("\x00(\\d+)\x00", lambda m: stash[int(m.group(1))], out)


def chunk_html(text: str, max_chars: int = 3500) -> list[str]:
    """Chia text HTML thành các chunk <= max_chars, đóng/mở lại thẻ cân bằng."""
    if len(text) <= max_chars:
        return [text]
    chunks: list[str] = []
    rest = text
    prefix = ""
    while rest:
        budget = max_chars - len(prefix)
        if len(rest) <= budget:
            chunks.append(prefix + rest)
            break
        window = rest[:budget]
        cut = max(window.rfind("\n\n"), window.rfind("\n"), window.rfind(" "))
        if cut < budget * 0.4:
            cut = budget
        piece, rest = rest[:cut], rest[cut:].lstrip("\n")
        stack = _open_tags(prefix + piece)
        closing = "".join(f"</{name}>" for name, _ in reversed(stack))
        chunks.append(prefix + piece + closing)
        prefix = "".join(
            f"<{name}{attrs}>" for name, attrs in stack if name in _KNOWN_TAGS
        )
    return [c for c in chunks if c.strip()]


def format_progress_lines(steps: list[dict[str, str]], max_items: int = 4, header: str = "⏳ Đang xử lý:") -> str:
    """Format danh sách các bước tiến trình chuẩn Muse hiển thị trên Telegram message placeholder."""
    lines = [f"<b>{header}</b>"]
    for step in steps[-max_items:]:
        icon = step.get("icon", "•")
        stext = html.escape(step.get("text", ""))
        lines.append(f"{icon} {stext}")
    return "\n".join(lines)
