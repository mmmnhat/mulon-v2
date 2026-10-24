"""Bề mặt group (thiết kế mục 16.0, 16.8, 16.11, 16.13).

- Topic = tab: một supergroup forum, mỗi topic là một bề mặt
  (Chat chính / Feed / Ideas / Goals / Library / Lịch sử & Hệ
  thống). Map topic<->bề mặt lưu trong kv_state theo chat.
- Bot cần quyền admin để tạo + ghim topic; thiếu điều kiện nào thì
  báo rõ lý do đó, degrade sạch — không giả vờ đã setup.
- Các hàm định dạng + trình duyệt note + kế hoạch quên + export/
  import ký ức nằm ở đây dạng hàm thuần/dịch vụ để test không cần
  aiogram; telegram_bot.py chỉ là lớp vỏ mỏng gọi vào.
"""

from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .memory import fold_vi, now_iso

logger = logging.getLogger("mulon.surfaces")

# key, tên topic, mô tả ngắn cho tin mục lục, lệnh chính của bề mặt.
SURFACES: list[dict] = [
    {
        "key": "main", "title": "Chat chính",
        "blurb": "Nơi ra lệnh và trao đổi chính với agent. Mọi bề "
                 "mặt khác đều gọi được bằng lời thường ngay tại đây.",
        "commands": "/status · /new · /memory · /quyen",
    },
    {
        "key": "feed", "title": "Feed",
        "blurb": "Bài Feed do agent tự viết từ goals + ký ức của "
                 "user (không lấy tin ngoài). Reaction trên bài là "
                 "tín hiệu gu (taste) cho các bài sau.",
        "commands": "/feed_now · /feedbrief <nội dung>",
    },
    {
        "key": "ideas", "title": "Ideas",
        "blurb": "Thẻ ý tưởng agent đề xuất. Trả lời 'làm luôn' vào "
                 "một thẻ để biến nó thành goal + task; thẻ tự hết "
                 "hạn sau ~14 ngày.",
        "commands": "/ideas · /idea_do <id> · /idea_bo <id>",
    },
    {
        "key": "goals", "title": "Goals",
        "blurb": "Mục tiêu dài hạn (2 trạng thái: đang chạy / đã "
                 "hoàn thành) và các cam kết đang được theo dõi.",
        "commands": "hỏi bằng lời thường: 'goals đang chạy có gì?'",
    },
    {
        "key": "library", "title": "Library",
        "blurb": "Catalog mọi file agent đã tạo/lưu cho user. Xóa "
                 "là vào thùng rác 30 ngày, khôi phục được; chia sẻ "
                 "tối đa 48h và phải duyệt từng lần.",
        "commands": "/library · /trash_item <id> · "
                    "/restore_item <id> · /share_item <id>",
    },
    {
        "key": "history", "title": "Lịch sử & Hệ thống",
        "blurb": "Đề xuất chủ động đang chờ duyệt, lịch sử quyết "
                 "định quyền, trạng thái hệ thống và ký ức.",
        "commands": "/notes · /note_ok <id> · /note_bo <id> · "
                    "/approvals · /memory",
    },
]

SURFACE_KEYS = [s["key"] for s in SURFACES]


def index_text(surface: dict, all_surfaces: list[dict]) -> str:
    others = "\n".join(
        f"· {s['title']}" for s in all_surfaces
        if s["key"] != surface["key"])
    return (
        f"📌 {surface['title']}\n\n{surface['blurb']}\n\n"
        f"Lệnh chính: {surface['commands']}\n\n"
        f"Các phòng khác:\n{others}"
    )


