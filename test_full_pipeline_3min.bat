@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\test_full_pipeline_3min.ps1" %*
exit /b %ERRORLEVEL%
