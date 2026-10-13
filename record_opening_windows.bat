@echo off
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe (
  echo Run install_windows.bat first.
  pause
  exit /b 1
)
.venv\Scripts\python.exe -m rm_match.opening_runner --mode navigation --max-seconds 40 --armor-profile role_v23 --out artifacts\opening_navigation
pause
