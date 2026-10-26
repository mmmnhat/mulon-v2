#!/usr/bin/env python3
"""Mulon Dev-Watcher (Antigravity Autowatch).

Tự động theo dõi commit mới trên remote (origin/main), tự khởi chạy
Antigravity CLI headless (`agy -p`) để nhận việc từ AGENT_TASKS.md
khi có task TODO giao cho Antigravity.
Quy định theo T-18, T-19, T-20 trong AGENT_TASKS.md:
- Chạy định kỳ 5 phút qua macOS LaunchAgent (com.mulon.devwatch.plist).
- So sánh SHA remote với watermark local (~/.mulon-dev-watch/last_seen_sha).
- Khóa đơn (lockfile qua fcntl.flock) chống 2 agent chạy đè lên nhau.
- Không có việc hoặc mạng lỗi thì thoát sạch sẽ, không retry vô hạn.
- Watermark chỉ tiến khi agy chạy thành công, có trần retry (3 lần) khi lỗi.
- Không hardcode đường dẫn cá nhân (tự suy từ $HOME, sys.executable, shutil.which).
"""

from __future__ import annotations

import argparse
import fcntl
import json
import logging
import os
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

HOME_DIR = Path.home()
WATCH_DIR = HOME_DIR / ".mulon-dev-watch"
WATERMARK_FILE = WATCH_DIR / "last_seen_sha"
LOCK_FILE = WATCH_DIR / "dev_watch.lock"
LOG_DIR = WATCH_DIR / "log"
FAIL_COUNT_FILE = WATCH_DIR / "fail_counts.json"
MAX_RETRIES = 3

REPO_DIR = Path(os.environ.get("MULON_REPO_DIR", Path(__file__).resolve().parent.parent))

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


def find_agy_bin() -> Path:
    env_bin = os.environ.get("AGY_BIN")
    if env_bin and Path(env_bin).exists():
        return Path(env_bin)
    which_bin = shutil.which("agy")
    if which_bin:
        return Path(which_bin)
    candidate = HOME_DIR / ".local/bin/agy"
    return candidate


def build_env() -> dict[str, str]:
    env = os.environ.copy()
    candidate_paths = [
        str(HOME_DIR / ".local/bin"),
        str(Path(sys.executable).parent),
        "/opt/homebrew/bin",
        "/usr/local/bin",
    ]
    existing = env.get("PATH", "")
    valid_paths = [p for p in candidate_paths if Path(p).exists()]
    env["PATH"] = ":".join(valid_paths) + (f":{existing}" if existing else "")
    return env


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


