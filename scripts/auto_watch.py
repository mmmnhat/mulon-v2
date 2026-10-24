#!/usr/bin/env python3
"""Mulon Auto-Watcher & Supervisor.

Tự động theo dõi commit mới trên remote git (origin/main), pull về và restart bot.
- Định kỳ kiểm tra git remote mà không ảnh hưởng git state local.
- Khi có commit mới: dừng bot, pull, chạy smoke test (--dry-run).
- Nếu pass: khởi động bot mới và gửi thông báo Telegram cho chủ nhân.
- Nếu fail: rollback về commit cũ, cảnh báo qua Telegram, giữ bot hoạt động an toàn.
- Tự động hồi sinh bot nếu bot bị crash đột ngột.
"""

from __future__ import annotations

import argparse
import html
import json
import logging
import os
import signal
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [watcher] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("watcher")


def load_config():
    try:
        from mulon.config import Config
        return Config.load()
    except Exception as e:
        logger.warning("Không thể nạp config: %s", e)
        return None


def send_telegram_alert(token: str, chat_id: int, message: str) -> bool:
    if not token or not chat_id:
        return False
    try:
        url = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = json.dumps({
            "chat_id": chat_id,
            "text": message,
            "parse_mode": "HTML",
            "disable_web_page_preview": True,
        }).encode("utf-8")
        req = urllib.request.Request(
            url, data=payload, headers={"Content-Type": "application/json"}
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            return resp.status == 200
    except Exception as e:
        logger.warning("Lỗi gửi thông báo Telegram: %s", e)
        return False


def get_local_commit() -> str:
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout.strip()
    except Exception as e:
        logger.error("Không thể lấy commit local: %s", e)
        return ""


def get_remote_commit(remote: str, branch: str) -> str:
    try:
        res = subprocess.run(
            ["git", "ls-remote", remote, f"refs/heads/{branch}"],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            timeout=20,
        )
        if res.returncode != 0:
            return ""
        lines = res.stdout.strip().splitlines()
        if not lines:
            return ""
        return lines[0].split()[0].strip()
    except Exception as e:
        logger.warning("Lỗi kiểm tra remote %s/%s: %s", remote, branch, e)
        return ""


def get_commit_summary(sha: str) -> str:
    try:
        res = subprocess.run(
            ["git", "log", "-1", "--pretty=%s", sha],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        return res.stdout.strip()
    except Exception:
        return ""


class BotSupervisor:
    def __init__(self, interval_s: int = 15, branch: str = "main", remote: str = "origin"):
        self.interval_s = interval_s
        self.branch = branch
        self.remote = remote
        self.proc: Optional[subprocess.Popen] = None
        self.stopping = False
        self.current_sha = get_local_commit()
        self.cfg = load_config()

    def start_bot(self):
        if self.stopping:
            return
        logger.info("Khởi động bot: %s -m mulon.main (commit %s)",
                    sys.executable, self.current_sha[:7])
        self.proc = subprocess.Popen(
            [sys.executable, "-m", "mulon.main"],
            cwd=PROJECT_ROOT,
            stdout=sys.stdout,
            stderr=sys.stderr,
        )

    def stop_bot(self, timeout_s: float = 10.0):
        if self.proc is None:
            return
        if self.proc.poll() is not None:
            self.proc = None
            return
        logger.info("Đang dừng bot (PID %d)...", self.proc.pid)
        self.proc.terminate()
        try:
            self.proc.wait(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            logger.warning("Bot chưa thoát sau %ss, gửi SIGKILL...", timeout_s)
            self.proc.kill()
            self.proc.wait()
        self.proc = None
        logger.info("Bot đã dừng hoàn tất.")

    def run_smoke_test(self) -> tuple[bool, str]:
        try:
            res = subprocess.run(
                [sys.executable, "-m", "mulon.main", "--dry-run"],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                timeout=30,
            )
            if res.returncode == 0:
                return True, ""
            err = (res.stderr or res.stdout).strip()
            return False, err
        except Exception as e:
            return False, str(e)

    def check_requirements_changed(self, old_sha: str, new_sha: str) -> bool:
        try:
            res = subprocess.run(
                ["git", "diff", "--name-only", old_sha, new_sha],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
            )
            return "requirements.txt" in res.stdout.splitlines()
        except Exception:
            return False

    def _patch_webapp_routes(self):
        """Tự động chèn các route tương thích (/a, /, /panel) nếu bản pull về bị thiếu."""
        server_file = PROJECT_ROOT / "mulon" / "webapp_server.py"
        if not server_file.is_file():
            return
        try:
            content = server_file.read_text(encoding="utf-8")
            if 'app.router.add_get("/a"' not in content and 'app.router.add_get("/app"' in content:
                patched = content.replace(
                    'app.router.add_get("/app", self._handle_index)',
                    'app.router.add_get("/", self._handle_index)\n'
                    '        app.router.add_get("/a", self._handle_index)\n'
                    '        app.router.add_get("/a/", self._handle_index)\n'
                    '        app.router.add_get("/app", self._handle_index)\n'
                    '        app.router.add_get("/app/", self._handle_index)\n'
                    '        app.router.add_get("/panel", self._handle_index)'
                )
                server_file.write_text(patched, encoding="utf-8")
                logger.info("Đã tự động bảo lưu các route /a, /, /panel trong webapp_server.py")
        except Exception as e:
            logger.warning("Không thể patch webapp_server routes: %s", e)

    def update_and_restart(self, new_sha: str):
        old_sha = self.current_sha
        short_new = new_sha[:7]
        short_old = old_sha[:7]
        logger.info("Phát hiện commit mới trên remote: %s -> %s", short_old, short_new)

        # 1. Dừng bot hiện tại
        self.stop_bot()

        # 2. Pull code mới
        logger.info("Đang thực hiện git pull %s %s...", self.remote, self.branch)
        subprocess.run(["git", "stash"], cwd=PROJECT_ROOT, capture_output=True)
        pull_res = subprocess.run(
            ["git", "pull", self.remote, self.branch],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        if pull_res.returncode != 0:
            err_msg = pull_res.stderr.strip() or pull_res.stdout.strip()
            logger.error("Git pull thất bại: %s", err_msg)
            # Khởi động lại bản hiện tại
            self.start_bot()
            if self.cfg:
                send_telegram_alert(
                    self.cfg.telegram_bot_token,
                    self.cfg.allowed_user_id,
                    f"⚠️ <b>Mulon Cảnh Báo</b>\n"
                    f"Phát hiện commit mới <code>{short_new}</code> nhưng <code>git pull</code> thất bại:\n"
                    f"<code>{html.escape(err_msg[:400])}</code>\n"
                    f"Bot vẫn đang chạy bản cũ <code>{short_old}</code>."
                )
            return

        # Tự động đảm bảo route tương thích không bị mất
        self._patch_webapp_routes()

        # 3. Kiểm tra nếu có package mới
        if self.check_requirements_changed(old_sha, new_sha):
            logger.info("Phát hiện thay đổi requirements.txt, đang cập nhật pip...")
            pip_res = subprocess.run(
                [sys.executable, "-m", "pip", "install", "-r", "requirements.txt"],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
            )
            if pip_res.returncode != 0:
                logger.warning("Cập nhật requirements.txt có cảnh báo: %s", pip_res.stderr[:300])

        # 4. Smoke test bản mới
        logger.info("Đang kiểm tra smoke test (--dry-run)...")
        ok, err_test = self.run_smoke_test()
        if not ok:
            logger.error("Smoke test thất bại: %s", err_test)
            # Rollback về commit cũ
            subprocess.run(
                ["git", "reset", "--hard", old_sha],
                cwd=PROJECT_ROOT,
                capture_output=True,
            )
            logger.info("Đã rollback về commit %s", short_old)
            self.start_bot()
            if self.cfg:
                send_telegram_alert(
                    self.cfg.telegram_bot_token,
                    self.cfg.allowed_user_id,
                    f"⚠️ <b>Mulon Cảnh Báo</b>\n"
                    f"Commit mới <code>{short_new}</code> bị lỗi smoke test (--dry-run):\n"
                    f"<code>{html.escape(err_test[:400])}</code>\n"
                    f"Đã tự động rollback về commit an toàn <code>{short_old}</code>."
                )
            return

        # 5. Cập nhật commit hash và reload config
        self.current_sha = new_sha
        self.cfg = load_config()
        commit_msg = get_commit_summary(new_sha)
        logger.info("Cập nhật thành công commit %s: %s", short_new, commit_msg)

        # 6. Khởi động bot mới
        self.start_bot()

        # 7. Gửi thông báo Telegram
        if self.cfg:
            msg = (
                f"🚀 <b>Mulon đã tự động cập nhật</b>\n\n"
                f"• Commit: <code>{short_new}</code>\n"
                f"• Nội dung: <i>{html.escape(commit_msg)}</i>\n"
                f"• Trạng thái: Kiểm thử đạt, bot đã khởi động lại hoàn tất."
            )
            send_telegram_alert(self.cfg.telegram_bot_token, self.cfg.allowed_user_id, msg)

    def run(self):
        self.start_bot()
        logger.info("Watcher đã bắt đầu. Chu kỳ kiểm tra remote: %ds", self.interval_s)

        while not self.stopping:
            try:
                # Kiểm tra trạng thái bot con
                if self.proc is not None and self.proc.poll() is not None:
                    code = self.proc.poll()
                    logger.warning("Bot con đã dừng đột ngột (exit code %s). Khởi động lại sau 3s...", code)
                    time.sleep(3)
                    self.start_bot()

                # Kiểm tra commit trên remote
                remote_sha = get_remote_commit(self.remote, self.branch)
                if remote_sha and remote_sha != self.current_sha:
                    self.update_and_restart(remote_sha)

            except Exception as e:
                logger.error("Lỗi trong vòng lặp watcher: %s", e)

            # Sleep theo từng nhịp nhỏ để phản hồi nhanh tín hiệu dừng
            for _ in range(self.interval_s * 2):
                if self.stopping:
                    break
                time.sleep(0.5)

        logger.info("Watcher đang dừng...")
        self.stop_bot()
        logger.info("Watcher đã dừng hẳn.")

    def handle_signal(self, signum, frame):
        logger.info("Nhận tín hiệu dừng (signal %s)...", signum)
        self.stopping = True
        self.stop_bot()
        sys.exit(0)


def main():
    parser = argparse.ArgumentParser(description="Mulon Git Auto-Watcher & Supervisor")
    parser.add_argument("--interval", type=int, default=15, help="Chu kỳ kiểm tra remote (giây)")
    parser.add_argument("--branch", type=str, default="main", help="Nhánh git cần theo dõi")
    parser.add_argument("--remote", type=str, default="origin", help="Tên remote")
    args = parser.parse_args()

    supervisor = BotSupervisor(
        interval_s=args.interval,
        branch=args.branch,
        remote=args.remote,
    )

    signal.signal(signal.SIGINT, supervisor.handle_signal)
    signal.signal(signal.SIGTERM, supervisor.handle_signal)

    supervisor.run()


if __name__ == "__main__":
    main()
