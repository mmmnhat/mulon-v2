"""Policy engine 2 lớp (thiết kế mục 6, mượn cấu trúc OpenClaw).

- Lớp host: file JSON chính sách trên máy (POLICY_PATH). Lớp này THẮNG
  mọi cấu hình trong phiên — prompt/session không tự nới được.
- Lớp session: override tạm trong phiên (đặt qua code, không qua prompt).
- Mặc định theo lệnh user: full-auto (allow) trong phạm vi đã cấp.
  Policy tồn tại để user siết lại khi muốn và để mọi quyết định đều
  được ghi trajectory truy vết — không phải cổng chặn mặc định.

Định dạng file host:
    {"default": "allow"|"deny",
     "tools":  {"run_command": "deny", ...},
     "groups": {"shell": "deny", ...}}
Thứ tự phân giải: host(tool) > host(group) > host(default)
                > session(tool) > session(group) > mặc định "allow".
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Optional


@dataclass
class PolicyDecision:
    allowed: bool
    layer: str  # host-tool | host-group | host-default | session-* | builtin
    reason: str = ""


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
        if value is None:
            return None
        return str(value).strip().lower() not in {"deny", "block", "false", "0", "no"}

    def decide(self, tool_name: str, group: str = "") -> PolicyDecision:
        host_tools = self.host.get("tools") or {}
        host_groups = self.host.get("groups") or {}
        for layer, table, key in (
            ("host-tool", host_tools, tool_name),
            ("host-group", host_groups, group),
        ):
            verdict = self._verdict(table.get(key)) if key else None
            if verdict is not None:
                return PolicyDecision(verdict, layer)
        verdict = self._verdict(self.host.get("default"))
        if verdict is not None:
            return PolicyDecision(verdict, "host-default")
        for layer, table, key in (
            ("session-tool", self.session_tools, tool_name),
            ("session-group", self.session_groups, group),
        ):
            verdict = self._verdict(table.get(key)) if key else None
            if verdict is not None:
                return PolicyDecision(verdict, layer)
        return PolicyDecision(True, "builtin", "mặc định full-auto theo lệnh user")

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
                    "layer": decision.layer,
                },
            )
        return decision
