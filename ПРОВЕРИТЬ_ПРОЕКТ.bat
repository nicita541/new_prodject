@echo off
setlocal
cd /d "%~dp0"
powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\verify_project.ps1" %*
set "RESULT=%ERRORLEVEL%"
echo.
echo Tests finished. Exit code: %RESULT%.
echo Reports: temp\verification-reports
pause
exit /b %RESULT%
