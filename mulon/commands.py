"""Bảng danh mục lệnh Slash Command tập trung của Mulon (T-26).

Nguồn sự thật duy nhất cho:
- Menu "/" trên Telegram (set_my_commands)
- Lệnh /help chi tiết theo nhóm
- Bảng tra cứu tương thích ngược (BOT_COMMANDS)
- Tập hợp mọi lệnh và bí danh hợp lệ để kiểm tra lệnh lạ
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class CommandCategory(str, Enum):
    BASIC = "basic"              # Cơ bản
    WORK_DATA = "work_data"      # Việc & Dữ liệu
    ADVANCED = "advanced"        # Nâng cao & Tài khoản
    INTERNAL = "internal"        # Nội bộ / Thao tác thẻ item (không hiện trong /help)


@dataclass(frozen=True)
class CommandDef:
    name: str
    description: str
    category: CommandCategory
    in_menu: bool = False
    in_help: bool = True
    aliases: tuple[str, ...] = field(default_factory=tuple)
    is_destructive: bool = False
    warning: str = ""
    usage: str = ""


# Bảng khai báo toàn bộ các lệnh hợp lệ của bot
COMMAND_DEFINITIONS: list[CommandDef] = [
    # --- 1. CƠ BẢN (10 lệnh cốt lõi cho Menu "/") ---
    CommandDef(
        name="start",
        description="Bắt đầu / Chào Mulon",
        category=CommandCategory.BASIC,
        in_menu=True,
    ),
    CommandDef(
        name="menu",
        description="Mở bảng điều khiển (Mini App)",
        category=CommandCategory.BASIC,
        in_menu=True,
    ),
    CommandDef(
        name="new",
        description="Chốt phiên, bắt đầu ngữ cảnh mới",
        category=CommandCategory.BASIC,
        in_menu=True,
    ),
    CommandDef(
        name="cancel",
        description="Dừng tác vụ đang chạy",
        category=CommandCategory.BASIC,
        in_menu=True,
        aliases=("stop",),
    ),
    CommandDef(
        name="status",
        description="Trạng thái hệ thống",
        category=CommandCategory.BASIC,
        in_menu=True,
    ),
    CommandDef(
        name="model",
        description="Xem hoặc đổi model AI (/model <tên>)",
        category=CommandCategory.BASIC,
        in_menu=True,
        usage="/model [tên_model]",
    ),
    CommandDef(
        name="vault",
        description="Nhập API Key & Khóa bảo mật",
        category=CommandCategory.BASIC,
        in_menu=True,
    ),
    CommandDef(
        name="upcoming",
        description="Sắp tới (tác vụ & lịch trình)",
        category=CommandCategory.BASIC,
        in_menu=True,
        aliases=("saptol", "lich"),
    ),
    CommandDef(
        name="goals",
        description="Xem mục tiêu đang theo dõi",
        category=CommandCategory.BASIC,
        in_menu=True,
        aliases=("goal",),
        usage="/goals hoặc /goal create, close, briefing",
    ),
    CommandDef(
        name="help",
        description="Hướng dẫn danh sách lệnh",
        category=CommandCategory.BASIC,
        in_menu=True,
    ),

    # --- 2. VIỆC & DỮ LIỆU ---
    CommandDef(
        name="memory",
        description="Tóm tắt bộ nhớ & tri thức đang lưu",
        category=CommandCategory.WORK_DATA,
    ),
    CommandDef(
        name="library",
        description="Xem Thư viện tài liệu & media",
        category=CommandCategory.WORK_DATA,
        usage="/library [từ_khóa]",
    ),
    CommandDef(
        name="ideas",
        description="Sinh và quản lý thẻ ý tưởng",
        category=CommandCategory.WORK_DATA,
    ),
    CommandDef(
        name="feed_now",
        description="Đăng ngay 1 bài Feed công nghệ & AI",
        category=CommandCategory.WORK_DATA,
    ),
    CommandDef(
        name="feedbrief",
        description="Xem hoặc sửa brief của Feed",
        category=CommandCategory.WORK_DATA,
    ),
    CommandDef(
        name="feedsources",
        description="Quản lý nguồn bổ sung của Feed",
        category=CommandCategory.WORK_DATA,
    ),
    CommandDef(
        name="chatphu",
        description="Tạo hoặc mở chat phụ (topic tự do)",
        category=CommandCategory.WORK_DATA,
        aliases=("chatphu_mo",),
    ),
    CommandDef(
        name="chatphu_dong",
        description="Đóng chat phụ hiện tại",
        category=CommandCategory.WORK_DATA,
        aliases=("dongchat",),
    ),
    CommandDef(
        name="chatphu_list",
        description="Danh sách các chat phụ đang mở",
        category=CommandCategory.WORK_DATA,
    ),
    CommandDef(
        name="topics",
        description="Quản lý chủ đề Topic-tab trong nhóm",
        category=CommandCategory.WORK_DATA,
        aliases=("setup_topics",),
    ),
    CommandDef(
        name="notes",
        description="Danh sách ghi chú chủ động",
        category=CommandCategory.WORK_DATA,
    ),
    CommandDef(
        name="quyen",
        description="Xem phân quyền công cụ của bot",
        category=CommandCategory.WORK_DATA,
    ),
    CommandDef(
        name="approvals",
        description="Lịch sử duyệt quyền gần đây",
        category=CommandCategory.WORK_DATA,
    ),

    # --- 3. NÂNG CAO & KẾT NỐI ---
    CommandDef(
        name="restart",
        description="Khởi động lại bot tiến trình",
        category=CommandCategory.ADVANCED,
        is_destructive=True,
        warning="Khởi động lại toàn bộ tiến trình bot",
    ),
    CommandDef(
        name="forget",
        description="Quên thông tin đã ghi nhớ (có xác nhận)",
        category=CommandCategory.ADVANCED,
        is_destructive=True,
        warning="Xoá vĩnh viễn dữ kiện khỏi bộ nhớ",
    ),
    CommandDef(
        name="export_memory",
        description="Xuất bản sao lưu toàn bộ bộ nhớ",
        category=CommandCategory.ADVANCED,
    ),
    CommandDef(
        name="google_auth",
        description="Xác thực tài khoản Google Workspace",
        category=CommandCategory.ADVANCED,
    ),
    CommandDef(
        name="claim",
        description="Nhận quyền sở hữu bot lần đầu (/claim <mã>)",
        category=CommandCategory.ADVANCED,
    ),
    CommandDef(
        name="setup",
        description="Quản lý allowlist người dùng bot (/setup add, remove)",
        category=CommandCategory.ADVANCED,
    ),
    CommandDef(
        name="voiceon",
        description="Bật tương tác bằng giọng nói",
        category=CommandCategory.ADVANCED,
    ),
    CommandDef(
        name="voiceoff",
        description="Tắt tương tác bằng giọng nói",
        category=CommandCategory.ADVANCED,
    ),
    CommandDef(
        name="zalo",
        description="Kết nối Zalo cá nhân (/zalo status, qr, disconnect)",
        category=CommandCategory.ADVANCED,
    ),
    CommandDef(
        name="telethon",
        description="Kết nối Telegram cá nhân userbot (/telethon status, qr)",
        category=CommandCategory.ADVANCED,
        aliases=("telegram_user",),
    ),
    CommandDef(
        name="facebook",
        description="Kết nối Facebook cá nhân (/facebook status, connect)",
        category=CommandCategory.ADVANCED,
    ),
    CommandDef(
        name="instagram",
        description="Kết nối Instagram cá nhân (/instagram status, connect)",
        category=CommandCategory.ADVANCED,
        aliases=("ig",),
    ),
    CommandDef(
        name="threads",
        description="Kết nối Threads cá nhân (/threads status, connect)",
        category=CommandCategory.ADVANCED,
        aliases=("threads_dm",),
    ),
    CommandDef(
        name="google",
        description="Quản lý Google Workspace (/google status, mail, drive)",
        category=CommandCategory.ADVANCED,
    ),
    CommandDef(
        name="fbpage",
        description="Kết nối Facebook Page (/fbpage status, post, feed)",
        category=CommandCategory.ADVANCED,
    ),
    CommandDef(
        name="tiktok",
        description="Kết nối TikTok Creator (/tiktok status, post, videos)",
        category=CommandCategory.ADVANCED,
    ),
    CommandDef(
        name="business",
        description="Xem trạng thái Telegram Business Chatbot (/business)",
        category=CommandCategory.ADVANCED,
        aliases=("biz",),
    ),
    CommandDef(
        name="the_duyet",
        description="Gửi thẻ phê duyệt thử nghiệm (chỉ bật khi dev)",
        category=CommandCategory.ADVANCED,
        warning="Chỉ hoạt động khi bật ENABLE_DEV_COMMANDS=1",
    ),

    # --- 4. NỘI BỘ / THAO TÁC THẺ ITEM (Ẩn khỏi /help & menu) ---
    CommandDef(
        name="pin_item",
        description="Ghim item Library theo id",
        category=CommandCategory.INTERNAL,
        in_help=False,
    ),
    CommandDef(
        name="rename_item",
        description="Đổi tên item Library theo id",
        category=CommandCategory.INTERNAL,
        in_help=False,
    ),
    CommandDef(
        name="trash_item",
        description="Chuyển item Library vào thùng rác",
        category=CommandCategory.INTERNAL,
        in_help=False,
    ),
    CommandDef(
        name="restore_item",
        description="Khôi phục item Library từ thùng rác",
        category=CommandCategory.INTERNAL,
        in_help=False,
    ),
    CommandDef(
        name="share_item",
        description="Tạo link chia sẻ item Library",
        category=CommandCategory.INTERNAL,
        in_help=False,
    ),
    CommandDef(
        name="note_ok",
        description="Duyệt ghi chú chủ động",
        category=CommandCategory.INTERNAL,
        in_help=False,
    ),
    CommandDef(
        name="note_bo",
        description="Bỏ qua ghi chú chủ động",
        category=CommandCategory.INTERNAL,
        in_help=False,
    ),
    CommandDef(
        name="idea_do",
        description="Thực hiện thẻ ý tưởng",
        category=CommandCategory.INTERNAL,
        in_help=False,
    ),
    CommandDef(
        name="idea_bo",
        description="Bỏ qua thẻ ý tưởng",
        category=CommandCategory.INTERNAL,
        in_help=False,
    ),
]

# Map tra cứu nhanh từ tên lệnh -> CommandDef
COMMAND_BY_NAME: dict[str, CommandDef] = {cmd.name: cmd for cmd in COMMAND_DEFINITIONS}

# Bảng bí danh: alias -> command chính
ALIAS_MAP: dict[str, str] = {}
for cmd in COMMAND_DEFINITIONS:
    for a in cmd.aliases:
        ALIAS_MAP[a] = cmd.name

# 10 lệnh rút gọn cho Menu "/" của Telegram UI (set_my_commands)
MENU_COMMANDS: list[tuple[str, str]] = [
    (cmd.name, cmd.description)
    for cmd in COMMAND_DEFINITIONS
    if cmd.in_menu
]

# Danh sách đầy đủ cho tương thích ngược với các test hiện có
BOT_COMMANDS: list[tuple[str, str]] = [
    ("start", "Bắt đầu / Chào Mulon"),
    ("help", "Xem hướng dẫn và danh sách lệnh"),
    ("menu", "Mở bảng điều khiển (Mini App)"),
    ("restart", "Khởi động lại bot tiến trình"),
    ("model", "Xem hoặc đổi model AI đang chạy (/model <tên>)"),
    ("upcoming", "Sắp tới (tác vụ & lịch trình)"),
    ("status", "Trạng thái hệ thống"),
    ("vault", "Nhập API Key & Khóa bảo mật"),
    ("new", "Chốt phiên, bắt đầu ngữ cảnh mới"),
    ("cancel", "Dừng tác vụ đang chạy"),
    ("memory", "Xem bộ nhớ + fact kèm nguồn"),
    ("chatphu", "Tạo chat phụ (topic tự do)"),
    ("setup_topics", "Thiết lập Topic-tab cho group"),
    ("quyen", "Quyền của agent bằng lời thường"),
    ("approvals", "Lịch sử quyết định quyền"),
    ("goals", "Xem mục tiêu đang theo dõi (Goals)"),
    ("goal", "Quản lý mục tiêu (/goal create, close, briefing)"),
    ("ideas", "Sinh thẻ ý tưởng mới"),
    ("feed_now", "Đăng bài Feed công nghệ & AI"),
    ("library", "Xem Thư viện & kho ảnh visual"),
    ("feedbrief", "Xem/sửa brief của Feed"),
    ("feedsources", "Nguồn bổ sung của Feed"),
    ("the_duyet", "Gửi thẻ phê duyệt thử (thật, vô hại)"),
    ("pin_item", "Ghim item Library theo id"),
    ("rename_item", "Đổi tên item Library theo id"),
    ("zalo", "Zalo cá nhân (/zalo status, qr, disconnect)"),
    ("telethon", "Telegram cá nhân userbot (/telethon status, qr, disconnect)"),
    ("facebook", "Facebook cá nhân (/facebook status, connect, disconnect)"),
]

# Tập hợp toàn bộ tên lệnh và bí danh mà bot có handler thật sự
ALL_HANDLED_COMMANDS: set[str] = set(COMMAND_BY_NAME.keys()) | set(ALIAS_MAP.keys())


def is_known_command(text: str) -> bool:
    """Kiểm tra xem chuỗi có phải là một lệnh slash hợp lệ hay không."""
    if not text or not text.startswith("/"):
        return False
    token = text.split()[0].split("@")[0].lower()
    cmd_name = token[1:]
    return cmd_name in ALL_HANDLED_COMMANDS


def format_help_text(is_dev: bool = False) -> str:
    """Sinh văn bản trợ giúp có cấu trúc cho lệnh /help."""
    lines = [
        "🤖 <b>DANH SÁCH LỆNH MULON</b>\n",
        "🌟 <b>Cơ bản (Menu '/')</b>",
    ]
    for cmd in COMMAND_DEFINITIONS:
        if cmd.category == CommandCategory.BASIC and cmd.in_help:
            alias_str = f" <i>(hoặc /{', /'.join(cmd.aliases)})</i>" if cmd.aliases else ""
            lines.append(f"/{cmd.name} — {cmd.description}{alias_str}")

    lines.append("\n📋 <b>Việc & Dữ liệu</b>")
    for cmd in COMMAND_DEFINITIONS:
        if cmd.category == CommandCategory.WORK_DATA and cmd.in_help:
            alias_str = f" <i>(hoặc /{', /'.join(cmd.aliases)})</i>" if cmd.aliases else ""
            lines.append(f"/{cmd.name} — {cmd.description}{alias_str}")

    lines.append("\n⚙️ <b>Nâng cao & Kết nối</b>")
    for cmd in COMMAND_DEFINITIONS:
        if cmd.category == CommandCategory.ADVANCED and cmd.in_help:
            if cmd.name == "the_duyet" and not is_dev:
                continue
            warn = f" <i>(⚠️ {cmd.warning})</i>" if cmd.warning else (" <i>(⚠️)</i>" if cmd.is_destructive else "")
            lines.append(f"/{cmd.name} — {cmd.description}{warn}")

    lines.append(
        "\n💡 <i>Gõ lệnh trực tiếp hoặc chạm nút <b>Menu (/)</b> ở góc màn hình "
        "để chọn nhanh các thao tác thường dùng.</i>"
    )
    return "\n".join(lines)
