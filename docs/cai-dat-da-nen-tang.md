# Hướng dẫn cài đặt và vận hành MuLon đa nền tảng (macOS, Linux, Windows)

Tài liệu hướng dẫn triển khai MuLon v1.7.2+ cho bất kỳ chủ sở hữu nào (T-15 mở khóa cài đặt).

---

## 1. Yêu cầu hệ thống

- **Hệ điều hành**:
  - macOS 12 (Monterey) trở lên (hỗ trợ cả Apple Silicon và Intel)
  - Linux (Ubuntu 20.04+, Debian 11+, Arch Linux, Fedora...)
  - Windows 10/11 (x64)
- **Python**: 3.12 (khuyến nghị 3.12.x)
- **Git**: Đã cài đặt và có trong PATH hệ thống
- **Proxy model**: Local proxy tương thích OpenAI (như CLIProxyAPI) tại `http://127.0.0.1:8317/v1`

---

## 2. Cài đặt tự động nhanh (One-click)

### Trên macOS & Linux
Mở terminal trong thư mục dự án và chạy:
```bash
./scripts/install.sh
```
Script sẽ tự động:
1. Kiểm tra Python 3.12+.
2. Khởi tạo môi trường ảo `.venv`.
3. Cài đặt toàn bộ dependencies trong `requirements.txt`.
4. Khởi chạy **Setup Wizard** để hướng dẫn cấu hình Bot Token và tài khoản chủ sở hữu.
5. Cung cấp tùy chọn cài đặt dịch vụ nền (launchd trên macOS, systemd trên Linux).

### Trên Windows
Mở PowerShell (Run as Administrator nếu muốn cài dịch vụ hệ thống) và chạy:
```powershell
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope CurrentUser
.\scripts\install.ps1
```
Script sẽ tự động chuẩn bị venv, thư viện và tạo sẵn các file `.bat` khởi chạy tiện lợi:
- `scripts\run_bot.bat`: Khởi động bot trực tiếp.
- `scripts\run_autowatch.bat`: Khởi động trình theo dõi git auto_watch.

---

## 3. Trình hướng dẫn cấu hình (Setup Wizard)

Bạn có thể chạy lại Setup Wizard bất cứ lúc nào bằng lệnh:
```bash
# Trên macOS / Linux:
.venv/bin/python -m mulon.setup

# Trên Windows:
.\.venv\Scripts\python.exe -m mulon.setup
```

### Các thông số cần thiết:
1. **Telegram Bot Token**: Lấy từ `@BotFather` trên Telegram.
2. **Telegram Owner User ID**: ID số của tài khoản bạn (lấy từ `@userinfobot`).
   - *Mẹo*: Bạn có thể **bỏ trống** bước này! Lần chạy đầu tiên, MuLon sẽ sinh một mã **Claim Token** trong terminal/log. Bạn chỉ cần nhắn `/setup <mã_token>` tới bot trên Telegram để nhận quyền chủ nhân.
3. **Proxy Base URL**: Mặc định `http://127.0.0.1:8317/v1`.
4. **Model chính (Model Brain)**: Mặc định `gemini-3.8-flash`.
5. **Múi giờ**: Mặc định `Asia/Ho_Chi_Minh`.

---

## 4. Ghép nối và quản lý quyền trong Telegram (`/setup`)

MuLon tuân thủ nguyên tắc bảo mật nghiêm ngặt: mặc định từ chối mọi người lạ, chỉ phục vụ chủ sở hữu và danh sách allowlist.

- **Ghép nối lần đầu**:
  Gửi lệnh:
  ```text
  /setup <claim_token>
  ```
  Bot sẽ tự động xác thực và gán tài khoản của bạn làm Chủ sở hữu (Owner).

- **Kiểm tra trạng thái cấu hình**:
  Gửi lệnh:
  ```text
  /setup
  ```
  Bot sẽ trả về thông tin chủ sở hữu, danh sách allowlist, OS, model và proxy.

- **Thêm người dùng vào danh sách cho phép (Allowlist)**:
  ```text
  /setup add <user_id>
  ```

- **Xóa người dùng khỏi danh sách cho phép**:
  ```text
  /setup remove <user_id>
  ```

---

## 5. Quản lý dịch vụ chạy ngầm tự khởi động (OS Service)

MuLon tích hợp sẵn công cụ quản lý dịch vụ nền chuẩn cho từng hệ điều hành:

```bash
# Xem trạng thái dịch vụ:
python -m mulon.service status

# Cài đặt dịch vụ nền tự chạy khi mở máy:
python -m mulon.service install

# Khởi động dịch vụ:
python -m mulon.service start

# Dừng dịch vụ:
python -m mulon.service stop

# Gỡ bỏ dịch vụ:
python -m mulon.service uninstall
```

- **macOS**: Sử dụng **launchd** (tạo file `~/Library/LaunchAgents/com.mulon.bot.plist`).
- **Linux**: Sử dụng **systemd** user service (`~/.config/systemd/user/mulon.service`).
- **Windows**: Sử dụng **Windows Task Scheduler** và các batch launcher trong `scripts/`.
