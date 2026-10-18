@echo off
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Please run setup.bat first.
  pause
  exit /b 1
)
rem start the web server in background with no window (safe to call repeatedly)
wscript "%~dp0run_hidden.vbs" "%~dp0start_web.bat"
timeout /t 2 /nobreak >nul
start "" http://127.0.0.1:8765
exit /b 0
