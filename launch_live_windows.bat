@echo off
set ORT_DISABLE_TELEMETRY=1
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo First run install_windows.bat to create the Python environment.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m rm_match.viewer %*
pause
