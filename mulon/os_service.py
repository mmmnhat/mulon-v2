"""mulon.os_service — Quản lý tiến trình và dịch vụ nền đa hệ điều hành (T-15).

Hỗ trợ:
- macOS: launchd (User LaunchAgents, com.mulon.bot.plist, com.mulon.autowatch.plist)
- Linux: systemd (User services, ~/.config/systemd/user/)
- Windows: Windows Task Scheduler (schtasks) và batch/powershell runners.
"""

from __future__ import annotations

import argparse
import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Optional

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def get_current_os() -> str:
    """Trả về 'darwin', 'linux', hoặc 'win32'."""
    p = sys.platform.lower()
    if p.startswith("darwin"):
        return "darwin"
    if p.startswith("linux"):
        return "linux"
    if p.startswith("win"):
        return "win32"
    return p


# ---------------------------------------------------------------------------
# macOS: launchd manager
# ---------------------------------------------------------------------------

class LaunchdManager:
    """Quản lý LaunchAgent cho macOS."""

    def __init__(self, project_root: Optional[Path] = None):
        self.root = project_root or PROJECT_ROOT
        self.launch_agents_dir = Path.home() / "Library" / "LaunchAgents"
        self.bot_plist = self.launch_agents_dir / "com.mulon.bot.plist"
        self.autowatch_plist = self.launch_agents_dir / "com.mulon.autowatch.plist"

    def _render_bot_plist(self) -> str:
        py_exe = sys.executable
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.mulon.bot</string>
    <key>WorkingDirectory</key>
    <string>{self.root}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{py_exe}</string>
        <string>-m</string>
        <string>mulon.main</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{self.root}/data/logs/bot_stdout.log</string>
    <key>StandardErrorPath</key>
    <string>{self.root}/data/logs/bot_stderr.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>{Path(py_exe).parent}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
</dict>
</plist>
"""

    def _render_autowatch_plist(self) -> str:
        py_exe = sys.executable
        return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.mulon.autowatch</string>
    <key>WorkingDirectory</key>
    <string>{self.root}</string>
    <key>ProgramArguments</key>
    <array>
        <string>{py_exe}</string>
        <string>scripts/auto_watch.py</string>
        <string>--enable</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{self.root}/data/logs/autowatch_stdout.log</string>
    <key>StandardErrorPath</key>
    <string>{self.root}/data/logs/autowatch_stderr.log</string>
    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>{Path(py_exe).parent}:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin</string>
    </dict>
</dict>
</plist>
"""

    def install(self, service: str = "all") -> bool:
        self.launch_agents_dir.mkdir(parents=True, exist_ok=True)
        (self.root / "data" / "logs").mkdir(parents=True, exist_ok=True)

        if service in ("bot", "all"):
            self.bot_plist.write_text(self._render_bot_plist(), encoding="utf-8")
            subprocess.run(["launchctl", "unload", str(self.bot_plist)], capture_output=True)
            res = subprocess.run(["launchctl", "load", "-w", str(self.bot_plist)], capture_output=True, text=True)
            if res.returncode == 0:
                print(f"✅ Đã cài đặt dịch vụ launchd: com.mulon.bot -> {self.bot_plist}")
            else:
                print(f"⚠️ Lỗi nạp com.mulon.bot: {res.stderr.strip()}")

        if service in ("autowatch", "all"):
            self.autowatch_plist.write_text(self._render_autowatch_plist(), encoding="utf-8")
            subprocess.run(["launchctl", "unload", str(self.autowatch_plist)], capture_output=True)
            res = subprocess.run(["launchctl", "load", "-w", str(self.autowatch_plist)], capture_output=True, text=True)
            if res.returncode == 0:
                print(f"✅ Đã cài đặt dịch vụ launchd: com.mulon.autowatch -> {self.autowatch_plist}")
            else:
                print(f"⚠️ Lỗi nạp com.mulon.autowatch: {res.stderr.strip()}")
        return True

    def uninstall(self, service: str = "all") -> bool:
        if service in ("bot", "all") and self.bot_plist.is_file():
            subprocess.run(["launchctl", "unload", "-w", str(self.bot_plist)], capture_output=True)
            self.bot_plist.unlink()
            print("✅ Đã gỡ bỏ dịch vụ com.mulon.bot")
        if service in ("autowatch", "all") and self.autowatch_plist.is_file():
            subprocess.run(["launchctl", "unload", "-w", str(self.autowatch_plist)], capture_output=True)
            self.autowatch_plist.unlink()
            print("✅ Đã gỡ bỏ dịch vụ com.mulon.autowatch")
        return True

    def start(self, service: str = "bot") -> bool:
        label = "com.mulon.bot" if service == "bot" else "com.mulon.autowatch"
        subprocess.run(["launchctl", "start", label], check=False)
        print(f"🚀 Đã gửi lệnh khởi động {label}")
        return True

    def stop(self, service: str = "bot") -> bool:
        label = "com.mulon.bot" if service == "bot" else "com.mulon.autowatch"
        subprocess.run(["launchctl", "stop", label], check=False)
        print(f"⏹ Đã gửi lệnh dừng {label}")
        return True

    def status(self) -> dict[str, str]:
        res = subprocess.run(["launchctl", "list"], capture_output=True, text=True)
        out = res.stdout
        bot_st = "ĐANG CHẠY" if "com.mulon.bot" in out else ("ĐÃ CÀI (DỪNG)" if self.bot_plist.is_file() else "CHƯA CÀI")
        watch_st = "ĐANG CHẠY" if "com.mulon.autowatch" in out else ("ĐÃ CÀI (DỪNG)" if self.autowatch_plist.is_file() else "CHƯA CÀI")
        return {"bot": bot_st, "autowatch": watch_st}


