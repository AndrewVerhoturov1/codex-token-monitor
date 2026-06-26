@echo off
chcp 65001 >nul
cd /d "%~dp0"

echo Killing old monitor processes...

for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8765"') do (
    echo Killing process on port 8765 PID %%a...
    taskkill /f /pid %%a >nul 2>nul
)

echo Starting Codex Token Monitor Server v2...
echo http://127.0.0.1:8765
echo Press Ctrl+C to stop.

where py >nul 2>nul
if %errorlevel% equ 0 (
    py -3 scripts\codex_token_monitor_server.py --host 127.0.0.1 --port 8765 --open-browser
    goto :eof
)

where python >nul 2>nul
if %errorlevel% equ 0 (
    python scripts\codex_token_monitor_server.py --host 127.0.0.1 --port 8765 --open-browser
    goto :eof
)

echo [ERROR] Python (py or python) not found in PATH.
pause
