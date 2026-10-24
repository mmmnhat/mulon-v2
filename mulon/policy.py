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
        for layer, table, key in (
            ("host-tool", host_tools, tool_name),
            ("host-group", host_groups, group),
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
            ("session-group", self.session_groups, group),
        ):
            verdict = parse_verdict(table.get(key)) if key else None
            if verdict is not None:
                return PolicyDecision(verdict == VERDICT_ALLOW, layer,
                                      verdict=verdict)
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

    def describe(self) -> dict:
        """Ảnh chụp policy cho bề mặt hiển thị (Mini App / /quyen)."""
        return {
            "default": parse_verdict(self.host.get("default"))
                       or VERDICT_ALLOW,
            "tools": {k: parse_verdict(v)
                      for k, v in (self.host.get("tools") or {}).items()},
            "groups": {k: parse_verdict(v)
                       for k, v in (self.host.get("groups") or {}).items()},
            "session_tools": dict(self.session_tools),
            "session_groups": dict(self.session_groups),
        }
