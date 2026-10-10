@echo off
setlocal
cd /d "%~dp0.."
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0..\scripts\publish_latest_ai_diagnostics.ps1"
set "RESULT=%ERRORLEVEL%"
if not "%KADR_NONINTERACTIVE%"=="1" pause
exit /b %RESULT%
