"""ApprovalBroker — cầu nối duyệt việc giữa agent và bề mặt (1.2.0).

Khi policy trả nấc ``ask``, agent mở 1 yêu cầu duyệt ở broker rồi
chờ. Bề mặt (Telegram/Mini App) trình thẻ cho user; quyết định đi
vào qua ``resolve()`` từ bất kỳ đường nào (nút inline, Mini App
/api/approve). Hết hạn (mặc định 60s) coi như từ chối.

Nguyên tắc:
- Broker không biết gì về Telegram: bề mặt đăng ký listener
  ``on_decided`` để tự gỡ thẻ + ghi dòng lịch sử khi có kết quả.
- "Duyệt và nhớ" (remember) ghi rule lớp session của policy:
  tool đó -> allow cho tới hết phiên (lớp host vẫn thắng).
- Payload duyệt chỉ chứa tóm tắt args AN TOÀN (cắt ngắn, che giá
  trị ở các khóa nhạy cảm) — không bao giờ chứa secret.
- Mỗi yêu cầu mang thêm DÒNG PHẠM VI (``approval_scope`` — suy từ
  tool/nhóm thật + cơ chế nhớ ở trên, bề mặt chỉ việc trình bày)
  và LÝ DO tùy chọn của agent (``reason`` — lời agent tự giải
  thích khi mở thẻ; không có thì thẻ vẫn dựng bình thường).
"""

from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Awaitable, Callable, Optional

logger = logging.getLogger("mulon.approvals")

_SENSITIVE_KEY = re.compile(
    r"(secret|token|password|passwd|api[_-]?key|auth|credential|"
    r"private|cookie|session)", re.IGNORECASE)

Listener = Callable[[dict], Awaitable[None] | None]


def summarize_args(args: dict, max_value: int = 60,
                   max_total: int = 240) -> str:
    """Tóm tắt args để trình duyệt: tên khóa + preview ngắn.

    Khóa nhạy cảm (token/password/secret...) bị che hoàn toàn;
    giá trị dài bị cắt. Không dùng tóm tắt này cho việc gì khác
    ngoài hiển thị.
    """
    if not isinstance(args, dict) or not args:
        return "(không có tham số)"
    parts: list[str] = []
    for key, value in args.items():
        if _SENSITIVE_KEY.search(str(key)):
            parts.append(f"{key}=***")
            continue
        text = value if isinstance(value, str) else repr(value)
        text = " ".join(str(text).split())
        if len(text) > max_value:
            text = text[:max_value] + "…"
        parts.append(f"{key}={text}")
    out = "; ".join(parts)
    return out[:max_total] + ("…" if len(out) > max_total else "")


_TARGET_KEYS = ("path", "file", "filepath", "url", "command", "cmd",
                "query", "name", "destination", "dir", "cwd")


def summarize_target(args: dict, max_len: int = 80) -> str:
    """Đích/tài nguyên chính của việc cần duyệt (cho dòng "Đích"
    trên thẻ): giá trị của khóa salient đầu tiên, cắt ngắn; khóa
    nhạy cảm không bao giờ thành đích."""
    if not isinstance(args, dict):
        return ""
    for key in _TARGET_KEYS:
        if key in args and not _SENSITIVE_KEY.search(str(key)):
            text = " ".join(str(args[key]).split())
            if text:
                return text[:max_len] + ("…" if len(text) > max_len
                                         else "")
    return ""


# Nhãn danh từ của nhóm việc — dùng cho DÒNG PHẠM VI trên thẻ
# duyệt ("áp cho công cụ X thuộc nhóm ..."). Khớp khái niệm với
# GROUP_STEP_LABELS của webapp_server nhưng ở dạng danh từ.
GROUP_SCOPE_LABELS = {
    "shell": "chạy lệnh hệ thống",
    "file": "thao tác file",
    "web": "đọc web",
    "outbound": "gửi tin nhắn",
    "connector": "gọi dịch vụ ngoài",
    "media": "xử lý media",
    "agent": "giao việc cho agent con",
    "skills": "dùng kỹ năng",
    "memory": "tra ký ức",
    "schedule": "xử lý lịch hẹn",
    "system": "thông tin hệ thống",
    "goals": "quản lý mục tiêu",
}


