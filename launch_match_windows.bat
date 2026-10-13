@echo off
set ORT_DISABLE_TELEMETRY=1
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run install_windows.bat first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m rm_match.match_viewer %*
pause
