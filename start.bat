@echo off
setlocal
cd /d "%~dp0"
set "TEMP=%~dp0temp"
set "TMP=%~dp0temp"
set "PYTHONUTF8=1"
set "PYTHONPYCACHEPREFIX=%~dp0cache\pycache"
if not exist "%~dp0tools\python\python.exe" (
  echo Run setup.bat first.
  pause
  exit /b 1
)
"%~dp0tools\python\python.exe" -m app.launcher
if errorlevel 1 pause
