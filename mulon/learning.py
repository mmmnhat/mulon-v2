"""Học từ lần bị sửa — vòng kín (thiết kế mục 4.4).

Tầng 2 của vòng học: khi user sửa/phàn nàn, sự kiện `correction` được
ghi NGAY trong lượt (không chờ worker nền):

1. Heuristic từ khoá tiếng Việt (có gấp dấu) phát hiện tín hiệu sửa.
2. Trúng heuristic -> model rẻ phân loại: có đúng là correction
   không, loại lỗi theo taxonomy, mức nghiêm trọng, có rõ ràng không.
   Model lỗi -> fallback phân loại bằng từ khoá, vẫn ghi sự kiện.
3. Rút bài học có chống overfit: chỉ thăng thành lesson khi có
   >=1 correction rõ ràng HOẶC >=2 lần lặp cùng loại lỗi; riêng lỗi
   đụng tiền bạc/an toàn (severity='critical') thì 1 lần là đủ.
4. Lesson lưu thành fact kind 'lesson' (subject = "lesson:<loại>"),
   được ContextEngine nạp vào snapshot ở mục riêng. Lesson mới cùng
   loại thay thế lesson cũ (bi-temporal), mọi thay đổi qua ledger.
5. Correction nghiêm trọng tự sinh test case vào evals/cases.jsonl
   (chỉ sinh, chưa chạy — bộ eval thuộc Phase 5).
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .memory import fold_vi
from .datafiles import load_json_data, load_prompt

logger = logging.getLogger("mulon.learning")

# Taxonomy cố định (mục 4.4 tầng 3).
TAXONOMY = ("du_kien", "quy_trinh", "giong_format", "tool", "tri_nho")

# Dấu hiệu sửa RÕ RÀNG — trúng là ứng viên explicit.
# Vá audit hardcode 2026-10-26: marker học tập ở
# config/learning_markers.json.
_LEARNING_DATA = load_json_data("learning_markers.json", {})
STRONG_MARKERS = tuple(_LEARNING_DATA.get("strong_markers", ()))
# Dấu hiệu sửa NHẸ — vẫn là tín hiệu correction, chờ phân loại.
WEAK_MARKERS = tuple(_LEARNING_DATA.get("weak_markers", ()))
# Từ khoá đụng tiền bạc / an toàn -> severity critical (1 lần là đủ học).
CRITICAL_HINTS = tuple(_LEARNING_DATA.get("critical_hints", ()))
# Fallback đoán loại lỗi bằng từ khoá khi model rẻ không dùng được.
_CATEGORY_HINTS = {k: tuple(v) for k, v in
                   _LEARNING_DATA.get("category_hints", {}).items()}

CLASSIFY_SYSTEM = load_prompt("classify_system")


def detect_correction(text: str) -> bool:
    """Heuristic rẻ: có dấu hiệu sửa trong tin nhắn hay không."""
    folded = fold_vi(text or "")
    plain = (text or "").lower()
    for marker in STRONG_MARKERS + WEAK_MARKERS:
        if marker in plain or fold_vi(marker) in folded:
            return True
    return False


def _guess_category(text: str) -> str:
    folded = fold_vi(text or "")
    for cat, hints in _CATEGORY_HINTS.items():
        if any(fold_vi(h) in folded for h in hints):
            return cat
    return "du_kien"


def _guess_severity(text: str) -> str:
    folded = fold_vi(text or "")
    return "critical" if any(fold_vi(h) in folded for h in CRITICAL_HINTS) \
        else "normal"


def _looks_explicit(text: str) -> bool:
    plain = (text or "").lower()
    folded = fold_vi(text or "")
    return any(m in plain or fold_vi(m) in folded for m in STRONG_MARKERS)


async def classify_correction(gateway, cfg, user_text: str,
                              wrong_output: str,
                              original_request: str) -> dict:
    """Phân loại bằng model rẻ; lỗi model -> fallback từ khoá."""
    fallback = {
        "is_correction": True,  # heuristic đã trúng thì mặc định ghi
        "explicit": _looks_explicit(user_text),
        "category": _guess_category(user_text),
        "severity": _guess_severity(user_text + " " + wrong_output),
        "corrected": user_text.strip(),
    }
    prompt = [
        {"role": "system", "content": CLASSIFY_SYSTEM},
        {
            "role": "user",
            "content": (
                f"YÊU CẦU GỐC CỦA USER:\n{original_request[:800]}\n\n"
                f"CÂU TRẢ LỜI BỊ SỬA:\n{wrong_output[:1200]}\n\n"
                f"TIN NHẮN MỚI CỦA USER:\n{user_text[:1200]}"
            ),
        },
    ]
    try:
        comp = await gateway.complete(
            prompt, model=cfg.model_cheap, purpose="correction_classify",
            temperature=0.1,
        )
        match = re.search(r"\{.*\}", comp.text or "", flags=re.DOTALL)
        if not match:
            return fallback
        data = json.loads(match.group(0))
        category = str(data.get("category") or "")
        if category not in TAXONOMY:
            category = fallback["category"]
        severity = str(data.get("severity") or "normal")
        if severity not in ("normal", "critical"):
            severity = fallback["severity"]
        return {
            "is_correction": bool(data.get("is_correction")),
            "explicit": bool(data.get("explicit", fallback["explicit"])),
            "category": category,
            "severity": severity,
            "corrected": str(data.get("corrected") or user_text).strip(),
        }
    except Exception as exc:
        logger.warning("phân loại correction lỗi, dùng fallback: %s", exc)
        return fallback


def build_lesson_text(corr: dict) -> str:
    """Bài học có cấu trúc: điều kiện áp dụng + hành vi đúng + ví dụ."""
    orig = (corr.get("original_request") or "").strip()[:200]
    wrong = (corr.get("wrong_output") or "").strip()[:200]
    right = (corr.get("corrected") or "").strip()[:300]
    return (
        f"ĐIỀU KIỆN ÁP DỤNG: yêu cầu tương tự như «{orig}». "
        f"HÀNH VI ĐÚNG: {right}. "
        f"VÍ DỤ SAI (đã bị user sửa): {wrong}. "
        f"VÍ DỤ ĐÚNG: {right}."
    )


def append_eval_case(cfg, corr: dict) -> Optional[Path]:
    """Correction nghiêm trọng -> 1 test case JSONL (chỉ sinh, chưa chạy)."""
    try:
        path = Path(cfg.evals_dir) / "cases.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        case = {
            "id": f"correction-{corr['id']}",
            "category": corr.get("category", ""),
            "severity": corr.get("severity", ""),
            "original_request": corr.get("original_request", ""),
            "wrong_output": corr.get("wrong_output", ""),
            "expected": corr.get("corrected", ""),
            "source_correction_id": corr["id"],
            "created_at": datetime.now(timezone.utc).isoformat(
                timespec="seconds"),
        }
        with path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(case, ensure_ascii=False) + "\n")
        return path
    except Exception as exc:
        logger.warning("ghi eval case lỗi (bỏ qua): %s", exc)
        return None


async def maybe_create_lesson(memory, corr: dict) -> Optional[int]:
    """Thăng correction thành lesson nếu đủ ngưỡng chống overfit.

    Ngưỡng: severity critical (1 lần) HOẶC explicit (1 lần rõ ràng)
    HOẶC >=2 correction cùng category. Lesson mới cùng category
    thay thế lesson cũ — qua supersede bi-temporal + ledger, hoàn
    tác được (mục 4.4 tầng 3).
    """
    category = corr.get("category") or "du_kien"
    repeats = await memory.count_corrections(category=category)
    promote = (
        corr.get("severity") == "critical"
        or bool(corr.get("explicit"))
        or repeats >= 2
    )
    if not promote:
        return None
    subject = f"lesson:{category}"
    active = await memory.active_facts(limit=500)
    old_lessons = [
        f["id"] for f in active if str(f.get("subject") or "") == subject
    ]
    text = build_lesson_text(corr)
    fact_id = await memory.add_fact(
        text, subject=subject, salience=0.95,
        source=f"correction:{corr['id']}",
        supersedes=old_lessons,
    )
    await memory.append_ledger(
        f"fact:{fact_id}", "lesson_created", text,
        detail=f"correction:{corr['id']} category:{category}",
    )
    await memory.set_correction_lesson(int(corr["id"]), fact_id)
    await memory.log_trajectory(
        corr.get("session_key", ""), "lesson_created",
        {"correction_id": corr["id"], "lesson_fact_id": fact_id,
         "category": category, "superseded": old_lessons},
    )
    return fact_id


async def record_correction(memory, cfg, session_key: str,
                            user_msg_id: Optional[int],
                            original_request: str, wrong_output: str,
                            user_text: str, cls: dict) -> int:
    """Ghi correction + rút lesson nếu đủ ngưỡng + sinh eval case."""
    corr_id = await memory.add_correction(
        session_key=session_key,
        corrected=str(cls.get("corrected") or user_text),
        original_request=original_request,
        wrong_output=wrong_output,
        user_msg_id=user_msg_id,
        category=str(cls.get("category") or "du_kien"),
        severity=str(cls.get("severity") or "normal"),
        explicit=bool(cls.get("explicit")),
    )
    corr = await memory.get_correction(corr_id) or {"id": corr_id}
    await memory.log_trajectory(
        session_key, "correction_recorded",
        {"correction_id": corr_id, "category": corr.get("category"),
         "severity": corr.get("severity"),
         "explicit": bool(corr.get("explicit"))},
    )
    try:
        await maybe_create_lesson(memory, corr)
    except Exception as exc:
        logger.warning("rút bài học lỗi (correction vẫn đã ghi): %s", exc)
    if corr.get("severity") == "critical":
        append_eval_case(cfg, corr)
    return corr_id


async def detect_and_record(memory, gateway, cfg, session_key: str,
                            user_msg_id: int,
                            user_text: str) -> Optional[int]:
    """Điểm vào từ agent: phát hiện + ghi correction ngay trong lượt.

    Không trúng heuristic -> None, không tốn lời gọi model nào.
    Trả id correction đã ghi, hoặc None.
    """
    if not detect_correction(user_text):
        return None
    # Lấy cặp (yêu cầu gốc, output sai) = 2 tin ngay trước tin này.
    cur = await memory.db.execute(
        "SELECT role, content FROM messages WHERE session_key=?"
        " AND id<? ORDER BY id DESC LIMIT 4",
        (session_key, user_msg_id),
    )
    prev = [dict(r) for r in await cur.fetchall()]
    wrong_output = ""
    original_request = ""
    for row in prev:
        if row["role"] == "assistant" and not wrong_output:
            wrong_output = row["content"]
        elif row["role"] == "user" and wrong_output and not original_request:
            original_request = row["content"]
            break
    cls = await classify_correction(
        gateway, cfg, user_text, wrong_output, original_request
    )
    if not cls.get("is_correction"):
        await memory.log_trajectory(
            session_key, "correction_rejected",
            {"user_msg_id": user_msg_id},
        )
        return None
    return await record_correction(
        memory, cfg, session_key, user_msg_id, original_request,
        wrong_output, user_text, cls,
    )