def load_fail_counts() -> dict[str, int]:
    if FAIL_COUNT_FILE.exists():
        try:
            return json.loads(FAIL_COUNT_FILE.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {}


def save_fail_counts(counts: dict[str, int]) -> None:
    try:
        FAIL_COUNT_FILE.write_text(json.dumps(counts, indent=2), encoding="utf-8")
    except Exception:
        pass


def ensure_launcher_trampoline() -> None:
    """Tạo trampoline script trong ~/.mulon-dev-watch để launchd có thể gọi an toàn
    mà không bị lỗi TCC/getcwd trên /Volumes (gọi python3 trực tiếp vào file .py thay
    vì exec file .sh để tránh lỗi kernel execve exit 126)."""
    launcher_file = WATCH_DIR / "dev_watch_launcher.sh"
    launcher_content = f"""#!/bin/bash
set -euo pipefail
# Mulon Dev-Watcher Trampoline for macOS LaunchAgent
REPO_DIR="{REPO_DIR}"
export MULON_REPO_DIR="$REPO_DIR"

PYTHON_BIN="$(which python3 2>/dev/null || echo "/usr/bin/python3")"
SCRIPT_PATH="$REPO_DIR/scripts/dev_watch.py"

if [ -f "$SCRIPT_PATH" ]; then
    exec "$PYTHON_BIN" "$SCRIPT_PATH" "$@"
else
    echo "[ERROR] dev_watch_launcher.sh: Không tìm thấy $SCRIPT_PATH" >&2
    exit 127
fi
"""
    try:
        launcher_file.write_text(launcher_content, encoding="utf-8")
        launcher_file.chmod(0o755)
    except Exception:
        pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Mulon Dev-Watcher (Antigravity Autowatch)")
    parser.add_argument("--force", action="store_true", help="Chạy agy bỏ qua kiểm tra SHA watermark")
    parser.add_argument("--prompt", type=str, default="", help="Prompt tuỳ biến thay thế brief mặc định")
    parser.add_argument("--check-only", action="store_true", help="Chỉ kiểm tra remote SHA và ghi log, không chạy agy")
    args = parser.parse_args()

    WATCH_DIR.mkdir(parents=True, exist_ok=True)
    ensure_launcher_trampoline()
    logger = setup_logger()

    lock_fd = acquire_lock(logger)
    if lock_fd is None:
        return 0

    try:
        agy_bin = find_agy_bin()
        if not agy_bin.exists():
            logger.error("Không tìm thấy agy CLI tại %s. Hãy cài đặt agy trước.", agy_bin)
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
            logger.info("Không có commit mới trên remote (SHA không đổi: %s). Thoát chu kỳ.", remote_sha[:8])
            return 0

        logger.info(
            "Phát hiện commit mới trên remote: %s -> %s (hoặc có cờ --force).",
            last_seen[:8] if last_seen else "none",
            remote_sha[:8],
        )

        if args.check_only:
            WATERMARK_FILE.write_text(remote_sha + "\n", encoding="utf-8")
            logger.info("[check-only] Đã đồng bộ watermark về %s.", remote_sha[:8])
            return 0

        # 4. Chạy agy -p
        prompt_text = args.prompt.strip() or BRIEF_PROMPT
        env = build_env()

        start_time = time.time()
        logger.info("Đang kích hoạt agy -p trong %s...", REPO_DIR)
        agy_res = subprocess.run(
            [str(agy_bin), "-p", prompt_text, "--dangerously-skip-permissions"],
            cwd=REPO_DIR,
            env=env,
            capture_output=True,
            text=True,
            timeout=1800,  # 30 phút tối đa cho một task
        )
        duration = round(time.time() - start_time, 2)

        # 5. Xử lý kết quả & Cập nhật watermark (T-19: chỉ tiến watermark khi agy thành công hoặc hết trần retry)
        counts = load_fail_counts()
        if agy_res.returncode == 0:
            logger.info("agy hoàn tất thành công trong %ss.", duration)
            if agy_res.stdout:
                logger.info("Output agy (tóm tắt):\n%s", agy_res.stdout[-1000:].strip())
            counts.pop(remote_sha, None)
            save_fail_counts(counts)

            head_res = run_git(["rev-parse", "HEAD"], cwd=REPO_DIR)
            final_sha = head_res.stdout.strip() if head_res.returncode == 0 else remote_sha
            WATERMARK_FILE.write_text(final_sha + "\n", encoding="utf-8")
            logger.info("Đã cập nhật watermark: %s", final_sha[:8])
            return 0
        else:
            current_fails = counts.get(remote_sha, 0) + 1
            counts[remote_sha] = current_fails
            save_fail_counts(counts)

            logger.error(
                "agy kết thúc với mã lỗi %s sau %ss (lần thử %s/%s).\nSTDOUT:\n%s\nSTDERR:\n%s",
                agy_res.returncode,
                duration,
                current_fails,
                MAX_RETRIES,
                agy_res.stdout[-1000:].strip(),
                agy_res.stderr[-1000:].strip(),
            )

            if current_fails >= MAX_RETRIES:
                logger.error(
                    "Đã đạt ngưỡng trần thử lại (%s lần) cho commit %s. Tiến watermark để tránh vòng lặp vô hạn.",
                    MAX_RETRIES,
                    remote_sha[:8],
                )
                WATERMARK_FILE.write_text(remote_sha + "\n", encoding="utf-8")
            else:
                logger.warning(
                    "Giữ nguyên watermark cũ để thử lại ở chu kỳ tiếp theo."
                )
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