class TopicManager:
    """Tạo/tra map topic<->bề mặt cho từng group forum."""

    @staticmethod
    def _kv_key(chat_id: int) -> str:
        return f"topics:{chat_id}"

    async def get_map(self, memory, chat_id: int) -> dict[str, int]:
        raw = await memory.kv_get(self._kv_key(chat_id))
        if not raw:
            return {}
        try:
            data = json.loads(raw)
            return {str(k): int(v) for k, v in data.items()}
        except Exception:
            return {}

    async def _save_map(self, memory, chat_id: int,
                        mapping: dict[str, int]) -> None:
        await memory.kv_set(
            self._kv_key(chat_id), json.dumps(mapping))

    def topic_for(self, mapping: dict[str, int],
                  surface: str) -> Optional[int]:
        tid = mapping.get(surface)
        return tid if tid else None

    async def setup(self, bot, memory, chat_id: int,
                    is_forum: bool) -> dict:
        """Tạo các topic còn thiếu + ghim mục lục. bot là duck-type
        có create_forum_topic / send_message / pin_chat_message /
        get_chat_member (aiogram Bot thật có đủ)."""
        result: dict = {"ok": False, "created": {}, "existing": {},
                        "pinned": [], "errors": [], "map": {}}
        if not is_forum:
            result["errors"].append(
                "Group này chưa bật Topics (forum) — vào cài đặt "
                "group bật Topics rồi chạy lại /setup_topics.")
            return result
        me_id = getattr(bot, "id", None)
        if me_id and hasattr(bot, "get_chat_member"):
            try:
                member = await bot.get_chat_member(chat_id, me_id)
                status = str(getattr(member, "status", ""))
                if status not in ("administrator", "creator"):
                    result["errors"].append(
                        "Bot chưa có quyền admin trong group này — "
                        "cần admin để tạo và ghim topic.")
                    return result
            except Exception as exc:
                logger.warning("check admin lỗi (đi tiếp): %s", exc)
        mapping = await self.get_map(memory, chat_id)
        for surface in SURFACES:
            key = surface["key"]
            if key in mapping:
                result["existing"][key] = mapping[key]
                continue
            if key == "main":
                # Topic General (thread 1) có sẵn trong mọi forum,
                # không tạo được bằng API.
                mapping[key] = 1
                result["created"][key] = 1
                continue
            try:
                topic = await bot.create_forum_topic(
                    chat_id, name=surface["title"])
                tid = int(topic.message_thread_id)
            except Exception as exc:
                result["errors"].append(
                    f"Không tạo được topic '{surface['title']}': "
                    f"{exc} (bot cần quyền admin/quản lý topic)")
                continue
            mapping[key] = tid
            result["created"][key] = tid
        # Ghim mục lục cho các topic mới tạo trong lần này.
        for key, tid in result["created"].items():
            surface = next(s for s in SURFACES if s["key"] == key)
            try:
                msg = await bot.send_message(
                    chat_id, index_text(surface, SURFACES),
                    message_thread_id=tid)
                await bot.pin_chat_message(chat_id, msg.message_id)
                result["pinned"].append(key)
            except Exception as exc:
                result["errors"].append(
                    f"Topic '{surface['title']}' đã tạo nhưng ghim "
                    f"mục lục lỗi: {exc}")
        await self._save_map(memory, chat_id, mapping)
        result["map"] = mapping
        result["ok"] = bool(mapping) and not (
            len(result["errors"]) > 0 and not result["created"]
            and not result["existing"])
        return result


def format_topics_result(result: dict) -> str:
    if not result["map"] and result["errors"]:
        return "Chưa setup được topic:\n- " + "\n- ".join(result["errors"])
    lines = ["Bản đồ topic của group này:"]
    by_key = {s["key"]: s for s in SURFACES}
    for key, tid in result["map"].items():
        title = by_key.get(key, {}).get("title", key)
        mark = " (vừa tạo)" if key in result.get("created", {}) else ""
        lines.append(f"- {title}: thread {tid}{mark}")
    for err in result.get("errors", []):
        lines.append(f"⚠️ {err}")
    return "\n".join(lines)


def format_topics_map(mapping: dict[str, int]) -> str:
    if not mapping:
        return ("Chưa có bản đồ topic cho group này. "
                "Chạy /setup_topics trong group forum trước.")
    by_key = {s["key"]: s for s in SURFACES}
    lines = ["Bản đồ topic hiện tại:"]
    for key, tid in mapping.items():
        lines.append(
            f"- {by_key.get(key, {}).get('title', key)}: thread {tid}")
    return "\n".join(lines)


# ----------------- chat phụ: topic tự do ngoài 6 tab cố định -----------------

SIDECHAT_MAX_TITLE_CHARS = 128


