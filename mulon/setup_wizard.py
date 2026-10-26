"""mulon.setup_wizard — Trình hướng dẫn thiết lập bản cài MuLon (T-15).

Hỗ trợ cả chế độ tương tác (interactive CLI) và tự động (non-interactive).
Tạo và cấu hình file .env, khởi tạo allowlist local, sinh claim token nếu cần,
và chuẩn bị sẵn môi trường để bot có thể chạy ngay trên Windows, macOS, Linux.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Optional

from mulon.paths import PROJECT_ROOT, get_default_paths, resolve_path
from mulon.allowlist import save_allowlist, get_or_create_claim_token


def _update_or_append_env(env_path: Path, updates: dict[str, str]) -> None:
    """Cập nhật hoặc thêm các biến vào file .env một cách an toàn."""
    content = ""
    if env_path.is_file():
        content = env_path.read_text(encoding="utf-8")
    else:
        # Nếu chưa có .env, nạp từ .env.example làm nền
        example_path = PROJECT_ROOT / ".env.example"
        if example_path.is_file():
            content = example_path.read_text(encoding="utf-8")

    lines = content.splitlines()
    keys_remaining = dict(updates)

    new_lines: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped and not stripped.startswith("#") and "=" in stripped:
            k = stripped.split("=", 1)[0].strip()
            if k in keys_remaining:
                new_val = keys_remaining.pop(k)
                new_lines.append(f"{k}={new_val}")
                continue
        new_lines.append(line)

    if keys_remaining:
        if new_lines and new_lines[-1].strip():
            new_lines.append("")
        new_lines.append("# --- Tự động cấu hình bởi Mulon Setup Wizard ---")
        for k, v in keys_remaining.items():
            new_lines.append(f"{k}={v}")

    env_path.write_text("\n".join(new_lines) + "\n", encoding="utf-8")


def run_setup(
    bot_token: Optional[str] = None,
    owner_id: Optional[int] = None,
    proxy_url: Optional[str] = None,
    model_brain: Optional[str] = None,
    timezone: Optional[str] = None,
    use_platformdirs: bool = False,
    non_interactive: bool = False,
    project_root: Optional[Path] = None,
) -> bool:
    """Thực thi quy trình thiết lập cấu hình MuLon."""
    root = project_root or PROJECT_ROOT
    env_file = root / ".env"
    paths = get_default_paths(use_platformdirs=use_platformdirs, project_root=root)

    # Đảm bảo các thư mục cần thiết tồn tại
    for p in (paths["data_dir"], paths["workspace_dir"], paths["dossier_dir"], paths["artifact_dir"]):
        p.mkdir(parents=True, exist_ok=True)

    if not non_interactive and sys.stdin.isatty():
        print("==================================================================")
        print("         MuLon Setup Wizard — Thiết lập bản cài đặt MuLon         ")
        print("==================================================================")
        print("Trình cài đặt sẽ hỗ trợ bạn cấu hình các thông số cơ bản.\n")

        # 1. Telegram Bot Token
        if not bot_token:
            while True:
                val = input("1. Nhập Telegram Bot Token (từ @BotFather): ").strip()
                if val:
                    bot_token = val
                    break
                print("   ⚠️ Token không được để trống!")

        # 2. Telegram Owner ID
        if owner_id is None:
            raw_id = input("2. Nhập Telegram User ID của chủ sở hữu [bỏ trống để ghép nối qua /setup sau]: ").strip()
            if raw_id:
                try:
                    owner_id = int(raw_id)
                except ValueError:
                    print("   ⚠️ User ID không hợp lệ, sẽ dùng chế độ ghép nối /setup sau.")
                    owner_id = 0
            else:
                owner_id = 0

        # 3. Proxy Base URL
        if not proxy_url:
            raw_proxy = input("3. Nhập Proxy Base URL [mặc định: http://127.0.0.1:8317/v1]: ").strip()
            proxy_url = raw_proxy or "http://127.0.0.1:8317/v1"

        # 4. Model Brain
        if not model_brain:
            raw_model = input("4. Nhập Model chính [mặc định: gemini-3.8-flash]: ").strip()
            model_brain = raw_model or "gemini-3.8-flash"

        # 5. Timezone
        if not timezone:
            raw_tz = input("5. Nhập múi giờ [mặc định: Asia/Ho_Chi_Minh]: ").strip()
            timezone = raw_tz or "Asia/Ho_Chi_Minh"

    # Giá trị mặc định nếu chạy non-interactive mà không truyền
    final_token = bot_token or ""
    final_owner_id = int(owner_id or 0)
    final_proxy = proxy_url or "http://127.0.0.1:8317/v1"
    final_model = model_brain or "gemini-3.8-flash"
    final_tz = timezone or "Asia/Ho_Chi_Minh"

    # Cập nhật file .env
    env_updates: dict[str, str] = {
        "PROXY_BASE_URL": final_proxy,
        "MODEL_BRAIN": final_model,
        "DEFAULT_TIMEZONE": final_tz,
    }
    if final_token:
        env_updates["TELEGRAM_BOT_TOKEN"] = final_token
    if final_owner_id > 0:
        env_updates["ALLOWED_USER_ID"] = str(final_owner_id)
    if use_platformdirs:
        env_updates["MULON_USE_PLATFORMDIRS"] = "1"

    _update_or_append_env(env_file, env_updates)

    # Cập nhật allowlist local
    allowlist_file = paths["allowlist_path"]
    if final_owner_id > 0:
        save_allowlist(allowlist_file, owner_id=final_owner_id, allowed_users=[final_owner_id])
    else:
        # Tạo claim token để người dùng có thể gửi /setup <token> qua Telegram
        claim_file = paths["claim_token_path"]
        tok = get_or_create_claim_token(claim_file)
        if not non_interactive:
            print("\n------------------------------------------------------------------")
            print(f"🔑 Mã Claim Token của bản cài: {tok}")
            print("   Khi khởi động bot, hãy gửi lệnh sau từ Telegram để nhận quyền chủ bot:")
            print(f"   /setup {tok}")
            print("------------------------------------------------------------------")

    if not non_interactive:
        print("\n✅ Thiết lập cấu hình thành công!")
        print(f"• File .env: {env_file}")
        print(f"• Thư mục dữ liệu: {paths['data_dir']}")
        print(f"• Chủ sở hữu: {final_owner_id if final_owner_id > 0 else '(chưa đặt — ghép nối qua bot)'}")
        print("\n🚀 Lệnh khởi động bot:")
        print("   python -m mulon.main")
        print("⚙️ Cài đặt chạy ngầm tự khởi động cùng máy:")
        print("   python -m mulon.service install\n")

    return True


def main() -> None:
    parser = argparse.ArgumentParser(description="Mulon Setup Wizard")
    parser.add_argument("--bot-token", type=str, help="Telegram Bot Token")
    parser.add_argument("--owner-id", type=int, help="Telegram Owner User ID")
    parser.add_argument("--proxy-url", type=str, help="Proxy Base URL")
    parser.add_argument("--model", type=str, help="Model Brain")
    parser.add_argument("--timezone", type=str, help="Múi giờ")
    parser.add_argument("--use-platformdirs", action="store_true", help="Sử dụng platformdirs cho dữ liệu")
    parser.add_argument("--non-interactive", action="store_true", help="Chạy không tương tác")
    args = parser.parse_args()

    run_setup(
        bot_token=args.bot_token,
        owner_id=args.owner_id,
        proxy_url=args.proxy_url,
        model_brain=args.model,
        timezone=args.timezone,
        use_platformdirs=args.use_platformdirs,
        non_interactive=args.non_interactive,
    )


if __name__ == "__main__":
    main()
