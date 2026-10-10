@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0logs" mkdir "%~dp0logs"
start "" explorer.exe "%~dp0logs"
exit /b 0