def normalize_reason(text, max_len: int = 280) -> str:
    """Chuẩn hoá lý do agent đính kèm yêu cầu duyệt: gộp khoảng
    trắng/xuống dòng thành 1 dòng, cắt dài. Rỗng/không phải chuỗi
    -> "" (thẻ khi đó không có dòng lý do — không bịa thêm)."""
    if not isinstance(text, str):
        return ""
    out = " ".join(text.split())
    if len(out) > max_len:
        out = out[:max_len].rstrip() + "…"
    return out


def approval_scope(payload: dict) -> dict:
    """Dòng phạm vi của 1 yêu cầu duyệt, suy từ dữ liệu THẬT:
    "duyệt" luôn chỉ áp cho lần này; "duyệt và nhớ" ghi rule lớp
    SESSION cho đúng NHÓM đó (xem broker.wait) tới hết phiên
    — không áp cho nhóm khác. Sửa 1.6.1: trước đây nhớ theo
    CÔNG CỤ (vd connector_call), nên 1 lần nhớ cho gmail:send
    đã mở cửa cho mọi connector_call khác, kể cả gcalendar:delete_event.
    Từ nay phạm vi nhớ = group trong payload (vd connector:gmail:send);
    chỉ khi payload không có group mới rơi về nhớ theo tool."""
    payload = payload or {}
    tool = str(payload.get("tool") or "")
    group = str(payload.get("group") or "")
    label = GROUP_SCOPE_LABELS.get(group, "")
    if not label and ":" in group:
        # Nhóm có tiền tố (connector:gmail, mcp:filesystem):
        # nhãn của nhóm gốc + tên riêng trong ngoặc.
        head, _, tail = group.partition(":")
        head_label = GROUP_SCOPE_LABELS.get(head, "")
        if head_label:
            label = f"{head_label} ({tail})"
    if group and tool and tool != group:
        # Giữ cả nhãn đọc được, tên nhóm đầy đủ và tên công cụ gốc:
        # thẻ duyệt phải cho user thấy chính xác phạm vi sẽ được nhớ,
        # không chỉ nhãn chung chung (lỗi 1.6.1: nhãn thay mất tên gốc).
        base = f"nhóm {label}" if label else f"nhóm {group}"
        subject = f"{base} ({group}) — công cụ {tool}"
    elif group:
        subject = f"nhóm {label} ({group})" if label else f"nhóm {group}"
    elif tool:
        subject = f"công cụ {tool}"
    else:
        subject = "việc này"
    return {
        "once": "“Duyệt” chỉ áp cho lần này.",
        "remember": (
            f"“Duyệt và nhớ” áp cho {subject} tới hết phiên này"
            " — không áp cho công cụ hay nhóm khác."),
    }


