@echo off
setlocal
for %%D in ("%~dp0..") do set "KADR_ROOT=%%~fD"
cd /d "%KADR_ROOT%"
echo ============================================================
echo KADR EXPERIMENTAL FULL TEST: local Qwen4B story selection
echo True 180s ASR + visual scenes + plot + FFmpeg + cache.
echo Strict production quality checks remain enabled.
echo This mode does NOT use DeepSeek or paid API.
echo It may differ in montage quality from local 9B.
echo Reports automatically publish to GitHub test-reports.
echo ============================================================
powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -File "%KADR_ROOT%\scripts\verify_project.ps1" -RequireRealModel -FastLocalStory %*
set "RESULT=%ERRORLEVEL%"
echo.
echo Experimental fast-local verification finished. Exit code: %RESULT%
echo Reports: %KADR_ROOT%\temp\verification-reports
echo Diagnostic logs: %KADR_ROOT%\logs\tests
if not "%KADR_NONINTERACTIVE%"=="1" pause
exit /b %RESULT%
