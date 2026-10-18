@echo off
rem background collection for Windows Task Scheduler (no window)
cd /d "%~dp0"
if not exist "data\logs" mkdir "data\logs"
if exist ".venv\Scripts\pythonw.exe" (
  ".venv\Scripts\pythonw.exe" -m radar.collect wave >> "data\logs\collect.log" 2>&1
) else (
  ".venv\Scripts\python.exe" -m radar.collect wave >> "data\logs\collect.log" 2>&1
)
exit /b 0