def sanitize_sidechat_title(raw_title: str) -> str:
    """Làm sạch tên topic: bỏ ký tự điều khiển/xuống dòng, gộp
    khoảng trắng và cắt đúng trần 128 ký tự của Telegram."""
    cleaned = "".join(
        " " if ord(ch) < 32 or ord(ch) == 127 else ch
        for ch in (raw_title or ""))
    return " ".join(cleaned.split())[:SIDECHAT_MAX_TITLE_CHARS].strip()


def default_sidechat_title(timezone_name: str = "Asia/Ho_Chi_Minh",
                           now: Optional[datetime] = None) -> str:
    if now is None:
        try:
            tz = ZoneInfo(timezone_name)
        except (ZoneInfoNotFoundError, ValueError):
            tz = timezone.utc
        now = datetime.now(tz)
    return f"Chat phụ {now:%H:%M %d/%m}"


def sidechat_opening_text(title: str) -> str:
    return (
        f"💬 {title}\n\n"
        "Đây là đoạn chat phụ: lịch sử hội thoại ở topic này tách "
        "riêng với các topic khác, còn ký ức dài hạn và hồ sơ vẫn "
        "dùng chung. Khi xong, gõ /dongchat để đóng chat phụ này."
    )


def format_sidechat_list(records: list[dict]) -> str:
    if not records:
        return "Chưa có chat phụ nào đang mở."
    lines = ["Chat phụ đang mở:"]
    for record in records:
        lines.append(
            f"- {record['title']} (thread {record['thread_id']})")
    return "\n".join(lines)


