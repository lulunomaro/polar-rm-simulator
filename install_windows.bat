@echo off
set ORT_DISABLE_TELEMETRY=1
cd /d "%~dp0"
if not exist .venv\Scripts\python.exe py -3 -m venv .venv
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m pip install -r requirements.txt
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m pip install -e . --no-deps
if errorlevel 1 exit /b 1
.venv\Scripts\python.exe -m pytest -q
pause
