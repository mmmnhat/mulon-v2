"""Nạp dữ liệu/prompt từ file thay vì hardcode trong code.

Vá audit hardcode 2026-10-26: bảng từ khóa intent, marker học tập,
danh sách nguồn Feed và các prompt hệ thống từng nằm chết trong
``.py`` — sửa hành vi là phải sửa code + deploy. Nay chúng là dữ
liệu:

- ``config/*.json`` ở thư mục gốc dự án (intent_hints,
  learning_markers, feed_sources, mcp_fallbacks...)
- ``mulon/prompts/*.txt`` cho prompt hệ thống

Thiếu/hỏng file thì trả fallback và ghi log — không sập hệ thống.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger("mulon.datafiles")

_PACKAGE_DIR = Path(__file__).resolve().parent
_CONFIG_DIR = _PACKAGE_DIR.parent / "config"
_PROMPTS_DIR = _PACKAGE_DIR / "prompts"

_json_cache: dict[str, object] = {}
_prompt_cache: dict[str, str] = {}


def load_json_data(name: str, fallback):
    """Đọc ``config/<name>`` (JSON). Lỗi -> fallback + log."""
    if name in _json_cache:
        return _json_cache[name]
    try:
        data = json.loads((_CONFIG_DIR / name).read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("đọc %s lỗi (%s) — dùng fallback", name, exc)
        data = fallback
    _json_cache[name] = data
    return data


def load_prompt(name: str, fallback: str = "") -> str:
    """Đọc ``mulon/prompts/<name>.txt`` nguyên văn. Lỗi -> fallback."""
    if name in _prompt_cache:
        return _prompt_cache[name]
    try:
        text = (_PROMPTS_DIR / f"{name}.txt").read_text(encoding="utf-8")
    except Exception as exc:
        logger.warning("đọc prompt %s lỗi (%s) — dùng fallback", name, exc)
        text = fallback
    _prompt_cache[name] = text
    return text
