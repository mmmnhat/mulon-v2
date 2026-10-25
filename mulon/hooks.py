"""Hook Subsystem — Sự kiện kích hoạt bằng polling Bash nhẹ (chuẩn kiến trúc Muse).

Mỗi Hook gồm 2 phần:
1. Script Bash polling nhẹ (scripts/poll.sh): Không cầm secret/credential, dùng curl + jq,
   có timeout chặt, trả về đúng 1 quyết định terminal: "silent" hoặc "wake" (kèm reason & payload).
2. Hướng dẫn cho worker agent (instruction.md): Chỉ được đánh thức khi có quyết định "wake".

Vòng đời:
- Hook mới tạo luôn bắt đầu ở trạng thái TẮT (enabled=False, dry_run_passed=False).
- Bắt buộc phải chạy dry_run kiểm tra script và log append trước khi cho phép enable.
- Log là file JSONL append-only.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger("mulon.hooks")


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class HookManager:
    """Quản lý các Hook trong thư mục hooks/."""

    def __init__(self, hooks_dir: Path | str):
        self.hooks_dir = Path(hooks_dir)
        self.hooks_dir.mkdir(parents=True, exist_ok=True)

    def list_hooks(self) -> list[dict[str, Any]]:
        """Liệt kê toàn bộ hook đã đăng ký."""
        hooks = []
        for p in sorted(self.hooks_dir.iterdir()):
            if p.is_dir() and (p / "manifest.json").exists():
                try:
                    data = json.loads((p / "manifest.json").read_text(encoding="utf-8"))
                    data["has_script"] = (p / "scripts" / "poll.sh").exists()
                    data["has_instruction"] = (p / "instruction.md").exists()
                    hooks.append(data)
                except Exception as exc:
                    logger.warning("Đọc hook manifest %s lỗi: %s", p.name, exc)
        return hooks

    def get_hook(self, hook_id: str) -> Optional[dict[str, Any]]:
        hdir = self.hooks_dir / hook_id
        mfile = hdir / "manifest.json"
        if not mfile.exists():
            return None
        try:
            data = json.loads(mfile.read_text(encoding="utf-8"))
            data["has_script"] = (hdir / "scripts" / "poll.sh").exists()
            data["has_instruction"] = (hdir / "instruction.md").exists()
            if data["has_instruction"]:
                data["instruction"] = (hdir / "instruction.md").read_text(encoding="utf-8")
            return data
        except Exception:
            return None

    def _save_manifest(self, hook_id: str, manifest: dict[str, Any]) -> None:
        hdir = self.hooks_dir / hook_id
        hdir.mkdir(parents=True, exist_ok=True)
        mfile = hdir / "manifest.json"
        mfile.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")

    def _append_log(self, hook_id: str, entry: dict[str, Any]) -> None:
        hdir = self.hooks_dir / hook_id
        hdir.mkdir(parents=True, exist_ok=True)
        logfile = hdir / "log.jsonl"
        with logfile.open("a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def register_hook(
        self,
        hook_id: str,
        title: str,
        poll_script_content: str,
        instruction_md: str,
        interval_s: int = 60,
    ) -> dict[str, Any]:
        """Tạo hook mới (mặc định tắt, chưa dry_run)."""
        hdir = self.hooks_dir / hook_id
        scripts_dir = hdir / "scripts"
        scripts_dir.mkdir(parents=True, exist_ok=True)

        script_path = scripts_dir / "poll.sh"
        script_path.write_text(poll_script_content, encoding="utf-8")
        try:
            os.chmod(script_path, 0o755)
        except Exception:
            pass

        (hdir / "instruction.md").write_text(instruction_md, encoding="utf-8")

        manifest = {
            "id": hook_id,
            "title": title[:120],
            "interval_s": max(5, min(interval_s, 604800)),
            "enabled": False,
            "dry_run_passed": False,
            "created_at": now_iso(),
            "updated_at": now_iso(),
            "last_poll_at": "",
            "last_decision": "",
        }
        self._save_manifest(hook_id, manifest)
        return manifest

    def dry_run(self, hook_id: str) -> dict[str, Any]:
        """Kiểm thử script poll.sh mà không tạo side effect wake."""
        hook = self.get_hook(hook_id)
        if not hook:
            return {"ok": False, "error": f"Không tìm thấy hook {hook_id}"}

        script_path = (self.hooks_dir / hook_id / "scripts" / "poll.sh").resolve()
        if not script_path.exists():
            return {"ok": False, "error": "Thiếu scripts/poll.sh"}

        start = time.perf_counter()
        try:
            res = subprocess.run(
                ["bash", str(script_path)],
                cwd=str((self.hooks_dir / hook_id).resolve()),
                capture_output=True,
                text=True,
                timeout=600,
            )
            duration_ms = int((time.perf_counter() - start) * 1000)
            stdout = res.stdout.strip()
            stderr = res.stderr.strip()

            if res.returncode != 0:
                log_entry = {
                    "ts": now_iso(),
                    "dry_run": True,
                    "exit_code": res.returncode,
                    "stderr": stderr,
                    "duration_ms": duration_ms,
                    "decision": "error",
                }
                self._append_log(hook_id, log_entry)
                return {
                    "ok": False,
                    "error": f"Script thất bại (code {res.returncode}): {stderr or stdout}",
                }

            # Parse terminal decision từ stdout
            decision = "silent"
            reason = ""
            payload = {}
            try:
                out_json = json.loads(stdout)
                decision = out_json.get("decision", "silent")
                reason = out_json.get("reason", "")
                payload = out_json.get("payload", {})
            except Exception:
                # Nếu không phải JSON, kiểm tra keyword
                if "wake" in stdout.lower():
                    decision = "wake"
                    reason = stdout
                else:
                    decision = "silent"

            log_entry = {
                "ts": now_iso(),
                "dry_run": True,
                "exit_code": 0,
                "duration_ms": duration_ms,
                "decision": decision,
                "reason": reason,
                "payload": payload,
            }
            self._append_log(hook_id, log_entry)

            # Đánh dấu dry_run_passed thành công
            manifest = self.get_hook(hook_id) or {}
            manifest["dry_run_passed"] = True
            manifest["updated_at"] = now_iso()
            self._save_manifest(hook_id, manifest)

            return {
                "ok": True,
                "decision": decision,
                "reason": reason,
                "payload": payload,
                "duration_ms": duration_ms,
            }
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": "Script poll bị timeout (>600s)"}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def enable(self, hook_id: str, enabled: bool = True) -> dict[str, Any]:
        """Bật/tắt hook. Chỉ được bật nếu đã dry_run thành công."""
        manifest = self.get_hook(hook_id)
        if not manifest:
            return {"ok": False, "error": f"Không tìm thấy hook {hook_id}"}
        if enabled and not manifest.get("dry_run_passed"):
            return {
                "ok": False,
                "error": "Chưa thể bật: Bắt buộc phải chạy dry_run kiểm tra thành công trước!",
            }
        manifest["enabled"] = bool(enabled)
        manifest["updated_at"] = now_iso()
        self._save_manifest(hook_id, manifest)
        return {"ok": True, "hook": manifest}

    def poll(self, hook_id: str) -> dict[str, Any]:
        """Lượt poll thật định kỳ."""
        manifest = self.get_hook(hook_id)
        if not manifest or not manifest.get("enabled"):
            return {"ok": False, "skipped": True}

        script_path = (self.hooks_dir / hook_id / "scripts" / "poll.sh").resolve()
        start = time.perf_counter()
        try:
            res = subprocess.run(
                ["bash", str(script_path)],
                cwd=str((self.hooks_dir / hook_id).resolve()),
                capture_output=True,
                text=True,
                timeout=600,
            )
            duration_ms = int((time.perf_counter() - start) * 1000)
            stdout = res.stdout.strip()
            stderr = res.stderr.strip()

            decision = "silent"
            reason = ""
            payload = {}
            if res.returncode == 0:
                try:
                    out_json = json.loads(stdout)
                    decision = out_json.get("decision", "silent")
                    reason = out_json.get("reason", "")
                    payload = out_json.get("payload", {})
                except Exception:
                    decision = "wake" if "wake" in stdout.lower() else "silent"
            else:
                decision = "error"
                reason = stderr

            log_entry = {
                "ts": now_iso(),
                "dry_run": False,
                "exit_code": res.returncode,
                "duration_ms": duration_ms,
                "decision": decision,
                "reason": reason,
                "payload": payload,
            }
            self._append_log(hook_id, log_entry)

            manifest["last_poll_at"] = now_iso()
            manifest["last_decision"] = decision
            self._save_manifest(hook_id, manifest)

            return {
                "ok": True,
                "decision": decision,
                "reason": reason,
                "payload": payload,
                "duration_ms": duration_ms,
                "instruction": manifest.get("instruction", ""),
            }
        except Exception as exc:
            logger.warning("Poll hook %s lỗi: %s", hook_id, exc)
            return {"ok": False, "error": str(exc)}
