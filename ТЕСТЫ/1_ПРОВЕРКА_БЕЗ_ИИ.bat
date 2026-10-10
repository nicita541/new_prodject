@echo off
setlocal
for %%D in ("%~dp0..") do set "KADR_ROOT=%%~fD"
cd /d "%KADR_ROOT%"
echo ============================================================
echo KADR TECHNICAL TEST: Python, React, FFmpeg, 180s media, cache
echo Real local ASR/VLM is NOT used in this test.
echo Results are published to GitHub branch test-reports.
echo ============================================================
powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -File "%KADR_ROOT%\scripts\verify_project.ps1" %*
set "RESULT=%ERRORLEVEL%"
echo.
echo Verification finished. Exit code: %RESULT%
echo Reports: %KADR_ROOT%\temp\verification-reports
echo Diagnostic logs: %KADR_ROOT%\logs\tests
if not "%KADR_NONINTERACTIVE%"=="1" pause
exit /b %RESULT%