class ApprovalBroker:
    def __init__(self, policy=None, timeout_s: float = 60.0):
        self.policy = policy
        self.timeout_s = float(timeout_s)
        self._pending: dict[str, dict] = {}
        self._recent: list[dict] = []
        self._listeners: list[Listener] = []

    # ---------- listener (bề mặt tự gỡ thẻ, ghi lịch sử) ----------
    def on_decided(self, fn: Listener) -> None:
        self._listeners.append(fn)

    async def _notify(self, record: dict) -> None:
        for fn in self._listeners:
            try:
                maybe = fn(record)
                if asyncio.iscoroutine(maybe):
                    await maybe
            except Exception as exc:  # listener hỏng không chặn việc
                logger.warning("listener duyệt lỗi (bỏ qua): %s", exc)

    # ---------- vòng đời 1 yêu cầu ----------
    def open(self, approval_id: str, payload: dict,
             ttl_s: Optional[float] = None) -> None:
        """Đăng ký yêu cầu đang chờ. Agent gọi TRƯỚC khi phát event
        để bề mặt kịp gắn thông tin thẻ (attach) khi event tới.
        ``reason`` (lý do agent tự giải thích, tùy chọn) được
        chuẩn hoá tại đây để mọi bề mặt thấy cùng một bản.
        ``ttl_s``: hạn chờ riêng cho yêu cầu này (1.3.0: operation
        của marketplace dùng TTL dài hơn thẻ gọi tool); None =
        dùng timeout mặc định của broker như trước."""
        if approval_id in self._pending:
            return
        loop = asyncio.get_event_loop()
        stored = dict(payload)
        stored["reason"] = normalize_reason(stored.get("reason"))
        self._pending[approval_id] = {
            "id": approval_id,
            "payload": stored,
            "future": loop.create_future(),
            "remember": False,
            "created_at": time.time(),
            "timeout_s": (float(ttl_s) if ttl_s else None),
            "card": None,
        }

    def attach(self, approval_id: str, card: dict) -> None:
        """Bề mặt gắn thông tin định tuyến thẻ (chat/message id)
        để listener gỡ đúng thẻ khi có quyết định."""
        entry = self._pending.get(approval_id)
        if entry is not None:
            entry["card"] = dict(card)

    def resolve(self, approval_id: str, approved: bool,
                remember: bool = False) -> bool:
        """Quyết định từ bất kỳ đường nào. False = không còn chờ
        (đã quyết/hết hạn/không tồn tại)."""
        entry = self._pending.get(approval_id)
        if entry is None or entry["future"].done():
            return False
        entry["remember"] = bool(remember)
        entry["future"].set_result(bool(approved))
        return True

    async def wait(self, approval_id: str) -> dict:
        """Chờ quyết định (hoặc hết hạn) và chốt hồ sơ.

        Trả record: {id, payload, approved, remember, outcome,
        card} — outcome thuộc {approved, denied, expired}.
        """
        entry = self._pending.get(approval_id)
        if entry is None:
            return {"id": approval_id, "approved": False,
                    "outcome": "missing", "payload": {}, "card": None,
                    "remember": False}
        try:
            approved = await asyncio.wait_for(
                asyncio.shield(entry["future"]),
                timeout=entry.get("timeout_s") or self.timeout_s)
            outcome = "approved" if approved else "denied"
        except asyncio.TimeoutError:
            approved = False
            outcome = "expired"
        self._pending.pop(approval_id, None)
        record = {
            "id": approval_id,
            "payload": entry["payload"],
            "approved": bool(approved),
            "remember": bool(entry.get("remember")),
            "outcome": outcome,
            "card": entry.get("card"),
            "created_at": entry["created_at"],
            "decided_at": time.time(),
        }
        if record["remember"] and approved and self.policy is not None:
            # Sửa 1.6.1: nhớ theo NHÓM (group) trước, không nhớ theo tool.
            # Nhớ theo tool "connector_call" đã từng mở cửa cho mọi
            # connector/action khác trong phiên, phá bảng quyền
            # action-level của 1.6.0. Chỉ khi không có group mới
            # rơi về nhớ theo tool (hành vi cũ, cho tool không nhóm).
            group = str(entry["payload"].get("group") or "")
            if group:
                self.policy.set_session_rule("group", group, "allow")
            else:
                tool = str(entry["payload"].get("tool") or "")
                if tool:
                    self.policy.set_session_rule("tool", tool, "allow")
        self._recent.insert(0, record)
        del self._recent[20:]
        await self._notify(record)
        return record

    # ---------- truy vấn cho bề mặt/API ----------
    def pending(self) -> list[dict]:
        out = []
        for e in self._pending.values():
            item = {"id": e["id"], **e["payload"],
                    "created_at": e["created_at"]}
            item.setdefault("reason", "")
            scope = approval_scope(item)
            item["scope_once"] = scope["once"]
            item["scope_remember"] = scope["remember"]
            out.append(item)
        return out

    def recent(self, limit: int = 10) -> list[dict]:
        out = []
        for r in self._recent[:limit]:
            out.append({
                "id": r["id"],
                "tool": r["payload"].get("tool", ""),
                "group": r["payload"].get("group", ""),
                "summary": r["payload"].get("summary", ""),
                "approved": r["approved"],
                "remember": r["remember"],
                "outcome": r["outcome"],
                "decided_at": r["decided_at"],
            })
        return out

    def is_pending(self, approval_id: str) -> bool:
        return approval_id in self._pending