# ---------------------------------------------------------------------------
# Linux: systemd user manager
# ---------------------------------------------------------------------------

class SystemdManager:
    """Quản lý systemd user service cho Linux."""

    def __init__(self, project_root: Optional[Path] = None):
        self.root = project_root or PROJECT_ROOT
        self.service_dir = Path.home() / ".config" / "systemd" / "user"
        self.bot_unit = self.service_dir / "mulon.service"
        self.autowatch_unit = self.service_dir / "mulon-autowatch.service"

    def _render_bot_unit(self) -> str:
        py_exe = sys.executable
        return f"""[Unit]
Description=MuLon Telegram Bot & Mini App Server
After=network.target

[Service]
Type=simple
WorkingDirectory={self.root}
ExecStart={py_exe} -m mulon.main
Restart=always
RestartSec=5
StandardOutput=append:{self.root}/data/logs/bot_stdout.log
StandardError=append:{self.root}/data/logs/bot_stderr.log

[Install]
WantedBy=default.target
"""

    def _render_autowatch_unit(self) -> str:
        py_exe = sys.executable
        return f"""[Unit]
Description=MuLon Auto-Watcher & Supervisor
After=network.target

[Service]
Type=simple
WorkingDirectory={self.root}
ExecStart={py_exe} scripts/auto_watch.py --enable
Restart=always
RestartSec=10
StandardOutput=append:{self.root}/data/logs/autowatch_stdout.log
StandardError=append:{self.root}/data/logs/autowatch_stderr.log

[Install]
WantedBy=default.target
"""

    def install(self, service: str = "all") -> bool:
        self.service_dir.mkdir(parents=True, exist_ok=True)
        (self.root / "data" / "logs").mkdir(parents=True, exist_ok=True)

        if service in ("bot", "all"):
            self.bot_unit.write_text(self._render_bot_unit(), encoding="utf-8")
        if service in ("autowatch", "all"):
            self.autowatch_unit.write_text(self._render_autowatch_unit(), encoding="utf-8")

        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)

        if service in ("bot", "all"):
            subprocess.run(["systemctl", "--user", "enable", "mulon.service"], check=False)
            subprocess.run(["systemctl", "--user", "start", "mulon.service"], check=False)
            print(f"✅ Đã cài đặt và khởi chạy systemd service: mulon.service")
        if service in ("autowatch", "all"):
            subprocess.run(["systemctl", "--user", "enable", "mulon-autowatch.service"], check=False)
            subprocess.run(["systemctl", "--user", "start", "mulon-autowatch.service"], check=False)
            print(f"✅ Đã cài đặt và khởi chạy systemd service: mulon-autowatch.service")
        return True

    def uninstall(self, service: str = "all") -> bool:
        if service in ("bot", "all"):
            subprocess.run(["systemctl", "--user", "stop", "mulon.service"], check=False)
            subprocess.run(["systemctl", "--user", "disable", "mulon.service"], check=False)
            if self.bot_unit.is_file():
                self.bot_unit.unlink()
            print("✅ Đã gỡ bỏ mulon.service")
        if service in ("autowatch", "all"):
            subprocess.run(["systemctl", "--user", "stop", "mulon-autowatch.service"], check=False)
            subprocess.run(["systemctl", "--user", "disable", "mulon-autowatch.service"], check=False)
            if self.autowatch_unit.is_file():
                self.autowatch_unit.unlink()
            print("✅ Đã gỡ bỏ mulon-autowatch.service")
        subprocess.run(["systemctl", "--user", "daemon-reload"], check=False)
        return True

    def start(self, service: str = "bot") -> bool:
        unit = "mulon.service" if service == "bot" else "mulon-autowatch.service"
        subprocess.run(["systemctl", "--user", "start", unit], check=False)
        print(f"🚀 Đã gửi lệnh khởi động {unit}")
        return True

    def stop(self, service: str = "bot") -> bool:
        unit = "mulon.service" if service == "bot" else "mulon-autowatch.service"
        subprocess.run(["systemctl", "--user", "stop", unit], check=False)
        print(f"⏹ Đã gửi lệnh dừng {unit}")
        return True

    def status(self) -> dict[str, str]:
        def _check(unit: str, file_path: Path) -> str:
            res = subprocess.run(["systemctl", "--user", "is-active", unit], capture_output=True, text=True)
            status_text = res.stdout.strip()
            if status_text == "active":
                return "ĐANG CHẠY"
            if file_path.is_file():
                return f"ĐÃ CÀI ({status_text.upper() or 'DỪNG'})"
            return "CHƯA CÀI"

        return {
            "bot": _check("mulon.service", self.bot_unit),
            "autowatch": _check("mulon-autowatch.service", self.autowatch_unit),
        }


