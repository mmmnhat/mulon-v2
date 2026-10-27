"""Policy engine 2 lớp (thiết kế mục 6, mượn cấu trúc OpenClaw).

- Lớp host: file JSON chính sách trên máy (POLICY_PATH). Lớp này THẮNG
  mọi cấu hình trong phiên — prompt/session không tự nới được.
- Lớp session: override tạm trong phiên (đặt qua code/Mini App,
  không qua prompt).
- Mặc định theo lệnh user: full-auto (allow) trong phạm vi đã cấp.
  Policy tồn tại để user siết lại khi muốn và để mọi quyết định đều
  được ghi trajectory truy vết — không phải cổng chặn mặc định.

Từ 1.2.0 verdict có 3 nấc: ``allow`` (tự làm), ``ask`` (hỏi trước
qua thẻ duyệt — ApprovalBroker), ``deny`` (chặn hẳn). File cũ chỉ
allow/deny vẫn chạy nguyên: mọi giá trị không thuộc nhóm deny/ask
đều hiểu là allow như trước.

Định dạng file host:
    {"default": "allow"|"ask"|"deny",
     "tools":  {"run_command": "ask", ...},
     "groups": {"shell": "deny", ...}}
Thứ tự phân giải: host(tool) > host(group) > host(default)
                > session(tool) > session(group) > mặc định "allow".
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

VERDICT_ALLOW = "allow"
VERDICT_ASK = "ask"
VERDICT_DENY = "deny"

_DENY_WORDS = {"deny", "block", "false", "0", "no"}
_ASK_WORDS = {"ask", "prompt", "confirm"}

# Mặc định theo hành động (1.6.0): đọc = Cho phép (allow), ghi/xoá = Hỏi (ask)
# PHẠM VI (sửa 1.6.1, ghi rõ để khỏi hiểu lầm): bảng này chỉ đúng cho
# đúng 6 action gmail/gcalendar liệt kê dưới đây. Action chưa liệt kê,
# call thiếu action, và mọi connector khác ngoài Google vẫn rơi về
# builtin allow theo triết lý full-auto của user — đó là thiết kế có
# chủ ý, không phải "quyền từng hành động cho mọi connector".
# Sửa 1.6.2: ngoại lệ duy nhất cho Google — action gmail/gcalendar
# CHƯA liệt kê (kể cả call thiếu action) thì rơi về ASK, không rơi
# về builtin allow nữa (xem cuối decide()). Connector khác và tool
# khác vẫn giữ nguyên builtin allow theo ý user.
CONNECTOR_ACTION_DEFAULTS = {
    # Gmail
    "connector:gmail:search": VERDICT_ALLOW,
    "connector:gmail:read": VERDICT_ALLOW,
    "connector:gmail:send": VERDICT_ASK,
    # Google Calendar
    "connector:gcalendar:list_events": VERDICT_ALLOW,
    "connector:gcalendar:list": VERDICT_ALLOW,
    "connector:gcalendar:create_event": VERDICT_ASK,
    "connector:gcalendar:create": VERDICT_ASK,
    "connector:gcalendar:delete_event": VERDICT_ASK,
    "connector:gcalendar:delete": VERDICT_ASK,
    # 1.7.8 (T-22.1): Zalo cá nhân
    "connector:zalo_personal:read_messages": VERDICT_ALLOW,
    "connector:zalo_personal:get_messages": VERDICT_ALLOW,
    "connector:zalo_personal:find_user": VERDICT_ALLOW,
    "connector:zalo_personal:listen": VERDICT_ALLOW,
    "connector:zalo_personal:send_message": VERDICT_ASK,
    "connector:zalo_personal:send_file": VERDICT_ASK,
    # 1.7.8 (T-22.1): Telegram cá nhân (MTProto userbot)
    "connector:telegram_personal:read_messages": VERDICT_ALLOW,
    "connector:telegram_personal:get_messages": VERDICT_ALLOW,
    "connector:telegram_personal:list_dialogs": VERDICT_ALLOW,
    "connector:telegram_personal:find_dialog": VERDICT_ALLOW,
    "connector:telegram_personal:listen": VERDICT_ALLOW,
    "connector:telegram_personal:send_message": VERDICT_ASK,
    "connector:telegram_personal:send_file": VERDICT_ASK,
    # 1.7.9 (T-22.2): Facebook cá nhân
    "connector:facebook_personal:get_profile": VERDICT_ALLOW,
    "connector:facebook_personal:get_friends": VERDICT_ALLOW,
    "connector:facebook_personal:read_feed": VERDICT_ALLOW,
    "connector:facebook_personal:read_messages": VERDICT_ALLOW,
    "connector:facebook_personal:get_messages": VERDICT_ALLOW,
    "connector:facebook_personal:check_session": VERDICT_ALLOW,
    "connector:facebook_personal:send_message": VERDICT_ASK,
    "connector:facebook_personal:send_post": VERDICT_ASK,
    "connector:facebook_personal:delete_post": VERDICT_ASK,
    # 1.7.10 (T-22.3): Tin nhắn Instagram (Direct Messages)
    "connector:instagram_messages:read_inbox": VERDICT_ALLOW,
    "connector:instagram_messages:get_inbox": VERDICT_ALLOW,
    "connector:instagram_messages:read_messages": VERDICT_ALLOW,
    "connector:instagram_messages:get_messages": VERDICT_ALLOW,
    "connector:instagram_messages:search_messages": VERDICT_ALLOW,
    "connector:instagram_messages:check_session": VERDICT_ALLOW,
    "connector:instagram_messages:send_message": VERDICT_ASK,
    "connector:instagram_messages:send_file": VERDICT_ASK,
    "connector:instagram_messages:send_reaction": VERDICT_ASK,
    "connector:instagram_messages:react": VERDICT_ASK,
    # 1.7.10 (T-22.3): Tin nhắn Threads (Direct Messages)
    "connector:threads_messages:read_inbox": VERDICT_ALLOW,
    "connector:threads_messages:get_inbox": VERDICT_ALLOW,
    "connector:threads_messages:read_messages": VERDICT_ALLOW,
    "connector:threads_messages:get_messages": VERDICT_ALLOW,
    "connector:threads_messages:check_session": VERDICT_ALLOW,
    "connector:threads_messages:send_message": VERDICT_ASK,
    "connector:threads_messages:send_reaction": VERDICT_ASK,
    "connector:threads_messages:react": VERDICT_ASK,
}

# Mặc định theo tên tool (sửa 1.6.2): tool tương tác web LUÔN ở
# nấc ask trừ khi host/session đã đặt rule rõ ràng (rule đó thắng,
# vì các lớp host/session được xét trước bảng này).
TOOL_DEFAULTS = {
    "web_click": VERDICT_ASK,
    "web_fill": VERDICT_ASK,
}

# Fallback có điều kiện cho mọi connector (sửa 1.6.2, gộp sau
# fail-closed Google): chỉ áp khi group dạng "connector:<tên>:<action>"
# mà action KHÔNG có trong CONNECTOR_ACTION_DEFAULTS (bảng đó thắng
# fallback này) và KHÔNG phải gmail/gcalendar (fail-closed Google ở
# decide() đã hỏi trước cho mọi action Google chưa liệt kê, kể cả
# token đọc — đặt fallback sau fail-closed để không mở lại cửa đó).
# So theo token đầu của action (vd "list_events" -> "list"):
# nhóm ghi/xoá -> ask, nhóm đọc -> allow. Token khác, group chỉ có
# "connector:<tên>" (call thiếu action), và mọi tool không phải
# connector vẫn rơi về builtin allow như cũ — KHÔNG đổi.
_CONNECTOR_WRITE_TOKENS = {
    "send", "create", "delete", "update", "remove", "trash", "edit",
    "write",
}
_CONNECTOR_READ_TOKENS = {"search", "read", "list", "get", "view", "find"}


def connector_fallback_verdict(group: str) -> Optional[str]:
    """Verdict fallback cho group connector chưa liệt kê.

    Trả None khi không áp được (không phải group connector 3 cấp,
    hoặc token đầu không thuộc 2 nhóm trên) để caller rơi tiếp về
    builtin như cũ.
    """
    parts = (group or "").split(":")
    if len(parts) != 3 or parts[0] != "connector":
        return None
    token = parts[2].strip().lower().split("_", 1)[0]
    if token in _CONNECTOR_WRITE_TOKENS:
        return VERDICT_ASK
    if token in _CONNECTOR_READ_TOKENS:
        return VERDICT_ALLOW
    return None

CONNECTOR_SPECS = {
    "gmail": {
        "title": "Gmail",
        "actions": [
            {"id": "search", "name": "connector:gmail:search",
             "label": "Tìm kiếm thư", "kind": "read", "default": VERDICT_ALLOW},
            {"id": "read", "name": "connector:gmail:read",
             "label": "Đọc thư", "kind": "read", "default": VERDICT_ALLOW},
            {"id": "send", "name": "connector:gmail:send",
             "label": "Gửi thư", "kind": "write", "default": VERDICT_ASK},
        ],
    },
    "gcalendar": {
        "title": "Google Calendar",
        "actions": [
            {"id": "list_events", "alias": "list",
             "name": "connector:gcalendar:list_events",
             "label": "Xem sự kiện", "kind": "read", "default": VERDICT_ALLOW},
            {"id": "create_event", "alias": "create",
             "name": "connector:gcalendar:create_event",
             "label": "Tạo sự kiện", "kind": "write", "default": VERDICT_ASK},
            {"id": "delete_event", "alias": "delete",
             "name": "connector:gcalendar:delete_event",
             "label": "Xoá sự kiện", "kind": "delete", "default": VERDICT_ASK},
        ],
    },
    "zalo_personal": {
        "title": "Zalo cá nhân",
        "description": "Kết nối tài khoản Zalo cá nhân qua mã QR (thư viện zca-js). Đọc/gửi tin nhắn, gửi file, tìm người dùng. Không hỗ trợ đăng nhật ký/bài viết.",
        "actions": [
            {"id": "read_messages", "name": "connector:zalo_personal:read_messages",
             "label": "Đọc tin nhắn Zalo", "kind": "read", "default": VERDICT_ALLOW},
            {"id": "find_user", "name": "connector:zalo_personal:find_user",
             "label": "Tìm người dùng theo SĐT", "kind": "read", "default": VERDICT_ALLOW},
            {"id": "send_message", "name": "connector:zalo_personal:send_message",
             "label": "Gửi tin nhắn Zalo", "kind": "write", "default": VERDICT_ASK},
            {"id": "send_file", "name": "connector:zalo_personal:send_file",
             "label": "Gửi tệp Zalo", "kind": "write", "default": VERDICT_ASK},
        ],
    },
    "telegram_personal": {
        "title": "Telegram cá nhân",
        "description": "Kết nối tài khoản Telegram cá nhân qua mã QR (Telethon MTProto userbot). Kênh riêng biệt chạy song song với Bot API. Giữ lượng dùng ở mức bình thường.",
        "actions": [
            {"id": "read_messages", "name": "connector:telegram_personal:read_messages",
             "label": "Đọc tin nhắn Telegram cá nhân", "kind": "read", "default": VERDICT_ALLOW},
            {"id": "list_dialogs", "name": "connector:telegram_personal:list_dialogs",
             "label": "Xem danh sách hội thoại", "kind": "read", "default": VERDICT_ALLOW},
            {"id": "send_message", "name": "connector:telegram_personal:send_message",
             "label": "Gửi tin nhắn Telegram cá nhân", "kind": "write", "default": VERDICT_ASK},
            {"id": "send_file", "name": "connector:telegram_personal:send_file",
             "label": "Gửi tệp Telegram cá nhân", "kind": "write", "default": VERDICT_ASK},
        ],
    },
    "facebook_personal": {
        "title": "Facebook cá nhân (Rủi ro cao)",
        "description": "Kết nối tài khoản Facebook cá nhân qua phiên web cookies (c_user, xs). Đọc trang cá nhân, bạn bè, bảng tin, đọc/gửi Messenger. Lưu ý: Tiềm ẩn nguy cơ checkpoint/khóa tài khoản nếu lạm dụng.",
        "actions": [
            {"id": "get_profile", "name": "connector:facebook_personal:get_profile",
             "label": "Xem trang cá nhân Facebook", "kind": "read", "default": VERDICT_ALLOW},
            {"id": "get_friends", "name": "connector:facebook_personal:get_friends",
             "label": "Xem danh sách bạn bè", "kind": "read", "default": VERDICT_ALLOW},
            {"id": "read_feed", "name": "connector:facebook_personal:read_feed",
             "label": "Đọc Bảng tin Facebook", "kind": "read", "default": VERDICT_ALLOW},
            {"id": "read_messages", "name": "connector:facebook_personal:read_messages",
             "label": "Đọc tin nhắn Messenger", "kind": "read", "default": VERDICT_ALLOW},
            {"id": "send_message", "name": "connector:facebook_personal:send_message",
             "label": "Gửi tin nhắn Messenger", "kind": "write", "default": VERDICT_ASK},
        ],
    },
    "instagram_messages": {
        "title": "Tin nhắn Instagram (Direct Messages)",
        "description": "Kết nối tin nhắn Instagram cá nhân qua phiên cookie/token (tách riêng với bài đăng Instagram). Đọc hộp thư, tìm kiếm tin nhắn, gửi tin nhắn, gửi file, thả reaction.",
        "actions": [
            {"id": "read_inbox", "name": "connector:instagram_messages:read_inbox",
             "label": "Đọc hộp thư Instagram", "kind": "read", "default": VERDICT_ALLOW},
            {"id": "read_messages", "name": "connector:instagram_messages:read_messages",
             "label": "Đọc tin nhắn hội thoại Instagram", "kind": "read", "default": VERDICT_ALLOW},
            {"id": "search_messages", "name": "connector:instagram_messages:search_messages",
             "label": "Tìm kiếm tin nhắn Instagram", "kind": "read", "default": VERDICT_ALLOW},
            {"id": "send_message", "name": "connector:instagram_messages:send_message",
             "label": "Gửi tin nhắn Instagram", "kind": "write", "default": VERDICT_ASK},
            {"id": "send_file", "name": "connector:instagram_messages:send_file",
             "label": "Gửi tệp qua tin nhắn Instagram", "kind": "write", "default": VERDICT_ASK},
            {"id": "send_reaction", "name": "connector:instagram_messages:send_reaction",
             "label": "Thả reaction tin nhắn Instagram", "kind": "write", "default": VERDICT_ASK},
        ],
    },
    "threads_messages": {
        "title": "Tin nhắn Threads (Direct Messages)",
        "description": "Kết nối tin nhắn Threads cá nhân qua phiên cookie/token (tách riêng với bài đăng Threads). Giới hạn cứng: Chỉ nhắn được người đã có hội thoại từ trước.",
        "actions": [
            {"id": "read_inbox", "name": "connector:threads_messages:read_inbox",
             "label": "Đọc hộp thư Threads", "kind": "read", "default": VERDICT_ALLOW},
            {"id": "read_messages", "name": "connector:threads_messages:read_messages",
             "label": "Đọc tin nhắn hội thoại Threads", "kind": "read", "default": VERDICT_ALLOW},
            {"id": "send_message", "name": "connector:threads_messages:send_message",
             "label": "Gửi tin nhắn Threads (hội thoại có sẵn)", "kind": "write", "default": VERDICT_ASK},
            {"id": "send_reaction", "name": "connector:threads_messages:send_reaction",
             "label": "Thả reaction tin nhắn Threads", "kind": "write", "default": VERDICT_ASK},
        ],
    },
}


def parse_verdict(value) -> Optional[str]:
    """Chuẩn hoá 1 giá trị policy thành allow/ask/deny.

    None (không khai) -> None (đi tiếp lớp dưới). Tương thích
    ngược: đúng tập từ cũ — thuộc nhóm deny thì deny, còn lại
    allow — cộng thêm nhóm ask mới của 1.2.0.
    """
    if value is None:
        return None
    word = str(value).strip().lower()
    if word in _DENY_WORDS:
        return VERDICT_DENY
    if word in _ASK_WORDS:
        return VERDICT_ASK
    return VERDICT_ALLOW


@dataclass
class PolicyDecision:
    allowed: bool
    layer: str  # host-tool | host-group | host-default | session-* | builtin
    reason: str = ""
    verdict: str = VERDICT_ALLOW  # allow | ask | deny (1.2.0)

    @property
    def needs_ask(self) -> bool:
        return self.verdict == VERDICT_ASK


class PolicyEngine:
    def __init__(self, policy_path: str | Path, memory=None):
        self.path = Path(policy_path)
        self.memory = memory
        self.host: dict = self._load_host()
        self.session_tools: dict[str, str] = {}
        self.session_groups: dict[str, str] = {}

    def _load_host(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def reload_host(self) -> None:
        self.host = self._load_host()

    @staticmethod
    def _verdict(value: Optional[str]) -> Optional[bool]:
        """Tương thích ngược cho nơi còn dùng dạng bool."""
        verdict = parse_verdict(value)
        return None if verdict is None else verdict == VERDICT_ALLOW

    def decide(self, tool_name: str, group: str = "") -> PolicyDecision:
        host_tools = self.host.get("tools") or {}
        host_groups = self.host.get("groups") or {}
        # Nhóm có tiền tố đa cấp (vd "connector:gmail:send", "connector:gmail", "mcp:filesystem"):
        # thử key đầy đủ trước, rồi bóc dần từng cấp tới nhóm gốc ("connector", "mcp").
        group_keys = []
        cur = group
        while cur:
            group_keys.append(cur)
            if ":" in cur:
                cur = cur.rsplit(":", 1)[0]
            else:
                break
        for layer, table, key in (
            ("host-tool", host_tools, tool_name),
            *[("host-group", host_groups, gk) for gk in group_keys],
        ):
            verdict = parse_verdict(table.get(key)) if key else None
            if verdict is not None:
                return PolicyDecision(verdict == VERDICT_ALLOW, layer,
                                      verdict=verdict)
        verdict = parse_verdict(self.host.get("default"))
        if verdict is not None:
            return PolicyDecision(verdict == VERDICT_ALLOW, "host-default",
                                  verdict=verdict)
        for layer, table, key in (
            ("session-tool", self.session_tools, tool_name),
            *[("session-group", self.session_groups, gk)
              for gk in group_keys],
        ):
            verdict = parse_verdict(table.get(key)) if key else None
            if verdict is not None:
                return PolicyDecision(verdict == VERDICT_ALLOW, layer,
                                      verdict=verdict)
        # sửa 1.6.2: mặc định theo tên tool (web_click/web_fill = ask).
        # Host/session ở trên vẫn thắng bảng này.
        if tool_name in TOOL_DEFAULTS:
            td = TOOL_DEFAULTS[tool_name]
            return PolicyDecision(td == VERDICT_ALLOW, "tool-default",
                                  reason="mặc định tool tương tác web "
                                         "(hỏi trước khi chạy)",
                                  verdict=td)
        # 1.6.0: Mặc định nấc riêng theo hành động connector (đọc=allow, ghi/xoá=ask)
        if group and group in CONNECTOR_ACTION_DEFAULTS:
            act_default = CONNECTOR_ACTION_DEFAULTS[group]
            return PolicyDecision(act_default == VERDICT_ALLOW,
                                  "connector-action-default",
                                  reason="mặc định hành động connector (đọc=cho phép, ghi/xoá=hỏi)",
                                  verdict=act_default)
        # Sửa 1.6.2: fail-closed RIÊNG cho Google. Group gmail/gcalendar
        # mà action không có trong CONNECTOR_ACTION_DEFAULTS (action mới
        # chưa liệt kê, hoặc call thiếu action) thì HỎI trước, không
        # rơi về builtin allow. Rule host/session do owner đặt rõ vẫn
        # thắng như mọi lớp trên (thứ tự phân giải không đổi). Mọi
        # connector khác và tool khác vẫn rơi về builtin allow bên
        # dưới, giữ nguyên triết lý full-auto của user cho phần còn lại.
        if group in ("connector:gmail", "connector:gcalendar") or \
                group.startswith(("connector:gmail:",
                                  "connector:gcalendar:")):
            return PolicyDecision(False, "connector-action-default",
                                  reason="hành động Google chưa liệt kê "
                                         "trong bảng action-level: hỏi "
                                         "trước thay vì tự cho phép",
                                  verdict=VERDICT_ASK)
        # sửa 1.6.2: fallback có điều kiện cho connector chưa liệt kê
        # (đặt SAU fail-closed Google để không mở lại cửa cho action
        # Google chưa liệt kê). Bảng 6 action Google ở trên đã thắng
        # nhánh này; group không phải connector, call thiếu action,
        # và token lạ vẫn về builtin allow như cũ.
        fallback = connector_fallback_verdict(group or "")
        if fallback is not None:
            return PolicyDecision(fallback == VERDICT_ALLOW,
                                  "connector-action-fallback",
                                  reason="fallback action-level cho "
                                         "connector chưa liệt kê "
                                         "(ghi/xoá=hỏi, đọc=cho phép)",
                                  verdict=fallback)
        return PolicyDecision(True, "builtin",
                              "mặc định full-auto theo lệnh user",
                              verdict=VERDICT_ALLOW)

    async def check(self, tool_name: str, group: str = "",
                    session_key: str = "") -> PolicyDecision:
        """Kiểm tra + ghi trajectory (quyết định nào cũng có dấu vết)."""
        decision = self.decide(tool_name, group)
        if self.memory is not None:
            await self.memory.log_trajectory(
                session_key,
                "policy_decision",
                {
                    "tool": tool_name,
                    "group": group,
                    "allowed": decision.allowed,
                    "verdict": decision.verdict,
                    "layer": decision.layer,
                },
            )
        return decision

    # ---------- sửa rule (Mini App / remember) ----------
    def set_session_rule(self, scope: str, name: str,
                         verdict: str) -> str:
        """Ghi rule vào lớp session (thua host, thắng mặc định).

        scope: "tool" | "group". Trả verdict đã chuẩn hoá.
        """
        normalized = parse_verdict(verdict) or VERDICT_ALLOW
        if scope == "group":
            self.session_groups[name] = normalized
        else:
            self.session_tools[name] = normalized
        return normalized

    def set_host_rule(self, scope: str, name: str, verdict: str) -> str:
        """Ghi rule vào file policy (lớp host — bền qua restart)."""
        normalized = parse_verdict(verdict) or VERDICT_ALLOW
        data = dict(self.host)
        if scope == "group":
            table = dict(data.get("groups") or {})
            table[name] = normalized
            data["groups"] = table
        elif scope == "default":
            data["default"] = normalized
        else:
            table = dict(data.get("tools") or {})
            table[name] = normalized
            data["tools"] = table
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(self.path)
        self.host = data
        return normalized

    def get_host_verdict(self, scope: str, name: str) -> Optional[str]:
        """Verdict host hiện tại của 1 rule (None = chưa có rule)."""
        if scope == "group":
            table = self.host.get("groups") or {}
        elif scope == "default":
            return parse_verdict(self.host.get("default"))
        else:
            table = self.host.get("tools") or {}
        return parse_verdict(table.get(name))

    def remove_host_rule(self, scope: str, name: str) -> bool:
        """Xoá 1 rule khỏi lớp host (ghi file nguyên tử như
        set_host_rule). Trả True nếu thật sự có rule bị xoá.
        Chỉ dùng cho rule do chính hệ thống tạo (vd installer của
        marketplace) — không xoá rule owner tự đặt."""
        data = dict(self.host)
        if scope == "group":
            table = dict(data.get("groups") or {})
        elif scope == "default":
            if "default" not in data:
                return False
            del data["default"]
            table = None
        else:
            table = dict(data.get("tools") or {})
        if table is not None:
            if name not in table:
                return False
            del table[name]
            data["groups" if scope == "group" else "tools"] = table
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        tmp.replace(self.path)
        self.host = data
        return True

    def describe(self) -> dict:
        """Ảnh chụp policy cho bề mặt hiển thị (Mini App / /quyen)."""
        connector_details = {}
        for cname, spec in CONNECTOR_SPECS.items():
            acts = []
            for act in spec["actions"]:
                full_name = act["name"]
                dec = self.decide("", full_name)
                acts.append({
                    "id": act["id"],
                    "name": full_name,
                    "label": act["label"],
                    "kind": act["kind"],
                    "default": act["default"],
                    "effective": dec.verdict,
                })
            connector_details[cname] = {
                "title": spec["title"],
                "actions": acts,
            }
        return {
            "default": parse_verdict(self.host.get("default"))
                       or VERDICT_ALLOW,
            "tools": {k: parse_verdict(v)
                      for k, v in (self.host.get("tools") or {}).items()},
            "groups": {k: parse_verdict(v)
                       for k, v in (self.host.get("groups") or {}).items()},
            "session_tools": dict(self.session_tools),
            "session_groups": dict(self.session_groups),
            "connector_specs": connector_details,
        }
