@echo off
title Mulon Auto-Watcher
cd /d "%~dp0\.."

if exist ".venv\Scripts\python.exe" (
    set "PY_BIN=.venv\Scripts\python.exe"
) else (
    set "PY_BIN=python"
)

echo Dang khoi dong MuLon Auto-Watcher tren Windows...
"%PY_BIN%" scripts\auto_watch.py --enable
pause
