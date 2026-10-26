# ==============================================================================
# Mulon Installer — Cài đặt tự động cho Windows (PowerShell) (T-15)
# ==============================================================================
$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $PSScriptRoot
Set-Location $ProjectRoot

Write-Host "==================================================================" -ForegroundColor Cyan
Write-Host "            MuLon Automated Installer (Windows PowerShell)         " -ForegroundColor Cyan
Write-Host "==================================================================" -ForegroundColor Cyan

# 1. Kiểm tra Python
$PythonCmd = ""
foreach ($cmd in @("py", "python", "python3")) {
    try {
        $ver = & $cmd -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")' 2>$null
        if ($ver -in @("3.12", "3.13", "3.14")) {
            $PythonCmd = $cmd
            break
        }
    } catch {
        # Bỏ qua
    }
}

if (-not $PythonCmd) {
    Write-Host "❌ Không tìm thấy Python 3.12 trở lên trên hệ thống!" -ForegroundColor Red
    Write-Host "   Vui lòng tải và cài đặt Python 3.12 từ python.org (nhớ tích chọn 'Add Python to PATH')." -ForegroundColor Yellow
    Exit 1
}

Write-Host "✓ Tìm thấy Python: $PythonCmd" -ForegroundColor Green

# 2. Tạo virtualenv nếu chưa có
$VenvDir = Join-Path $ProjectRoot ".venv"
$VenvPy = Join-Path $VenvDir "Scripts\python.exe"

if (-not (Test-Path $VenvPy)) {
    Write-Host "📦 Đang tạo môi trường ảo Python .venv..." -ForegroundColor Cyan
    & $PythonCmd -m venv $VenvDir
}

# 3. Cài đặt dependencies
Write-Host "📦 Đang cài đặt thư viện cần thiết từ requirements.txt..." -ForegroundColor Cyan
& $VenvPy -m pip install --upgrade pip --quiet
& $VenvPy -m pip install -r requirements.txt --quiet
if (Test-Path "requirements-dev.txt") {
    & $VenvPy -m pip install -r requirements-dev.txt --quiet
}
Write-Host "✓ Cài đặt dependencies thành công!" -ForegroundColor Green

# 4. Chạy Setup Wizard
Write-Host ""
& $VenvPy -m mulon.setup

# 5. Tạo batch launchers và hỏi cài service
& $VenvPy -m mulon.service install --service all

Write-Host "==================================================================" -ForegroundColor Green
Write-Host "🎉 Cài đặt hoàn tất trên Windows!" -ForegroundColor Green
Write-Host "• Chạy trực tiếp: .\.venv\Scripts\python.exe -m mulon.main" -ForegroundColor White
Write-Host "• Hoặc nhấn đúp chuột vào file: scripts\run_bot.bat" -ForegroundColor White
Write-Host "==================================================================" -ForegroundColor Green
