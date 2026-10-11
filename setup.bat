@echo off
setlocal
cd /d "%~dp0"
set "TEMP=%~dp0temp"
set "TMP=%~dp0temp"
set "TMPDIR=%~dp0temp"
set "npm_config_cache=%~dp0cache\npm"
if not exist "%TEMP%" mkdir "%TEMP%"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\setup.ps1"
if errorlevel 1 (
  echo Setup failed. Details are above.
  pause
  exit /b 1
)
echo Ready. Run start.bat.
pause
