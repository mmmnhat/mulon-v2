#!/usr/bin/env python3
"""Mulon Dev-Watcher (Antigravity Autowatch).

Tự động theo dõi commit mới trên remote (origin/main), tự khởi chạy
Antigravity CLI headless (`agy -p`) để nhận việc từ AGENT_TASKS.md
khi có task TODO giao cho Antigravity.
Quy định theo T-18 trong AGENT_TASKS.md:
- Chạy định kỳ 5 phút qua macOS LaunchAgent (com.mulon.devwatch.plist).
- So sánh SHA remote với watermark local (~/.mulon-dev-watch/last_seen_sha).
- Khóa đơn (lockfile qua fcntl.flock) chống 2 agent chạy đè lên nhau.
- Không có việc hoặc mạng lỗi thì thoát sạch sẽ, không retry vô hạn.
"""

from __future__ import annotations

import argparse
import fcntl
import logging
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

WATCH_DIR = Path.home() / ".mulon-dev-watch"
WATERMARK_FILE = WATCH_DIR / "last_seen_sha"
LOCK_FILE = WATCH_DIR / "dev_watch.lock"
LOG_DIR = WATCH_DIR / "log"

REPO_DIR = Path(__file__).resolve().parent.parent
AGY_BIN = Path.home() / ".local/bin/agy"

BRIEF_PROMPT = """Bạn là Antigravity, builder trên máy Mac của dự án MuLon. Hãy thực hiện chu kỳ autowatch:
1. git pull bản mới nhất từ origin main.
2. Đọc AGENTS.md và AGENT_TASKS.md.
3. Tìm trong AGENT_TASKS.md các mục có trạng thái TODO giao cho Antigravity:
   - Nếu không có mục TODO nào giao Antigravity: thoát ngay, không sửa bất cứ file nào.
   - Nếu có: chọn đúng MỘT mục TODO có thứ tự ưu tiên cao nhất (theo thứ tự xuất hiện hoặc mục ghi ƯU TIÊN 1).
   - Đổi trạng thái mục đó thành DOING trong AGENT_TASKS.md và git commit + push ngay lên main để thông báo nhận việc.
   - Thực hiện công việc của mục đó theo đúng quy trình trong AGENTS.md:
     * Nguyên tắc số 0: KHÔNG hardcode bất cứ giá trị nào.
     * Viết code + test tương ứng.
     * Chạy toàn bộ test pytest tests/ -q (phải pass 100%).
     * Bump version trong mulon/__init__.py và ghi CHANGELOG.md.
     * Cập nhật trạng thái mục đó thành DONE trong AGENT_TASKS.md kèm kết quả + commit SHA.
     * Commit và push lên main.
"""


