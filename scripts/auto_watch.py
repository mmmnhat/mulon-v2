#!/usr/bin/env python3
"""Mulon Auto-Watcher & Supervisor.

Tự động theo dõi commit mới trên remote git (origin/main), pull về và restart bot.
- Định kỳ kiểm tra git remote mà không ảnh hưởng git state local.
- Khi có commit mới: dừng bot, pull, chạy smoke test (--dry-run).
- Nếu pass: khởi động bot mới và gửi thông báo Telegram cho chủ nhân.
- Nếu fail: rollback về commit cũ, cảnh báo qua Telegram, giữ bot hoạt động an toàn.
- Tự động hồi sinh bot nếu bot bị crash đột ngột.

Sửa 1.6.3 — quy trình stash an toàn (lỗi cũ: git stash rồi không
bao giờ stash pop, local changes kẹt trong stash; rollback reset
--hard mà không khôi phục local changes):
- Trước khi stash, local changes (tracked) được backup ra file
  patch có tên + timestamp trong data/auto_watch_backups/ (thư
  mục này đã gitignore qua data/) và log rõ đường dẫn.
- Sau pull thành công + smoke pass: stash pop; nếu pop xung đột
  thì DỪNG ở bản mới, báo Telegram rõ stash nào + patch backup
  nào, KHÔNG tự reset --hard vứt local changes đi.
- Sau pull thất bại: stash pop trả lại rồi mới restart bản cũ;
  nếu pop xung đột thì KHÔNG restart với cây đang xung đột mà
  báo rõ stash + patch backup để xử lý tay.
- Rollback khi smoke fail: backup patch đã lưu TRƯỚC khi reset,
  reset --hard về commit cũ, rồi stash pop (local changes vốn
  dựa trên commit cũ nên pop về đúng nền); nếu pop xung đột thì
  KHÔNG khởi động bot với danh nghĩa "bản cũ an toàn" mà báo rõ.

Sửa 1.6.3 — cờ tắt: auto_watch MẶC ĐỊNH TẮT. Chỉ chạy khi
env AUTO_WATCH_ENABLED=1/true/yes/on hoặc cờ --enable, cho tới
khi quy trình trên được test xong trên Mac mini với local
changes giả lập. Chạy file này mà không bật cờ sẽ thoát ngay.
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


def is_remote_ahead(remote_sha: str) -> bool:
    """True nếu remote_sha có commit mới mà HEAD local chưa có."""
    if not remote_sha:
        return False
    try:
        res = subprocess.run(
            ["git", "merge-base", "--is-ancestor", remote_sha, "HEAD"],
            cwd=PROJECT_ROOT,
            capture_output=True,
        )
        return res.returncode != 0
    except Exception:
        return False


def auto_watch_enabled(env: Optional[dict] = None, flag: bool = False) -> bool:
    """Sửa 1.6.3: cờ bật auto_watch. Mặc định TẮT."""
    if flag:
        return True
    source = env if env is not None else os.environ
    return str(source.get("AUTO_WATCH_ENABLED", "")).strip().lower() in (
        "1", "true", "yes", "on")


def _git(project_root: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["git", *args], cwd=project_root, capture_output=True, text=True)


def latest_stash_ref(project_root: Path) -> str:
    """Dòng đầu của `git stash list`, ví dụ 'stash@{0}: On main: ...'."""
    res = _git(project_root, "stash", "list")
    lines = (res.stdout or "").strip().splitlines()
    return lines[0].strip() if lines else ""


def backup_local_changes(project_root: Path) -> Optional[Path]:
    """Sửa 1.6.3: backup local changes tracked ra file patch.

    Trả về đường dẫn patch, hoặc None nếu không có thay đổi tracked.
    File untracked KHÔNG nằm trong `git diff` và cũng không bị
    `git stash` (không -u) cuốn đi, nên chúng ở lại trong cây và
    không cần backup ở đây — log rõ điều này để khỏi hiểu lầm.
    """
    status = _git(project_root, "status", "--porcelain")
    if not (status.stdout or "").strip():
        return None
    backup_dir = project_root / "data" / "auto_watch_backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = time.strftime("%Y%m%d-%H%M%S")
    patch_path = backup_dir / f"local-{stamp}.patch"
    diff = _git(project_root, "diff").stdout or ""
    diff_cached = _git(project_root, "diff", "--cached").stdout or ""
    with patch_path.open("w", encoding="utf-8") as fh:
        fh.write("# auto_watch backup of tracked local changes\n")
        fh.write(diff)
        if diff_cached:
            fh.write("\n# --- staged changes ---\n")
            fh.write(diff_cached)
    if patch_path.stat().st_size == 0 or not (diff or diff_cached):
        # Chỉ còn untracked: không có gì để backup, xoá file rỗng.
        try:
            patch_path.unlink()
        except OSError:
            pass
        logger.info(
            "Local changes chỉ gồm file untracked, không bị stash cuốn đi, "
            "không cần file backup patch.")
        return None
    logger.info("Đã backup local changes ra file: %s", patch_path)
    return patch_path


def stash_local_changes(project_root: Path) -> str:
    """Sửa 1.6.3: stash có tên + timestamp, trả về ref stash mới.

    Trả "" nếu không có gì để stash hoặc stash thất bại.
    """
    before = _git(project_root, "stash", "list").stdout or ""
    stamp = time.strftime("%Y%m%d-%H%M%S")
    res = _git(project_root, "stash", "push", "-m", f"auto_watch-backup-{stamp}")
    if res.returncode != 0:
        logger.error("git stash thất bại: %s", (res.stderr or res.stdout).strip())
        return ""
    after = _git(project_root, "stash", "list").stdout or ""
    if after == before:
        return ""  # Không có thay đổi nào, không tạo stash mới.
    ref = latest_stash_ref(project_root)
    logger.info("Đã stash local changes: %s", ref)
    return ref


def pop_stash(project_root: Path) -> tuple[bool, str]:
    """Sửa 1.6.3: stash pop an toàn.

    Trả (True, "") nếu pop thành công; (False, ref) nếu xung đột —
    khi đó stash VẪN CÒN trên đầu stack, caller TUYỆT ĐỐI không
    được reset --hard hay tiếp tục như thể local changes đã về.
    """
    res = _git(project_root, "stash", "pop")
    if res.returncode == 0:
        logger.info("Đã stash pop, local changes đã về cây làm việc.")
        return True, ""
    ref = latest_stash_ref(project_root)
    logger.error(
        "stash pop XUNG ĐỘT (stash vẫn còn: %s). Dừng lại để xử lý tay, "
        "không tự reset --hard.", ref)
    return False, ref


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
                timeout=45,
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

    def _alert(self, message: str):
        if self.cfg:
            send_telegram_alert(
                self.cfg.telegram_bot_token, self.cfg.allowed_user_id, message)

    def update_and_restart(self, new_sha: str):
        """Sửa 1.6.3: xem docstring module về quy trình stash an toàn."""
        old_sha = self.current_sha
        short_new = new_sha[:7]
        short_old = old_sha[:7]
        logger.info("Phát hiện commit mới trên remote: %s -> %s", short_old, short_new)

        # 1. Dừng bot hiện tại
        self.stop_bot()

        # 2. Backup + stash local changes TRƯỚC khi pull (sửa 1.6.3).
        backup_path = backup_local_changes(PROJECT_ROOT)
        stash_ref = stash_local_changes(PROJECT_ROOT)
        if backup_path is not None:
            logger.info("Backup local changes: %s (stash: %s)",
                        backup_path, stash_ref or "không có stash mới")

        # 3. Pull code mới
        logger.info("Đang thực hiện git pull %s %s...", self.remote, self.branch)
        pull_res = subprocess.run(
            ["git", "pull", self.remote, self.branch],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
        )
        if pull_res.returncode != 0:
            err_msg = pull_res.stderr.strip() or pull_res.stdout.strip()
            logger.error("Git pull thất bại: %s", err_msg)
            # Sửa 1.6.3: pop trả lại rồi MỚI restart bản cũ.
            if stash_ref:
                ok, ref = pop_stash(PROJECT_ROOT)
                if not ok:
                    self._alert(
                        f"⚠️ <b>Mulon Cảnh Báo</b>\n"
                        f"git pull thất bại và stash pop XUNG ĐỘT.\n"
                        f"Local changes vẫn ở: <code>{html.escape(ref)}</code>\n"
                        f"Backup patch: <code>{html.escape(str(backup_path))}</code>\n"
                        f"Bot CHƯA restart (cây đang xung đột) — cần xử lý tay.")
                    return
            self.start_bot()
            self._alert(
                f"⚠️ <b>Mulon Cảnh Báo</b>\n"
                f"Phát hiện commit mới <code>{short_new}</code> nhưng <code>git pull</code> thất bại:\n"
                f"<code>{html.escape(err_msg[:400])}</code>\n"
                f"Bot vẫn đang chạy bản cũ <code>{short_old}</code>.")
            return

        # Tự động đảm bảo route tương thích không bị mất
        self._patch_webapp_routes()

        # 4. Kiểm tra nếu có package mới
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

        # 5. Smoke test bản mới
        logger.info("Đang kiểm tra smoke test (--dry-run)...")
        ok, err_test = self.run_smoke_test()
        if not ok:
            logger.error("Smoke test thất bại: %s", err_test)
            # Sửa 1.6.3: backup patch đã lưu ở bước 2 TRƯỚC khi reset;
            # reset --hard về commit cũ, rồi stash pop (local changes
            # vốn dựa trên commit cũ nên pop về đúng nền). KHÔNG
            # reset khi còn stash chưa pop mà bỏ quên nó.
            subprocess.run(
                ["git", "reset", "--hard", old_sha],
                cwd=PROJECT_ROOT,
                capture_output=True,
            )
            logger.info("Đã rollback về commit %s", short_old)
            if stash_ref:
                popped, ref = pop_stash(PROJECT_ROOT)
                if not popped:
                    self._alert(
                        f"⚠️ <b>Mulon Cảnh Báo</b>\n"
                        f"Commit mới <code>{short_new}</code> bị lỗi smoke test (--dry-run):\n"
                        f"<code>{html.escape(err_test[:400])}</code>\n"
                        f"Đã rollback về <code>{short_old}</code> nhưng stash pop XUNG ĐỘT.\n"
                        f"Local changes vẫn ở: <code>{html.escape(ref)}</code>\n"
                        f"Backup patch: <code>{html.escape(str(backup_path))}</code>\n"
                        f"Bot CHƯA restart với danh nghĩa bản cũ an toàn — cần xử lý tay.")
                    return
            self.start_bot()
            self._alert(
                f"⚠️ <b>Mulon Cảnh Báo</b>\n"
                f"Commit mới <code>{short_new}</code> bị lỗi smoke test (--dry-run):\n"
                f"<code>{html.escape(err_test[:400])}</code>\n"
                f"Đã tự động rollback về commit an toàn <code>{short_old}</code>.")
            return

        # 6. Smoke pass: pop local changes về bản mới (sửa 1.6.3).
        if stash_ref:
            popped, ref = pop_stash(PROJECT_ROOT)
            if not popped:
                # Dừng bot ở bản mới, KHÔNG tự reset --hard vứt đi.
                self.current_sha = new_sha
                self.cfg = load_config()
                self._alert(
                    f"⚠️ <b>Mulon Cảnh Báo</b>\n"
                    f"Commit mới <code>{short_new}</code> đã qua smoke test, "
                    f"nhưng stash pop XUNG ĐỘT.\n"
                    f"Local changes vẫn ở: <code>{html.escape(ref)}</code>\n"
                    f"Backup patch: <code>{html.escape(str(backup_path))}</code>\n"
                    f"Bot ĐANG DỪNG ở bản mới <code>{short_new}</code> — "
                    f"cần xử lý tay rồi restart, không tự reset --hard.")
                return

        # 7. Cập nhật commit hash và reload config
        self.current_sha = new_sha
        self.cfg = load_config()
        commit_msg = get_commit_summary(new_sha)
        logger.info("Cập nhật thành công commit %s: %s", short_new, commit_msg)

        # 8. Khởi động bot mới
        self.start_bot()

        # 9. Gửi thông báo Telegram
        if self.cfg:
            msg = (
                f"🚀 <b>Mulon đã tự động cập nhật</b>\n\n"
                f"• Commit: <code>{short_new}</code>\n"
                f"• Nội dung: <i>{html.escape(commit_msg)}</i>\n"
                f"• Trạng thái: Kiểm thử đạt, bot đã khởi động lại hoàn tất."
            )
            if stash_ref:
                msg += "\n• Local changes: đã stash pop về bản mới."
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

                # Kiểm tra commit trên remote (chỉ update nếu remote có commit mới mà local chưa có)
                remote_sha = get_remote_commit(self.remote, self.branch)
                if remote_sha and remote_sha != self.current_sha and is_remote_ahead(remote_sha):
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
    parser.add_argument("--enable", action="store_true",
                        help="Bật auto_watch (sửa 1.6.3: mặc định TẮT, "
                        "hoặc đặt env AUTO_WATCH_ENABLED=1)")
    args = parser.parse_args()

    # Sửa 1.6.3: mặc định tắt cho tới khi quy trình stash an toàn
    # được test xong trên Mac mini với local changes giả lập.
    if not auto_watch_enabled(flag=args.enable):
        logger.error(
            "auto_watch đang TẮT theo mặc định (sửa 1.6.3). Để bật sau khi "
            "đã test xong, chạy với --enable hoặc đặt AUTO_WATCH_ENABLED=1.")
        sys.exit(2)

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