class SideChatRegistry:
    """Registry các topic phụ tự do của từng group forum.

    Lưu ở kv_state dưới key riêng ``sidechats:<chat_id>`` để không
    trộn với map 6 topic-tab cố định của TopicManager. Mỗi record
    chỉ gồm thread_id, title, status (open/closed), created_at.
    """

    @staticmethod
    def _kv_key(chat_id: int) -> str:
        return f"sidechats:{chat_id}"

    async def list_all(self, memory, chat_id: int,
                       status: Optional[str] = None) -> list[dict]:
        raw = await memory.kv_get(self._kv_key(chat_id))
        if not raw:
            return []
        try:
            data = json.loads(raw)
        except Exception:
            return []
        if not isinstance(data, list):
            return []
        records = []
        for item in data:
            if not isinstance(item, dict):
                continue
            try:
                record = {
                    "thread_id": int(item["thread_id"]),
                    "title": str(item.get("title") or ""),
                    "status": str(item.get("status") or "open"),
                    "created_at": str(item.get("created_at") or ""),
                }
            except (KeyError, TypeError, ValueError):
                continue
            if status is None or record["status"] == status:
                records.append(record)
        return records

    async def _save_all(self, memory, chat_id: int,
                        records: list[dict]) -> None:
        await memory.kv_set(
            self._kv_key(chat_id),
            json.dumps(records, ensure_ascii=False))

    async def get(self, memory, chat_id: int,
                  thread_id: int) -> Optional[dict]:
        for record in await self.list_all(memory, chat_id):
            if record["thread_id"] == int(thread_id):
                return record
        return None

    async def list_open(self, memory, chat_id: int) -> list[dict]:
        return await self.list_all(memory, chat_id, status="open")

    async def _upsert(self, memory, chat_id: int,
                      record: dict) -> dict:
        records = await self.list_all(memory, chat_id)
        for idx, old in enumerate(records):
            if old["thread_id"] == record["thread_id"]:
                records[idx] = record
                break
        else:
            records.append(record)
        await self._save_all(memory, chat_id, records)
        return record

    async def set_status(self, memory, chat_id: int, thread_id: int,
                         status: str) -> Optional[dict]:
        records = await self.list_all(memory, chat_id)
        updated = None
        for record in records:
            if record["thread_id"] == int(thread_id):
                record["status"] = status
                updated = record
                break
        if updated is None:
            return None
        await self._save_all(memory, chat_id, records)
        return updated

    async def create(self, bot, memory, chat_id: int, raw_title: str,
                     is_forum: bool,
                     timezone_name: str = "Asia/Ho_Chi_Minh") -> dict:
        """Tạo topic phụ + gửi tin mở đầu; chỉ ghi registry khi
        cả hai bước Telegram đều thành công."""
        result: dict = {"ok": False, "record": None, "error": ""}
        if bot is None:
            result["error"] = "Bot chưa sẵn sàng để tạo chat phụ."
            return result
        if not is_forum:
            result["error"] = (
                "Chat phụ chỉ tạo được trong group đã bật Topics "
                "(forum). Group này chưa bật Topics.")
            return result

        me_id = getattr(bot, "id", None)
        if me_id and hasattr(bot, "get_chat_member"):
            try:
                member = await bot.get_chat_member(chat_id, me_id)
                status = str(getattr(member, "status", ""))
                if status not in ("administrator", "creator"):
                    result["error"] = (
                        "Bot chưa có quyền admin/quản lý topic "
                        "trong group này nên chưa tạo được chat phụ.")
                    return result
            except Exception as exc:
                logger.warning("check admin chat phụ lỗi (đi tiếp): %s",
                               exc)

        title = sanitize_sidechat_title(raw_title) \
            or default_sidechat_title(timezone_name)
        try:
            topic = await bot.create_forum_topic(chat_id, name=title)
            thread_id = int(topic.message_thread_id)
        except Exception as exc:
            result["error"] = (
                f"Không tạo được chat phụ: {exc} "
                "(bot cần quyền admin/quản lý topic).")
            return result

        opening = sidechat_opening_text(title)
        try:
            await bot.send_message(
                chat_id, opening, message_thread_id=thread_id)
        except Exception as exc:
            # Topic đã sinh nhưng chưa có tin mở đầu/registry thì là
            # trạng thái nửa vời: đóng lại ngay để dọn sạch.
            try:
                await bot.close_forum_topic(
                    chat_id, message_thread_id=thread_id)
            except Exception as close_exc:
                logger.warning(
                    "đóng topic phụ sau lỗi gửi tin mở đầu lỗi: %s",
                    close_exc)
            result["error"] = (
                f"Đã tạo topic nhưng không gửi được tin mở đầu: {exc}")
            return result

        record = {
            "thread_id": thread_id,
            "title": title,
            "status": "open",
            "created_at": now_iso(),
        }
        await self._upsert(memory, chat_id, record)
        result.update({"ok": True, "record": record})
        return result

    async def _change_status(self, bot, memory, chat_id: int,
                             thread_id: int,
                             target_status: str) -> dict:
        record = await self.get(memory, chat_id, thread_id)
        if record is None:
            return {
                "ok": False, "record": None,
                "error": (
                    f"Không thấy chat phụ với thread id {thread_id} "
                    "trong group này."),
            }
        if record["status"] == target_status:
            state = "đóng" if target_status == "closed" else "mở"
            return {
                "ok": False, "record": record,
                "error": f"Chat phụ '{record['title']}' đã {state} rồi.",
            }
        if bot is None:
            return {
                "ok": False, "record": record,
                "error": "Bot chưa sẵn sàng để đổi trạng thái chat phụ.",
            }
        try:
            if target_status == "closed":
                await bot.close_forum_topic(
                    chat_id, message_thread_id=int(thread_id))
            else:
                await bot.reopen_forum_topic(
                    chat_id, message_thread_id=int(thread_id))
        except Exception as exc:
            action = "đóng" if target_status == "closed" else "mở lại"
            return {
                "ok": False, "record": record,
                "error": f"Không {action} được chat phụ: {exc}",
            }
        updated = await self.set_status(
            memory, chat_id, thread_id, target_status)
        return {"ok": True, "record": updated, "error": ""}

    async def close_by_id(self, bot, memory, chat_id: int,
                          thread_id: int) -> dict:
        return await self._change_status(
            bot, memory, chat_id, thread_id, "closed")

    async def reopen_by_id(self, bot, memory, chat_id: int,
                           thread_id: int) -> dict:
        return await self._change_status(
            bot, memory, chat_id, thread_id, "open")

    async def close_current(self, bot, memory, topics, chat_id: int,
                            current_thread_id: Optional[int]) -> dict:
        thread_id = int(current_thread_id or 0)
        if thread_id in (0, 1):
            return {
                "ok": False, "record": None,
                "error": (
                    "Bạn đang ở Chat chính (General), không phải "
                    "chat phụ, nên mình không đóng ở đây."),
            }
        if topics is not None:
            mapping = await topics.get_map(memory, chat_id)
            if thread_id in mapping.values():
                return {
                    "ok": False, "record": None,
                    "error": (
                        "Đây là topic cố định của group, không phải "
                        "chat phụ, nên mình không đóng nhầm."),
                }
        record = await self.get(memory, chat_id, thread_id)
        if record is None:
            return {
                "ok": False, "record": None,
                "error": (
                    "Topic hiện tại không phải chat phụ đã đăng ký, "
                    "nên mình không đóng."),
            }
        return await self._change_status(
            bot, memory, chat_id, thread_id, "closed")


