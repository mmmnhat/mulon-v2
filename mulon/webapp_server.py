"""Mini App server (1.2.0) — backend cho bảng điều khiển Mulon.

Một aiohttp app nhỏ chạy CÙNG process bot, bind 127.0.0.1 cổng
WEBAPP_PORT. Telegram mở Mini App qua Direct Link
(https://t.me/<bot>/<app>?startapp=...) trỏ tới WEBAPP_URL (URL
HTTPS công khai, thường là tunnel về cổng này).

BẢO MẬT (bắt buộc, không có ngoại lệ):
- Mọi /api/* phải có header ``X-Telegram-Init-Data`` hợp lệ:
  chữ ký HMAC-SHA256 theo chuẩn Telegram WebApp (secret key =
  HMAC_SHA256(key="WebAppData", msg=bot_token)), ``auth_date``
  không quá 1 giờ, và ``user.id`` == ALLOWED_USER_ID. Sai bất
  kỳ điều nào -> 401/403.
- Không payload nào chứa giá trị bí mật Vault — chỉ nhãn + ref.
- Server chỉ bind localhost; lớp HTTPS/tunnel là việc của host.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import html
import json
import logging
import platform
import re
import socket
import time
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qsl

from . import __version__ as MULON_VERSION
from .approvals import GROUP_SCOPE_LABELS
from .memory import redact_trajectory_payload
from .cron import next_run_iso, parse_cron
from .feed_auto import (DEFAULT_CRON as FEED_DEFAULT_CRON,
                        SCHEDULE_ID as FEED_SCHEDULE_ID,
                        valid_quiet_hours)
from .planning import internal_kind
from .paths import sanitize_path_display, fix_glued_words
from .proactivity import PROACTIVITY_KV_KEY, effective_enabled
from .ideas import IDEAS_AUTO_KV_KEY, effective_auto_enabled
from .library import _denied_reason
from .memory import fold_vi, now_iso

logger = logging.getLogger("mulon.webapp")

try:
    import aiohttp
    from aiohttp import web

    HAS_AIOHTTP = True
except Exception:  # pragma: no cover - môi trường thiếu gói
    web = None  # type: ignore
    HAS_AIOHTTP = False

INIT_DATA_MAX_AGE_S = 3600
INDEX_HTML = Path(__file__).resolve().parent / "webapp" / "index.html"
WEBAPP_DIR = Path(__file__).resolve().parent / "webapp"
# Asset tĩnh của Mini App (1.3.0): atlas sprite states của avatar
# + manifest hình học đi kèm. Chỉ phục vụ đúng 2 file trong danh
# sách trắng này — không mở đường duyệt thư mục.
STATIC_ASSETS = {
    "sprite-sheet-alpha.png": "image/png",
    "mulon-states-manifest.json": "application/json",
}

# Màu chủ đề Mini App: chỉ đổi HỌ màu nhận diện (lớp 30% — tím
# Mulon và các hue thay thế). Accent hành động chính (10%) là
# bậc đậm nhất của chính hue đang chọn, suy ra ở frontend —
# không có hue riêng. Danh sách này phải khớp THEMES ở
# frontend (index.html).
THEME_KEYS = ("lavender", "blue", "pink", "peach", "green",
              "graphite")
DEFAULT_THEME = "lavender"
THEME_KV_KEY = "webapp_theme"

PROXY_HOST, PROXY_PORT = "127.0.0.1", 8317
PROXY_CACHE_TTL_S = 5.0


# ---------------------------------------------------------------------------
# Validate initData (thuần — test được không cần server)
# ---------------------------------------------------------------------------

def validate_init_data(init_data: str, bot_token: str,
                       allowed_user_id: int | Collection[int],
                       max_age_s: int = INIT_DATA_MAX_AGE_S,
                       now: Optional[float] = None) -> Optional[dict]:
    """Kiểm initData của Telegram WebApp. Hợp lệ -> dict user;
    sai chữ ký / hết hạn / sai user / thiếu trường -> None."""
    if not init_data or not bot_token or not allowed_user_id:
        return None
    try:
        pairs = parse_qsl(init_data, keep_blank_values=True)
    except Exception:
        return None
    data = dict(pairs)
    received_hash = data.pop("hash", None)
    if not received_hash:
        return None
    check_string = "\n".join(
        f"{k}={v}" for k, v in sorted(data.items()))
    secret = hmac.new(b"WebAppData", bot_token.encode("utf-8"),
                      hashlib.sha256).digest()
    calc = hmac.new(secret, check_string.encode("utf-8"),
                    hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, received_hash):
        return None
    now = time.time() if now is None else now
    try:
        auth_date = int(data.get("auth_date") or 0)
    except ValueError:
        return None
    if not auth_date or now - auth_date > max_age_s \
            or auth_date - now > 300:
        return None
    try:
        user = json.loads(data.get("user") or "{}")
    except Exception:
        return None
    if not isinstance(user, dict):
        return None
    uid = int(user.get("id") or 0)
    if isinstance(allowed_user_id, (list, tuple, set)):
        if uid not in allowed_user_id:
            return None
    else:
        if uid != int(allowed_user_id):
            return None
    return user


# ---------------------------------------------------------------------------
# Nhãn trạng thái LỜI THƯỜNG — một bảng ánh xạ duy nhất dùng cho
# cả dòng trạng thái trong chat lẫn header Mini App. Mặt chat/app
# không bao giờ lộ tên tool thô (run_command...) — tên thô chỉ
# xuất hiện ở màn chi tiết lượt việc.
# ---------------------------------------------------------------------------

TOOL_STEP_LABELS = {
    "run_command": "Đang chạy lệnh",
    "read_file": "Đang đọc file",
    "write_file": "Đang ghi file",
    "edit_file": "Đang sửa file",
    "list_files": "Đang liệt kê file",
    "web_fetch": "Đang đọc web",
    "web_read": "Đang đọc web",
    "web_search": "Đang tìm trên web",
    "web_click": "Đang bấm trên trang web",
    "web_fill": "Đang điền trên trang web",
    "web_screenshot": "Đang chụp trang web",
    "now": "Đang xem giờ",
    "connector_health": "Đang kiểm tra kết nối",
    "connector_call": "Đang gọi dịch vụ ngoài",
    "session_search": "Đang tra ký ức",
    "spawn_subagent": "Đang giao việc cho agent con",
    "skill_list": "Đang tra kỹ năng",
    "skill_read": "Đang đọc kỹ năng",
}

GROUP_STEP_LABELS = {
    "shell": "Đang chạy lệnh",
    "file": "Đang xử lý file",
    "web": "Đang đọc web",
    "outbound": "Đang gửi tin nhắn",
    "connector": "Đang gọi dịch vụ ngoài",
    "media": "Đang xử lý media",
    "agent": "Đang giao việc con",
    "skills": "Đang tra kỹ năng",
    "memory": "Đang tra ký ức",
    "schedule": "Đang xử lý lịch hẹn",
    "goals": "Đang xử lý mục tiêu",
}

EVENT_STEP_LABELS = {
    "task_start": "Đang làm việc",
    "verify": "Đang kiểm chứng",
    "retry": "Đang làm lại",
    "approval_requested": "Đang chờ duyệt",
    "task_done": "Sẵn sàng",
}

TOOL_ACTION_LABELS = {
    "run_command": "Chạy lệnh hệ thống",
    "read_file": "Đọc file",
    "write_file": "Ghi file",
    "edit_file": "Sửa file",
    "web_fetch": "Đọc trang web",
    "web_read": "Đọc trang web",
    "web_search": "Tìm trên web",
    "connector_call": "Gọi dịch vụ ngoài",
    "spawn_subagent": "Giao việc cho agent con",
    "send_message": "Gửi tin nhắn",
    "github_push": "Đẩy lên GitHub",
}

_POLICY_LAYER_LABELS = {
    "ask": "Hỏi trước khi chạy",
    "allow": "Cho phép tự động",
    "deny": "Chặn thực thi",
    "host": "Quy tắc lưu bền trên máy",
    "host-tool": "Quy tắc lưu bền trên máy",
    "host-group": "Quy tắc lưu bền trên máy",
    "session": "Quy tắc nhớ trong phiên",
    "session-tool": "Quy tắc nhớ trong phiên",
    "session-group": "Quy tắc nhớ trong phiên",
    "tool-default": "Mặc định an toàn hệ thống",
    "connector-action-default": "Mặc định an toàn hệ thống",
    "connector-action-fallback": "Mặc định an toàn hệ thống",
    "builtin": "Mặc định hệ thống",
}


def policy_layer_label(layer: str) -> str:
    """Nhãn tiếng Việt cho chế độ quyền (layer) trong lịch sử phê duyệt."""
    raw = str(layer or "ask").strip().lower()
    if raw in _POLICY_LAYER_LABELS:
        return _POLICY_LAYER_LABELS[raw]
    return "Hỏi trước khi chạy"


def plain_step_label(kind: str, payload: Optional[dict] = None) -> str:
    """Ánh xạ 1 event của agent -> cụm động từ tiếng Việt ngắn."""
    payload = payload or {}
    if kind == "tool_start":
        tool = str(payload.get("tool") or "")
        if tool in TOOL_STEP_LABELS:
            return TOOL_STEP_LABELS[tool]
        if tool.startswith("media_"):
            return "Đang xử lý media"
        if tool.startswith("schedule"):
            return "Đang xử lý lịch hẹn"
        group = str(payload.get("group") or "")
        return GROUP_STEP_LABELS.get(group, "Đang xử lý")
    return EVENT_STEP_LABELS.get(kind, "")


_GROUP_ACTION_LABELS = {
    "shell": "Chạy lệnh hệ thống",
    "web": "Đọc trang web",
    "file": "Thao tác file",
    "outbound": "Gửi tin nhắn",
}


def known_action_label(tool: str, group: str = "") -> str:
    """Nhãn hành động lời thường ĐÃ BIẾT cho 1 tool: tra bảng
    theo tool trước, theo nhóm sau. Không có nhãn nào khớp ->
    "" để bề mặt tự fallback về tên tool thô (vẫn truy vết
    được ở dòng chi tiết) thay vì bịa nhãn."""
    if tool in TOOL_ACTION_LABELS:
        return TOOL_ACTION_LABELS[tool]
    return _GROUP_ACTION_LABELS.get(group, "")


def tool_action_label(tool: str, group: str = "") -> str:
    """Tên hành động lời thường cho dòng 1 của thẻ duyệt."""
    label = known_action_label(tool, group)
    if label:
        return label
    return f"Dùng công cụ {tool}"


def policy_group_label(group: str) -> str:
    """Nhãn tiếng Việt của 1 nhóm policy cho màn Quyền: dùng
    lại GROUP_SCOPE_LABELS (nguồn nhãn nhóm của thẻ duyệt trên
    chat, ở dạng danh từ) viết hoa chữ đầu. Nhóm lạ (vd
    "mcp:<server>") -> "" để frontend fallback về key thô."""
    raw = GROUP_SCOPE_LABELS.get(group or "", "")
    if not raw:
        return ""
    return raw[:1].upper() + raw[1:]


# ---------------------------------------------------------------------------
# Chuẩn hoá tiêu đề lịch, diễn giải cron tiếng Việt & trạng thái việc (T-23.2..T-23.4)
# ---------------------------------------------------------------------------

def _truncate_words(text: str, max_len: int = 80) -> str:
    """Cắt chuỗi theo ranh giới từ (không cắt đứt giữa từ, QA Q-07 / T-23.4)."""
    s = re.sub(r"\s+", " ", (text or "").strip())
    if len(s) <= max_len:
        return s
    cut = s[:max_len]
    last_space = cut.rfind(" ")
    if last_space > 0:
        cut = cut[:last_space]
    return cut.rstrip(" ,;:-") + "…"


_DOW_VI_NAMES = {
    "0": "Chủ nhật",
    "7": "Chủ nhật",
    "1": "Thứ 2",
    "2": "Thứ 3",
    "3": "Thứ 4",
    "4": "Thứ 5",
    "5": "Thứ 6",
    "6": "Thứ 7",
}


def _describe_cron_vi(cron_expr: str) -> str:
    """Diễn giải biểu thức cron sang tiếng Việt thân thiện dễ hiểu (T-23.4)."""
    raw = re.sub(r"\s+", " ", (cron_expr or "").strip())
    if not raw:
        return "Theo lịch định kỳ"
    fields = raw.split(" ")
    # Nếu chuỗi đã là tiếng Việt hoặc không phải cron 5/6 trường
    if len(fields) not in (5, 6) or any(
        w in raw.lower() for w in ("phút", "giờ", "ngày", "lần", "vòng", "hằng")
    ):
        return raw
    # Nếu 6 trường (có giây ở đầu), bỏ trường giây để diễn giải 5 trường chuẩn
    if len(fields) == 6:
        fields = fields[1:]
    minute, hour, dom, month, dow = fields

    if minute == "*" and hour == "*" and dom == "*" and month == "*" and dow == "*":
        return "Mỗi phút"
    if minute.startswith("*/") and hour == "*" and dom == "*" and month == "*" and dow == "*":
        step = minute[2:]
        return f"Mỗi {step} phút"
    if minute.isdigit() and hour == "*" and dom == "*" and month == "*" and dow == "*":
        m = int(minute)
        return "Mỗi giờ" if m == 0 else f"Mỗi giờ (phút {m:02d})"
    if minute.isdigit() and hour.startswith("*/") and dom == "*" and month == "*" and dow == "*":
        step = hour[2:]
        m = int(minute)
        return f"Mỗi {step} giờ" if m == 0 else f"Mỗi {step} giờ (phút {m:02d})"

    # Chuẩn hoá phần giờ:phút
    time_desc = ""
    m_val = int(minute) if minute.isdigit() else None
    if m_val is not None:
        h_parts = [p.strip() for p in hour.split(",") if p.strip()]
        if all(p.isdigit() for p in h_parts):
            times = [f"{int(h):02d}:{m_val:02d}" for h in h_parts]
            time_desc = "lúc " + ", ".join(times)
        elif "-" in hour and "/" not in hour:
            a, b = hour.split("-", 1)
            if a.isdigit() and b.isdigit():
                time_desc = f"mỗi giờ từ {int(a):02d}:{m_val:02d} đến {int(b):02d}:{m_val:02d}"
    elif minute.startswith("*/") and "-" in hour:
        step = minute[2:]
        a, b = hour.split("-", 1)
        if a.isdigit() and b.isdigit():
            time_desc = f"mỗi {step} phút (khung {int(a):02d}:00–{int(b):02d}:59)"

    # Chuẩn hoá phần ngày/thứ
    day_desc = "Hằng ngày"
    if dom == "*" and dow != "*":
        if dow in ("1-5", "1,2,3,4,5"):
            day_desc = "Thứ 2 – Thứ 6"
        elif dow in ("0,6", "6,0", "6-7", "6,7"):
            day_desc = "Cuối tuần (Thứ 7, CN)"
        else:
            d_parts = [_DOW_VI_NAMES.get(d.strip(), f"Thứ ({d.strip()})") for d in dow.split(",")]
            day_desc = ", ".join(d_parts) + " hằng tuần"
    elif dom != "*" and dow == "*":
        if dom.startswith("*/"):
            day_desc = f"Mỗi {dom[2:]} ngày"
        else:
            day_desc = f"Ngày {dom} hằng tháng"

    if month != "*":
        day_desc += f" (tháng {month})"

    if time_desc:
        return f"{day_desc} {time_desc}"
    return f"{day_desc} ({minute} {hour})"


def _format_cron_display(cron_expr: str) -> tuple[str, str]:
    """Trả (cron_human, cron_display) kết hợp tiếng Việt + cron gốc (T-23.4)."""
    raw = re.sub(r"\s+", " ", (cron_expr or "").strip())
    human = _describe_cron_vi(raw)
    if not raw or human == raw:
        return human, human
    return human, f"{human} ({raw})"


def _clean_schedule_title(raw_title: str, raw_payload: str) -> str:
    """Làm sạch tiêu đề lịch, bỏ tiền tố kỹ thuật và giữ nguyên nghĩa (T-23.4)."""
    base = (raw_title or "").strip() or (raw_payload or "").strip()
    base = re.sub(
        r"^\[(?:Nhắc việc(?:\s+tự động)?|Lịch hẹn|Schedule|Auto|Job)[^\]]*\]\s*[:\-–]?\s*",
        "",
        base,
        flags=re.IGNORECASE,
    )
    base = sanitize_path_display(base)
    base = fix_glued_words(base)
    base = re.sub(r"\s+", " ", base).strip()
    return base


def _disambiguate_schedule_items(raw_items: list[dict], title_key: str = "name",
                                 full_key: str = "prompt", max_len: int = 72) -> None:
    """Nếu nhiều mục lịch có cùng phần đầu (vd 3 lịch 'Quét TẤT CẢ…'),
    tự động nối thêm phần phân biệt ở phía sau và không cắt giữa từ (Q-07 / T-23.4)."""
    counts: dict[str, list[dict]] = {}
    for it in raw_items:
        t = str(it.get(title_key) or "").strip()
        # Gom nhóm theo 24 ký tự đầu không dấu để bắt cả các lịch chỉ khác nhau ở cuối câu
        prefix_key = fold_vi(_truncate_words(t, 24).rstrip("…").strip())
        if not prefix_key:
            prefix_key = t
        counts.setdefault(prefix_key, []).append(it)
    for _, group in counts.items():
        if len(group) <= 1:
            continue
        full_texts = [
            re.sub(r"\s+", " ", str(g.get(full_key) or g.get(title_key) or "").strip())
            for g in group
        ]
        prefix_len = 0
        if full_texts and all(full_texts):
            min_l = min(len(x) for x in full_texts)
            while prefix_len < min_l and len({x[prefix_len] for x in full_texts}) == 1:
                prefix_len += 1
        # Lùi prefix_len về ranh giới khoảng trắng để không cắt ngang từ
        if prefix_len > 0 and full_texts[0]:
            space_back = full_texts[0][:prefix_len].rfind(" ")
            if space_back > 0:
                prefix_len = space_back
        for idx, g in enumerate(group):
            full = full_texts[idx]
            diff_part = full[prefix_len:].strip(" ,;:-")
            if diff_part and len({full_texts[i] for i in range(len(group))}) > 1:
                head = _truncate_words(full[:prefix_len].strip(), 32)
                tail = _truncate_words(diff_part, 38)
                g[title_key] = f"{head} · {tail}" if head else tail
            else:
                cron_str = str(g.get("cron_human") or g.get("cron") or g.get("time_label") or f"#{idx + 1}")
                base_t = _truncate_words(str(g.get(title_key) or ""), 44)
                g[title_key] = f"{base_t} ({cron_str})"


def _normalize_task_view(t: dict, live_step: str = "") -> dict:
    """MỘT nguồn sự thật duy nhất chuẩn hoá trạng thái, bước và tóm tắt của task (T-23.4).
    Dùng chung cho cả /api/state (danh sách Việc) và /api/task (chi tiết Việc)."""
    raw_status = str(t.get("status") or "pending").strip().lower()
    clean_title = _clean_schedule_title("", str(t.get("title") or "")) or "Chi tiết việc"
    clean_error = fix_glued_words(sanitize_path_display(str(t.get("error") or "").strip()))
    clean_result = fix_glued_words(sanitize_path_display(str(t.get("result") or "").strip()))

    raw_steps = list(t.get("steps") or [])
    # Loại bỏ bước placeholder chung chung khi đã có các bước thực thi thật
    has_non_placeholder = any(
        str(s.get("title") or "").strip() not in ("", "Hoàn thành yêu cầu của user")
        for s in raw_steps
    )
    norm_steps: list[dict] = []
    seen_started = False
    for s in raw_steps:
        st_title = fix_glued_words(sanitize_path_display(str(s.get("title") or "").strip()))
        if has_non_placeholder and st_title == "Hoàn thành yêu cầu của user":
            continue
        if st_title == "Đã bắt đầu":
            if seen_started:
                continue
            seen_started = True
        st_status = str(s.get("status") or "pending").strip().lower()
        st_detail = str(s.get("detail") or "")
        # Đồng bộ trạng thái bước con với trạng thái cuối của task
        if raw_status == "failed":
            if st_status in ("doing", "pending"):
                st_status = "failed"
            if st_title.startswith("Kiểm chứng: Đạt yêu cầu"):
                st_title = "Kiểm chứng: Không đạt (tác vụ lỗi)"
                st_status = "failed"
        elif raw_status == "cancelled":
            if st_status in ("doing", "pending"):
                st_status = "cancelled"
        norm_steps.append({
            "idx": s.get("idx", len(norm_steps)),
            "title": st_title or "Bước thực thi",
            "status": st_status,
            "detail": st_detail,
            "updated_at": str(s.get("updated_at") or t.get("updated_at") or ""),
        })

    if norm_steps:
        steps_total = len(norm_steps)
        steps_done = sum(1 for s in norm_steps if s.get("status") == "done")
        steps_failed = sum(1 for s in norm_steps if s.get("status") in ("failed", "cancelled"))
    else:
        steps_total = int(t.get("steps_total") or 0)
        steps_done = int(t.get("steps_done") or 0)
        steps_failed = max(0, steps_total - steps_done) if raw_status in ("failed", "cancelled") else 0

    c_step = live_step or str(t.get("current_step") or "").strip()
    if not c_step and norm_steps:
        for s in reversed(norm_steps):
            if s.get("status") == "doing":
                c_step = s["title"]
                break
        if not c_step:
            c_step = norm_steps[-1]["title"]
    c_step = fix_glued_words(sanitize_path_display(c_step))

    step_ratio = f"{steps_done}/{steps_total} bước" if steps_total > 0 else ""

    if raw_status == "running":
        status = "running"
        status_label = "◌ Đang chạy"
        status_sub = " · ".join(
            x for x in [f"Đang chạy: {c_step}" if c_step else "Đang thực hiện", step_ratio] if x
        )
        final_step = {
            "title": "◌ Đang thực hiện…",
            "status": "doing",
            "cls": "doing",
            "detail": c_step,
        }
        summary_md = clean_result or "*Tác vụ đang được thực thi…*"
    elif raw_status == "cancelled":
        status = "cancelled"
        status_label = "⊘ Đã dừng"
        err_txt = clean_error or "Tác vụ đã bị người dùng dừng."
        status_sub = f"Đã dừng ({step_ratio}): {err_txt}" if step_ratio else f"Đã dừng: {err_txt}"
        final_step = {
            "title": "⊘ Đã dừng việc",
            "status": "cancelled",
            "cls": "err",
            "detail": err_txt,
        }
        summary_md = (
            f"**Trạng thái: ⊘ Đã dừng" + (f" ({step_ratio})" if step_ratio else "") + "**\n\n"
            f"- **Lý do dừng:** {err_txt}"
            + (f"\n\n---\n\n**Ghi nhận trước khi dừng:**\n\n{clean_result}" if clean_result else "")
        )
    elif raw_status == "failed":
        status = "failed"
        status_label = "✕ Đã lỗi"
        err_txt = clean_error or "Tác vụ gặp lỗi hoặc chưa đạt yêu cầu kiểm chứng."
        status_sub = f"Lỗi ({step_ratio}): {err_txt}" if step_ratio else f"Lỗi: {err_txt}"
        final_step = {
            "title": "✕ Đã lỗi",
            "status": "failed",
            "cls": "err",
            "detail": err_txt,
        }
        summary_md = (
            f"**Trạng thái: ✕ Đã lỗi" + (f" ({step_ratio})" if step_ratio else "") + "**\n\n"
            f"- **Chi tiết lỗi / Chẩn đoán:** {err_txt}"
            + (
                f"\n\n---\n\n**Kết quả nháp trước khi lỗi (chưa đạt yêu cầu):**\n\n{clean_result}"
                if clean_result
                else ""
            )
        )
    elif steps_total > 0 and steps_done < steps_total:
        # Chưa đủ bước (vd 5/6 bước, 17/19 bước): tuyệt đối KHÔNG ghi "✓ Đã xong" (T-23.4)
        status = "partial"
        status_label = f"· Xong {steps_done}/{steps_total} bước"
        reason_part = (
            f"{steps_failed} bước lỗi"
            if steps_failed > 0
            else f"{steps_total - steps_done} bước chưa hoàn tất"
        )
        status_sub = f"Hoàn tất {steps_done}/{steps_total} bước ({reason_part})"
        final_step = {
            "title": f"· Hoàn tất một phần ({steps_done}/{steps_total} bước)",
            "status": "partial",
            "cls": "doing",
            "detail": reason_part,
        }
        summary_md = (
            f"**Trạng thái: · Hoàn tất {steps_done}/{steps_total} bước ({reason_part})**\n\n"
            + (clean_result or clean_error or "(chưa có tóm tắt)")
        )
    elif raw_status == "unverified":
        status = "unverified"
        status_label = "· Chưa kiểm chứng"
        status_sub = f"{step_ratio} · Chưa kiểm chứng" if step_ratio else "Chưa kiểm chứng"
        final_step = {
            "title": "· Hoàn tất (chưa kiểm chứng)",
            "status": "unverified",
            "cls": "doing",
            "detail": "",
        }
        summary_md = "**Trạng thái: · Chưa kiểm chứng**\n\n" + (clean_result or "(chưa có tóm tắt)")
    else:
        status = "done"
        status_label = "✓ Đã xong"
        status_sub = f"Hoàn tất {steps_done}/{steps_total} bước" if steps_total > 0 else "Hoàn tất"
        final_step = {
            "title": "✓ Hoàn tất",
            "status": "done",
            "cls": "done",
            "detail": "",
        }
        summary_md = clean_result or "Đã hoàn tất công việc."

    return {
        "id": t.get("id") or "",
        "kind": "task",
        "title": clean_title,
        "status": status,
        "raw_status": raw_status,
        "status_label": status_label,
        "status_sub": status_sub,
        "result": clean_result[:4000],
        "summary_markdown": summary_md[:4500],
        "error": clean_error,
        "steps_total": steps_total,
        "steps_done": steps_done,
        "steps_failed": steps_failed,
        "current_step": c_step,
        "created_at": str(t.get("created_at") or ""),
        "updated_at": str(t.get("updated_at") or t.get("created_at") or ""),
        "steps": norm_steps,
        "final_step": final_step,
    }


DOSSIER_FILE_DESCRIPTIONS: dict[str, str] = {
    "AGENTS.md": "Quy tắc & chuẩn mực vận hành cốt lõi",
    "SOUL.md": "Tính cách, linh hồn & giá trị của Mulon",
    "USER.md": "Hồ sơ & ngữ cảnh về chủ nhân",
    "IDENTITY.md": "Danh tính & thông tin nhận diện",
    "TOOLS.md": "Hướng dẫn sử dụng công cụ & môi trường",
    "HEARTBEAT.md": "Checklist tự kiểm định kỳ (Heartbeat)",
    "PROACTIVE_PREFERENCES.md": "Sở thích & giới hạn nhắc việc chủ động",
    "STYLE.md": "Giọng văn & định dạng phản hồi",
    "MEMORY.md": "Ghi chép ký ức tổng hợp dài hạn",
}

LIBRARY_KIND_LABELS: dict[str, str] = {
    "document": "Tài liệu văn bản",
    "image": "Hình ảnh",
    "media": "Âm thanh & Video",
    "code": "Mã nguồn & Dữ liệu",
    "archive": "Tệp nén",
    "other": "Tệp khác",
}


def _classify_fact_topic(subject: str, fact: str) -> str:
    """Phân loại fact vào chủ đề tiếng Việt rõ ràng để gom nhóm (T-23.3)."""
    s_low = fold_vi(f"{subject or ''} {fact or ''}")
    subj_low = fold_vi(subject or "").strip()
    if subj_low in ("user", "owner", "chu nhan", "ca nhan", "preference", "preferences", "so thich"):
        return "Chủ nhân & Sở thích"
    if subj_low in ("social", "threads", "facebook", "zalo", "instagram", "telegram"):
        return "Mạng xã hội & Kết nối"
    if subj_low in ("work", "task", "schedule", "goal", "cong viec", "lich trinh", "muc tieu"):
        return "Công việc & Lịch trình"
    if subj_low in ("project", "mulon", "system", "code", "bot", "he thong", "du an"):
        return "Dự án & Hệ thống"

    if any(k in s_low for k in ("threads", "facebook", "zalo", "instagram", "bai dang", "comment", "group", "kenh", "post", "tiktok", "youtube")):
        return "Mạng xã hội & Kết nối"
    if any(k in s_low for k in ("lich", "nhac", "hen", "muc tieu", "goal", "deadline", "bao cao", "hang ngay", "cron", "heartbeat")):
        return "Công việc & Lịch trình"
    if any(k in s_low for k in ("mulon", "repo", "git", "commit", "test", "pytest", "python", "server", "api", "model", "proxy", "connector", "mcp", "vault", "sqlite")):
        return "Dự án & Hệ thống"
    if any(k in s_low for k in ("thich", "muon", "uu tien", "ten", "goi", "chu du an", "chu nhan", "ghet", "thoi quen", "phong cach", "xung ho")):
        return "Chủ nhân & Sở thích"
    return "Ghi nhớ chung"


def _classify_skill_group(name: str, desc: str = "", source: str = "") -> str:
    """Gom nhóm kỹ năng theo chủ đề tiếng Việt rõ ràng (T-23.3)."""
    n_low = (name or "").lower()
    d_low = (desc or "").lower()
    if n_low.startswith("elevenlabs") or any(k in n_low for k in ("audio", "voice", "loudness", "sfx", "speech", "say")):
        return "Âm thanh & Giọng nói"
    if any(k in n_low for k in ("premiere", "video", "cut", "clip", "pacing", "lut", "color", "sync", "synchronize", "pauses", "comedy", "visual-editing", "content-shield", "asset-indexer", "source-understanding")):
        return "Video & Dựng phim"
    if n_low.startswith(("writing-", "to-")) or any(k in n_low for k in ("gsheets", "sheet", "doc", "prd", "issues", "beats", "fragments", "shape")):
        return "Viết lách & Tài liệu"
    if n_low.startswith(("ponytail", "grill")) or any(k in n_low for k in ("tdd", "diagnose", "review", "qa", "triage", "refactor", "architecture", "brainstorming", "handoff")):
        return "Kỹ thuật & Kiểm thử"
    if any(k in d_low for k in ("video", "premiere", "clip", "timeline", "footage")):
        return "Video & Dựng phim"
    if any(k in d_low for k in ("audio", "voice", "speech", "sound", "elevenlabs")):
        return "Âm thanh & Giọng nói"
    return "Tự động hoá & Hệ thống"


_VI_DIACRITIC_RE = re.compile(
    r"[àáạảãâầấậẩẫăằắặẳẵèéẹẻẽêềếệểễìíịỉĩòóọỏõôồốộổỗơờớợởỡùúụủũưừứựửữỳýỵỷỹđ]",
    re.IGNORECASE,
)

SKILL_VI_DESC_MAP: dict[str, str] = {
    "adaptive-pacing": "Thiết kế nhịp độ dựng video giữ chân người xem theo cấu trúc 4-5 nhịp.",
    "agy-customizations": "Hướng dẫn cấu hình và tuỳ biến hệ thống Antigravity (skills, rules, plugins, MCP).",
    "antigravity-guide": "Tài liệu tham khảo nhanh và sơ đồ tính năng cho Antigravity IDE & CLI.",
    "asset-indexer": "Đánh chỉ mục và tìm kiếm kho hiệu ứng âm thanh (SFX), meme, nhạc nền và overlay.",
    "auto-match-loudness": "Tự động cân bằng âm lượng (Auto-Match Loudness) cho clip thoại trong Premiere Pro.",
    "automation": "Thiết kế và tạo tác vụ tự động chạy định kỳ theo lịch trình.",
    "brainstorming": "Phân tích ý tưởng, làm rõ yêu cầu và thiết kế giải pháp trước khi bắt tay vào làm.",
    "calibrate-lut": "Tạo và hiệu chuẩn bảng màu LUT từ ảnh chụp bảng chuẩn màu ColorChecker.",
    "check-sequence-sync": "Kiểm tra và rà soát độ lệch đồng bộ âm thanh/hình ảnh trên timeline Premiere Pro.",
    "clean-cut": "Tách cảnh video thông minh bằng AI Vision, lọc đoạn thừa và cắt viền mờ.",
    "clip-inspector": "Thẩm định thư mục video, tạo dải ảnh xem trước (filmstrip) và chuẩn hoá dữ liệu cảnh.",
    "comedy-timing": "Điều chỉnh nhịp dựng hài hước theo cấu trúc 4 nhịp (Mở đầu - Cao trào - Điểm nổ - Dư âm).",
    "content-shield": "Tự động phát hiện, theo dõi và làm mờ watermark, logo hoặc vùng nội dung nhạy cảm.",
    "context-aware-sfx": "Thiết kế âm thanh thông minh, chèn tiếng động và hiệu ứng chuyển cảnh khớp ngữ cảnh.",
    "correct-color": "Chỉnh màu tự động cho clip Premiere Pro dựa trên bảng màu chuẩn trong timeline.",
    "create-empty-premiere-project": "Khởi tạo dự án Premiere Pro mới, sạch sẽ từ dòng lệnh.",
    "delegate-task": "Uỷ thác tác vụ phức tạp cho tiến trình tự hành OpenSpace xử lý.",
    "diagnose": "Quy trình chẩn đoán lỗi sâu: tái hiện, cô lập, đặt giả thuyết, sửa lỗi và viết test hồi quy.",
    "elevenlabs-agents": "Xây dựng, cấu hình và quản lý các hội thoại viên AI trên nền tảng ElevenLabs.",
    "elevenlabs-assets": "Quản lý các tệp phương tiện và tài nguyên đã tải lên ElevenLabs.",
    "elevenlabs-audio-effects": "Danh sách hiệu ứng lọc âm, vang âm (reverb) và âm nền cho giọng đọc.",
    "elevenlabs-audio-isolation": "Tách giọng nói trong trẻo và lọc bỏ tạp âm nền khỏi tệp âm thanh.",
    "elevenlabs-audio-native": "Nhúng trình phát âm thanh đọc bài tự động bằng AI vào trang web.",
    "elevenlabs-dubbing": "Lồng tiếng đa ngôn ngữ cho video và âm thanh, giữ nguyên giọng người nói gốc.",
    "elevenlabs-environment-variables": "Quản lý biến môi trường không gian làm việc cho agent và công cụ ElevenLabs.",
    "elevenlabs-flows": "Chạy quy trình sinh nội dung đa bước kết hợp giọng nói, hình ảnh và video.",
    "elevenlabs-forced-alignment": "Căn chỉnh văn bản khớp chính xác từng từ và ký tự với tệp âm thanh.",
    "elevenlabs-history": "Tra cứu và tải lại lịch sử các bản thu giọng nói đã tạo.",
    "elevenlabs-models": "Tra cứu danh sách các mô hình giọng nói AI trên ElevenLabs.",
    "elevenlabs-music": "Sáng tác và tạo nhạc nền tự động từ mô tả văn bản.",
    "elevenlabs-productions": "Quản lý các đơn hàng sản xuất âm thanh chuyên nghiệp ElevenProductions.",
    "elevenlabs-pronunciation-dictionaries": "Quản lý từ điển phát âm tuỳ chỉnh cho các từ chuyên ngành hoặc tên riêng.",
    "elevenlabs-samples": "Quản lý các mẫu giọng nói (voice samples) trong tài khoản.",
    "elevenlabs-say": "Đọc to văn bản trực tiếp từ dòng lệnh hoặc xuất nhanh tệp MP3 lồng tiếng.",
    "elevenlabs-service-accounts": "Quản lý khoá API (API keys) cho không gian làm việc ElevenLabs.",
    "elevenlabs-shared": "Chuẩn xác thực, cờ dòng lệnh dùng chung và định dạng đầu ra cho ElevenLabs CLI.",
    "elevenlabs-speech-engine": "Giao diện tạo giọng nói thời gian thực với độ trễ cực thấp.",
    "elevenlabs-speech-to-speech": "Chuyển đổi giọng nói từ tệp thu âm sẵn sang một giọng nhân vật khác.",
    "elevenlabs-speech-to-text": "Chuyển giọng nói thành văn bản kèm phân biệt người nói và mốc thời gian chi tiết.",
    "elevenlabs-studio": "Tạo và quản lý các dự án thu âm dài tập trong ElevenLabs Studio.",
    "elevenlabs-text-to-dialogue": "Tạo đoạn hội thoại nhiều nhân vật từ kịch bản văn bản với các giọng khác nhau.",
    "elevenlabs-text-to-sound-effects": "Tạo hiệu ứng tiếng động (SFX) và âm thanh môi trường từ mô tả chữ.",
    "elevenlabs-text-to-speech": "Chuyển đổi văn bản thành giọng đọc tự nhiên với giọng nhân vật tuỳ chọn.",
    "elevenlabs-text-to-voice": "Thiết kế và tạo giọng nhân vật mới hoàn toàn từ mô tả văn bản.",
    "elevenlabs-tokens": "Cấp mã token ngắn hạn dùng một lần cho ứng dụng hội thoại AI phía client.",
    "elevenlabs-usage": "Thống kê mức sử dụng ký tự và tín dụng (credits) của tài khoản.",
    "elevenlabs-user": "Xem thông tin tài khoản và gói thuê bao ElevenLabs hiện tại.",
    "elevenlabs-voices": "Tra cứu và quản lý danh sách giọng đọc có sẵn hoặc tự tạo.",
    "elevenlabs-webhooks": "Cấu hình webhook nhận sự kiện và kiểm tra lịch sử gửi từ ElevenLabs.",
    "elevenlabs-workspace": "Truy cập và quản lý thông tin không gian làm việc chung.",
    "elevenlabs-workspaces": "Vô hiệu hoá hoặc thu hồi khoá API của không gian làm việc.",
    "generative_ui": "Dựng giao diện tương tác trực quan, biểu đồ và sơ đồ minh hoạ ngay trong khung chat.",
    "grill-me": "Đặt câu hỏi phản biện sâu để kiểm tra kế hoạch và chốt mọi nhánh quyết định thiết kế.",
    "grill-with-docs": "Phản biện kế hoạch đối chiếu với tài liệu kiến trúc và mô hình nghiệp vụ sẵn có.",
    "gsheets": "Đọc, ghi, định dạng bảng tính, tạo biểu đồ và quản lý Google Sheets.",
    "handoff": "Đóng gói ngữ cảnh công việc hiện tại thành tài liệu bàn giao gọn gàng cho phiên sau.",
    "improve-codebase-architecture": "Khảo sát mã nguồn, tìm điểm nghẽn kiến trúc và đề xuất gom mô-đun dễ kiểm thử.",
    "migrate-workflows": "Chuyển đổi các quy trình (workflows) cũ sang chuẩn kỹ năng SKILL.md mới.",
    "pacing-editor": "Dựng timeline Premiere Pro tự động, làm mượt tốc độ (Optical Flow) và khớp nhạc/SFX.",
    "plugin": "Quản lý, cài đặt, bật/tắt và đóng gói các bộ tiện ích mở rộng (plugins).",
    "ponytail": "Ưu tiên giải pháp tối giản, gọn nhẹ nhất và dùng thư viện chuẩn thay vì làm phức tạp.",
    "ponytail-audit": "Rà soát toàn bộ kho mã nguồn để tìm phần thừa, phức tạp hoá và có thể rút gọn.",
    "ponytail-debt": "Tổng hợp danh sách các ghi chú nợ kỹ thuật (ponytail) trong mã nguồn.",
    "ponytail-gain": "Hiển thị bảng thống kê mức tiết kiệm mã nguồn, chi phí và tốc độ.",
    "ponytail-help": "Bảng tra cứu nhanh các chế độ và câu lệnh rút gọn mã nguồn.",
    "ponytail-review": "Đánh giá thay đổi mã nguồn tập trung vào việc loại bỏ sự phức tạp không cần thiết.",
    "premiere-cli": "Điều khiển và truy vấn Adobe Premiere Pro trực tiếp qua bảng kết nối Premiere Bridge.",
    "premiere-execution": "Thực thi kế hoạch dựng phim thành thao tác cắt ghép trên timeline Premiere Pro.",
    "premiere-log": "Ghi nhật ký tiến trình tự động hoá trực tiếp lên bảng điều khiển trong Premiere Pro.",
    "qa": "Phiên kiểm thử chất lượng tương tác: ghi nhận lỗi từ người dùng và tạo phiếu báo lỗi chuẩn.",
    "remove-pauses-from-track": "Tự động cắt bỏ khoảng lặng, đoạn ngập ngừng trên rãnh âm thanh và giữ đồng bộ hình.",
    "request-refactor-plan": "Lập kế hoạch tái cấu trúc mã nguồn theo từng bước nhỏ an toàn.",
    "review": "Kiểm tra mã nguồn song song theo hai tiêu chí: chuẩn mực kỹ thuật và đúng đặc tả yêu cầu.",
    "skill-discovery": "Tìm kiếm và tái sử dụng kỹ năng có sẵn trong thư viện cục bộ hoặc đám mây.",
    "source-understanding": "Phân tích video gốc đa phương thức: tách cảnh, tìm điểm nhấn chuyển động và âm thanh.",
    "synchronize-clips": "Đồng bộ hoá âm thanh từ micro rời khớp chính xác với video quay từ máy ảnh.",
    "tdd": "Phát triển phần mềm theo hướng kiểm thử trước (Viết test đỏ -> Viết code xanh -> Tối ưu).",
    "to-issues": "Chia nhỏ bản kế hoạch hoặc PRD thành các nhiệm vụ độc lập dễ triển khai.",
    "to-prd": "Tổng hợp nội dung thảo luận thành tài liệu đặc tả sản phẩm (PRD) hoàn chỉnh.",
    "triage": "Phân loại, xác định mức ưu tiên và chuẩn bị quy trình xử lý cho lỗi hoặc yêu cầu mới.",
    "ui-plugin-navigation": "Mở nhanh các bảng điều khiển tiện ích giao diện ngay trong thanh bên.",
    "video-quality-control": "Kiểm tra chất lượng timeline tự động theo 5 tiêu chuẩn và sinh bản vá lỗi.",
    "video-transform": "Biến đổi hình học video (phóng to, xoay nhẹ, lật gương) và chỉnh tốc độ giữ nguyên tông giọng.",
    "visioncut": "Trợ lý dựng phim AI tự hành: đọc storyboard 12 khung hình, cắt cảnh và lên timeline 5 rãnh.",
    "visual-editing": "Hiệu ứng hình ảnh, phóng cận cảnh nhấn mạnh (punch-in zoom) và lớp phủ che nội dung.",
    "writing-beats": "Biên tập bài viết theo từng nhịp câu chuyện tương tác từng bước với người đọc.",
    "writing-fragments": "Thu thập và ghi chép các mảnh ý tưởng, câu chữ sắc sảo làm nguyên liệu viết bài.",
    "writing-shape": "Nhào nặn bản nháp thô hoặc ghi chú rời rạc thành bài viết hoàn chỉnh từng đoạn.",
}


def _localize_skill_description(name: str, desc: str, body: str = "") -> str:
    """Chuẩn hoá và dịch mô tả kỹ năng sang tiếng Việt 1 dòng gọn gàng (T-23.3)."""
    clean = (desc or "").strip()
    if clean in ("", ">", ">-", "|", "|-"):
        for line in (body or "").splitlines():
            s = line.strip()
            if s and not s.startswith(("#", "---", "```", "<!--")):
                clean = s
                break
        else:
            clean = ""
    clean = sanitize_path_display(clean)
    clean = fix_glued_words(clean)
    clean = re.sub(r"\s+", " ", clean).strip()

    key = (name or "").strip().lower()
    if key in SKILL_VI_DESC_MAP:
        # Nếu mô tả gốc là tiếng Anh hoặc bị rỗng/vỡ thì ưu tiên bản dịch chuẩn tiếng Việt
        if not clean or not _VI_DIACRITIC_RE.search(clean):
            return SKILL_VI_DESC_MAP[key]

    if clean and _VI_DIACRITIC_RE.search(clean):
        return _truncate_words(clean, 140)

    if not clean:
        return f"Kỹ năng chuyên biệt hỗ trợ tác vụ {name}."

    # Dịch nhanh các mẫu câu tiếng Anh phổ biến trong SKILL.md
    en_vi_replacements = [
        (r"^Use when asked to\s+", "Sử dụng khi cần "),
        (r"^Use when the user wants to\s+", "Sử dụng khi người dùng muốn "),
        (r"^Use when the user asks to\s+", "Sử dụng khi người dùng yêu cầu "),
        (r"^Use this skill when\s+", "Sử dụng kỹ năng này khi "),
        (r"^Use when\s+", "Sử dụng khi "),
        (r"^Build, configure and manage\s+", "Xây dựng, cấu hình và quản lý "),
        (r"^Access and manage\s+", "Truy cập và quản lý "),
        (r"^Manage\s+", "Quản lý "),
        (r"^Generate\s+", "Tạo tự động "),
        (r"^Convert\s+", "Chuyển đổi "),
        (r"^Read, write, format, and manage\s+", "Đọc, ghi, định dạng và quản lý "),
        (r"^Search\s+", "Tìm kiếm "),
        (r"^Inspect\s+", "Kiểm tra và phân tích "),
    ]
    translated = clean
    for pat, rep in en_vi_replacements:
        if re.search(pat, translated, flags=re.IGNORECASE):
            translated = re.sub(pat, rep, translated, count=1, flags=re.IGNORECASE)
            break
    first_sentence = re.split(r"(?<=[.!?])\s+", translated)[0]
    return _truncate_words(first_sentence, 140)


# ---------------------------------------------------------------------------
# Theo dõi hoạt động (header trạng thái + tab Việc)
# ---------------------------------------------------------------------------

class ActivityTracker:
    """Trạng thái sống cho Mini App: lượt đang chạy, bước hiện tại,
    và quản lý huỷ tác vụ thời gian thực (kể cả sub-agent)."""

    def __init__(self):
        self.current: Optional[dict] = None
        self._running_tasks: dict[str, asyncio.Task] = {}
        self._task_meta: dict[str, dict] = {}

    def start_turn(self, session_key: str, text: str) -> None:
        self.current = {
            "session_key": session_key,
            "title": (text or "")[:120],
            "step": "Đang xử lý…",
            "started_at": time.time(),
        }

    def set_step(self, label: str) -> None:
        if self.current is not None:
            self.current["step"] = label

    def end_turn(self) -> None:
        self.current = None

    def register_task(
        self, task_id: str, task: asyncio.Task,
        title: str = "", session_key: str = "",
        current_step: str = "Đang xử lý…", kind: str = "main"
    ) -> None:
        """Đăng ký tác vụ đang chạy kèm asyncio.Task thật để cho phép huỷ từ bất kỳ đâu."""
        self._running_tasks[task_id] = task
        self._task_meta[task_id] = {
            "task_id": task_id,
            "title": title or "Tác vụ",
            "session_key": session_key,
            "current_step": current_step,
            "kind": kind,
            "started_at": time.time(),
        }

    def update_task_step(self, task_id: str, step_title: str) -> None:
        """Cập nhật bước hiện tại đang chạy của task."""
        if task_id in self._task_meta:
            self._task_meta[task_id]["current_step"] = step_title
        if self.current is not None:
            self.current["step"] = step_title

    def unregister_task(self, task_id: str) -> None:
        """Gỡ bỏ task khi đã hoàn thành hoặc đã dừng."""
        self._running_tasks.pop(task_id, None)
        self._task_meta.pop(task_id, None)

    def stop_task(self, task_id: str) -> bool:
        """Huỷ thật sự (cancel) asyncio.Task đang chạy của task_id hoặc session_key."""
        target_task = self._running_tasks.get(task_id)
        if target_task is not None:
            if not target_task.done():
                target_task.cancel()
            self.unregister_task(task_id)
            return True
        for tid, meta in list(self._task_meta.items()):
            if meta.get("session_key") == task_id or tid == task_id:
                t = self._running_tasks.get(tid)
                if t is not None and not t.done():
                    t.cancel()
                self.unregister_task(tid)
                return True
        return False

    def stop_session_tasks(self, session_key: str) -> int:
        """Huỷ và gỡ bỏ toàn bộ task đang chạy thuộc session_key."""
        count = 0
        for tid, meta in list(self._task_meta.items()):
            if meta.get("session_key") == session_key:
                t = self._running_tasks.get(tid)
                if t is not None and not t.done():
                    t.cancel()
                self.unregister_task(tid)
                count += 1
        if self.current and self.current.get("session_key") == session_key:
            self.current = None
        return count

    def get_running_task_info(self, task_id: str) -> Optional[dict]:
        return self._task_meta.get(task_id)

    def list_running_tasks(self) -> list[dict]:
        return list(self._task_meta.values())

    def snapshot(self) -> dict:
        running = self.list_running_tasks()
        if self.current is None:
            return {"busy": len(running) > 0,
                    "label": "Đang chạy việc nền" if running else "Sẵn sàng",
                    "current": None,
                    "running_tasks": running}
        return {"busy": True,
                "label": self.current.get("step") or "Đang xử lý",
                "current": dict(self.current),
                "running_tasks": running}


# ---------------------------------------------------------------------------
# Render markdown tối giản cho trang share (sửa 1.6.2)
# ---------------------------------------------------------------------------
# Không dùng gói markdown ngoài (chưa có trong requirements): tự
# render tập con heading/bold/italic/code/link/list/quote. NGUYÊN
# TẮC AN TOÀN: escape toàn bộ HTML của nội dung TRƯỚC, rồi mới
# chèn thẻ do chính hàm này sinh ra — HTML thô trong file (kể cả
# <script>) không bao giờ chui qua được. Link chỉ nhận scheme
# http/https hoặc đường dẫn tương đối; scheme khác (javascript:,
# data:, ...) được render thành chữ thường, không thành <a>.

_MD_LINK_RE = re.compile(
    # Nhóm URL cho phép 1 cặp ngoặc trong (vd javascript:alert(1))
    # để link scheme lạ bị loại cũng không để sót dấu ")" lẻ.
    r"\[([^\]]+)\]\(([^)\s]+(?:\)[^\s)]*)?)(?:\s+\"[^\"]*\")?\)")


def _render_share_inline(text: str) -> str:
    """Inline trong 1 dòng đã escape: code, bold, italic, link."""
    # Code inline trước để ** hay * bên trong code không bị parse.
    parts = re.split(r"(`[^`]+`)", text)
    for i, part in enumerate(parts):
        if part.startswith("`") and part.endswith("`") and len(part) > 2:
            parts[i] = "<code>" + part[1:-1] + "</code>"
        else:
            part = _MD_LINK_RE.sub(_md_link_sub, part)
            part = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", part)
            part = re.sub(r"(?<!\w)\*([^*]+)\*(?!\w)",
                          r"<em>\1</em>", part)
            part = re.sub(r"(?<!\w)_([^_]+)_(?!\w)",
                          r"<em>\1</em>", part)
            parts[i] = part
    return "".join(parts)


def _md_link_sub(match: "re.Match[str]") -> str:
    label, url = match.group(1), match.group(2)
    lowered = url.lower()
    if (lowered.startswith(("http://", "https://", "/", "#"))
            or lowered.startswith("mailto:")):
        href = html.escape(url, quote=True)
        return f'<a href="{href}">{label}</a>'
    return label  # Scheme lạ: chỉ giữ chữ, không tạo link.


def _render_share_markdown(content: str) -> str:
    """Render markdown tối giản, an toàn (xem ghi chú ở đầu mục)."""
    escaped = html.escape(content)
    lines = escaped.split("\n")
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        # Khối code ``` ... ```
        if stripped.startswith("```"):
            block = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                block.append(lines[i])
                i += 1
            i += 1  # Bỏ dòng ``` đóng (hoặc hết file).
            out.append("<pre><code>" + "\n".join(block) + "</code></pre>")
            continue
        # Heading # .. ######
        m = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if m:
            level = len(m.group(1))
            out.append(f"<h{level}>" + _render_share_inline(m.group(2))
                       + f"</h{level}>")
            i += 1
            continue
        # Đường kẻ ngang
        if stripped in ("---", "***", "___"):
            out.append("<hr>")
            i += 1
            continue
        # Trích dẫn > ...
        if stripped.startswith("&gt;"):
            quote = []
            while i < len(lines) and lines[i].strip().startswith("&gt;"):
                quote.append(lines[i].strip()[4:].strip())
                i += 1
            out.append("<blockquote>"
                       + "<br>".join(_render_share_inline(q) for q in quote)
                       + "</blockquote>")
            continue
        # Danh sách - / * / 1.
        if re.match(r"^[-*]\s+\S", stripped) or \
                re.match(r"^\d+\.\s+\S", stripped):
            ordered = bool(re.match(r"^\d+\.\s+", stripped))
            tag = "ol" if ordered else "ul"
            items = []
            while i < len(lines):
                s = lines[i].strip()
                im = re.match(r"^[-*]\s+(.*)$", s) or \
                    re.match(r"^\d+\.\s+(.*)$", s)
                if not im:
                    break
                items.append("<li>" + _render_share_inline(im.group(1))
                             + "</li>")
                i += 1
            out.append(f"<{tag}>" + "".join(items) + f"</{tag}>")
            continue
        # Đoạn văn: gom các dòng liên tiếp thành 1 <p>.
        if stripped:
            para = []
            while i < len(lines) and lines[i].strip() and \
                    not lines[i].strip().startswith(("```", "#", "&gt;")) \
                    and not re.match(r"^[-*]\s+\S", lines[i].strip()) \
                    and not re.match(r"^\d+\.\s+\S", lines[i].strip()):
                para.append(lines[i].strip())
                i += 1
            out.append("<p>" + "<br>".join(_render_share_inline(p)
                                           for p in para) + "</p>")
            continue
        i += 1  # Dòng trống.
    return "\n".join(out)


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Server
# ---------------------------------------------------------------------------

class WebAppServer:
    def __init__(self, cfg, *, memory, policy, broker, connectors,
                 mcp_manager, vault_store, registry, dossier=None,
                 skills=None, activity: Optional[ActivityTracker] = None,
                 marketplace=None, feed_auto=None, google_auth=None,
                 library=None, ideas=None):
        self.cfg = cfg
        self.memory = memory
        self.policy = policy
        self.broker = broker
        self.connectors = connectors
        self.mcp = mcp_manager
        self.vault_store = vault_store
        self.vault_notifier = None
        self.registry = registry
        self.dossier = dossier
        self.skills = skills
        self.library = library
        self.ideas = ideas
        # Marketplace 1.3.0 (mulon.marketplace) — None thì toàn bộ
        # /api/marketplace/* trả 503 sạch, màn Kết nối giữ hành vi cũ.
        self.marketplace = marketplace
        # Feed chủ động 1.4.0 (mulon.feed_auto.FeedAutoRunner) —
        # None thì block state "feed" là None và /api/feed trả 503.
        # KHÔNG có action tắt Feed ở API này (quyết định 0.2b).
        self.feed_auto = feed_auto
        # Google connectors 1.5.0 (mulon.google_conn.GoogleAuth)
        # — None thì /api/google/* trả 503 và /google/callback
        # trả trang báo chưa nối.
        self.google_auth = google_auth
        self.activity = activity or ActivityTracker()
        self._runner = None
        self._site = None
        # Mốc start của tiến trình webapp (uptime cho thẻ hệ thống)
        # + cache kiểm tra proxy 8317 (tránh probe mỗi lần poll).
        self._started_at = time.time()
        self._proxy_cache: Optional[tuple] = None
        from .cliproxy import CLIProxyManager
        self.cliproxy = CLIProxyManager(self.cfg)

    # ---------- vòng đời ----------
    def set_vault_notifier(self, fn) -> None:
        """Gắn callback khi có bí mật được lưu qua Vault (Mini App)."""
        self.vault_notifier = fn

    @property
    def port(self) -> int:
        if self._site is not None:
            return int(self._site._server.sockets[0].getsockname()[1])
        return int(self.cfg.webapp_port)

    @property
    def running(self) -> bool:
        return self._runner is not None

    def build_app(self):
        if not HAS_AIOHTTP:
            raise RuntimeError("aiohttp chưa được cài")

        @web.middleware
        async def _auth(request, handler):
            return await self._auth_middleware(request, handler)

        app = web.Application(middlewares=[_auth])
        app.router.add_get("/", self._handle_index)
        app.router.add_get("/a", self._handle_index)
        app.router.add_get("/a/", self._handle_index)
        app.router.add_get("/app", self._handle_index)
        app.router.add_get("/app/", self._handle_index)
        app.router.add_get("/panel", self._handle_index)
        app.router.add_get("/app/avatar", self._handle_avatar)
        app.router.add_get("/app/assets/{name}",
                           self._handle_static_asset)
        app.router.add_get("/api/state", self._handle_state)
        app.router.add_get("/api/heartbeat/history", self._handle_heartbeat_history)
        app.router.add_get("/api/task", self._handle_task)
        app.router.add_post("/api/task/stop", self._handle_task_stop)
        app.router.add_get("/api/upcoming", self._handle_upcoming)
        app.router.add_get("/api/profile/content",
                           self._handle_profile_content)
        app.router.add_get("/api/profile/facts",
                           self._handle_profile_facts)
        app.router.add_get("/api/profile/facts/{id}",
                           self._handle_profile_fact_detail)
        app.router.add_post("/api/profile/facts/delete",
                            self._handle_profile_fact_delete)
        app.router.add_post("/api/profile/facts/{id}/delete",
                            self._handle_profile_fact_delete)
        app.router.add_post("/api/policy", self._handle_policy)
        app.router.add_post("/api/connector", self._handle_connector)
        app.router.add_post("/api/approve", self._handle_approve)
        app.router.add_post("/api/schedule", self._handle_schedule)
        app.router.add_get("/api/schedules/{id}", self._handle_schedule_detail)
        app.router.add_post("/api/schedules/{id}/update", self._handle_schedule_update)
        app.router.add_post("/api/schedules/{id}/delete", self._handle_schedule_delete)
        app.router.add_post("/api/schedule/update", self._handle_schedule_update)
        app.router.add_post("/api/schedule/delete", self._handle_schedule_delete)
        # 1.4.0: điều khiển Feed chủ động (không có action tắt).
        app.router.add_post("/api/feed", self._handle_feed)
        # Thẻ ý tưởng chủ động (Ideas) theo chuẩn Muse (T-10.3)
        app.router.add_get("/api/ideas", self._handle_ideas_list)
        app.router.add_post("/api/ideas/generate", self._handle_ideas_generate)
        app.router.add_post("/api/ideas/do", self._handle_ideas_do)
        app.router.add_post("/api/ideas/dismiss", self._handle_ideas_dismiss)
        # Mục tiêu & Thư Briefings (Goals + Briefings theo T-10.4)
        app.router.add_get("/api/goals", self._handle_goals_list)
        app.router.add_get("/api/goals/{id}", self._handle_goal_detail)
        app.router.add_post("/api/goals/create", self._handle_goal_create)
        app.router.add_post("/api/goals/update", self._handle_goal_update)
        app.router.add_post("/api/goals/close", self._handle_goal_close)
        app.router.add_post("/api/goals/{id}/briefing", self._handle_goal_briefing)
        app.router.add_post("/api/profile/theme", self._handle_theme)
        # 1.3.0 (gói vá Mini App): kỹ năng đọc được + Vault nhập
        # ngay trong app — cùng middleware auth initData.
        app.router.add_get("/api/skills", self._handle_skills)
        app.router.add_get("/api/skills/{name}",
                           self._handle_skill_detail)
        app.router.add_post("/api/vault/capture",
                            self._handle_vault_capture)
        app.router.add_post("/api/vault/delete",
                            self._handle_vault_delete)
        app.router.add_post("/api/vault/update",
                            self._handle_vault_update)
        # 1.5.0: Google OAuth — auth-url + disconnect qua auth
        # initData như mọi /api/*; callback là route CÔNG KHAI
        # duy nhất (trình duyệt ngoài quay về từ Google, bảo vệ
        # bằng state nonce dùng 1 lần, xem _handle_google_callback).
        app.router.add_get("/api/google/auth-url",
                           self._handle_google_auth_url)
        app.router.add_get("/api/google/config",
                           self._handle_google_config)
        app.router.add_post("/api/google/config",
                            self._handle_google_config)
        app.router.add_post("/api/google/disconnect",
                            self._handle_google_disconnect)
        app.router.add_get("/google/callback",
                           self._handle_google_callback)
        app.router.add_get("/oauth2callback",
                           self._handle_mcp_oauth2callback)
        # 1.7.8 (T-22.1 / T-22.2): Personal Connectors (Zalo, Telegram cá nhân, Facebook cá nhân)
        app.router.add_get("/api/personal-connector/status",
                           self._handle_personal_connector_status)
        app.router.add_post("/api/personal-connector/qr",
                            self._handle_personal_connector_qr)
        app.router.add_post("/api/personal-connector/connect",
                            self._handle_personal_connector_connect)
        app.router.add_post("/api/personal-connector/disconnect",
                            self._handle_personal_connector_disconnect)
        # 1.3.0: Chợ MCP — mọi route qua cùng middleware auth
        # initData owner-only như các /api/* khác.
        app.router.add_get("/api/marketplace/summary",
                           self._mkt_summary)
        app.router.add_get("/api/marketplace/categories",
                           self._mkt_categories)
        app.router.add_get("/api/marketplace/catalog",
                           self._mkt_catalog)
        app.router.add_get(
            "/api/marketplace/listings/{provider}/{slug}",
            self._mkt_listing)
        app.router.add_get("/api/marketplace/installed",
                           self._mkt_installed)
        app.router.add_get("/api/marketplace/installed/{name}",
                           self._mkt_installed_detail)
        app.router.add_get("/api/marketplace/operations/{id}",
                           self._mkt_operation)
        app.router.add_post("/api/marketplace/refresh",
                            self._mkt_refresh)
        app.router.add_post("/api/marketplace/import/parse",
                            self._mkt_import_parse)
        app.router.add_post("/api/marketplace/install/prepare",
                            self._mkt_prepare)
        app.router.add_post(
            "/api/marketplace/operations/{id}/bind-secrets",
            self._mkt_bind_secrets)
        app.router.add_post(
            "/api/marketplace/operations/{id}/request-probe-approval",
            self._mkt_request_probe)
        app.router.add_post(
            "/api/marketplace/operations/{id}/request-commit-approval",
            self._mkt_request_commit)
        app.router.add_post("/api/marketplace/operations/{id}/cancel",
                            self._mkt_cancel)
        app.router.add_post(
            "/api/marketplace/installed/{name}/health-check",
            self._mkt_health_check)
        app.router.add_post("/api/marketplace/installed/{name}/enable",
                            self._mkt_enable)
        app.router.add_post("/api/marketplace/installed/{name}/disable",
                            self._mkt_disable)
        app.router.add_post(
            "/api/marketplace/installed/{name}/update/check",
            self._mkt_update_check)
        app.router.add_post(
            "/api/marketplace/installed/{name}/update/prepare",
            self._mkt_update_prepare)
        app.router.add_post(
            "/api/marketplace/installed/{name}/uninstall/prepare",
            self._mkt_uninstall_prepare)
        app.router.add_get("/media/{path:.*}", self._handle_workspace_media)
        # 1.6.0: Chia sẻ tài liệu / Artifacts công khai không qua auth
        app.router.add_get("/share/{token}", self._handle_public_share)
        # 1.6.0: Library management API cho Mini App
        app.router.add_get("/api/library/items", self._handle_library_items)
        app.router.add_get("/api/library/items/{id}", self._handle_library_item_detail)
        app.router.add_get("/api/library/search", self._handle_library_search)
        app.router.add_post("/api/library/items/{id}/pin", self._handle_library_pin)
        app.router.add_post("/api/library/items/{id}/trash", self._handle_library_trash)
        app.router.add_post("/api/library/items/{id}/restore", self._handle_library_restore)
        app.router.add_post("/api/library/items/{id}/delete", self._handle_library_delete)
        app.router.add_post("/api/library/items/{id}/rename", self._handle_library_rename)
        app.router.add_post("/api/library/items/{id}/share", self._handle_library_share)
        app.router.add_post("/api/library/items/{id}/unshare", self._handle_library_unshare)
        # 1.6.0: One-click MCP Install
        app.router.add_post(
            "/api/marketplace/operations/{id}/install-now",
            self._mkt_install_now)
        # T-14: CLIProxyAPI Management API
        app.router.add_get("/api/cliproxy/status", self._handle_cliproxy_status)
        app.router.add_get("/api/cliproxy/models", self._handle_cliproxy_models)
        app.router.add_get("/api/cliproxy/accounts", self._handle_cliproxy_accounts)
        app.router.add_post("/api/cliproxy/start", self._handle_cliproxy_start)
        app.router.add_post("/api/cliproxy/stop", self._handle_cliproxy_stop)
        return app

    async def start(self) -> bool:
        if not HAS_AIOHTTP:
            logger.warning("thiếu aiohttp — Mini App server TẮT")
            return False
        if self._runner is not None:
            return True
        self._runner = web.AppRunner(self.build_app())
        await self._runner.setup()
        self._site = web.TCPSite(self._runner, "127.0.0.1",
                                 int(self.cfg.webapp_port))
        await self._site.start()
        logger.info("Mini App server: http://127.0.0.1:%d/app",
                    self.port)
        return True

    async def stop(self) -> None:
        if self._runner is not None:
            await self._runner.cleanup()
            self._runner = None
            self._site = None

    # ---------- auth ----------
    async def _auth_middleware(self, request, handler):
        if request.path.startswith("/api/"):
            init_data = request.headers.get("X-Telegram-Init-Data", "")
            allowed_ids = set(getattr(self.cfg, "allowed_user_ids", ()))
            if self.cfg.allowed_user_id:
                allowed_ids.add(self.cfg.allowed_user_id)
            max_age = getattr(self.cfg, "init_data_max_age_s", 86400)
            user = validate_init_data(
                init_data, self.cfg.telegram_bot_token,
                allowed_ids or self.cfg.allowed_user_id,
                max_age_s=max_age)
            if user is None:
                return web.json_response(
                    {"ok": False, "error": "initData không hợp lệ "
                                           "hoặc không phải chủ nhân"},
                    status=403)
            request["tg_user"] = user
        return await handler(request)

    # ---------- trang tĩnh ----------
    async def _handle_index(self, request):
        if not INDEX_HTML.exists():
            return web.Response(status=404, text="thiếu index.html")
        return web.FileResponse(INDEX_HTML)

    async def _handle_static_asset(self, request):
        """Phục vụ asset tĩnh trong danh sách trắng STATIC_ASSETS
        (atlas sprite + manifest). Tên ngoài danh sách -> 404."""
        name = str(request.match_info.get("name") or "")
        ctype = STATIC_ASSETS.get(name)
        if ctype is None:
            return web.Response(status=404, text="asset lạ")
        path = WEBAPP_DIR / "assets" / name
        if not path.is_file():
            return web.Response(status=404, text="thiếu asset")
        resp = web.FileResponse(path)
        resp.content_type = ctype
        # Atlas/manifest bất biến theo bản phát hành — cho trình
        # duyệt cache để avatar không tải lại 1.2MB mỗi lần mở app.
        resp.headers["Cache-Control"] = "public, max-age=86400"
        return resp

    async def _handle_workspace_media(self, request):
        rel = request.match_info.get("path", "").strip()
        if not rel or ".." in rel or rel.startswith("/") or rel.startswith("\\"):
            return web.Response(text="Đường dẫn không hợp lệ", status=400)
        ws = Path(self.cfg.workspace_dir).resolve()
        target = (ws / rel).resolve()
        try:
            target.relative_to(ws)
        except ValueError:
            return web.Response(text="Từ chối truy cập ngoài workspace", status=403)
        if not target.is_file():
            return web.Response(text="Không tìm thấy file", status=404)
        ext = target.suffix.lower()
        content_types = {
            ".png": "image/png",
            ".jpg": "image/jpeg",
            ".jpeg": "image/jpeg",
            ".webp": "image/webp",
            ".gif": "image/gif",
            ".svg": "image/svg+xml",
            ".mp3": "audio/mpeg",
            ".wav": "audio/wav",
            ".mp4": "video/mp4",
        }
        ctype = content_types.get(ext, "application/octet-stream")
        return web.Response(body=target.read_bytes(), content_type=ctype)

    async def _handle_avatar(self, request):
        # Sửa 1.6.2: thử lần lượt nhiều đường dẫn thay vì chỉ 1.
        # Trước đây chỉ có dossier_dir.parent/assets/... trong khi
        # file thật nằm ở repo root và mulon/webapp/assets/ nên
        # handler luôn 404 dù file có tồn tại. Thứ tự giữ đường
        # cũ đầu tiên để không đổi hành vi khi file cũ có mặt.
        repo_root = Path(__file__).resolve().parent.parent
        candidates = [
            Path(self.cfg.dossier_dir).parent / "assets"
            / "mulon-avatar.webp",
            repo_root / "mulon-avatar.webp",
            repo_root / "mulon" / "webapp" / "assets"
            / "mulon-avatar.webp",
            repo_root / "assets" / "mulon-avatar.webp",
        ]
        seen: set[Path] = set()
        for path in candidates:
            if path in seen:
                continue
            seen.add(path)
            if path.is_file():
                return web.FileResponse(path)
        return web.Response(status=404, text="no avatar")

    # ---------- state ----------
    async def _connectors_state(self) -> list[dict]:
        out: list[dict] = []
        try:
            health = await self.connectors.health_all()
        except Exception:
            health = {}
        for name in self.connectors.names():
            h = health.get(name) or {}
            item = {
                "id": name, "name": name, "kind": "builtin",
                "ok": bool(h.get("ok")), "enabled": True,
                "toggleable": False,
                "detail": str(h.get("error") or h.get("detail") or ""),
            }
            if name in ("gmail", "gcalendar") \
                    and self.google_auth is not None:
                # 1.5.0: frontend vẽ nút Kết nối/Ngắt kết nối
                # theo trạng thái này (cả 2 connector dùng
                # chung 1 ủy quyền Google).
                item["google"] = self.google_auth.status()
            elif name == "zalo_personal":
                # 1.7.8 (T-22.1): Zalo cá nhân
                item["zalo"] = {
                    "configured": bool(h.get("configured")),
                    "connected": bool(h.get("connected")),
                    "user": h.get("user"),
                    "limitations": h.get("limitations", ""),
                }
            elif name == "telegram_personal":
                # 1.7.8 (T-22.1): Telegram cá nhân
                item["telegram_personal"] = {
                    "configured": bool(h.get("configured")),
                    "connected": bool(h.get("connected")),
                    "user": h.get("user"),
                    "warning": h.get("warning", ""),
                }
            elif name == "facebook_personal":
                # 1.7.9 (T-22.2): Facebook cá nhân
                item["facebook_personal"] = {
                    "configured": bool(h.get("configured")),
                    "connected": bool(h.get("connected")),
                    "checkpoint_detected": bool(h.get("checkpoint_detected")),
                    "user": h.get("user"),
                    "warning": h.get("warning", ""),
                    "limitations": h.get("limitations", ""),
                }
            elif name == "instagram_messages":
                # 1.7.10 (T-22.3): Tin nhắn Instagram
                item["instagram_messages"] = {
                    "configured": bool(h.get("configured")),
                    "connected": bool(h.get("connected")),
                    "checkpoint_detected": bool(h.get("checkpoint_detected")),
                    "user": h.get("user"),
                    "warning": h.get("warning", ""),
                    "limitations": h.get("limitations", ""),
                }
            elif name == "threads_messages":
                # 1.7.10 (T-22.3): Tin nhắn Threads
                item["threads_messages"] = {
                    "configured": bool(h.get("configured")),
                    "connected": bool(h.get("connected")),
                    "checkpoint_detected": bool(h.get("checkpoint_detected")),
                    "user": h.get("user"),
                    "warning": h.get("warning", ""),
                    "limitations": h.get("limitations", ""),
                }
            out.append(item)
        # MCP servers: trạng thái nối từ manager + enabled từ file
        # cấu hình (đọc tươi để toggle phản ánh đúng).
        if self.mcp is not None:
            from .mcp_client import load_server_configs

            entries = load_server_configs(self.mcp.config_path)
            status = self.mcp.status()
            managed = {}
            if self.marketplace is not None:
                managed = {r["local_name"]: r for r in
                           self.marketplace.installed_list()}
            for entry in entries:
                name = str(entry.get("name"))
                st = status.get(name) or {}
                item = {
                    "id": f"mcp:{name}", "name": name, "kind": "mcp",
                    "ok": bool(st.get("connected")),
                    "enabled": bool(entry.get("enabled", False)),
                    "toggleable": True,
                    "detail": str(st.get("error") or ""),
                }
                record = managed.get(name)
                if record is not None:
                    # Server do marketplace quản lý: UI hiện vòng
                    # đời + sức khoẻ thay cho trạng thái nối thô.
                    item["managed"] = True
                    item["lifecycle_state"] = record[
                        "lifecycle_state"]
                    item["health_state"] = record["health_state"]
                    item["pending_restart"] = record[
                        "pending_restart"]
                out.append(item)
        return out

    def _policy_state(self) -> dict:
        desc = self.policy.describe()
        groups = sorted({
            *(desc["groups"].keys()), *(desc["session_groups"].keys()),
            *(spec.group for spec in self.registry.specs() if spec.group),
        })
        # Nhóm có tiền tố (mcp:<server>, connector:<tên>) không
        # liệt kê ở mục Nhóm việc nữa — chúng có mục riêng
        # "Connector & server MCP" ngay dưới, tên đọc được.
        groups = [g for g in groups
                  if not g.startswith(("mcp:", "connector:"))]
        tools = sorted({
            *(desc["tools"].keys()),
            *(desc["session_tools"].keys()),
            *self.registry.names(),
        })
        # Quyền RIÊNG từng connector/server (đợt vá sau 1.4 —
        # trước đây màn Quyền không có mục nào cho connector).
        # Danh sách lấy từ trạng thái sống nên cài thêm cái nào
        # là tự xuất hiện.
        connectors: dict[str, str] = {}
        for name in self.connectors.names():
            key = f"connector:{name}"
            connectors[key] = self.policy.decide("", key).verdict
        if self.mcp is not None:
            try:
                from .mcp_client import load_server_configs
                for entry in load_server_configs(self.mcp.config_path):
                    key = f"mcp:{entry.get('name')}"
                    connectors[key] = self.policy.decide(
                        "", key).verdict
            except Exception:
                pass

        specs = dict(desc.get("connector_specs", {}))
        if self.mcp is not None and self.registry is not None:
            try:
                from .mcp_client import load_server_configs
                for entry in load_server_configs(self.mcp.config_path):
                    sname = str(entry.get("name") or "")
                    mcp_group = f"mcp:{sname}"
                    if sname and (sname not in specs or mcp_group not in specs):
                        mcp_tools = [s for s in self.registry.specs() if s.group == mcp_group]
                        acts = []
                        for s in mcp_tools:
                            is_write = any(w in s.name.lower() for w in ("write", "create", "delete", "edit", "update", "run", "post", "send", "remove"))
                            k = "write" if is_write else "read"
                            acts.append({
                                "id": s.name,
                                "name": s.name,
                                "label": s.description or s.name,
                                "kind": k,
                                "default": "ask" if is_write else "allow",
                                "effective": self.policy.decide(s.name, mcp_group).verdict,
                            })
                        mcp_item = {
                            "title": f"MCP: {sname}",
                            "description": f"Server MCP {sname} ({len(acts)} công cụ)",
                            "actions": acts,
                        }
                        specs[sname] = mcp_item
                        specs[mcp_group] = mcp_item
            except Exception:
                pass

        return {
            "default": desc["default"],
            "groups": {
                g: self.policy.decide("", g).verdict for g in groups},
            "group_labels": {
                g: label for g in groups
                if (label := policy_group_label(g))},
            "connectors": connectors,
            "connector_labels": {
                k: k.split(":", 1)[1] for k in connectors},
            "tools": {
                t: self.policy.decide(
                    t, (self.registry.get(t).group
                        if self.registry.get(t) else "")).verdict
                for t in tools},
            "host": desc,
            "connector_specs": specs,
        }

    async def _library_state(self) -> list[dict]:
        """Danh sách Library active cho /api/state (sửa UI)."""
        if self.library is None:
            return []
        try:
            items = await self.library.list_items(status="active",
                                                  limit=100)
        except Exception:
            return []
        out = []
        for it in items:
            k = it.get("kind") or "other"
            out.append({
                "id": it.get("id"),
                "title": it.get("name") or "",
                "name": it.get("name") or "",
                "kind": k,
                "kind_label": LIBRARY_KIND_LABELS.get(k, "Tệp khác"),
                "caption": it.get("caption") or "",
                "source": it.get("source") or "",
                "status": it.get("status") or "active",
                "share_status": it.get("share_status") or "",
                "pinned": bool(it.get("pinned")),
                "created_at": it.get("created_at") or "",
            })
        return out

    async def _schedule_state(self) -> dict:
        items: list[dict] = []
        try:
            rows = await self.memory.list_schedules()
        except Exception:
            rows = []
            available = False
        else:
            available = True
        for r in rows:
            payload = str(r.get("payload") or "")
            raw_title = str(r.get("title") or "")
            cron_raw = str(r.get("cron") or "")
            cron_human, cron_display = _format_cron_display(cron_raw)
            internal = internal_kind(payload)
            if internal is not None:
                items.append({
                    "id": str(r.get("id")),
                    "name": "Feed chủ động (tự động)",
                    "cron": cron_raw,
                    "cron_human": cron_human,
                    "cron_display": cron_display,
                    "prompt": "Job hệ thống: tự viết bài Feed theo lịch.",
                    "enabled": bool(r.get("enabled", 1)),
                    "next_run_at": r.get("next_run_at") or "",
                    "last_run_at": r.get("last_run_at") or "",
                    "toggleable": True,
                    "kind": "feed_auto",
                })
                continue
            clean_t = _clean_schedule_title(raw_title, payload)
            items.append({
                "id": str(r.get("id")),
                "name": _truncate_words(clean_t, 72) or str(r.get("id")),
                "cron": cron_raw,
                "cron_human": cron_human,
                "cron_display": cron_display,
                "prompt": _clean_schedule_title("", payload)[:400],
                "full_payload": payload,
                "enabled": bool(r.get("enabled")),
                "next_run_at": r.get("next_run_at") or "",
                "last_run_at": r.get("last_run_at") or "",
                "toggleable": True,
                "kind": "schedule",
            })
        _disambiguate_schedule_items(
            [it for it in items if it.get("kind") == "schedule"],
            title_key="name", full_key="prompt", max_len=72,
        )
        items.append({
            "id": "ideas_auto",
            "name": "Ideas tự sinh (chờ duyệt)",
            "cron": "theo vòng nền",
            "cron_human": "Theo vòng nền",
            "cron_display": "Theo vòng nền",
            "prompt": "Chỉ sinh thẻ chờ duyệt, không tự nhắn, không tự chạy, không tự tạo goal.",
            "enabled": await effective_auto_enabled(self.memory, self.cfg),
            "next_run_at": "",
            "last_run_at": "",
            "toggleable": True,
            "kind": "ideas_auto",
        })
        items.append({
            "id": "heartbeat",
            "name": "Heartbeat",
            "cron": "*/30 * * * *",
            "cron_human": "Mỗi 30 phút",
            "cron_display": "Mỗi 30 phút (*/30 * * * *)",
            "prompt": "Quét checklist HEARTBEAT.md định kỳ.",
            "enabled": await effective_enabled(self.memory, self.cfg),
            "next_run_at": "",
            "last_run_at": "",
            "toggleable": True,
            "kind": "heartbeat",
        })
        scheduler_on = bool(self.cfg.scheduler_enabled)
        hb_en = await effective_enabled(self.memory, self.cfg)
        heartbeat_info = {
            "id": "heartbeat",
            "name": "Heartbeat",
            "interval": "Mỗi 30 phút (*/30 * * * *)",
            "cron": "*/30 * * * *",
            "cron_human": "Mỗi 30 phút",
            "status": "scheduled" if hb_en else "paused",
            "status_label": "Đã lên lịch" if hb_en else "Đã tạm dừng",
            "enabled": hb_en,
        }
        return {
            "available": available,
            "scheduler_enabled": scheduler_on,
            "feed_auto": self.feed_auto is not None,
            "heartbeat": heartbeat_info,
            "items": items,
        }

    async def _upcoming_state(self) -> list[dict]:
        """Danh sách Sắp tới (Upcoming) hợp nhất từ 100% dữ liệu thật:
        - Job theo lịch hẹn (schedules)
        - Chu kỳ quét định kỳ (Heartbeat)
        - Lịch Feed chủ động (feed_auto)
        - Cam kết/hạn đang theo dõi (tracked_items mở)."""
        upcoming: list[dict] = []

        # 1. Job theo lịch từ DB
        try:
            rows = await self.memory.list_schedules()
        except Exception:
            rows = []
        for r in rows:
            payload = str(r.get("payload") or "")
            raw_title = str(r.get("title") or "")
            internal = internal_kind(payload)
            if internal is not None:
                continue
            if bool(r.get("enabled", 1)):
                cron_raw = str(r.get("cron") or "")
                cron_human, cron_display = _format_cron_display(cron_raw)
                clean_t = _clean_schedule_title(raw_title, payload)
                upcoming.append({
                    "id": f"sched_{r.get('id')}",
                    "raw_id": str(r.get("id")),
                    "kind": "schedule",
                    "kind_label": "Lịch hẹn cá nhân",
                    "title": _truncate_words(clean_t, 72) or f"Lịch #{r.get('id')}",
                    "full_title": _clean_schedule_title("", payload)[:400],
                    "cron": cron_raw,
                    "cron_human": cron_human,
                    "time_label": cron_display,
                    "next_run_at": r.get("next_run_at") or "",
                    "can_modify_via_chat": True,
                    "chat_instruction": f"Huỷ bằng chat: 'huỷ lịch {r.get('id')}' hoặc nhấn mở để sửa/xoá",
                    "read_only": False,
                })
        _disambiguate_schedule_items(
            [it for it in upcoming if it.get("kind") == "schedule"],
            title_key="title", full_key="full_title", max_len=72,
        )

        # 2. Heartbeat định kỳ
        try:
            hb_en = await effective_enabled(self.memory, self.cfg)
        except Exception:
            hb_en = bool(self.cfg.proactivity_enabled)
        if hb_en:
            upcoming.append({
                "id": "heartbeat",
                "raw_id": "heartbeat",
                "kind": "heartbeat",
                "kind_label": "Hệ thống định kỳ",
                "title": "Heartbeat (quét chủ động checklist & cam kết)",
                "cron": "*/30 * * * *",
                "cron_human": "Mỗi 30 phút",
                "time_label": "Mỗi 30 phút (*/30 * * * *)",
                "next_run_at": "",
                "can_modify_via_chat": False,
                "chat_instruction": "Chỉ xem (tiến trình nền hệ thống, bật/tắt trong Lịch)",
                "read_only": True,
            })

        # 3. Lịch Feed chủ động
        if self.feed_auto is not None:
            try:
                feed_st = await self.feed_auto.get_state()
            except Exception:
                feed_st = {}
            if feed_st and feed_st.get("enabled", True):
                f_cron = str(feed_st.get("cron") or FEED_DEFAULT_CRON)
                f_human, f_disp = _format_cron_display(f_cron)
                upcoming.append({
                    "id": "feed_auto",
                    "raw_id": FEED_SCHEDULE_ID,
                    "kind": "feed_auto",
                    "kind_label": "Hệ thống định kỳ",
                    "title": "Feed chủ động (tự động điểm tin)",
                    "cron": f_cron,
                    "cron_human": f_human,
                    "time_label": f_disp,
                    "next_run_at": str(feed_st.get("next_run_at") or ""),
                    "can_modify_via_chat": False,
                    "chat_instruction": "Chỉ xem (tiến trình nền hệ thống)",
                    "read_only": True,
                })

        # 4. Cam kết đang theo dõi (tracked items)
        try:
            tracked = await self.memory.list_tracked_items(status="open")
        except Exception:
            tracked = []
        for t in tracked:
            due = t.get("due_at") or ""
            time_str = f"Hạn: {due}" if due else "Đang theo dõi"
            upcoming.append({
                "id": f"tracked_{t['id']}",
                "raw_id": f"tracked_{t['id']}",
                "kind": "tracked_item",
                "kind_label": "Cam kết đang theo dõi",
                "title": _truncate_words(_clean_schedule_title(t.get("title") or "", t.get("detail") or ""), 72) or "Cam kết",
                "time_label": time_str,
                "next_run_at": due,
                "detail": t.get("detail") or "",
                "can_modify_via_chat": True,
                "chat_instruction": f"Cập nhật/đóng bằng chat: 'đóng cam kết #{t['id']}'",
                "read_only": False,
            })

        return upcoming

    async def _profile_state(self) -> dict:
        import os

        files = []
        if self.dossier is not None:
            base = Path(self.cfg.dossier_dir)
            for name in sorted(self.dossier.files):
                if name == "BOOTSTRAP.md":
                    continue
                updated = ""
                fpath = base / name
                if fpath.exists():
                    import datetime

                    updated = datetime.datetime.fromtimestamp(
                        os.path.getmtime(fpath)).isoformat(
                        timespec="seconds")
                files.append({
                    "name": name,
                    "description": DOSSIER_FILE_DESCRIPTIONS.get(name, "Tài liệu hồ sơ agent"),
                    "updated_at": updated,
                    "chars": len(self.dossier.files[name]),
                })
        facts = 0
        try:
            facts = len(await self.memory.active_facts(limit=10000))
        except Exception:
            pass
        skills_info = {"available": False, "count": 0, "names": []}
        if self.skills is not None:
            try:
                names = self.skills.visible_names()
                skills_info = {"available": True, "count": len(names),
                               "names": names}
            except Exception:
                pass
        theme = DEFAULT_THEME
        if self.memory is not None:
            try:
                stored = await self.memory.kv_get(THEME_KV_KEY)
                if stored in THEME_KEYS:
                    theme = stored
            except Exception:
                pass
        return {"dossier_files": files, "facts_active": facts,
                "skills": skills_info, "theme": theme}

    async def _probe_proxy(self) -> dict:
        """Kiểm tra proxy model 127.0.0.1:8317 qua CLIProxyManager (T-14)."""
        return await self.cliproxy.get_status()

    async def _handle_cliproxy_status(self, request):
        st = await self.cliproxy.get_status()
        return web.json_response({"ok": True, **st})

    async def _handle_cliproxy_models(self, request):
        models = await self.cliproxy.fetch_models()
        return web.json_response({"ok": True, "models": models})

    async def _handle_cliproxy_accounts(self, request):
        accounts = self.cliproxy.get_accounts()
        return web.json_response({"ok": True, "accounts": accounts})

    async def _handle_cliproxy_start(self, request):
        res = await self.cliproxy.start_process()
        return web.json_response(res)

    async def _handle_cliproxy_stop(self, request):
        res = await self.cliproxy.stop_process()
        return web.json_response(res)

    async def _system_state(self, user: Optional[dict]) -> dict:
        """Thẻ "Thiết bị & hệ thống": chỉ dữ kiện THẬT của máy
        đang chạy Mulon + phiên Telegram đang xem. Mulon không
        có hệ thống ghép thiết bị — không bịa danh sách máy."""
        viewer = None
        if user:
            name = " ".join(
                x for x in [str(user.get("first_name") or ""),
                            str(user.get("last_name") or "")] if x)
            viewer = {
                "id": user.get("id"),
                "name": name,
                "username": str(user.get("username") or ""),
            }
        os_name = " ".join(
            x for x in [platform.system(), platform.release()] if x)
        return {
            "hostname": socket.gethostname(),
            "os": os_name,
            "arch": platform.machine() or "",
            "version": MULON_VERSION,
            "uptime_s": max(0, int(time.time() - self._started_at)),
            "proxy": await self._probe_proxy(),
            "scheduler_enabled": bool(self.cfg.scheduler_enabled),
            "heartbeat_enabled": await effective_enabled(
                self.memory, self.cfg),
            "viewer": viewer,
        }

    async def _handle_state(self, request):
        # Tab Việc = TASK THẬT (vá sau 1.4, owner bắt): chỉ
        # bản ghi từ bảng tasks (đường plan-act-verify, job,
        # agent con, build ý tưởng). Bản 1.3 từng gộp lượt
        # chat (trajectory turn_done/turn_error) cho khỏi
        # trống — owner chê đúng: đó là lịch sử chat, không
        # phải việc. Lượt chat ở yên trong chat.
        tasks = []
        try:
            for t in await self.memory.list_tasks(limit=20):
                c_step = t.get("current_step") or ""
                if t.get("status") == "running" and self.activity:
                    live_info = self.activity.get_running_task_info(t["id"])
                    if live_info and live_info.get("current_step"):
                        c_step = live_info["current_step"]
                norm_t = _normalize_task_view(t, live_step=c_step)
                tasks.append(norm_t)
        except Exception:
            pass
        history = []
        try:
            rows = await self.memory.recent_trajectory(
                kind="approval_decision", limit=20)
            for r in rows:
                p = r.get("payload") or {}
                h_tool = str(p.get("tool", "?"))
                h_group = str(p.get("group", ""))
                # T-23.5: Loại bỏ hoàn toàn các bản ghi thẻ duyệt thử khỏi Mini App
                if (h_tool == "the_duyet"
                        or bool(p.get("test"))
                        or str(p.get("kind") or "") == "test"
                        or "phê duyệt thử" in str(p.get("summary") or "").lower()
                        or "thẻ duyệt thử" in str(p.get("summary") or "").lower()):
                    continue
                h_layer = str(p.get("layer") or "ask")
                history.append({
                    "tool": h_tool,
                    "group": h_group,
                    # Nhãn lời thường để app hiện thay tên thô;
                    # không có nhãn -> "" và frontend fallback
                    # về tên tool (chi tiết vẫn còn tên thô).
                    "action_label": known_action_label(h_tool, h_group),
                    "group_label": policy_group_label(h_group),
                    "layer": h_layer,
                    "layer_label": policy_layer_label(h_layer),
                    "outcome": p.get("outcome", ""),
                    "approved": bool(p.get("approved")),
                    "remember": bool(p.get("remember")),
                    "at": r.get("created_at", ""),
                })
        except Exception:
            pass
        # Thẻ chờ duyệt: server gắn nhãn hành động lời thường
        # (cùng tool_action_label mà thẻ duyệt trên chat dùng)
        # để frontend chỉ trình bày — tên tool thô chỉ còn ở
        # dòng chi tiết của thẻ.
        pending = []
        if self.broker:
            for item in self.broker.pending():
                item = dict(item)
                i_tool = str(item.get("tool") or "")
                i_group = str(item.get("group") or "")
                if (i_tool == "the_duyet"
                        or bool(item.get("test"))
                        or str(item.get("kind") or "") == "test"
                        or "phê duyệt thử" in str(item.get("summary") or "").lower()
                        or "thẻ duyệt thử" in str(item.get("summary") or "").lower()):
                    continue
                item["action_label"] = tool_action_label(
                    i_tool, i_group)
                item["group_label"] = policy_group_label(i_group)
                pending.append(item)
        state = {
            "ok": True,
            "status": self.activity.snapshot(),
            "tasks": tasks,
            "upcoming": await self._upcoming_state(),
            "approvals": {
                "pending": pending,
                "history": history,
            },
            "schedule": await self._schedule_state(),
            "profile": await self._profile_state(),
            "system": await self._system_state(
                request.get("tg_user")),
            "connectors": await self._connectors_state(),
            "vault": self.vault_store.labels()
                     if self.vault_store is not None else [],
            "policy": self._policy_state(),
            # 1.3.0: tóm tắt marketplace nhỏ cho badge điều hướng.
            "marketplace_summary": (self.marketplace.summary()
                                    if self.marketplace is not None
                                    else None),
            # 1.4.0: trạng thái Feed chủ động cho màn Cài đặt →
            # Feed chủ động. None khi bản chạy chưa nối runner.
            "feed": (await self._feed_state()
                     if self.feed_auto is not None else None),
            "ideas": (await self.memory.list_idea_cards(status="open")
                      if self.memory is not None else []),
            "goals": await self._goals_state(),
            "library": await self._library_state(),
            "heartbeat_history": (await self.memory.get_heartbeat_history(limit=5)
                                  if self.memory is not None else []),
        }
        return web.json_response(state)

    async def _handle_heartbeat_history(self, request):
        limit = 20
        try:
            limit = int(request.query.get("limit", 20))
        except Exception:
            pass
        history = (await self.memory.get_heartbeat_history(limit=limit)
                   if self.memory is not None else [])
        return web.json_response({"ok": True, "history": history})

    async def _handle_task(self, request):
        task_id = request.query.get("id", "")
        task = await self.memory.get_task(task_id) if task_id else None
        if task is None:
            return web.json_response(
                {"ok": False, "error": "không thấy task"}, status=404)
        c_step = task.get("current_step") or ""
        if task.get("status") == "running" and self.activity:
            live_info = self.activity.get_running_task_info(task_id)
            if live_info and live_info.get("current_step"):
                c_step = live_info["current_step"]
        norm_task = _normalize_task_view(task, live_step=c_step)
        events = []
        try:
            rows = await self.memory.recent_trajectory(limit=300)
            for r in rows:
                p = r.get("payload") or {}
                if p.get("task_id") == task_id:
                    events.append({"kind": r.get("kind"),
                                   "payload": redact_trajectory_payload(p),
                                   "at": r.get("created_at", "")})
        except Exception:
            pass
        events.reverse()
        return web.json_response({
            "ok": True,
            "task": norm_task,
            "events": events,
        })

    async def _handle_task_stop(self, request):
        """Huỷ tác vụ đang chạy (kể cả sub-agent) — dừng thật sự asyncio.Task."""
        data = {}
        if request.can_read_body:
            try:
                data = await request.json()
            except Exception:
                data = {}
        task_id = str(data.get("id") or request.query.get("id") or "").strip()
        if not task_id:
            return web.json_response({"ok": False, "error": "Thiếu mã task_id (tham số id)"}, status=400)

        # 1. Thử huỷ qua ActivityTracker
        stopped_live = False
        if self.activity is not None:
            stopped_live = self.activity.stop_task(task_id)

        # 2. Cập nhật DB và huỷ dứt điểm ngữ cảnh làm việc của session
        db_updated = False
        if self.memory is not None:
            try:
                task_row = await self.memory.get_task(task_id)
                if task_row:
                    await self.memory.cancel_task(task_id, error="Đã dừng theo yêu cầu người dùng qua Mini App")
                    s_key = task_row.get("session_key")
                    if s_key:
                        await self.memory.cancel_turn(s_key, reason="miniapp_stop")
                        if self.activity is not None:
                            self.activity.stop_session_tasks(s_key)
                    db_updated = True
            except Exception as exc:
                logger.warning("Cập nhật huỷ task %s trong DB lỗi: %s", task_id, exc)

        if stopped_live or db_updated:
            return web.json_response({
                "ok": True,
                "task_id": task_id,
                "stopped_live": stopped_live,
                "message": "Đã dừng tác vụ thành công.",
            })
        return web.json_response({
            "ok": False,
            "error": "Tác vụ không còn chạy hoặc không tồn tại.",
        }, status=404)

    async def _handle_upcoming(self, request):
        """Trả về danh sách việc sắp tới hợp nhất từ dữ liệu thật."""
        upcoming = await self._upcoming_state()
        return web.json_response({
            "ok": True,
            "upcoming": upcoming,
            "count": len(upcoming),
        })

    async def _handle_profile_content(self, request):
        kind = request.query.get("kind", "")
        name = request.query.get("name", "")
        if kind == "dossier":
            if self.dossier is None:
                return web.json_response({"ok": True, "files": [], "content": ""})
            if name and name != "all":
                if name in self.dossier.files:
                    return web.json_response({
                        "ok": True,
                        "title": name,
                        "description": DOSSIER_FILE_DESCRIPTIONS.get(name, "Tài liệu hồ sơ agent"),
                        "content": self.dossier.files[name][:8000]})
                return web.json_response(
                    {"ok": False, "error": "không có file này"}, status=404)
            # Trả về toàn bộ file dossier trong 1 request duy nhất (tối ưu tải < 3s, T-23.2 / T-23.3)
            files = []
            for fname, fcontent in sorted(self.dossier.files.items()):
                if fname == "BOOTSTRAP.md":
                    continue
                files.append({
                    "name": fname,
                    "title": fname,
                    "description": DOSSIER_FILE_DESCRIPTIONS.get(fname, "Tài liệu hồ sơ agent"),
                    "chars": len(fcontent),
                    "content": fcontent[:8000],
                })
            return web.json_response({"ok": True, "files": files})
        if kind == "memory":
            facts = await self.memory.active_facts(limit=50)
            lines = [f"- {f['fact']}" for f in facts]
            mem_md = ""
            if self.dossier is not None:
                mem_md = self.dossier.files.get("MEMORY.md", "")
            content = (mem_md[:3000] + "\n\n### Facts đang hiệu lực\n\n" + "\n".join(lines))[:6000]
            return web.json_response({
                "ok": True, "title": "Bộ nhớ (MEMORY.md + facts)",
                "content": content})
        return web.json_response(
            {"ok": False, "error": "không có nội dung này"}, status=404)

    async def _handle_profile_facts(self, request):
        """Danh sách FACT thật đang hiệu lực trong Bộ nhớ dài hạn (T-23.3).
        Hỗ trợ tìm kiếm (q), lọc chủ đề (topic) và lọc thời gian (days).
        Số đếm total_active khớp 100% với facts_active ngoài tab Hồ sơ."""
        if self.memory is None:
            return web.json_response({
                "ok": True, "total_active": 0, "count": 0,
                "topics": [], "facts": []
            })
        q_raw = str(request.query.get("q") or request.query.get("query") or "").strip()
        topic_filter = str(request.query.get("topic") or "").strip()
        days_filter = str(request.query.get("days") or "").strip()

        raw_facts = await self.memory.active_facts(limit=10000)
        total_active = len(raw_facts)

        cutoff_iso = ""
        if days_filter:
            from datetime import datetime, timedelta, timezone
            now_dt = datetime.now(timezone.utc)
            if days_filter == "today":
                cutoff_iso = now_dt.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
            elif days_filter in ("7", "7d"):
                cutoff_iso = (now_dt - timedelta(days=7)).isoformat()
            elif days_filter in ("30", "30d"):
                cutoff_iso = (now_dt - timedelta(days=30)).isoformat()

        q_fold = fold_vi(q_raw) if q_raw else ""
        topic_counts: dict[str, int] = {}
        out_facts: list[dict] = []

        for r in raw_facts:
            subj = str(r.get("subject") or "")
            fact_txt = str(r.get("fact") or "")
            topic = _classify_fact_topic(subj, fact_txt)
            topic_counts[topic] = topic_counts.get(topic, 0) + 1

            created = str(r.get("created_at") or r.get("valid_from") or "")
            if cutoff_iso and created and created < cutoff_iso:
                continue
            if topic_filter and topic_filter != "all" and topic != topic_filter:
                continue
            if q_fold:
                haystack = fold_vi(f"{subj} {topic} {fact_txt} {r.get('source') or ''}")
                if q_fold not in haystack:
                    continue

            out_facts.append({
                "id": r.get("id"),
                "subject": subj,
                "topic": topic,
                "topic_label": topic,
                "fact": fact_txt,
                "text": fact_txt,
                "salience": float(r.get("salience") or 0.5),
                "confidence": float(r.get("salience") or 0.5),
                "source": str(r.get("source") or "Ghi nhớ từ hội thoại"),
                "source_msg_id": r.get("source_msg_id"),
                "valid_from": str(r.get("valid_from") or created),
                "created_at": created,
            })

        topics_list = [
            {"id": k, "name": k, "label": k, "count": v}
            for k, v in sorted(topic_counts.items(), key=lambda x: (-x[1], x[0]))
        ]
        return web.json_response({
            "ok": True,
            "total_active": total_active,
            "count": len(out_facts),
            "filtered_count": len(out_facts),
            "topics": topics_list,
            "facts": out_facts,
        })

    async def _handle_profile_fact_detail(self, request):
        """Chi tiết 1 fact trong Bộ nhớ dài hạn (T-23.3)."""
        if self.memory is None:
            return web.json_response({"ok": False, "error": "Chưa có bộ nhớ"}, status=503)
        fid_str = request.match_info.get("id", "")
        try:
            fid = int(fid_str)
        except ValueError:
            return web.json_response({"ok": False, "error": "ID fact không hợp lệ"}, status=400)
        row = await self.memory.get_fact(fid)
        if not row or row.get("valid_to") is not None:
            return web.json_response({"ok": False, "error": "Không tìm thấy fact này"}, status=404)
        subj = str(row.get("subject") or "")
        fact_txt = str(row.get("fact") or "")
        topic = _classify_fact_topic(subj, fact_txt)
        created = str(row.get("created_at") or row.get("valid_from") or "")
        return web.json_response({
            "ok": True,
            "fact": {
                "id": row.get("id"),
                "subject": subj,
                "topic": topic,
                "topic_label": topic,
                "fact": fact_txt,
                "text": fact_txt,
                "salience": float(row.get("salience") or 0.5),
                "confidence": float(row.get("salience") or 0.5),
                "source": str(row.get("source") or "Ghi nhớ từ hội thoại"),
                "source_msg_id": row.get("source_msg_id"),
                "valid_from": str(row.get("valid_from") or created),
                "created_at": created,
            },
        })

    async def _handle_profile_fact_delete(self, request):
        """Xoá (đóng vòng đời valid_to) một fact khỏi Bộ nhớ dài hạn (T-23.3)."""
        if self.memory is None:
            return web.json_response({"ok": False, "error": "Chưa có bộ nhớ"}, status=503)
        body = await self._json_body(request)
        fid_raw = request.match_info.get("id") or body.get("id") or request.query.get("id")
        try:
            fid = int(fid_raw)
        except (TypeError, ValueError):
            return web.json_response({"ok": False, "error": "Thiếu hoặc sai mã fact (id)"}, status=400)
        row = await self.memory.get_fact(fid)
        if not row or row.get("valid_to") is not None:
            return web.json_response({"ok": False, "error": "Fact không tồn tại hoặc đã bị xoá"}, status=404)
        ts = now_iso()
        await self.memory.db.execute(
            "UPDATE memory_facts SET valid_to=? WHERE id=? AND valid_to IS NULL",
            (ts, fid),
        )
        await self.memory.db.commit()
        try:
            await self.memory.log_trajectory("webapp", "fact_deleted", {"fact_id": fid})
        except Exception:
            pass
        remaining = len(await self.memory.active_facts(limit=10000))
        return web.json_response({
            "ok": True,
            "id": fid,
            "facts_active": remaining,
        })

    # ---------- actions ----------
    async def _json_body(self, request) -> dict:
        try:
            data = await request.json()
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    async def _handle_policy(self, request):
        body = await self._json_body(request)
        scope = str(body.get("scope") or "group")
        name = str(body.get("name") or "")
        verdict = str(body.get("verdict") or "")
        if not name or verdict not in ("allow", "ask", "deny"):
            return web.json_response(
                {"ok": False, "error": "thiếu name/verdict hợp lệ"},
                status=400)
        if body.get("persist"):
            applied = self.policy.set_host_rule(scope, name, verdict)
            layer = "host"
        else:
            applied = self.policy.set_session_rule(scope, name, verdict)
            layer = "session"
        if self.memory is not None:
            await self.memory.log_trajectory(
                "webapp", "policy_changed",
                {"scope": scope, "name": name, "verdict": applied,
                 "layer": layer})
        return web.json_response(
            {"ok": True, "verdict": applied, "layer": layer,
             "policy": self._policy_state()})

    async def _handle_connector(self, request):
        body = await self._json_body(request)
        name = str(body.get("name") or "")
        enabled = bool(body.get("enabled"))
        if name.startswith("mcp:") and self.mcp is not None:
            server = name[4:]
            # 1.3.0: server do marketplace quản lý -> route sang
            # MarketplaceService (kèm policy deny/restore + journal
            # + restart) — KHÔNG ghi file trực tiếp, không ghi 2 lần.
            if self.marketplace is not None and \
                    self.marketplace.store.get_installed(server) \
                    is not None:
                from .marketplace import MarketplaceError

                try:
                    result = (self.marketplace.enable(server)
                              if enabled else
                              self.marketplace.disable(server))
                except MarketplaceError as exc:
                    return web.json_response(
                        {"ok": False, "error": exc.message,
                         "code": exc.code}, status=400)
                return web.json_response({
                    "ok": True, "enabled": enabled,
                    "operation_id": result.get("operation_id"),
                    "restart_required": True,
                    "note": "Đã ghi — bot đang tự khởi động lại "
                            "để áp dụng."})
            path = Path(self.mcp.config_path)
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
                servers = data.get("servers") or []
                hit = False
                for entry in servers:
                    if isinstance(entry, dict) \
                            and entry.get("name") == server:
                        entry["enabled"] = enabled
                        hit = True
                if not hit:
                    return web.json_response(
                        {"ok": False,
                         "error": f"không thấy MCP server {server}"},
                        status=404)
                tmp = path.with_suffix(path.suffix + ".tmp")
                tmp.write_text(json.dumps(data, ensure_ascii=False,
                                          indent=2),
                               encoding="utf-8")
                tmp.replace(path)
            except Exception as exc:
                return web.json_response(
                    {"ok": False, "error": f"ghi config lỗi: {exc}"},
                    status=500)
            return web.json_response({
                "ok": True, "enabled": enabled,
                "restart_required": True,
                "note": "Đã ghi vào mcp_servers.json — khởi động "
                        "lại bot để áp dụng."})
        return web.json_response({
            "ok": False, "restart_required": True,
            "error": "Connector này không tắt/bật nóng được — "
                     "chỉ MCP server mới đổi được qua đây."})

    async def _handle_approve(self, request):
        body = await self._json_body(request)
        approval_id = str(body.get("id") or "")
        decision = str(body.get("decision") or "")
        if self.broker is None or not approval_id:
            return web.json_response(
                {"ok": False, "error": "thiếu id"}, status=400)
        mapping = {"approve": (True, False), "deny": (False, False),
                   "approve_remember": (True, True)}
        if decision not in mapping:
            return web.json_response(
                {"ok": False, "error": "decision không hợp lệ"},
                status=400)
        approved, remember = mapping[decision]
        resolved = self.broker.resolve(approval_id, approved,
                                       remember=remember)
        if not resolved:
            return web.json_response(
                {"ok": False, "resolved": False,
                 "error": "Thẻ này đã được xử lý hoặc đã hết hạn."})
        return web.json_response({"ok": True,
                                  "resolved": True})

    async def _handle_theme(self, request):
        body = await self._json_body(request)
        theme = str(body.get("theme") or "")
        if theme not in THEME_KEYS:
            return web.json_response(
                {"ok": False,
                 "error": "theme không thuộc danh sách cho phép"},
                status=400)
        if self.memory is not None:
            await self.memory.kv_set(THEME_KV_KEY, theme)
            await self.memory.log_trajectory(
                "webapp", "theme_changed", {"theme": theme})
        return web.json_response({"ok": True, "theme": theme})

    async def _handle_schedule(self, request):
        body = await self._json_body(request)
        schedule_id = str(body.get("id") or "")
        enabled = bool(body.get("enabled"))
        if not schedule_id:
            return web.json_response(
                {"ok": False, "error": "Thiếu id lịch."},
                status=400)
        if schedule_id == "heartbeat":
            # Công tắc heartbeat thật: lưu kv, engine đọc lại mỗi
            # lượt quét nên ăn ngay, không restart.
            await self.memory.kv_set(
                PROACTIVITY_KV_KEY, "1" if enabled else "0")
            await self.memory.log_trajectory(
                "webapp", "heartbeat_toggled",
                {"enabled": enabled})
            return web.json_response(
                {"ok": True, "enabled": enabled})
        if schedule_id == "ideas_auto":
            # sửa 1.6.2: công tắc Ideas tự sinh (mặc định tắt) —
            # cùng cơ chế kv như heartbeat: vòng nền đọc lại mỗi
            # lượt nên ăn ngay, không restart. Bật chỉ cho phép
            # sinh thẻ chờ duyệt, không tự nhắn, không tự chạy.
            await self.memory.kv_set(
                IDEAS_AUTO_KV_KEY, "1" if enabled else "0")
            await self.memory.log_trajectory(
                "webapp", "ideas_auto_toggled",
                {"enabled": enabled})
            return web.json_response(
                {"ok": True, "enabled": enabled})
        row = await self.memory.get_schedule(schedule_id)
        if schedule_id == FEED_SCHEDULE_ID or (row is not None and internal_kind(
                row.get("payload") or "") == "feed_auto"):
            ok = await self.memory.set_schedule_enabled(schedule_id, enabled)
            if self.feed_auto is not None:
                if enabled:
                    await self.feed_auto.resume()
                    await self.feed_auto.ensure_schedule()
            await self.memory.log_trajectory(
                "webapp", "feed_schedule_toggled", {"enabled": enabled})
            return web.json_response({"ok": True, "enabled": enabled})
        if row is not None and internal_kind(
                row.get("payload") or "") is not None:
            return web.json_response(
                {"ok": False,
                 "error": "Job hệ thống nội bộ — không hỗ trợ bật/tắt."},
                status=400)
        ok = await self.memory.set_schedule_enabled(schedule_id,
                                                    enabled)
        return web.json_response({"ok": ok})

    async def _build_schedule_detail(self, raw_id: str) -> Optional[dict]:
        """Xây dựng đối tượng chi tiết lịch trình đầy đủ (thông tin, diễn giải
        cron tiếng Việt, quyền hạn, lịch sử chạy kèm thời lượng/đầu ra/lỗi).
        """
        from datetime import datetime as _dt, timezone as _tz
        sid = (raw_id or "").strip()
        if sid.startswith("sched_"):
            sid = sid[6:]
        if not sid or self.memory is None:
            return None

        def _calc_duration_label(start_iso: str, end_iso: str) -> str:
            if not start_iso or not end_iso:
                return "Tức thời"
            try:
                t0 = _dt.fromisoformat(start_iso.replace("Z", "+00:00"))
                t1 = _dt.fromisoformat(end_iso.replace("Z", "+00:00"))
                sec = max(0, int((t1 - t0).total_seconds()))
                if sec <= 1:
                    return "< 1 giây"
                if sec < 60:
                    return f"{sec} giây"
                mins, rem = divmod(sec, 60)
                return f"{mins} phút {rem:02d} giây" if rem else f"{mins} phút"
            except Exception:
                return "Tức thời"

        # 1. Nhịp kiểm tra chủ động (Heartbeat)
        if sid == "heartbeat":
            hb_en = await effective_enabled(self.memory, self.cfg)
            hb_history = await self.memory.get_heartbeat_history(limit=25)
            interval_s = int(getattr(self.cfg, "proactivity_interval_s", 300) or 300)
            mins = max(1, interval_s // 60)
            cron_expr = f"*/{mins} * * * *" if mins < 60 else f"0 */{max(1, mins // 60)} * * *"
            enabled = bool(hb_en)
            runs = []
            for idx, r in enumerate(hb_history):
                st_raw = str(r.get("status") or "ok")
                is_err = st_raw in ("error", "failed")
                runs.append({
                    "id": f"hb_{idx}",
                    "started_at": r.get("created_at") or r.get("time_str") or "",
                    "time_str": r.get("time_str") or "",
                    "duration_label": "< 1 giây",
                    "status": "failed" if is_err else "done",
                    "status_label": "✕ Đã lỗi" if is_err else "✓ Hoàn tất",
                    "summary": r.get("summary") or "Kiểm tra chủ động định kỳ",
                    "output": r.get("detail") or r.get("summary") or "Không có cảnh báo phát sinh.",
                    "error": r.get("detail") if is_err else "",
                })
            return {
                "id": "heartbeat",
                "kind": "heartbeat",
                "kind_label": "Nhịp kiểm tra chủ động",
                "name": "Kiểm tra chủ động (Heartbeat)",
                "title": "Kiểm tra chủ động (Heartbeat)",
                "prompt": "Quét các việc đang mở, lịch trình sắp tới hạn và tín hiệu hệ thống để chủ động nhắc nhở khi cần thiết.",
                "payload": "Quét các việc đang mở, lịch trình sắp tới hạn và tín hiệu hệ thống để chủ động nhắc nhở khi cần thiết.",
                "cron": cron_expr,
                "cron_human": _describe_cron_vi(cron_expr),
                "cron_display": _format_cron_display(cron_expr)[1],
                "timezone": getattr(self.cfg, "default_timezone", "Asia/Ho_Chi_Minh"),
                "enabled": enabled,
                "status_label": "Đã lên lịch" if enabled else "Đã tạm dừng",
                "next_run_at": "",
                "last_run_at": runs[0]["started_at"] if runs else "",
                "editable": False,
                "deletable": False,
                "permissions": [
                    "Đọc danh sách việc đang mở và lịch trình tới hạn",
                    "Quét tín hiệu chủ động theo chu kỳ nền",
                    "Tôn trọng chống làm phiền: tối đa 1 thông báo / 24 giờ cho mỗi việc",
                ],
                "runs": runs,
            }

        # 2. Ý tưởng tự sinh (ideas_auto)
        if sid == "ideas_auto":
            ideas_st = await self._ideas_state()
            enabled = bool(ideas_st.get("auto_enabled"))
            interval_s = int(getattr(self.cfg, "ideas_interval_s", 21600) or 21600)
            hrs = max(1, interval_s // 3600)
            cron_expr = f"0 */{hrs} * * *"
            runs = []
            try:
                cur = await self.memory.db.execute(
                    "SELECT id, kind, payload, created_at FROM trajectory "
                    "WHERE kind IN ('ideas_generated', 'ideas_auto_toggled', 'ideas_error') "
                    "ORDER BY id DESC LIMIT 20"
                )
                for r in await cur.fetchall():
                    d = dict(r)
                    try:
                        pl = json.loads(d.get("payload") or "{}")
                    except Exception:
                        pl = {}
                    is_err = d["kind"] == "ideas_error"
                    cnt = pl.get("count", 0)
                    summ = (
                        f"Lỗi sinh ý tưởng: {pl.get('error', '')}" if is_err
                        else (f"Đã sinh {cnt} thẻ ý tưởng mới" if d["kind"] == "ideas_generated"
                              else ("Đã bật tự sinh ý tưởng" if pl.get("enabled") else "Đã tạm dừng tự sinh ý tưởng"))
                    )
                    runs.append({
                        "id": f"idea_run_{d['id']}",
                        "started_at": d.get("created_at") or "",
                        "duration_label": "< 1 giây",
                        "status": "failed" if is_err else "done",
                        "status_label": "✕ Đã lỗi" if is_err else "✓ Hoàn tất",
                        "summary": summ,
                        "output": summ,
                        "error": str(pl.get("error") or "") if is_err else "",
                    })
            except Exception:
                pass
            return {
                "id": "ideas_auto",
                "kind": "ideas_auto",
                "kind_label": "Khám phá ý tưởng nền",
                "name": "Ý tưởng tự sinh",
                "title": "Ý tưởng tự sinh",
                "prompt": "Tự động tổng hợp thẻ ý tưởng mới dựa trên mối quan tâm và công việc gần đây của chủ sở hữu (chỉ tạo thẻ chờ duyệt, không tự thực thi).",
                "payload": "Tự động tổng hợp thẻ ý tưởng mới dựa trên mối quan tâm và công việc gần đây của chủ sở hữu.",
                "cron": cron_expr,
                "cron_human": _describe_cron_vi(cron_expr),
                "cron_display": _format_cron_display(cron_expr)[1],
                "timezone": getattr(self.cfg, "default_timezone", "Asia/Ho_Chi_Minh"),
                "enabled": enabled,
                "status_label": "Đã lên lịch" if enabled else "Đã tạm dừng",
                "next_run_at": "",
                "last_run_at": runs[0]["started_at"] if runs else "",
                "editable": False,
                "deletable": False,
                "permissions": [
                    "Đọc sở thích, ghi nhớ và chủ đề quan tâm của chủ sở hữu",
                    "Tạo thẻ ý tưởng ở trạng thái chờ duyệt (không tự chạy tác vụ)",
                ],
                "runs": runs,
            }

        # 3. Mục theo dõi định kỳ (tracked_<id>)
        if sid.startswith("tracked_"):
            try:
                tid = int(sid.split("_", 1)[1])
                cur = await self.memory.db.execute(
                    "SELECT * FROM tracked_items WHERE id=?", (tid,)
                )
                trow = await cur.fetchone()
            except Exception:
                trow = None
            if not trow:
                return None
            td = dict(trow)
            cron_expr = str(td.get("schedule_cron") or "0 9 * * *")
            name = _clean_schedule_title(str(td.get("name") or ""), str(td.get("query") or ""))
            return {
                "id": f"tracked_{td['id']}",
                "kind": "tracked",
                "kind_label": "Theo dõi chỉ số mục tiêu",
                "name": name,
                "title": name,
                "prompt": str(td.get("query") or td.get("name") or ""),
                "payload": str(td.get("query") or td.get("name") or ""),
                "cron": cron_expr,
                "cron_human": _describe_cron_vi(cron_expr),
                "cron_display": _format_cron_display(cron_expr)[1],
                "timezone": getattr(self.cfg, "default_timezone", "Asia/Ho_Chi_Minh"),
                "enabled": True,
                "status_label": "Đã lên lịch",
                "next_run_at": "",
                "last_run_at": str(td.get("last_checked_at") or td.get("updated_at") or ""),
                "editable": False,
                "deletable": False,
                "permissions": [
                    "Truy vấn chỉ số theo dõi định kỳ cho mục tiêu",
                    "Ghi nhật ký tiến độ vào mục tiêu liên kết",
                ],
                "runs": [],
            }

        # 4. Lịch trong bảng schedules (lịch cá nhân hoặc feed_auto)
        row = await self.memory.get_schedule(sid)
        if row is None and sid == "feed_auto":
            row = await self.memory.get_schedule(FEED_SCHEDULE_ID)
        if row is None:
            return None

        sched_id = str(row.get("id") or sid)
        payload = str(row.get("payload") or "")
        ikind = internal_kind(payload)
        is_feed = (sched_id == FEED_SCHEDULE_ID or ikind == "feed_auto")
        cron_expr = str(row.get("cron") or "")
        tz_name = str(row.get("timezone") or getattr(self.cfg, "default_timezone", "Asia/Ho_Chi_Minh"))
        enabled = bool(row.get("enabled"))
        if is_feed:
            title = "Feed chủ động"
            prompt_text = "Tự động thu thập tin tức từ nguồn RSS/Atom và trang web đã đăng ký, lọc trùng và tóm tắt vào kênh Feed."
            kind_str = "feed_auto"
            kind_label = "Hệ thống · Feed chủ động"
            editable = True
            deletable = False
            permissions = [
                "Đọc nguồn RSS/Atom và trang web trong danh sách theo dõi",
                "Tóm tắt và đăng bài vào kênh Feed theo hạn mức ngày",
                "Tự động tạm ngưng trong khung giờ yên lặng",
            ]
        else:
            title = _clean_schedule_title(str(row.get("title") or ""), payload)
            prompt_text = sanitize_path_display(fix_glued_words(payload))
            kind_str = "custom"
            kind_label = "Lịch hẹn cá nhân"
            editable = (ikind is None)
            deletable = (ikind is None)
            permissions = [
                "Tự động giao việc cho agent đúng chu kỳ cron đã hẹn",
                "Đọc hồ sơ, bộ nhớ và kỹ năng phục vụ nội dung lời nhắc",
                "Mọi thao tác gửi tin/ghi ngoài hệ thống vẫn qua chốt quyền công cụ",
            ]

        # Thu thập lịch sử chạy từ trajectory + đối chiếu bảng tasks
        runs: list[dict] = []
        try:
            cur = await self.memory.db.execute(
                "SELECT id, session_key, kind, payload, created_at FROM trajectory "
                "WHERE kind IN ('schedule_fired', 'schedule_error') "
                "ORDER BY id DESC LIMIT 80"
            )
            traj_rows = [dict(r) for r in await cur.fetchall()]
        except Exception:
            traj_rows = []

        # Lấy các tasks gần đây để ghép kết quả chạy thật (thời lượng / đầu ra / lỗi)
        all_tasks = await self.memory.list_tasks(limit=60)
        norm_tasks = [_normalize_task_view(t) for t in all_tasks]
        payload_prefix = fold_vi(payload.strip())[:32] if payload.strip() else ""

        matched_task_ids: set[str] = set()
        for tr in traj_rows:
            try:
                pl = json.loads(tr.get("payload") or "{}")
            except Exception:
                pl = {}
            if str(pl.get("schedule_id") or "") != sched_id:
                continue
            tr_time = str(tr.get("created_at") or "")
            if tr.get("kind") == "schedule_error":
                err_msg = sanitize_path_display(str(pl.get("error") or "Lỗi thực thi lịch trình"))
                runs.append({
                    "id": f"sched_err_{tr['id']}",
                    "started_at": tr_time,
                    "finished_at": tr_time,
                    "duration_label": "< 1 giây",
                    "status": "failed",
                    "status_label": "✕ Đã lỗi",
                    "summary": err_msg,
                    "output": "",
                    "error": err_msg,
                })
                continue

            # Ghép với task được sinh ra ngay thời điểm schedule_fired
            matched_task = None
            for nt in norm_tasks:
                if nt["id"] in matched_task_ids:
                    continue
                nt_title_fold = fold_vi(str(nt.get("title") or ""))
                if payload_prefix and payload_prefix[:20] in nt_title_fold:
                    matched_task = nt
                    matched_task_ids.add(nt["id"])
                    break
            if matched_task:
                st = matched_task["status"]
                dur = _calc_duration_label(
                    str(matched_task.get("created_at") or tr_time),
                    str(matched_task.get("updated_at") or tr_time),
                )
                out_text = str(matched_task.get("result") or matched_task.get("summary_markdown") or "")
                err_text = str(matched_task.get("error") or "")
                runs.append({
                    "id": f"sched_run_{tr['id']}",
                    "task_id": matched_task["id"],
                    "started_at": str(matched_task.get("created_at") or tr_time),
                    "finished_at": str(matched_task.get("updated_at") or tr_time),
                    "duration_label": dur,
                    "status": st,
                    "status_label": matched_task.get("status_label") or "✓ Hoàn tất",
                    "summary": matched_task.get("status_sub") or matched_task.get("title") or "Đã chạy lịch hẹn",
                    "output": out_text or "Đã thực thi xong yêu cầu định kỳ.",
                    "error": err_text,
                })
            else:
                runs.append({
                    "id": f"sched_run_{tr['id']}",
                    "started_at": tr_time,
                    "finished_at": tr_time,
                    "duration_label": "Tức thời",
                    "status": "done",
                    "status_label": "✓ Đã kích hoạt",
                    "summary": "Đã giao việc định kỳ cho agent",
                    "output": prompt_text,
                    "error": "",
                })

        # Bổ sung các tasks khớp nội dung lời nhắc nếu chưa có trong trajectory
        if payload_prefix and not is_feed:
            for nt in norm_tasks:
                if nt["id"] in matched_task_ids:
                    continue
                nt_title_fold = fold_vi(str(nt.get("title") or ""))
                if payload_prefix[:24] and payload_prefix[:24] in nt_title_fold:
                    matched_task_ids.add(nt["id"])
                    dur = _calc_duration_label(
                        str(nt.get("created_at") or ""),
                        str(nt.get("updated_at") or ""),
                    )
                    runs.append({
                        "id": f"task_{nt['id']}",
                        "task_id": nt["id"],
                        "started_at": str(nt.get("created_at") or ""),
                        "finished_at": str(nt.get("updated_at") or ""),
                        "duration_label": dur,
                        "status": nt["status"],
                        "status_label": nt.get("status_label") or "✓ Hoàn tất",
                        "summary": nt.get("status_sub") or nt.get("title") or "",
                        "output": str(nt.get("result") or nt.get("summary_markdown") or ""),
                        "error": str(nt.get("error") or ""),
                    })

        # Nếu có last_run_at trên dòng lịch mà chưa có bản ghi runs nào, tạo 1 bản ghi tổng hợp
        last_run_at = str(row.get("last_run_at") or "")
        if last_run_at and not runs:
            runs.append({
                "id": f"last_{sched_id}",
                "started_at": last_run_at,
                "finished_at": last_run_at,
                "duration_label": "Tức thời",
                "status": "done",
                "status_label": "✓ Hoàn tất",
                "summary": "Lần chạy gần nhất theo lịch hẹn",
                "output": prompt_text,
                "error": "",
            })

        return {
            "id": sched_id,
            "kind": kind_str,
            "kind_label": kind_label,
            "name": title,
            "title": title,
            "raw_title": str(row.get("title") or ""),
            "prompt": prompt_text,
            "payload": payload,
            "cron": cron_expr,
            "cron_human": _describe_cron_vi(cron_expr),
            "cron_display": _format_cron_display(cron_expr)[1],
            "timezone": tz_name,
            "enabled": enabled,
            "status_label": "Đã lên lịch" if enabled else "Đã tạm dừng",
            "next_run_at": str(row.get("next_run_at") or ""),
            "last_run_at": last_run_at or (runs[0]["started_at"] if runs else ""),
            "created_at": str(row.get("created_at") or ""),
            "updated_at": str(row.get("updated_at") or ""),
            "editable": editable,
            "deletable": deletable,
            "permissions": permissions,
            "runs": runs[:25],
        }

    async def _handle_schedule_detail(self, request):
        raw_id = request.match_info.get("id", "") or request.query.get("id", "")
        detail = await self._build_schedule_detail(raw_id)
        if detail is None:
            return web.json_response(
                {"ok": False, "error": "Không tìm thấy lịch trình."},
                status=404,
            )
        return web.json_response({"ok": True, "schedule": detail, **detail})

    async def _handle_schedule_update(self, request):
        from datetime import datetime as _dt, timezone as _tz
        body = await self._json_body(request)
        raw_id = (
            request.match_info.get("id", "")
            or str(body.get("id") or "")
        ).strip()
        if raw_id.startswith("sched_"):
            raw_id = raw_id[6:]
        if not raw_id:
            return web.json_response(
                {"ok": False, "error": "Thiếu id lịch trình."}, status=400
            )
        row = await self.memory.get_schedule(raw_id)
        if row is None:
            return web.json_response(
                {"ok": False, "error": "Không tìm thấy lịch trình để sửa."},
                status=404,
            )
        new_cron = str(body.get("cron") if body.get("cron") is not None else row.get("cron") or "").strip()
        if not new_cron:
            return web.json_response(
                {"ok": False, "error": "Biểu thức cron không được để trống."},
                status=400,
            )
        tz_name = str(body.get("timezone") or row.get("timezone") or getattr(self.cfg, "default_timezone", "Asia/Ho_Chi_Minh"))
        try:
            parse_cron(new_cron)
            nxt = next_run_iso(new_cron, _dt.now(_tz.utc), tz_name)
        except Exception as exc:
            return web.json_response(
                {"ok": False, "error": f"Biểu thức cron không hợp lệ: {exc}"},
                status=400,
            )

        ikind = internal_kind(str(row.get("payload") or ""))
        if ikind is not None:
            # Với job hệ thống như feed_auto, chỉ cho phép đổi cron
            new_payload = str(row.get("payload") or "")
            new_title = str(row.get("title") or "")
        else:
            raw_prompt = body.get("payload") if body.get("payload") is not None else body.get("prompt")
            new_payload = str(raw_prompt if raw_prompt is not None else row.get("payload") or "").strip()
            if not new_payload:
                return web.json_response(
                    {"ok": False, "error": "Nội dung lời nhắc không được để trống."},
                    status=400,
                )
            new_title = str(
                body.get("title") if body.get("title") is not None else row.get("title") or ""
            ).strip()

        new_enabled = (
            1 if bool(body.get("enabled")) else 0
        ) if body.get("enabled") is not None else int(row.get("enabled") or 0)
        ts = now_iso()
        await self.memory.db.execute(
            "UPDATE schedules SET cron=?, timezone=?, payload=?, title=?, "
            "enabled=?, next_run_at=?, updated_at=? WHERE id=?",
            (new_cron, tz_name, new_payload, new_title, new_enabled, nxt, ts, raw_id),
        )
        await self.memory.db.commit()
        await self.memory.log_trajectory(
            "webapp", "schedule_updated",
            {"schedule_id": raw_id, "cron": new_cron, "enabled": bool(new_enabled)},
        )
        detail = await self._build_schedule_detail(raw_id)
        return web.json_response({"ok": True, "schedule": detail})

    async def _handle_schedule_delete(self, request):
        body = await self._json_body(request)
        raw_id = (
            request.match_info.get("id", "")
            or str(body.get("id") or "")
        ).strip()
        if raw_id.startswith("sched_"):
            raw_id = raw_id[6:]
        if not raw_id:
            return web.json_response(
                {"ok": False, "error": "Thiếu id lịch trình."}, status=400
            )
        if raw_id in ("heartbeat", "ideas_auto", "feed_auto", FEED_SCHEDULE_ID):
            return web.json_response(
                {"ok": False, "error": "Lịch hệ thống chỉ hỗ trợ tạm dừng, không xóa vĩnh viễn."},
                status=400,
            )
        row = await self.memory.get_schedule(raw_id)
        if row is None:
            return web.json_response(
                {"ok": False, "error": "Không tìm thấy lịch trình."},
                status=404,
            )
        if internal_kind(str(row.get("payload") or "")) is not None:
            return web.json_response(
                {"ok": False, "error": "Job hệ thống nội bộ — không hỗ trợ xóa."},
                status=400,
            )
        ok = await self.memory.delete_schedule(raw_id)
        if ok:
            await self.memory.log_trajectory(
                "webapp", "schedule_deleted", {"schedule_id": raw_id}
            )
        return web.json_response({"ok": ok, "deleted_id": raw_id})

    # ---------- 1.4.0: Feed chủ động ----------
    async def _handle_feed(self, request):
        """Điều khiển Feed chủ động từ Mini App (owner-only qua
        middleware auth như mọi /api/*).

        Cố ý KHÔNG có action tắt/bật tổng (quyết định 0.2b: Feed
        luôn tự động). Actions: set_cron, set_quiet, set_limits,
        add_source, remove_source, set_source_enabled,
        set_denylist, run_now, resume.
        """
        if self.feed_auto is None:
            return web.json_response(
                {"ok": False, "error": "Feed chủ động chưa được "
                                       "nối ở bản chạy này."},
                status=503)
        body = await self._json_body(request)
        action = str(body.get("action") or "")
        runner = self.feed_auto
        engine = runner.engine

        def _bad(msg: str):
            return web.json_response(
                {"ok": False, "error": msg}, status=400)

        if action == "set_cron":
            cron = str(body.get("cron") or "").strip()
            try:
                parse_cron(cron)
            except Exception:
                return _bad("cron không hợp lệ (cần 5 trường: "
                            "phút giờ ngày tháng thứ)")
            await runner.apply_settings({"cron": cron})
        elif action == "set_quiet":
            quiet = str(body.get("quiet_hours") or "").strip()
            if not valid_quiet_hours(quiet):
                return _bad("giờ yên lặng phải dạng HH:MM-HH:MM")
            await runner.apply_settings({"quiet_hours": quiet})
        elif action == "set_limits":
            changes = {}
            for key in ("max_posts_per_day", "daily_token_budget"):
                if body.get(key) is not None:
                    try:
                        value = int(body[key])
                    except (TypeError, ValueError):
                        return _bad(f"{key} phải là số nguyên")
                    if value < 0:
                        return _bad(f"{key} không được âm")
                    changes[key] = value
            if not changes:
                return _bad("không có giới hạn nào để đặt")
            await runner.apply_settings(changes)
        elif action == "add_source":
            url = str(body.get("url") or "").strip()
            if not url.startswith(("http://", "https://")):
                return _bad("URL nguồn phải bắt đầu http:// "
                            "hoặc https://")
            trust = str(body.get("trust") or "normal").lower()
            if trust not in ("high", "normal", "low"):
                trust = "normal"
            sources = engine.read_sources()
            if any(s["url"] == url for s in sources):
                return _bad("nguồn này đã có trong danh sách")
            sources.append({"url": url,
                            "label": str(body.get("label") or "")[:60],
                            "trust": trust, "enabled": True})
            engine.set_sources(sources)
        elif action == "remove_source":
            url = str(body.get("url") or "").strip()
            sources = [s for s in engine.read_sources()
                       if s["url"] != url]
            engine.set_sources(sources)
        elif action == "set_source_enabled":
            url = str(body.get("url") or "").strip()
            sources = engine.read_sources()
            for s in sources:
                if s["url"] == url:
                    s["enabled"] = bool(body.get("enabled"))
            engine.set_sources(sources)
        elif action == "set_denylist":
            raw = body.get("denylist")
            if not isinstance(raw, list):
                return _bad("denylist phải là danh sách domain")
            await runner.apply_settings(
                {"denylist": [str(d) for d in raw]})
        elif action == "save_all":
            changes = {}
            if "cron" in body and body.get("cron") is not None:
                cron = str(body.get("cron") or "").strip()
                try:
                    parse_cron(cron)
                except Exception:
                    return _bad("cron không hợp lệ (cần 5 trường: "
                                "phút giờ ngày tháng thứ)")
                changes["cron"] = cron
            if "quiet_hours" in body and body.get("quiet_hours") is not None:
                quiet = str(body.get("quiet_hours") or "").strip()
                if not valid_quiet_hours(quiet):
                    return _bad("giờ yên lặng phải dạng HH:MM-HH:MM")
                changes["quiet_hours"] = quiet
            for key in ("max_posts_per_day", "daily_token_budget"):
                if body.get(key) is not None and str(body.get(key)).strip() != "":
                    try:
                        value = int(body[key])
                    except (TypeError, ValueError):
                        return _bad(f"{key} phải là số nguyên")
                    if value < 0:
                        return _bad(f"{key} không được âm")
                    changes[key] = value
            if "denylist" in body and body.get("denylist") is not None:
                raw_dl = body.get("denylist")
                if not isinstance(raw_dl, list):
                    return _bad("denylist phải là danh sách domain")
                changes["denylist"] = [
                    str(d).strip() for d in raw_dl if str(d).strip()
                ]
            if not changes:
                return _bad("không có cấu hình nào để lưu")
            await runner.apply_settings(changes)
        elif action == "run_now":
            if runner._sender is None:
                return web.json_response(
                    {"ok": False,
                     "error": "bot chưa sẵn sàng gửi (sender "
                              "chưa được gắn)"},
                    status=503)
            result = await runner.run_once(force=True)
            return web.json_response(
                {"ok": bool(result.get("ok")), "result": result,
                 "feed": await self._feed_state()})
        elif action == "resume":
            await runner.resume()
        elif action == "set_enabled":
            enabled = bool(body.get("enabled"))
            await self.memory.set_schedule_enabled(FEED_SCHEDULE_ID, enabled)
            if enabled:
                await runner.resume()
                await runner.ensure_schedule()
            await self.memory.log_trajectory(
                "webapp", "feed_schedule_toggled", {"enabled": enabled})
        else:
            return _bad(f"action không hỗ trợ: {action or '(trống)'}")
        return web.json_response(
            {"ok": True, "feed": await self._feed_state()})

    async def _feed_state(self) -> Optional[dict]:
        if self.feed_auto is None:
            return None
        st = await self.feed_auto.get_state()
        if isinstance(st, dict):
            cron_raw = str(st.get("cron") or "")
            st["cron_human"] = _describe_cron_vi(cron_raw)
            st["cron_display"] = _format_cron_display(cron_raw)
        return st

    # ---------- Ideas chủ động theo chuẩn Muse (T-10.3) ----------
    async def _handle_ideas_list(self, request):
        if self.memory is None:
            return web.json_response({"ok": False, "error": "Chưa có database"}, status=503)
        status = request.query.get("status", "open")
        limit = 50
        try:
            limit = int(request.query.get("limit", 50))
        except ValueError:
            pass
        items = await self.memory.list_idea_cards(status=status, limit=limit)
        return web.json_response({"ok": True, "ideas": items})

    async def _handle_ideas_generate(self, request):
        if self.ideas is None:
            return web.json_response({"ok": False, "error": "Ideas chưa sẵn sàng ở bản này"}, status=503)
        try:
            cards = await self.ideas.generate()
            return web.json_response({"ok": True, "ideas": cards})
        except Exception as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=500)

    async def _handle_ideas_do(self, request):
        if self.ideas is None:
            return web.json_response({"ok": False, "error": "Ideas chưa sẵn sàng ở bản này"}, status=503)
        body = await self._json_body(request)
        try:
            card_id = int(body.get("card_id") or 0)
        except ValueError:
            return web.json_response({"ok": False, "error": "card_id không hợp lệ"}, status=400)
        res = await self.ideas.do_card(card_id, session_key="webapp:ideas")
        return web.json_response({"ok": bool(res.get("ok")), **res})

    async def _handle_ideas_dismiss(self, request):
        if self.ideas is None:
            return web.json_response({"ok": False, "error": "Ideas chưa sẵn sàng ở bản này"}, status=503)
        body = await self._json_body(request)
        try:
            card_id = int(body.get("card_id") or 0)
        except ValueError:
            return web.json_response({"ok": False, "error": "card_id không hợp lệ"}, status=400)
        res = await self.ideas.dismiss(card_id)
        return web.json_response({"ok": bool(res.get("ok")), **res})

    # ---------- Goals + Briefings (T-10.4) ----------
    async def _goals_state(self) -> dict:
        if self.memory is None:
            return {"tree": [], "count": 0, "active_count": 0}
        tree = await self.memory.get_goal_tree()
        active = sum(1 for g in tree if g.get("status") == "active")
        return {"tree": tree, "count": len(tree), "active_count": active}

    async def _handle_goals_list(self, request):
        if self.memory is None:
            return web.json_response({"ok": False, "error": "Chưa có database"}, status=503)
        status = request.query.get("status", "")
        tree = await self.memory.get_goal_tree(status=status or None)
        return web.json_response({"ok": True, "goals": tree})

    async def _handle_goal_detail(self, request):
        if self.memory is None:
            return web.json_response({"ok": False, "error": "Chưa có database"}, status=503)
        gid_str = request.match_info.get("id", "")
        try:
            gid = int(gid_str)
        except ValueError:
            return web.json_response({"ok": False, "error": "goal id không hợp lệ"}, status=400)
        detail = await self.memory.get_goal_detail(gid)
        if detail is None:
            return web.json_response({"ok": False, "error": f"Không tìm thấy goal #{gid}"}, status=404)
        return web.json_response({"ok": True, "goal": detail})

    async def _handle_goal_create(self, request):
        if self.memory is None:
            return web.json_response({"ok": False, "error": "Chưa có database"}, status=503)
        body = await self._json_body(request)
        title = (body.get("title") or "").strip()
        if not title:
            return web.json_response({"ok": False, "error": "Thiếu tiêu đề goal"}, status=400)
        desc = (body.get("description") or "").strip()
        cat = (body.get("category") or "productivity").strip()
        kind = (body.get("goal_kind") or "outcome").strip()
        pid = body.get("parent_id")
        try:
            goal = await self.memory.create_goal(
                title=title, description=desc, parent_id=int(pid) if pid is not None else None,
                category=cat, goal_kind=kind
            )
            return web.json_response({"ok": True, "goal": goal})
        except ValueError as err:
            return web.json_response({"ok": False, "error": str(err)}, status=400)

    async def _handle_goal_update(self, request):
        if self.memory is None:
            return web.json_response({"ok": False, "error": "Chưa có database"}, status=503)
        body = await self._json_body(request)
        gid = body.get("goal_id") or body.get("id")
        if not gid:
            return web.json_response({"ok": False, "error": "Thiếu goal_id"}, status=400)
        try:
            pid = int(body["parent_id"]) if "parent_id" in body and body["parent_id"] is not None else None
            updated = await self.memory.update_goal(
                goal_id=int(gid),
                title=body.get("title"),
                description=body.get("description"),
                current_state=body.get("current_state"),
                category=body.get("category"),
                goal_kind=body.get("goal_kind"),
                parent_id=pid,
            )
            if updated is None:
                return web.json_response({"ok": False, "error": f"Không tìm thấy goal #{gid}"}, status=404)
            return web.json_response({"ok": True, "goal": updated})
        except ValueError as err:
            return web.json_response({"ok": False, "error": str(err)}, status=400)

    async def _handle_goal_close(self, request):
        if self.memory is None:
            return web.json_response({"ok": False, "error": "Chưa có database"}, status=503)
        body = await self._json_body(request)
        gid = body.get("goal_id") or body.get("id")
        if not gid:
            return web.json_response({"ok": False, "error": "Thiếu goal_id"}, status=400)
        goal = await self.memory.close_goal(int(gid))
        if goal is None:
            return web.json_response({"ok": False, "error": f"Không tìm thấy goal #{gid} hoặc đã đóng"}, status=404)
        return web.json_response({"ok": True, "goal": goal})

    async def _handle_goal_briefing(self, request):
        if self.memory is None:
            return web.json_response({"ok": False, "error": "Chưa có database"}, status=503)
        gid_str = request.match_info.get("id", "")
        try:
            gid = int(gid_str)
        except ValueError:
            return web.json_response({"ok": False, "error": "goal id không hợp lệ"}, status=400)
        from .goal_briefing import GoalBriefingService
        svc = GoalBriefingService(self.cfg, self.memory, getattr(self, "gateway", None))
        try:
            briefing = await svc.generate_briefing(gid)
            return web.json_response({"ok": True, "briefing": briefing})
        except ValueError as err:
            return web.json_response({"ok": False, "error": str(err)}, status=400)
        except Exception as exc:
            return web.json_response({"ok": False, "error": str(exc)}, status=500)

    # ---------- 1.3.0 (gói vá Mini App): kỹ năng + Vault ----------
    async def _handle_skills(self, request):
        """Danh sách kỹ năng owner ĐỌC được: tên + mô tả + nhóm + nguồn
        (đường file SKILL.md) — từ đúng catalog agent đang nạp
        (đã qua vet + đủ điều kiện), không danh sách bịa.
        Sửa T-23.3: chuẩn hoá mô tả vỡ ('>', '>-'), dịch mô tả sang
        tiếng Việt ở tầng hiển thị và phân nhóm theo chủ đề."""
        if self.skills is None:
            return web.json_response(
                {"ok": True, "available": False, "skills": []})
        paths = {}
        bodies = {}
        try:
            for e in self.skills.entries:
                paths[e["name"]] = e.get("path", "")
                bodies[e["name"]] = e.get("body", "")
        except Exception:
            pass
        items = []
        for e in self.skills.catalog():
            sname = e["name"]
            raw_desc = str(e.get("description") or "")
            sbody = bodies.get(sname, "")
            vi_desc = _localize_skill_description(sname, raw_desc, sbody)
            clean_src = sanitize_path_display(paths.get(sname, ""))
            group = _classify_skill_group(sname, raw_desc, clean_src)
            items.append({
                "name": sname,
                "description": vi_desc,
                "display_description": vi_desc,
                "raw_description": raw_desc if raw_desc not in (">", ">-", "|", "|-") else "",
                "group": group,
                "group_label": group,
                "source": clean_src,
            })
        return web.json_response(
            {"ok": True, "available": True, "count": len(items), "skills": items})

    async def _handle_skill_detail(self, request):
        """Nội dung đầy đủ của 1 SKILL.md để owner mở đọc ngay
        trong app (trước đây app chỉ có tên + số lượng). Nội dung
        qua SkillCatalog.read — cùng cửa agent dùng, tôn trọng
        vet/eligibility."""
        name = str(request.match_info.get("name") or "")
        if self.skills is None:
            return web.json_response(
                {"ok": False, "error": "chưa nạp catalog kỹ năng"},
                status=404)
        result = self.skills.read(name)
        if not result.get("ok"):
            return web.json_response(
                {"ok": False,
                 "error": result.get("error") or "không đọc được"},
                status=404)
        return web.json_response({
            "ok": True, "name": name,
            "content": result.get("content", ""),
            "source": sanitize_path_display(result.get("path", ""))})

    async def _handle_vault_capture(self, request):
        """Nhập bí mật NGAY trong Mini App (1.3.0): owner gõ nhãn
        + giá trị ở màn Vault -> ghi thẳng VaultStore.put -> chỉ
        trả ref. Giá trị KHÔNG echo về response, KHÔNG vào
        trajectory/log (chỉ nhãn + ref được ghi vết) — cùng kỷ
        luật với form một lần qua link, nhưng không cần link
        127.0.0.1 (link đó chết trên điện thoại vì trỏ về máy
        tính của owner)."""
        body = await self._json_body(request)
        label = str(body.get("label") or "").strip()
        value = body.get("value")
        value = value if isinstance(value, str) else ""
        if self.vault_store is None:
            return web.json_response(
                {"ok": False, "error": "Vault chưa được nối ở "
                                       "bản chạy này."},
                status=503)
        if not label or not value:
            return web.json_response(
                {"ok": False, "error": "thiếu nhãn hoặc giá trị"},
                status=400)
        if len(label) > 120 or len(value) > 8192:
            return web.json_response(
                {"ok": False, "error": "nhãn hoặc giá trị quá dài"},
                status=400)
        ref = self.vault_store.put(label, value)
        if self.memory is not None:
            try:
                await self.memory.log_trajectory(
                    "webapp", "vault_captured",
                    {"label": label, "ref": ref})
            except Exception:
                pass
        notifier = getattr(self, "vault_notifier", None)
        # Sửa T-24.4: Nếu notifier chính là callback đã đăng ký qua on_captured trên vault_store,
        # bỏ qua gọi thừa để không gửi 2 lần tin xác nhận vào Telegram
        store_listeners = getattr(self.vault_store, "_capture_listeners", [])
        if notifier is not None and notifier not in store_listeners:
            try:
                res = notifier(label, ref)
                if asyncio.iscoroutine(res):
                    asyncio.create_task(res)
            except Exception as exc:
                logger.warning("vault_notifier lỗi: %s", exc)
        return web.json_response({"ok": True, "ref": ref})

    async def _handle_vault_delete(self, request):
        """Xoá một bí mật khỏi Vault qua ref."""
        body = await self._json_body(request)
        ref = str(body.get("ref") or "").strip()
        if self.vault_store is None:
            return web.json_response(
                {"ok": False, "error": "Vault chưa được nối ở bản chạy này."},
                status=503)
        if not ref:
            return web.json_response(
                {"ok": False, "error": "thiếu ref bí mật"},
                status=400)
        ok = self.vault_store.delete(ref)
        if not ok:
            return web.json_response(
                {"ok": False, "error": "không tìm thấy bí mật trong kho"},
                status=404)
        if self.memory is not None:
            try:
                await self.memory.log_trajectory(
                    "webapp", "vault_deleted", {"ref": ref})
            except Exception:
                pass
        return web.json_response({"ok": True, "ref": ref})

    async def _handle_vault_update(self, request):
        """Sửa nhãn hoặc cập nhật giá trị bí mật trong Vault."""
        body = await self._json_body(request)
        ref = str(body.get("ref") or "").strip()
        label = body.get("label")
        value = body.get("value")
        if self.vault_store is None:
            return web.json_response(
                {"ok": False, "error": "Vault chưa được nối ở bản chạy này."},
                status=503)
        if not ref:
            return web.json_response(
                {"ok": False, "error": "thiếu ref bí mật"},
                status=400)
        lbl_str = str(label).strip() if label is not None else None
        val_str = str(value) if value is not None and value != "" else None
        if lbl_str is not None and len(lbl_str) > 120:
            return web.json_response(
                {"ok": False, "error": "nhãn quá dài (tối đa 120 ký tự)"},
                status=400)
        if val_str is not None and len(val_str) > 8192:
            return web.json_response(
                {"ok": False, "error": "giá trị quá dài (tối đa 8192 ký tự)"},
                status=400)
        ok = self.vault_store.update(ref, label=lbl_str, value=val_str)
        if not ok:
            return web.json_response(
                {"ok": False, "error": "không tìm thấy bí mật trong kho"},
                status=404)
        if self.memory is not None:
            try:
                await self.memory.log_trajectory(
                    "webapp", "vault_updated",
                    {"ref": ref, "label": lbl_str, "value_changed": bool(val_str)})
            except Exception:
                pass
        return web.json_response({"ok": True, "ref": ref})

    # ---------- 1.5.0: Google OAuth ----------

    _GOOGLE_KV_STATE = "google_oauth_state"
    _GOOGLE_OAUTH_TTL = 600  # giây, khớp doc + hành vi 1.6.1

    # Sửa 1.6.2: state OAuth lưu dạng DANH SÁCH các state đang chờ
    # thay vì 1 key đơn — bấm Kết nối 2 lần (2 tab/thiết bị) không
    # còn ghi đè lẫn nhau. Mỗi state kèm ts, hết hạn 10 phút,
    # dùng 1 lần: chỉ xoá state đã khớp hoặc đã hết hạn, các state
    # chờ khác giữ nguyên. Tương thích đọc format cũ 1.6.1
    # {"state": ..., "ts": ...}: gặp thì coi như danh sách 1 state.
    async def _google_states_load(self):
        try:
            raw = await self.memory.kv_get(self._GOOGLE_KV_STATE)
        except Exception:
            return []
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except Exception:
            return []
        if isinstance(data, dict):  # format cũ 1 state
            data = [data]
        if not isinstance(data, list):
            return []
        now = time.time()
        states = []
        for item in data:
            if not isinstance(item, dict):
                continue
            st = str(item.get("state") or "")
            try:
                ts = float(item.get("ts") or 0)
            except (TypeError, ValueError):
                ts = 0
            if st and now - ts <= self._GOOGLE_OAUTH_TTL:
                states.append({"state": st, "ts": ts})
        return states

    async def _google_states_save(self, states):
        # Lưu danh sách đã prune hết hạn; rỗng thì ghi "" như hành
        # vi xoá cũ (kv_get("") -> load ra []).
        pruned = [s for s in states
                  if time.time() - float(s.get("ts") or 0)
                  <= self._GOOGLE_OAUTH_TTL]
        try:
            await self.memory.kv_set(
                self._GOOGLE_KV_STATE,
                json.dumps(pruned) if pruned else "")
        except Exception:
            pass

    async def _handle_google_config(self, request):
        if self.google_auth is None:
            return web.json_response(
                {"ok": False,
                 "error": "Google connector chưa được nối ở bản chạy này."},
                status=503)
        if request.method == "GET":
            return web.json_response({
                "ok": True,
                "configured": self.google_auth.configured(),
                "connected": self.google_auth.connected(),
                "email": self.google_auth.account_email(),
                "redirect_uri": self.google_auth.redirect_uri(),
                "client_id": self.google_auth.client_id(),
                "has_client_secret": bool(self.google_auth.client_secret()),
            })
        body = await self._json_body(request)
        cid = str(body.get("client_id") or "").strip()
        csec = str(body.get("client_secret") or "").strip()
        if not cid:
            return web.json_response(
                {"ok": False, "error": "Vui lòng nhập Client ID."},
                status=400)
        if not csec and not self.google_auth.client_secret():
            return web.json_response(
                {"ok": False, "error": "Vui lòng nhập Client Secret."},
                status=400)
        self.google_auth.save_credentials(cid, csec)
        await self.memory.log_trajectory(
            "webapp", "google_configured", {"client_id_prefix": cid[:10]})
        return web.json_response({
            "ok": True,
            "configured": self.google_auth.configured(),
            "connected": self.google_auth.connected(),
            "email": self.google_auth.account_email(),
            "redirect_uri": self.google_auth.redirect_uri(),
            "client_id": self.google_auth.client_id(),
            "has_client_secret": bool(self.google_auth.client_secret()),
        })

    async def _handle_google_auth_url(self, request):
        if self.google_auth is None:
            return web.json_response(
                {"ok": False, "error": "Google connector chưa "
                                       "được nối ở bản chạy này."},
                status=503)
        if not self.google_auth.configured():
            return web.json_response(
                {"ok": False,
                 "error": "Chưa có client id/secret: nhập 2 bí "
                          "mật nhãn google:client_id và "
                          "google:client_secret ở màn Kho lưu "
                          "trữ, hoặc đặt env GOOGLE_CLIENT_ID / "
                          "GOOGLE_CLIENT_SECRET."},
                status=400)
        import secrets as _secrets

        state = _secrets.token_urlsafe(24)
        states = await self._google_states_load()
        states.append({"state": state, "ts": time.time()})
        await self._google_states_save(states)
        return web.json_response({
            "ok": True,
            "url": self.google_auth.build_auth_url(state),
            "redirect_uri": self.google_auth.redirect_uri(),
        })

    async def _handle_google_disconnect(self, request):
        if self.google_auth is None:
            return web.json_response(
                {"ok": False, "error": "Google connector chưa "
                                       "được nối ở bản chạy này."},
                status=503)
        # Sửa UI/flow: thu hồi token ở phía Google trước khi xóa
        # local; revoke lỗi thì vẫn ngắt local để user không bị kẹt,
        # nhưng ghi rõ revoked=False để biết token có thể còn sống.
        revoked = False
        try:
            revoked = await self.google_auth.revoke()
        except Exception:
            revoked = False
        self.google_auth.disconnect()
        await self.memory.log_trajectory(
            "webapp", "google_disconnected", {"revoked": revoked})
        return web.json_response({"ok": True})

    # ---------- Personal Connectors (T-22.1 / T-22.2 / T-22.3) ----------
    VALID_PERSONAL_CONNECTORS = (
        "zalo_personal",
        "telegram_personal",
        "facebook_personal",
        "instagram_messages",
        "threads_messages",
    )

    async def _handle_personal_connector_status(self, request):
        name = request.query.get("name") or ""
        if name not in self.VALID_PERSONAL_CONNECTORS:
            return web.json_response(
                {"ok": False, "error": f"Tên connector không hợp lệ (phải là một trong: {', '.join(self.VALID_PERSONAL_CONNECTORS)})"},
                status=400,
            )
        conn = await self.connectors.get(name)
        if conn is None:
            return web.json_response(
                {"ok": False, "error": f"Connector {name} không khả dụng."},
                status=503,
            )
        health = await conn.health_check()
        return web.json_response({"ok": True, "health": health})

    async def _handle_personal_connector_qr(self, request):
        body = await self._json_body(request)
        name = str(body.get("name") or request.query.get("name") or "")
        if name not in self.VALID_PERSONAL_CONNECTORS:
            return web.json_response(
                {"ok": False, "error": f"Tên connector không hợp lệ (phải là một trong: {', '.join(self.VALID_PERSONAL_CONNECTORS)})"},
                status=400,
            )
        conn = await self.connectors.get(name)
        if conn is None:
            return web.json_response(
                {"ok": False, "error": f"Connector {name} không khả dụng."},
                status=503,
            )
        step = body.get("step", "start")
        result = await conn.call("qr_login", {"step": step})
        return web.json_response(result)

    async def _handle_personal_connector_connect(self, request):
        body = await self._json_body(request)
        name = str(body.get("name") or request.query.get("name") or "")
        if name not in self.VALID_PERSONAL_CONNECTORS:
            return web.json_response(
                {"ok": False, "error": f"Tên connector không hợp lệ (phải là một trong: {', '.join(self.VALID_PERSONAL_CONNECTORS)})"},
                status=400,
            )
        conn = await self.connectors.get(name)
        if conn is None:
            return web.json_response(
                {"ok": False, "error": f"Connector {name} không khả dụng."},
                status=503,
            )
        result = await conn.call("configure", body)
        return web.json_response(result)

    async def _handle_personal_connector_disconnect(self, request):
        body = await self._json_body(request)
        name = str(body.get("name") or request.query.get("name") or "")
        if name not in self.VALID_PERSONAL_CONNECTORS:
            return web.json_response(
                {"ok": False, "error": f"Tên connector không hợp lệ (phải là một trong: {', '.join(self.VALID_PERSONAL_CONNECTORS)})"},
                status=400,
            )
        conn = await self.connectors.get(name)
        if conn is None:
            return web.json_response(
                {"ok": False, "error": f"Connector {name} không khả dụng."},
                status=503,
            )
        result = await conn.call("disconnect", {})
        return web.json_response(result)
        return web.json_response(result)

    async def _handle_google_callback(self, request):
        """Route CÔNG KHAI duy nhất của webapp: trình duyệt
        ngoài quay về từ Google nên không có initData. Bảo vệ
        bằng state nonce (ngẫu nhiên, lưu kv, hạn 10 phút, dùng
        1 lần) + code chỉ đổi được token khi kèm client_secret
        phía server. Trang trả về không chứa dữ liệu nhạy cảm."""

        def page(msg: str, ok: bool):
            # sửa 1.6.2: tiêu đề trang kết quả OAuth dùng màu chữ trung tính
            # cho cả thành công lẫn thất bại; trạng thái phân biệt bằng
            # chính nội dung msg. Tham số ok giữ lại để khỏi đổi chữ ký hàm.
            color = "#1e293b"
            body = (
                "<!doctype html><html lang=\"vi\"><head>"
                "<meta charset=\"utf-8\"><title>Mulon — Google"
                "</title></head><body style=\"font-family:"
                "sans-serif;max-width:32rem;margin:3rem auto;"
                "text-align:center\">"
                f"<h3 style=\"color:{color}\">{msg}</h3>"
                "<p>Đóng trang này và quay lại Telegram được "
                "rồi.</p></body></html>")
            return web.Response(text=body,
                                content_type="text/html")

        if self.google_auth is None:
            return page("Bản chạy này chưa nối Google "
                        "connector.", False)
        code = request.query.get("code") or ""
        state = request.query.get("state") or ""
        # Sửa 1.6.2: đối chiếu trong danh sách state đang chờ.
        # State sai hoàn toàn thì giữ nguyên mọi state chờ (hành vi
        # 1.6.1 giữ lại), chỉ prune state đã hết hạn. State khớp và
        # còn hạn thì đốt đúng state đó, dùng đúng 1 lần, các state
        # chờ khác vẫn dùng được. KHÔNG đổi redirect URI, KHÔNG đổi
        # scope Google.
        states = await self._google_states_load()
        matched = next((s for s in states if s.get("state") == state),
                       None)
        if not code or not matched:
            # Callback lạ: chỉ dọn state hết hạn, không đốt state chờ.
            await self._google_states_save(states)
            return page("Liên kết kết nối không hợp lệ hoặc đã "
                        "hết hạn. Hãy bấm Kết nối lại trong Mini "
                        "App.", False)
        # State khớp: đốt riêng state này, giữ các state chờ khác.
        await self._google_states_save(
            [s for s in states if s.get("state") != state])
        result = await self.google_auth.exchange_code(code)
        if not result.get("ok"):
            return page("Google từ chối kết nối: " +
                        str(result.get("error") or "không rõ"),
                        False)
        await self.memory.log_trajectory(
            "webapp", "google_connected",
            {"email": result.get("email") or ""})
        return page("Đã kết nối Google" +
                    (f" ({result['email']})"
                     if result.get("email") else "") + ".", True)

    async def _handle_mcp_oauth2callback(self, request):
        """Route công khai nhận redirect từ Google OAuth (Web Application) qua Cloudflare tunnel,
        chuyển tiếp thẳng vào cổng minimal OAuth server của MCP (8001/8000/8002) để lưu token."""
        query = request.query_string
        target_ports = [8001, 8000, 8002, 8003, 8004]
        success = False
        error_detail = ""
        user_email = ""
        response_body = ""

        timeout = aiohttp.ClientTimeout(total=15)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            for port in target_ports:
                target_url = f"http://127.0.0.1:{port}/oauth2callback?{query}"
                try:
                    async with session.get(target_url) as resp:
                        response_body = await resp.text()
                        if "Authentication Successful" in response_body or "successful" in response_body.lower() or resp.status == 200:
                            success = True
                            em_m = re.search(r'for user:\s*<strong>([^<]+)</strong>', response_body, re.IGNORECASE)
                            if em_m:
                                user_email = em_m.group(1).strip()
                            break
                        else:
                            err_m = re.search(r'<p>([^<]+)</p>', response_body)
                            if err_m:
                                error_detail = err_m.group(1).strip()
                except Exception as e:
                    error_detail = str(e)

        if success:
            acc_str = f" ({html.escape(user_email)})" if user_email else ""
            html_content = f"""<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Mulon — Google Workspace</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #FAF9F7; color: #1F1E1D; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; padding: 16px; box-sizing: border-box; }}
.card {{ background: #FFFFFF; border-radius: 20px; padding: 32px 24px; max-width: 420px; width: 100%; text-align: center; box-shadow: 0 8px 24px rgba(31,30,29,.08); border: 1px solid #E8E4DC; }}
h2 {{ color: #3E9B6C; margin-top: 0; margin-bottom: 12px; }}
p {{ line-height: 1.5; color: #6E6A61; margin-bottom: 24px; }}
.btn {{ display: inline-block; background: #5A5E94; color: #FFFFFF; padding: 12px 24px; border-radius: 12px; text-decoration: none; font-weight: 600; }}
</style>
</head>
<body>
<div class="card">
  <h2>🎉 Kết nối Google thành công!</h2>
  <p>Đã cấp quyền Google Workspace{acc_str} cho bot Mulon.<br>Ní có thể đóng trang này và quay lại Telegram làm việc tiếp rồi nha!</p>
  <a href="https://t.me" class="btn">Quay lại Telegram</a>
</div>
</body>
</html>"""
            return web.Response(text=html_content, content_type="text/html")
        else:
            fail_html = f"""<!doctype html>
<html lang="vi">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Mulon — Lỗi xác thực</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #FAF9F7; color: #1F1E1D; display: flex; align-items: center; justify-content: center; min-height: 100vh; margin: 0; padding: 16px; box-sizing: border-box; }}
.card {{ background: #FFFFFF; border-radius: 20px; padding: 32px 24px; max-width: 420px; width: 100%; text-align: center; box-shadow: 0 8px 24px rgba(31,30,29,.08); border: 1px solid #E8E4DC; }}
h2 {{ color: #D95F57; margin-top: 0; margin-bottom: 12px; }}
p {{ line-height: 1.5; color: #6E6A61; margin-bottom: 24px; }}
.err {{ background: #FAE7E4; padding: 10px; border-radius: 8px; font-family: monospace; font-size: 13px; color: #D95F57; word-break: break-all; margin-bottom: 20px; }}
.btn {{ display: inline-block; background: #5A5E94; color: #FFFFFF; padding: 12px 24px; border-radius: 12px; text-decoration: none; font-weight: 600; }}
</style>
</head>
<body>
<div class="card">
  <h2>⚠️ Chưa hoàn tất xác thực</h2>
  <div class="err">{html.escape(error_detail or "Không nhận được phản hồi từ MCP server")}</div>
  <p>Mã xác thực hoặc phiên có thể đã hết hạn. Hãy mở Telegram và gõ <code>/google_auth</code> để lấy link mới tinh nhé!</p>
  <a href="https://t.me" class="btn">Quay lại Telegram</a>
</div>
</body>
</html>"""
            return web.Response(text=fail_html, content_type="text/html", status=400)

    # ---------- 1.3.0: Chợ MCP ----------
    def _mkt_guard(self):
        """None nếu marketplace sẵn sàng; response 503 nếu chưa
        nối (giữ hành vi sạch như các dịch vụ tuỳ chọn khác)."""
        if self.marketplace is None:
            return web.json_response(
                {"ok": False, "code": "catalog_unavailable",
                 "error": "Marketplace chưa được nối trong bản "
                          "chạy này."}, status=503)
        return None

    def _mkt_error(self, exc):
        from .marketplace import MarketplaceError

        if isinstance(exc, MarketplaceError):
            status = 404 if exc.code in (
                "catalog_unavailable", "invalid_config") else 400
            if exc.code == "operation_conflict":
                status = 409
            return web.json_response(
                {"ok": False, "error": exc.message,
                 "code": exc.code}, status=status)
        logger.exception("marketplace API lỗi")
        return web.json_response(
            {"ok": False, "error": "lỗi nội bộ marketplace",
             "code": "probe_failed"}, status=500)

    def _idem_key(self, request) -> str:
        return str(request.headers.get("Idempotency-Key") or "")

    async def _mkt_summary(self, request):
        guard = self._mkt_guard()
        if guard is not None:
            return guard
        return web.json_response(
            {"ok": True, **self.marketplace.summary()})

    async def _mkt_categories(self, request):
        guard = self._mkt_guard()
        if guard is not None:
            return guard
        cats = await self.marketplace.get_categories()
        return web.json_response({"ok": True, **cats})

    async def _mkt_catalog(self, request):
        guard = self._mkt_guard()
        if guard is not None:
            return guard
        q = request.query
        page = int(q.get("page", "1") or 1)
        query = (q.get("query") or q.get("q") or "").strip()
        locality = (q.get("locality") or "").strip().lower()
        try:
            min_score = float(q.get("min_score") or 0)
        except (TypeError, ValueError):
            min_score = 0.0
        result = await self.marketplace.search_catalog_async(
            query=query, category=q.get("category", ""),
            pricing=q.get("pricing", ""),
            installed=q.get("installed", ""),
            locality=locality,
            min_score=min_score,
            cursor=q.get("cursor", ""),
            page=page,
            limit=int(q.get("limit", "20") or 20))
        return web.json_response({"ok": True, **result})

    async def _mkt_listing(self, request):
        guard = self._mkt_guard()
        if guard is not None:
            return guard
        try:
            detail = await self.marketplace.get_listing_detail(
                request.match_info["provider"],
                request.match_info["slug"])
        except Exception as exc:
            return self._mkt_error(exc)
        return web.json_response({"ok": True, "listing": detail})

    async def _mkt_installed(self, request):
        guard = self._mkt_guard()
        if guard is not None:
            return guard
        return web.json_response(
            {"ok": True, "items": self.marketplace.installed_list()})

    async def _mkt_installed_detail(self, request):
        guard = self._mkt_guard()
        if guard is not None:
            return guard
        try:
            view = self.marketplace.installed_detail(
                request.match_info["name"])
        except Exception as exc:
            return self._mkt_error(exc)
        return web.json_response({"ok": True, "installed": view})

    async def _mkt_operation(self, request):
        guard = self._mkt_guard()
        if guard is not None:
            return guard
        op = self.marketplace.store.get_operation(
            request.match_info["id"])
        if op is None:
            return web.json_response(
                {"ok": False, "error": "không tìm thấy operation",
                 "code": "invalid_config"}, status=404)
        return web.json_response(
            {"ok": True,
             "operation": self.marketplace.operation_view(op)})

    async def _mkt_refresh(self, request):
        guard = self._mkt_guard()
        if guard is not None:
            return guard
        result = await self.marketplace.refresh_catalog()
        return web.json_response({"ok": True, **result})

    async def _mkt_import_parse(self, request):
        guard = self._mkt_guard()
        if guard is not None:
            return guard
        body = await self._json_body(request)
        try:
            result = self.marketplace.parse_import(
                text=body.get("text"), url=body.get("url"),
                name=body.get("name"))
        except Exception as exc:
            return self._mkt_error(exc)
        if not result.get("ok"):
            return web.json_response(result, status=400)
        return web.json_response(result)

    async def _mkt_prepare(self, request):
        guard = self._mkt_guard()
        if guard is not None:
            return guard
        body = await self._json_body(request)
        source = {}
        if body.get("draft_id"):
            source = {"draft_id": str(body["draft_id"])}
        elif body.get("slug"):
            pid = str(body.get("provider_id") or "mulon-curated")
            source = {"provider_id": pid, "slug": str(body["slug"])}
            if pid == "mcp-marketplace":
                try:
                    detail = await self.marketplace.get_listing_detail(
                        pid, str(body["slug"]))
                    manifest = detail.get("manifest") or {}
                    cmd = body.get("custom_command") or manifest.get("command")
                    args = body.get("custom_args") if body.get("custom_args") is not None else (manifest.get("args") or [])
                    url = body.get("custom_url") or manifest.get("url")
                    transport = "http" if url and not cmd else (manifest.get("transport") or "stdio")
                    source["install"] = {
                        "transport": transport,
                        "command": cmd,
                        "args": args,
                        "url": url,
                        "env": manifest.get("public_env") or {},
                        "setup_requirements": manifest.get("setup_requirements") or [],
                    }
                    source["security"] = detail.get("security")
                    source["name"] = detail.get("name")
                    source["source_url"] = detail.get("source_url")
                    source["version"] = detail.get("version")
                except Exception as exc:
                    logger.warning("Không thể lấy install config cho %s: %s",
                                   body.get("slug"), exc)
        else:
            return web.json_response(
                {"ok": False, "code": "invalid_config",
                 "error": "thiếu slug hoặc draft_id"}, status=400)
        try:
            view = self.marketplace.prepare_install(
                source, alias=body.get("alias"),
                idempotency_key=self._idem_key(request))
            if body.get("auto_install") and view.get("stage") == "awaiting_probe_approval":
                import asyncio as _asyncio
                _asyncio.create_task(
                    self.marketplace.install_one_click(view["id"]))
        except Exception as exc:
            return self._mkt_error(exc)
        return web.json_response({"ok": True, "operation": view})

    async def _mkt_bind_secrets(self, request):
        guard = self._mkt_guard()
        if guard is not None:
            return guard
        body = await self._json_body(request)
        try:
            view = self.marketplace.bind_secrets(
                request.match_info["id"],
                body.get("bindings") or {})
        except Exception as exc:
            return self._mkt_error(exc)
        return web.json_response({"ok": True, "operation": view})

    async def _mkt_request_probe(self, request):
        guard = self._mkt_guard()
        if guard is not None:
            return guard
        try:
            result = self.marketplace.request_stage_approval(
                request.match_info["id"], "probe")
        except Exception as exc:
            return self._mkt_error(exc)
        return web.json_response({"ok": True, **result})

    async def _mkt_request_commit(self, request):
        guard = self._mkt_guard()
        if guard is not None:
            return guard
        try:
            result = self.marketplace.request_stage_approval(
                request.match_info["id"], "commit")
        except Exception as exc:
            return self._mkt_error(exc)
        return web.json_response({"ok": True, **result})

    async def _mkt_cancel(self, request):
        guard = self._mkt_guard()
        if guard is not None:
            return guard
        try:
            view = self.marketplace.cancel_operation(
                request.match_info["id"])
        except Exception as exc:
            return self._mkt_error(exc)
        return web.json_response({"ok": True, "operation": view})

    async def _mkt_health_check(self, request):
        guard = self._mkt_guard()
        if guard is not None:
            return guard
        try:
            result = await self.marketplace.run_health_check(
                request.match_info["name"])
        except Exception as exc:
            return self._mkt_error(exc)
        return web.json_response({"ok": True, **result})

    async def _mkt_enable(self, request):
        guard = self._mkt_guard()
        if guard is not None:
            return guard
        try:
            result = self.marketplace.enable(
                request.match_info["name"])
        except Exception as exc:
            return self._mkt_error(exc)
        return web.json_response({"ok": True, **result})

    async def _mkt_disable(self, request):
        guard = self._mkt_guard()
        if guard is not None:
            return guard
        try:
            result = self.marketplace.disable(
                request.match_info["name"])
        except Exception as exc:
            return self._mkt_error(exc)
        return web.json_response({"ok": True, **result})

    async def _mkt_update_check(self, request):
        guard = self._mkt_guard()
        if guard is not None:
            return guard
        try:
            result = self.marketplace.update_check(
                request.match_info["name"])
        except Exception as exc:
            return self._mkt_error(exc)
        return web.json_response({"ok": True, **result})

    async def _mkt_update_prepare(self, request):
        guard = self._mkt_guard()
        if guard is not None:
            return guard
        try:
            view = self.marketplace.prepare_update(
                request.match_info["name"],
                idempotency_key=self._idem_key(request))
        except Exception as exc:
            return self._mkt_error(exc)
        return web.json_response({"ok": True, "operation": view})

    async def _mkt_uninstall_prepare(self, request):
        guard = self._mkt_guard()
        if guard is not None:
            return guard
        body = await self._json_body(request)
        try:
            view = self.marketplace.prepare_uninstall(
                request.match_info["name"],
                delete_vault_refs=body.get("delete_vault_refs")
                or [],
                idempotency_key=self._idem_key(request))
        except Exception as exc:
            return self._mkt_error(exc)
        return web.json_response({"ok": True, "operation": view})

    async def _mkt_install_now(self, request):
        guard = self._mkt_guard()
        if guard is not None:
            return guard
        op_id = request.match_info["id"]
        try:
            res = await self.marketplace.install_one_click(op_id)
            return web.json_response({"ok": True, "operation": res})
        except Exception as exc:
            return self._mkt_error(exc)

    # ---------- 1.6.0: Library & Public Artifact Sharing ----------
    async def _handle_public_share(self, request):
        token = request.match_info.get("token", "")
        if self.library is None:
            return web.Response(
                text="Library service chưa được kích hoạt.", status=503)
        res = await self.library.get_item_by_token(token)
        if not res.get("ok"):
            err = html.escape(res.get("error", "Tài liệu không khả dụng."))
            html_body = f"""<!doctype html>
<html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Mulon Share · Lỗi</title>
<style>
body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f8fafc; color: #1e293b; max-width: 600px; margin: 80px auto; padding: 20px; text-align: center; }}
h2 {{ font-size: 20px; font-weight: 600; color: #1e293b; margin-bottom: 8px; }}
p {{ color: #64748b; font-size: 15px; }}
</style></head>
<body><h2>Liên kết không khả dụng</h2><p>{err}</p></body></html>"""
            return web.Response(text=html_body, content_type="text/html", status=404)

        item = res["item"]
        name = html.escape(str(item.get("name") or "Tài liệu"))
        kind = html.escape(str(item.get("kind") or "tài liệu"))
        content = str(res.get("content") or "")
        is_binary = res.get("is_binary", False)

        if is_binary:
            p = Path(item["path"])
            if p.is_file():
                return web.FileResponse(p)
            return web.Response(text="File không tồn tại", status=404)

        # Sửa 1.6.2: render markdown thật thay cho <pre> escaped.
        # File nhị phân vẫn trả FileResponse ở nhánh trên như cũ.
        rendered_content = _render_share_markdown(content)
        html_page = f"""<!doctype html>
<html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{name} · Mulon Artifact</title>
<style>
:root {{
  --bg: #ffffff; --fg: #0f172a; --muted: #64748b; --border: #e2e8f0;
  --card-bg: #f8fafc; --accent: #2563eb; --accent-hover: #1d4ed8;
  --code-bg: #1e293b; --code-fg: #f8fafc;
}}
@media (prefers-color-scheme: dark) {{
  :root {{
    --bg: #0b0f17; --fg: #f1f5f9; --muted: #94a3b8; --border: #1e293b;
    --card-bg: #131b2a; --accent: #3b82f6; --accent-hover: #60a5fa;
    --code-bg: #050811; --code-fg: #f1f5f9;
  }}
}}
body {{
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  background: var(--bg); color: var(--fg);
  max-width: 820px; margin: 0 auto; padding: 24px 16px 80px;
  line-height: 1.65;
}}
header {{
  display: flex; align-items: center; justify-content: space-between;
  border-bottom: 1px solid var(--border); padding-bottom: 16px; margin-bottom: 24px;
}}
.title-group {{ display: flex; flex-direction: column; gap: 4px; }}
h1 {{ font-size: 20px; font-weight: 700; margin: 0; }}
.meta {{ font-size: 13px; color: var(--muted); display: flex; gap: 10px; align-items: center; }}
.badge {{ background: var(--card-bg); border: 1px solid var(--border); padding: 2px 8px; border-radius: 999px; text-transform: uppercase; font-size: 11px; font-weight: 600; letter-spacing: 0.5px; }}
.actions {{ display: flex; gap: 8px; }}
button {{
  background: var(--card-bg); border: 1px solid var(--border); color: var(--fg);
  padding: 8px 14px; border-radius: 8px; font-size: 13px; font-weight: 500;
  cursor: pointer; transition: all 0.15s ease;
}}
button:hover {{ border-color: var(--accent); color: var(--accent); }}
pre {{
  background: var(--card-bg); border: 1px solid var(--border);
  padding: 20px; border-radius: 12px; overflow-x: auto;
  font-family: ui-monospace, SFMono-Regular, Menlo, Monaco, Consolas, monospace;
  font-size: 14px; line-height: 1.6; white-space: pre-wrap; word-break: break-word;
}}
/* Sửa 1.6.2: kiểu cho nội dung markdown đã render. */
#artifact-content h1 {{ font-size: 22px; }}
#artifact-content h2 {{ font-size: 19px; }}
#artifact-content h3 {{ font-size: 17px; }}
#artifact-content a {{ color: var(--accent); }}
#artifact-content a:hover {{ color: var(--accent-hover); }}
#artifact-content code:not(pre code) {{
  background: var(--card-bg); border: 1px solid var(--border);
  padding: 1px 5px; border-radius: 5px; font-size: 13px;
}}
#artifact-content blockquote {{
  border-left: 3px solid var(--border); margin: 16px 0;
  padding-left: 16px; color: var(--muted);
}}
footer {{ margin-top: 40px; text-align: center; font-size: 12px; color: var(--muted); }}
</style></head>
<body>
<header>
  <div class="title-group">
    <h1>{name}</h1>
    <div class="meta">
      <span class="badge">{kind}</span>
      <span>Được chia sẻ từ Mulon</span>
    </div>
  </div>
  <div class="actions">
    <button id="copy-btn" onclick="copyContent()">Sao chép</button>
  </div>
