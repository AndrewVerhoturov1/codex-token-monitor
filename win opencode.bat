@echo off
setlocal

set "PROJECT_DIR=D:\Codex+opencode_new\Proect_C_O\codex-token-monitor"
set "LAUNCHER=%PROJECT_DIR%\win-opencode-launch.ps1"

where wt.exe >nul 2>&1
if errorlevel 1 (
    echo Windows Terminal ^(wt.exe^) not found.
    pause
    exit /b 1
)

if not exist "%LAUNCHER%" (
    echo Launcher not found:
    echo %LAUNCHER%
    pause
    exit /b 1
)

start "" wt.exe -w new new-tab --title "Win OpenCode" -d "%PROJECT_DIR%" powershell.exe -NoLogo -NoProfile -NoExit -ExecutionPolicy Bypass -File "%LAUNCHER%"

if errorlevel 1 (
    echo Failed to start Windows Terminal.
    pause
    exit /b 1
)

endlocal