# ----------------- trình duyệt proactive notes -----------------

_ID_RE = re.compile(r"#(\d+)")


def parse_note_action(text: str,
                      replied_text: Optional[str] = None
                      ) -> Optional[tuple[str, int]]:
    """'duyệt'/'bỏ' (+ id trong text hoặc trong tin được reply)
    -> (status, note_id). Không đủ thông tin -> None (đừng đoán)."""
    folded = fold_vi((text or "").strip())
    action: Optional[str] = None
    if folded.startswith("duyet") or folded.startswith("duyệt"):
        action = "sent"  # 'duyệt' = chấp nhận cho gửi đi
    elif folded.startswith("bo ") or folded == "bo" \
            or folded.startswith("bỏ"):
        action = "dismissed"
    if action is None:
        return None
    m = _ID_RE.search(text or "") or _ID_RE.search(replied_text or "")
    if not m:
        return None
    return action, int(m.group(1))


def format_notes_list(notes: list[dict]) -> str:
    if not notes:
        return "Không có đề xuất chủ động nào đang chờ."
    lines = ["Đề xuất chủ động đang chờ duyệt:"]
    for n in notes:
        why = f" — {n['reason']}" if n.get("reason") else ""
        lines.append(f"- #{n['id']}: {n['content']}{why}")
    lines.append(
        "\nDuyệt: /note_ok <id> · Bỏ: /note_bo <id> "
        "(hoặc reply 'duyệt'/'bỏ' vào danh sách này kèm số #id)")
    return "\n".join(lines)


# ----------------- quyền bằng lời thường (mục 16.13) -----------------

def summarize_policy(policy) -> str:
    """Tóm tắt policy 2 lớp thành tiếng Việt dễ hiểu."""
    host = getattr(policy, "host", {}) or {}
    default = str(host.get("default") or "allow").lower()
    lines = ["Quyền hiện tại (đọc từ policy của máy):"]
    if default in {"deny", "block"}:
        lines.append("- Mặc định: KHÔNG tự làm — mọi tool bị chặn "
                     "hẳn.")
    elif default in {"ask", "prompt", "confirm"}:
        lines.append("- Mặc định: phải hỏi trước — tool nào cũng "
                     "qua thẻ duyệt, mọi quyết định vẫn ghi vào "
                     "lịch sử duyệt (/approvals).")
    else:
        lines.append("- Mặc định: full-auto — agent tự làm trong "
                     "phạm vi đã cấp, mọi quyết định vẫn ghi vào "
                     "lịch sử duyệt (/approvals).")
    def _verdict_text(v: str) -> str:
        if v in {"ask", "prompt", "confirm"}:
            return "phải hỏi trước khi làm (hiện thẻ duyệt)."
        if v in {"deny", "block"}:
            return ("bị chặn — không tự làm được (muốn làm phải "
                    "hỏi và sửa policy).")
        return "được tự làm."

    tools = host.get("tools") or {}
    for name, verdict in sorted(tools.items()):
        lines.append(
            f"- Tool {name}: " + _verdict_text(str(verdict).lower()))
    groups = host.get("groups") or {}
    for name, verdict in sorted(groups.items()):
        lines.append(
            f"- Nhóm {name}: " + _verdict_text(str(verdict).lower()))
    s_tools = getattr(policy, "session_tools", {}) or {}
    s_groups = getattr(policy, "session_groups", {}) or {}
    if s_tools or s_groups:
        lines.append("- Có override tạm trong phiên hiện tại: "
                     + ", ".join(sorted({**s_tools, **s_groups})))
    lines.append(
        "Muốn siết/nới: mở /menu -> Cài đặt -> Quyền (đổi tại "
        "chỗ, chọn lưu bền để ghi vào file policy.json — lớp "
        "host luôn thắng phiên).")
    return "\n".join(lines)