def setup_logger() -> logging.Logger:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.now().strftime("%Y%m%d")
    log_file = LOG_DIR / f"dev_watch_{today}.log"

    logger = logging.getLogger("dev_watch")
    logger.setLevel(logging.INFO)
    logger.handlers.clear()

    formatter = logging.Formatter(
        "%(asctime)s [dev_watch] %(levelname)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    fh = logging.FileHandler(str(log_file), encoding="utf-8")
    fh.setFormatter(formatter)
    logger.addHandler(fh)

    sh = logging.StreamHandler(sys.stdout)
    sh.setFormatter(formatter)
    logger.addHandler(sh)

    return logger


def acquire_lock(logger: logging.Logger):
    """Mở khóa đơn bằng fcntl.flock non-blocking. Tự nhả khi process thoát."""
    LOCK_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        lock_fd = open(LOCK_FILE, "a+")
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        lock_fd.seek(0)
        lock_fd.truncate()
        lock_fd.write(f"PID: {os.getpid()}\nStarted: {datetime.now().isoformat()}\n")
        lock_fd.flush()
        return lock_fd
    except (BlockingIOError, OSError):
        logger.info("Một phiên dev_watch khác đang chạy (lock đang bị giữ). Bỏ qua chu kỳ này.")
        return None


def run_git(args: list[str], cwd: Path, timeout: int = 45) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ["git"] + args,
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=timeout,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Mulon Dev-Watcher (Antigravity Autowatch)")
    parser.add_argument("--force", action="store_true", help="Chạy agy bỏ qua kiểm tra SHA watermark")
    parser.add_argument("--prompt", type=str, default="", help="Prompt tuỳ biến thay thế brief mặc định")
    args = parser.parse_args()

    WATCH_DIR.mkdir(parents=True, exist_ok=True)
    logger = setup_logger()

    lock_fd = acquire_lock(logger)
    if lock_fd is None:
        return 0

    try:
        if not AGY_BIN.exists():
            logger.error("Không tìm thấy agy CLI tại %s. Hãy cài đặt agy trước.", AGY_BIN)
            return 1

        # 1. Fetch remote origin main
        logger.info("Kiểm tra git remote tại %s...", REPO_DIR)
        fetch_res = run_git(["fetch", "origin", "main"], cwd=REPO_DIR)
        if fetch_res.returncode != 0:
            logger.warning(
                "git fetch thất bại (mạng rớt hoặc không tới được GitHub): %s. Chờ chu kỳ sau.",
                fetch_res.stderr.strip(),
            )
            return 0

        # 2. Lấy SHA remote origin/main
        sha_res = run_git(["rev-parse", "origin/main"], cwd=REPO_DIR)
        if sha_res.returncode != 0:
            logger.warning("Không lấy được rev-parse origin/main: %s", sha_res.stderr.strip())
            return 0
        remote_sha = sha_res.stdout.strip()

        # 3. Đọc watermark
        last_seen = ""
        if WATERMARK_FILE.exists():
            last_seen = WATERMARK_FILE.read_text(encoding="utf-8").strip()

        if not args.force and remote_sha == last_seen:
            # Không có commit mới, thoát êm
            return 0

        logger.info(
            "Phát hiện commit mới trên remote: %s -> %s (hoặc có cờ --force). Kích hoạt agy...",
            last_seen[:8] if last_seen else "none",
            remote_sha[:8],
        )

        # 4. Chạy agy -p
        prompt_text = args.prompt.strip() or BRIEF_PROMPT
        env = os.environ.copy()
        env["PATH"] = f"{Path.home()}/.local/bin:/Volumes/External/homebrew/bin:/opt/homebrew/bin:/usr/local/bin:{env.get('PATH', '')}"

        start_time = time.time()
        logger.info("Đang chạy agy -p trong %s...", REPO_DIR)
        agy_res = subprocess.run(
            [str(AGY_BIN), "-p", prompt_text, "--dangerously-skip-permissions"],
            cwd=REPO_DIR,
            env=env,
            capture_output=True,
            text=True,
            timeout=1800,  # 30 phút tối đa cho một task
        )
        duration = round(time.time() - start_time, 2)

        if agy_res.returncode == 0:
            logger.info("agy hoàn tất thành công trong %ss.", duration)
            if agy_res.stdout:
                logger.info("Output agy (tóm tắt):\n%s", agy_res.stdout[-1000:].strip())
        else:
            logger.error(
                "agy kết thúc với mã lỗi %s sau %ss.\nSTDOUT:\n%s\nSTDERR:\n%s",
                agy_res.returncode,
                duration,
                agy_res.stdout[-1000:].strip(),
                agy_res.stderr[-1000:].strip(),
            )

        # 5. Cập nhật watermark về commit HEAD mới nhất sau khi chạy xong
        head_res = run_git(["rev-parse", "HEAD"], cwd=REPO_DIR)
        final_sha = head_res.stdout.strip() if head_res.returncode == 0 else remote_sha
        WATERMARK_FILE.write_text(final_sha + "\n", encoding="utf-8")
        logger.info("Đã cập nhật watermark: %s", final_sha[:8])
        return agy_res.returncode

    except subprocess.TimeoutExpired:
        logger.error("agy bị timeout sau 30 phút.")
        return 1
    except Exception as exc:
        logger.exception("Lỗi không mong muốn trong dev_watch: %s", exc)
        return 1
    finally:
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
            lock_fd.close()
        except Exception:
            pass


if __name__ == "__main__":
    sys.exit(main())
