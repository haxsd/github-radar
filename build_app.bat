@echo off
rem Build desktop app into dist\StarScout (PyInstaller, needs requirements installed)
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Please run setup.bat first.
  pause
  exit /b 1
)
echo [1/2] building icon...
".venv\Scripts\python.exe" scripts\make_icon.py
echo [2/2] packaging with PyInstaller...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean --windowed --name StarScout --icon "assets\icon.ico" --add-data "radar\templates;radar\templates" --add-data "radar\demo_data.json;radar" --add-data "assets\icon.png;assets" desktop.py
echo.
echo Done: dist\StarScout\StarScout.exe
pause