def format_approvals(rows: list[dict]) -> str:
    """Lịch sử quyết định — DUY-1: hàng từ thẻ duyệt (kind
    approval_decision, có `outcome`) phải dịch theo outcome:
    việc user ĐÃ DUYỆT qua nấc ask không được hiện thành CHẶN
    chỉ vì policy.check ban đầu ghi allowed=False."""
    if not rows:
        return "Chưa có quyết định quyền nào được ghi."
    lines = ["Lịch sử duyệt gần nhất:"]
    for r in rows:
        p = r.get("payload") or {}
        outcome = p.get("outcome")
        if outcome == "approved":
            verdict = "CHO (đã duyệt qua thẻ)"
        elif outcome == "denied":
            verdict = "CHẶN (user từ chối qua thẻ)"
        elif outcome == "expired":
            verdict = "HẾT HẠN (thẻ duyệt không ai bấm)"
        elif outcome:
            verdict = str(outcome).upper()
        else:
            verdict = "CHO" if p.get("allowed") else "CHẶN"
        lines.append(
            f"- {r.get('created_at', '')} · {verdict} tool "
            f"{p.get('tool', '?')} (nhóm {p.get('group', '') or '—'}, "
            f"lớp {p.get('layer', '?')})")
    return "\n".join(lines)


# ----------------- bộ nhớ có bề mặt: quên / export / import -----------------

async def build_forget_plan(memory, dossier_dir, topic: str) -> dict:
    """Kế hoạch quên: fact + lesson + dòng dossier liên quan.
    Chỉ LIỆT KÊ — thực thi chờ user xác nhận 'quên thật'."""
    facts = await memory.search_facts(topic, limit=100)
    lessons = [f for f in facts
               if str(f.get("subject") or "").startswith("lesson:")]
    plain = [f for f in facts if f not in lessons]
    needle = fold_vi(topic)
    dossier_lines: list[dict] = []
    base = Path(dossier_dir)
    if base.exists():
        for path in sorted(base.glob("*.md")):
            for i, line in enumerate(
                    path.read_text(encoding="utf-8").splitlines(), 1):
                if needle and needle in fold_vi(line):
                    dossier_lines.append({
                        "file": path.name, "line_no": i,
                        "text": line.strip()[:200]})
    return {
        "topic": topic,
        "facts": [{"id": f["id"], "fact": f["fact"]} for f in plain],
        "lessons": [{"id": f["id"], "fact": f["fact"]} for f in lessons],
        "dossier_lines": dossier_lines,
        "created_at": now_iso(),
    }


def format_forget_plan(plan: dict) -> str:
    lines = [f"Kế hoạch quên chủ đề: {plan['topic']}"]
    if plan["facts"]:
        lines.append("Fact sẽ bị vô hiệu:")
        lines += [f"- #{f['id']}: {f['fact']}" for f in plan["facts"]]
    if plan["lessons"]:
        lines.append("Bài học (lesson) sẽ bị tắt:")
        lines += [f"- #{f['id']}: {f['fact']}" for f in plan["lessons"]]
    if plan["dossier_lines"]:
        lines.append("Dòng dossier sẽ bị gỡ:")
        lines += [f"- {d['file']}:{d['line_no']}: {d['text']}"
                  for d in plan["dossier_lines"][:20]]
    if not (plan["facts"] or plan["lessons"] or plan["dossier_lines"]):
        lines.append("(không tìm thấy gì liên quan — không có gì "
                     "để quên)")
        return "\n".join(lines)
    lines.append(
        "\nVô hiệu = fact đóng vòng đời (vẫn truy được dấu vết kiểm "
        "toán), lesson tắt, dòng dossier bị gỡ khỏi file. "
        "Trả lời đúng câu 'quên thật' để thực thi.")
    return "\n".join(lines)


