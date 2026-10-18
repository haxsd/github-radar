@echo off
rem background translation loop (hidden, chunked with timeout)
cd /d "%~dp0"
if not exist "data\logs" mkdir "data\logs"
.venv\Scripts\python.exe -u translate_loop.py >> "data\logs\translate_loop.log" 2>&1
exit /b 0
