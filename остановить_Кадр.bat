@echo off
setlocal
cd /d "%~dp0"
set "TEMP=%~dp0temp"
set "TMP=%~dp0temp"
set "TMPDIR=%~dp0temp"
set "PYTHONUTF8=1"
set "PYTHONPYCACHEPREFIX=%~dp0cache\pycache"
if not exist "%TEMP%" mkdir "%TEMP%"
if not exist "%~dp0tools\python\python.exe" (
  echo [ERROR] Portable Python is missing. Use Ctrl+C in the original KADR console.
  if not "%KADR_NONINTERACTIVE%"=="1" pause
  exit /b 1
)
"%~dp0tools\python\python.exe" -m app.launcher --stop
set "RESULT=%ERRORLEVEL%"
if not "%RESULT%"=="0" if not "%KADR_NONINTERACTIVE%"=="1" pause
exit /b %RESULT%
