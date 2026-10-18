@echo off
chcp 65001 >nul
cd /d "%~dp0"
where python >nul 2>&1
if errorlevel 1 (
  echo Python not found. Please install Python 3.11+ and add it to PATH.
  pause
  exit /b 1
)
echo [1/3] creating virtual environment...
python -m venv .venv
echo [2/3] installing requirements...
".venv\Scripts\python.exe" -m pip install -r requirements.txt
echo [3/3] initializing database...
".venv\Scripts\python.exe" -c "from radar import db; db.init_db(); print(\"DB OK\")"
echo.
echo Done. Next: run collect.bat to fetch data, then open the web page.
pause
