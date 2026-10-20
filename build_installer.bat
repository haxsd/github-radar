@echo off
rem 构建安装包：需要先运行 build_app.bat，并安装 Inno Setup 6
chcp 65001 >nul
cd /d "%~dp0"
set "ISCC="
if exist "%ProgramFiles(x86)%\Inno Setup 7\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 7\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 7\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 7\ISCC.exe"
if exist "%LOCALAPPDATA%\Programs\Inno Setup 7\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 7\ISCC.exe"
if exist "%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist "%ProgramFiles%\Inno Setup 6\ISCC.exe" set "ISCC=%ProgramFiles%\Inno Setup 6\ISCC.exe"
if exist "%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe" set "ISCC=%LOCALAPPDATA%\Programs\Inno Setup 6\ISCC.exe"
if "%ISCC%"=="" (
  echo Inno Setup not found. Install Inno Setup 6/7 first: https://jrsoftware.org/isdl.php
  pause
  exit /b 1
)
if not exist "dist\StarScout\StarScout.exe" (
  echo dist\StarScout not found. Run build_app.bat first.
  pause
  exit /b 1
)
echo Building installer with "%ISCC%"...
"%ISCC%" /Qp "packaging\github-radar.iss"
if errorlevel 1 (
  echo Installer build failed.
  pause
  exit /b 1
)
echo.
echo Done. Installer written to the dist folder:
dir /b "dist\GitHubRadar-Setup-*.exe"
pause
