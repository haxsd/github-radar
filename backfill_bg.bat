@echo off
chcp 65001 >nul
cd /d "%~dp0"
if exist "data\.backfill.run" (
  echo [skip] another backfill is running
  exit /b 0
)
echo locked > "data\.backfill.run"
if not exist "data\logs" mkdir "data\logs"
echo [start] %date% %time% >> "data\logs\collect.log"
.venv\Scripts\python.exe -u -m radar.collect translate --limit 2000 >> "data\logs\collect.log" 2>&1
.venv\Scripts\python.exe -u -m radar.collect rewrite --limit 700 >> "data\logs\collect.log" 2>&1
.venv\Scripts\python.exe -u -m radar.collect tag --limit 3000 >> "data\logs\collect.log" 2>&1
echo [done] %date% %time% >> "data\logs\collect.log"
del "data\.backfill.run"
exit /b 0
