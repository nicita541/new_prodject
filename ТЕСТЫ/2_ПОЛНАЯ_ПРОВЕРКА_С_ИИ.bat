@echo off
setlocal
for %%D in ("%~dp0..") do set "KADR_ROOT=%%~fD"
cd /d "%KADR_ROOT%"
echo ============================================================
echo KADR FULL TEST: technical tests + real local ASR/VLM
echo Choose a story video in the file selection dialog.
echo A long episode is excerpted to 180 seconds without alteration.
echo A failed/missing model is FAIL, never a synthetic PASS.
echo Results are published to GitHub branch test-reports.
echo ============================================================
powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -File "%KADR_ROOT%\scripts\verify_project.ps1" -RequireRealModel %*
set "RESULT=%ERRORLEVEL%"
echo.
echo Full verification finished. Exit code: %RESULT%
echo Reports: %KADR_ROOT%\temp\verification-reports
echo Diagnostic logs: %KADR_ROOT%\logs\tests
if not "%KADR_NONINTERACTIVE%"=="1" pause
exit /b %RESULT%
