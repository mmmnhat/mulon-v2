@echo off
title Mulon Bot Runner
cd /d "%~dp0\.."

if exist ".venv\Scripts\python.exe" (
    set "PY_BIN=.venv\Scripts\python.exe"
) else (
    set "PY_BIN=python"
)

echo Dang khoi dong MuLon Bot tren Windows...
"%PY_BIN%" -m mulon.main
pause