async def execute_forget_plan(memory, dossier_dir, plan: dict,
                              session_key: str = "") -> dict:
    """Thực thi kế hoạch quên sau khi user xác nhận. Mọi bước ghi
    ledger + trajectory — quên có kiểm chứng, không xóa dấu vết."""
    ids = [f["id"] for f in plan.get("facts", [])] \
        + [f["id"] for f in plan.get("lessons", [])]
    n_facts = await memory.forget_facts(ids) if ids else 0
    removed_lines = 0
    base = Path(dossier_dir)
    by_file: dict[str, set[int]] = {}
    for d in plan.get("dossier_lines", []):
        by_file.setdefault(d["file"], set()).add(int(d["line_no"]))
    for name, line_nos in by_file.items():
        path = base / name
        if not path.exists():
            continue
        lines = path.read_text(encoding="utf-8").splitlines()
        kept = [ln for i, ln in enumerate(lines, 1)
                if i not in line_nos]
        removed_lines += len(lines) - len(kept)
        path.write_text("\n".join(kept) + ("\n" if kept else ""),
                        encoding="utf-8")
    summary = {
        "topic": plan.get("topic", ""),
        "fact_ids": ids,
        "facts_forgotten": n_facts,
        "dossier_lines_removed": removed_lines,
    }
    await memory.append_ledger(
        "memory", "forget", json.dumps(summary, ensure_ascii=False),
        detail=f"user xác nhận quên chủ đề '{plan.get('topic', '')}'")
    await memory.log_trajectory(session_key, "memory_forget", summary)
    return summary


async def export_memory_text(memory, dossier_files: dict) -> str:
    """Toàn bộ ký ức xuất ra 1 file Markdown: dossier + mọi fact
    (đang hiệu lực trước, đã đóng vòng đời sau, kèm nguồn)."""
    parts = ["# Mulon — bản xuất ký ức",
             f"Xuất lúc: {now_iso()}", ""]
    for name in sorted(dossier_files):
        text = (dossier_files.get(name) or "").strip()
        if text:
            parts += [f"## Dossier — {name}", "", text, ""]
    active = await memory.active_facts(limit=1000)
    parts.append("## Fact đang hiệu lực")
    if not active:
        parts.append("(chưa có)")
    for f in active:
        src = f.get("source") or "—"
        parts.append(
            f"- #{f['id']} [{f.get('subject', '')}] {f['fact']} "
            f"(nguồn: {src}, từ {f.get('valid_from', '')})")
    parts.append("")
    cur = await memory.db.execute(
        "SELECT * FROM memory_facts WHERE valid_to IS NOT NULL"
        " ORDER BY id DESC LIMIT 1000")
    closed = [dict(r) for r in await cur.fetchall()]
    parts.append("## Fact đã đóng vòng đời (bị thay thế / đã quên)")
    if not closed:
        parts.append("(chưa có)")
    for f in closed:
        parts.append(
            f"- #{f['id']} [{f.get('subject', '')}] {f['fact']} "
            f"(đóng lúc {f.get('valid_to', '')})")
    parts.append("")
    return "\n".join(parts)


def parse_import_content(text: str, filename: str = "") -> list[dict]:
    """Parse file import (.json / .md / .txt) thành [{subject, fact}]
    — phòng thủ: sai định dạng thì trả rỗng, không ném lỗi."""
    name = (filename or "").lower()
    if name.endswith(".json"):
        try:
            data = json.loads(text)
        except Exception:
            return []
        items = data.get("facts") if isinstance(data, dict) else data
        if not isinstance(items, list):
            return []
        out = []
        for it in items:
            if isinstance(it, str) and it.strip():
                out.append({"subject": "", "fact": it.strip()})
            elif isinstance(it, dict) and str(it.get("fact") or "").strip():
                out.append({
                    "subject": str(it.get("subject") or ""),
                    "fact": str(it["fact"]).strip(),
                })
        return out
    out = []
    subject = ""
    for raw in (text or "").splitlines():
        line = raw.strip()
        if not line:
            continue
        if line.startswith("#"):
            subject = line.lstrip("# ").strip()[:80]
            continue
        fact = line.lstrip("-* ").strip()
        # Gỡ hậu tố nguồn kiểu "(nguồn: x, từ y)" của file export.
        fact = re.sub(r"\s*\(nguồn:.*\)\s*$", "", fact)
        if len(fact) >= 4:
            out.append({"subject": subject, "fact": fact})
    return out