# ---------------------------------------------------------------------------
# Windows: Task Scheduler & Batch runner manager
# ---------------------------------------------------------------------------

class WindowsServiceManager:
    """Quản lý tác vụ chạy ngầm Task Scheduler và scripts cho Windows."""

    def __init__(self, project_root: Optional[Path] = None):
        self.root = project_root or PROJECT_ROOT
        self.bot_task = "MulonBot"
        self.autowatch_task = "MulonAutoWatch"
        self.scripts_dir = self.root / "scripts"

    def _generate_bat_launchers(self) -> None:
        """Tạo các file .bat khởi động nhanh trên Windows."""
        self.scripts_dir.mkdir(parents=True, exist_ok=True)
        py_exe = sys.executable

        run_bot_bat = self.scripts_dir / "run_bot.bat"
        run_bot_bat.write_text(f"""@echo off
cd /d "{self.root}"
"{py_exe}" -m mulon.main
pause
""", encoding="utf-8")

        run_autowatch_bat = self.scripts_dir / "run_autowatch.bat"
        run_autowatch_bat.write_text(f"""@echo off
cd /d "{self.root}"
"{py_exe}" scripts\\auto_watch.py --enable
pause
""", encoding="utf-8")

        print(f"✅ Đã tạo file khởi chạy Windows: {run_bot_bat} và {run_autowatch_bat}")

    def install(self, service: str = "all") -> bool:
        self._generate_bat_launchers()
        (self.root / "data" / "logs").mkdir(parents=True, exist_ok=True)
        py_exe = sys.executable

        if service in ("bot", "all"):
            cmd = [
                "schtasks", "/Create", "/F",
                "/TN", self.bot_task,
                "/TR", f'"{py_exe}" -m mulon.main',
                "/SC", "ONLOGON",
                "/RL", "LIMITED",
            ]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode == 0:
                print(f"✅ Đã đăng ký Windows Task Scheduler: {self.bot_task} (khởi động khi đăng nhập)")
            else:
                print(f"⚠️ Ghi chú Task Scheduler: {res.stderr.strip() or res.stdout.strip()}")

        if service in ("autowatch", "all"):
            cmd = [
                "schtasks", "/Create", "/F",
                "/TN", self.autowatch_task,
                "/TR", f'"{py_exe}" "{self.root / "scripts" / "auto_watch.py"}" --enable',
                "/SC", "ONLOGON",
                "/RL", "LIMITED",
            ]
            res = subprocess.run(cmd, capture_output=True, text=True)
            if res.returncode == 0:
                print(f"✅ Đã đăng ký Windows Task Scheduler: {self.autowatch_task}")
            else:
                print(f"⚠️ Ghi chú Task Scheduler: {res.stderr.strip() or res.stdout.strip()}")
        return True

    def uninstall(self, service: str = "all") -> bool:
        if service in ("bot", "all"):
            subprocess.run(["schtasks", "/Delete", "/TN", self.bot_task, "/F"], capture_output=True)
            print(f"✅ Đã xóa task {self.bot_task}")
        if service in ("autowatch", "all"):
            subprocess.run(["schtasks", "/Delete", "/TN", self.autowatch_task, "/F"], capture_output=True)
            print(f"✅ Đã xóa task {self.autowatch_task}")
        return True

    def start(self, service: str = "bot") -> bool:
        task = self.bot_task if service == "bot" else self.autowatch_task
        res = subprocess.run(["schtasks", "/Run", "/TN", task], capture_output=True, text=True)
        if res.returncode == 0:
            print(f"🚀 Đã khởi chạy task {task}")
        else:
            print(f"⚠️ Không thể khởi chạy {task}: {res.stderr.strip() or res.stdout.strip()}")
        return True

    def stop(self, service: str = "bot") -> bool:
        task = self.bot_task if service == "bot" else self.autowatch_task
        res = subprocess.run(["schtasks", "/End", "/TN", task], capture_output=True, text=True)
        print(f"⏹ Đã gửi lệnh dừng task {task}")
        return True

    def status(self) -> dict[str, str]:
        def _check(task: str) -> str:
            res = subprocess.run(["schtasks", "/Query", "/TN", task], capture_output=True, text=True)
            if res.returncode == 0:
                return "ĐÃ CÀI (Task Scheduler)"
            return "CHƯA CÀI"

        return {
            "bot": _check(self.bot_task),
            "autowatch": _check(self.autowatch_task),
        }


