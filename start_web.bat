@echo off
rem start local web server in background (used by run_hidden.vbs)
cd /d "%~dp0"
if not exist "data\logs" mkdir "data\logs"
.venv\Scripts\python.exe -m radar.web >> "data\logs\web.log" 2>&1