</header>
<main>
  <div id="artifact-content">{rendered_content}</div>
</main>
<footer>Mulon Personal Agent · Chia sẻ bảo mật</footer>
<script>
function copyContent() {{
  const txt = document.getElementById("artifact-content").innerText;
  navigator.clipboard.writeText(txt).then(() => {{
    const b = document.getElementById("copy-btn");
    b.innerText = "Đã sao chép!";
    setTimeout(() => b.innerText = "Sao chép", 2000);
  }});
}}
</script>
</body></html>"""
        return web.Response(text=html_page, content_type="text/html")

    async def _handle_library_items(self, request):
        if self.library is None:
            return web.json_response(
                {"ok": False, "error": "Library chưa được kết nối"}, status=503)
        status = str(request.query.get("status") or "active")
        if status not in ("active", "trashed"):
            status = "active"
        query = str(request.query.get("q") or request.query.get("query") or "").strip()
        kind = str(request.query.get("kind") or "").strip()
        if query:
            items = await self.library.search(query, kind=kind or None, status=status, limit=100)
        else:
            items = await self.library.list_items(status=status, limit=100)
            if kind and kind != "all":
                items = [it for it in items if (it.get("kind") or "other") == kind]
        for it in items:
            k = it.get("kind") or "other"
            it["kind_label"] = LIBRARY_KIND_LABELS.get(k, "Tệp khác")
            it["title"] = it.get("name") or it.get("title") or ""
        return web.json_response({"ok": True, "items": items})

    async def _handle_library_item_detail(self, request):
        """Chi tiết + Xem trước tài liệu trong Thư viện (T-23.3)."""
        if self.library is None:
            return web.json_response(
                {"ok": False, "error": "Library chưa được kết nối"}, status=503)
        try:
            item_id = int(request.match_info["id"])
        except (KeyError, ValueError):
            return web.json_response(
                {"ok": False, "error": "ID tài liệu không hợp lệ"}, status=400)
        item = await self.library.get_item(item_id)
        if item is None:
            return web.json_response(
                {"ok": False, "error": f"Không tìm thấy tài liệu #{item_id}"}, status=404)

        item_dict = dict(item)
        item_dict.pop("share_token", None)
        k = item_dict.get("kind") or "other"
        item_dict["kind_label"] = LIBRARY_KIND_LABELS.get(k, "Tệp khác")
        item_dict["title"] = item_dict.get("name") or ""

        raw_path = item_dict.get("trash_path") if item_dict.get("status") == "trashed" and item_dict.get("trash_path") else item_dict.get("path")
        p = Path(raw_path) if raw_path else None
        size_bytes = 0
        preview_text = ""
        media_url = ""

        if p is not None and p.is_file() and not _denied_reason(p):
            try:
                size_bytes = p.stat().st_size
            except Exception:
                size_bytes = 0

            ws = Path(self.cfg.workspace_dir).resolve()
            try:
                rel = p.resolve().relative_to(ws)
                media_url = "/media/" + rel.as_posix()
            except Exception:
                media_url = ""

            ext = p.suffix.lower()
            if k in ("document", "code") or ext in (".md", ".txt", ".csv", ".py", ".json", ".html", ".css", ".js", ".yaml", ".yml", ".log"):
                try:
                    preview_text = p.read_text(encoding="utf-8", errors="replace")[:12000]
                except Exception:
                    preview_text = ""

        item_dict["path"] = sanitize_path_display(str(item_dict.get("path") or ""))
        item_dict["size_bytes"] = size_bytes
        item_dict["preview_text"] = preview_text
        item_dict["media_url"] = media_url
        return web.json_response({"ok": True, "item": item_dict, **item_dict})

    async def _handle_library_delete(self, request):
        """Xoá hẳn tài liệu khỏi Thùng rác (T-23.3)."""
        if self.library is None:
            return web.json_response(
                {"ok": False, "error": "Library chưa được kết nối"}, status=503)
        try:
            item_id = int(request.match_info["id"])
        except (KeyError, ValueError):
            return web.json_response(
                {"ok": False, "error": "ID tài liệu không hợp lệ"}, status=400)
        item = await self.library.get_item(item_id)
        if item is None:
            return web.json_response(
                {"ok": False, "error": f"Không tìm thấy tài liệu #{item_id}"}, status=404)
        trash_p = item.get("trash_path") or ""
        if trash_p:
            tp = Path(trash_p)
            try:
                if tp.is_file() and tp.resolve().is_relative_to(self.library.trash_dir.resolve()):
                    tp.unlink()
            except Exception:
                pass
        if self.memory is not None:
            await self.memory.db.execute("DELETE FROM library_items WHERE id=?", (item_id,))
            await self.memory.db.commit()
            try:
                await self.memory.log_trajectory("webapp", "library_deleted_permanently", {"item_id": item_id})
            except Exception:
                pass
        return web.json_response({"ok": True, "item_id": item_id})

    async def _handle_library_search(self, request):
        if self.library is None:
            return web.json_response(
                {"ok": False, "error": "Library chưa được kết nối"}, status=503)
        query = str(request.query.get("q") or request.query.get("query") or "").strip()
        kind = str(request.query.get("kind") or "").strip()
        items = await self.library.search(query, kind=kind or None, status="active", limit=100)
        return web.json_response({"ok": True, "query": query, "items": items})

    async def _handle_library_pin(self, request):
        if self.library is None:
            return web.json_response(
                {"ok": False, "error": "Library chưa được kết nối"}, status=503)
        body = await self._json_body(request)
        item_id = int(request.match_info["id"])
        pinned = bool(body.get("pinned", True))
        res = await self.library.pin_item(item_id, pinned=pinned)
        return web.json_response(res)

    async def _handle_library_rename(self, request):
        if self.library is None:
            return web.json_response(
                {"ok": False, "error": "Library chưa được kết nối"}, status=503)
        body = await self._json_body(request)
        item_id = int(request.match_info["id"])
        # Sửa UI: frontend cũ gửi {title}, backend chỉ đọc {name}
        # nên đổi tên luôn fail. Chấp nhận cả hai, ưu tiên {name}.
        name = str(body.get("name") or body.get("title") or "").strip()
        res = await self.library.rename_item(item_id, name)
        return web.json_response(res)

    async def _handle_library_trash(self, request):
        if self.library is None:
            return web.json_response(
                {"ok": False, "error": "Library chưa được kết nối"}, status=503)
        item_id = int(request.match_info["id"])
        res = await self.library.trash_item(item_id)
        return web.json_response(res)

    async def _handle_library_restore(self, request):
        if self.library is None:
            return web.json_response(
                {"ok": False, "error": "Library chưa được kết nối"}, status=503)
        item_id = int(request.match_info["id"])
        res = await self.library.restore_item(item_id)
        return web.json_response(res)

    async def _handle_library_unshare(self, request):
        if self.library is None:
            return web.json_response(
                {"ok": False, "error": "Library chưa được kết nối"}, status=503)
        item_id = int(request.match_info["id"])
        res = await self.library.unshare_item(item_id)
        return web.json_response(res)

    async def _handle_library_share(self, request):
        if self.library is None:
            return web.json_response(
                {"ok": False, "error": "Library chưa được kết nối"}, status=503)
        body = await self._json_body(request)
        item_id = int(request.match_info["id"])
        hours = float(body.get("hours") or 48.0)
        base = self.cfg.webapp_url or f"{request.scheme}://{request.host}"
        res = await self.library.share_item(item_id, hours=hours, base_url=base)
        return web.json_response(res)
