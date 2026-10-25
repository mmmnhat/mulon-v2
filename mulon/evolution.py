"""MuLon Self-Evolution & Self-Modification Tools.

Cho phép MuLon tự kiểm tra mã nguồn, chạy test, và tự khởi động lại
sau khi chỉnh sửa code chính mình theo yêu cầu của người dùng.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from .tools import ToolRegistry, ToolSpec

logger = logging.getLogger("mulon.evolution")


def register_evolution_tools(registry: ToolRegistry, cfg, memory=None) -> None:
    """Đăng ký các tool tự tiến hóa & vòng đời cho MuLon."""

    async def restart_bot(reason: str = "Tự khởi động lại sau khi cập nhật code") -> dict:
        """Khởi động lại bot Mulon trong 1 giây để nạp mã nguồn hoặc cấu hình mới."""
        if memory is not None:
            try:
                # Ghi nhận trạng thái thông báo sau khi bot sống lại
                chat_id = getattr(cfg, "allowed_user_id", None)
                await memory.kv_set("system:restart_notify", json.dumps({
                    "reason": reason,
                    "chat_id": chat_id,
                }))
            except Exception as exc:
                logger.warning("Không thể lưu restart_notify: %s", exc)

        def _reexec():
            time.sleep(1.0)
            logger.warning("restart_bot: re-executing bot process (%s)...", reason)
            python = sys.executable
            os.execv(python, [python, "-m", "mulon.main"])

        threading.Thread(target=_reexec, daemon=True, name="bot-self-restart").start()
        return {
            "ok": True,
            "status": "restarting",
            "message": f"Bot đang khởi động lại trong 1 giây ({reason}). Sau khi khởi động xong sẽ tự động gửi thông báo cho bạn.",
        }

    registry.register(
        ToolSpec(
            name="restart_bot",
            description=(
                "Khởi động lại tiến trình bot Mulon để nạp code mới hoặc áp dụng thay đổi cấu hình. "
                "Trước khi gọi tool này, hãy đảm bảo đã kiểm tra cú pháp và chạy test thành công."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Lý do khởi động lại (ví dụ: 'Đã thêm lệnh /hello', 'Đã sửa hàm X')",
                    }
                },
                "required": [],
            },
            group="system",
            timeout_s=15.0,
            handler=restart_bot,
        )
    )
