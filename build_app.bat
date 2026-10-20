@echo off
rem 构建桌面版：生成 dist\StarScout\StarScout.exe（onedir，带托盘/版本信息）
chcp 65001 >nul
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Please run setup.bat first.
  pause
  exit /b 1
)
echo [1/2] building icon...
".venv\Scripts\python.exe" scripts\make_icon.py
if errorlevel 1 exit /b 1
echo [2/2] packaging with PyInstaller...
".venv\Scripts\python.exe" -m PyInstaller --noconfirm --clean packaging\github-radar.spec
if errorlevel 1 exit /b 1
echo.
echo Done: dist\StarScout\StarScout.exe
pause
