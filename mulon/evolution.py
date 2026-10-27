"""MuLon Self-Evolution & Self-Modification Tools.

Cho phép MuLon tự kiểm tra mã nguồn, chạy test, và tự khởi động lại
sau khi chỉnh sửa code chính mình theo yêu cầu của người dùng.
"""

from __future__ import annotations

import json
import logging
import os
import sys
import threading
import time

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

    async def self_verify_and_restart(reason: str = "Tự sửa theo yêu cầu", run_evals: bool = False):
        import asyncio
        from pathlib import Path
        project_root = (getattr(cfg, "project_root", None) or Path(__file__).resolve().parent.parent).resolve()

        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "pytest", "tests/", "-q",
            cwd=str(project_root),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=90.0)
        except asyncio.TimeoutError:
            proc.kill()
            out, err = b"", b"pytest timeout sau 90s"

        stdout_txt = out.decode("utf-8", "replace")[-4000:]
        stderr_txt = err.decode("utf-8", "replace")[-2000:]

        if proc.returncode != 0:
            rb_proc = await asyncio.create_subprocess_exec(
                "git", "checkout", "--", "mulon/",
                cwd=str(project_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await rb_proc.communicate()
            return {
                "ok": False,
                "status": "failed_and_rolled_back",
                "error": "Kiểm thử thất bại. Đã tự động rollback mã nguồn về trạng thái an toàn.",
                "test_output": stdout_txt or stderr_txt,
                "returncode": proc.returncode,
            }

        if run_evals:
            eval_proc = await asyncio.create_subprocess_exec(
                sys.executable, "-m", "mulon.evals",
                cwd=str(project_root),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            eval_out, _ = await eval_proc.communicate()
            if eval_proc.returncode != 0:
                rb_proc = await asyncio.create_subprocess_exec(
                    "git", "checkout", "--", "mulon/",
                    cwd=str(project_root),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await rb_proc.communicate()
                return {
                    "ok": False,
                    "status": "evals_failed_and_rolled_back",
                    "error": "Kiểm thử evals vàng không đạt cổng 85%. Đã rollback mã nguồn.",
                    "eval_output": eval_out.decode("utf-8", "replace")[-2000:],
                }

        if memory is not None:
            try:
                await memory.kv_set("system:restart_notify", json.dumps({
                    "reason": f"Self-evolution: {reason}",
                    "timestamp": time.time(),
                }))
            except Exception:
                pass

        def _trigger_restart():
            time.sleep(1.0)
            os.execv(sys.executable, [sys.executable, "-m", "mulon.main"])

        threading.Thread(target=_trigger_restart, daemon=True, name="self-restart").start()

        return {
            "ok": True,
            "status": "verified_and_restarting",
            "message": "Toàn bộ kiểm thử PASS 100%. Đang khởi động lại bot an toàn...",
            "test_summary": stdout_txt.splitlines()[-1] if stdout_txt else "All tests passed",
        }

    registry.register(
        ToolSpec(
            name="self_verify_and_restart",
            description=(
                "Tự kiểm thử toàn bộ hệ thống sau khi sửa code và khởi động lại bot an toàn (Self-evolution). "
                "Nếu test pass (100% xanh) -> ghi nhận và khởi động lại bot sạch sẽ; "
                "nếu test fail -> tự động rollback (git checkout) các thay đổi mã nguồn để bảo vệ bot không bị sập."
            ),
            parameters={
                "type": "object",
                "properties": {
                    "reason": {
                        "type": "string",
                        "description": "Lý do sửa đổi code hoặc tính năng",
                        "default": "Tự sửa mã nguồn theo yêu cầu của chủ dự án",
                    },
                    "run_evals": {
                        "type": "boolean",
                        "description": "Có chạy thêm evals vàng không (nếu đụng agent loop/router)",
                        "default": False,
                    },
                },
                "required": [],
            },
            group="system",
            timeout_s=120.0,
            handler=self_verify_and_restart,
        )
    )
