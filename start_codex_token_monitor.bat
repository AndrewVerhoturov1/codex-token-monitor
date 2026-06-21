@echo off
chcp 65001 >nul
cd /d "%~dp0"

if not exist "scripts\codex_token_monitor_server.py" (
    echo [ERROR] Server script not found: scripts\codex_token_monitor_server.py
    pause
    exit /b 1
)

REM Kill any python process running codex_token_monitor_server
echo Killing old monitor processes...
for /f "tokens=2" %%a in ('tasklist /fi "imagename eq python.exe" /fo csv /nh ^| findstr /i "python"') do (
    wmic process where ProcessId^=%%a get CommandLine 2>nul | findstr /i "codex_token_monitor_server" >nul && (
        echo Killing old monitor PID %%a...
        taskkill /PID %%a /F >nul 2>&1
    )
)
REM Also kill any server on port 8765
for /f "tokens=5" %%a in ('netstat -ano ^| findstr ":8765.*LISTENING"') do (
    echo Killing process on port 8765 PID %%a...
    taskkill /PID %%a /F >nul 2>&1
)
timeout /t 1 /nobreak >nul

echo Starting Codex Token Monitor Server v2...
echo http://127.0.0.1:8765
echo Press Ctrl+C to stop.
echo.

python scripts\codex_token_monitor_server.py --host 127.0.0.1 --port 8765 --open-browser

echo.
echo Server stopped.
pause
