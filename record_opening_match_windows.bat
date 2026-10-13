@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run install_windows.bat first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m rm_match.opening_runner --mode match --max-seconds 300 --armor-profile role_v23 --out artifacts\full_match
pause