def get_service_manager(project_root: Optional[Path] = None):
    """Lấy service manager phù hợp với hệ điều hành hiện tại."""
    os_name = get_current_os()
    if os_name == "darwin":
        return LaunchdManager(project_root)
    elif os_name == "linux":
        return SystemdManager(project_root)
    else:
        return WindowsServiceManager(project_root)


def main() -> None:
    parser = argparse.ArgumentParser(description="Mulon OS Service Manager (macOS, Linux, Windows)")
    parser.add_argument("action", choices=["status", "install", "uninstall", "start", "stop"],
                        help="Hành động dịch vụ")
    parser.add_argument("--service", choices=["bot", "autowatch", "all"], default="all",
                        help="Chọn dịch vụ áp dụng (mặc định: all)")
    args = parser.parse_args()

    mgr = get_service_manager()
    os_name = get_current_os()
    print(f"=== Quản lý dịch vụ MuLon ({platform.system()} {platform.release()}) ===")

    if args.action == "status":
        st = mgr.status()
        print(f"• Dịch vụ Bot:        {st['bot']}")
        print(f"• Dịch vụ Auto-Watch: {st['autowatch']}")
    elif args.action == "install":
        mgr.install(args.service)
    elif args.action == "uninstall":
        mgr.uninstall(args.service)
    elif args.action == "start":
        target = "bot" if args.service == "all" else args.service
        mgr.start(target)
    elif args.action == "stop":
        target = "bot" if args.service == "all" else args.service
        mgr.stop(target)


if __name__ == "__main__":
    main()
