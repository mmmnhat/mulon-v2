# ==============================================================================
# Mulon Windows Service Helper (PowerShell) (T-15)
# ==============================================================================
param (
    [Parameter(Position=0)]
    [ValidateSet("status", "install", "uninstall", "start", "stop")]
    [string]$Action = "status"
)

$ProjectRoot = Split-Path -Parent $PSScriptRoot
$VenvPy = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPy)) {
    $VenvPy = "python.exe"
}

& $VenvPy -m mulon.service $Action --service all
