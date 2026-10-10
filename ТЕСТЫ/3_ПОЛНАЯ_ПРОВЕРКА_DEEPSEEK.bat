@echo off
setlocal
for %%D in ("%~dp0..") do set "KADR_ROOT=%%~fD"
cd /d "%KADR_ROOT%"
echo ============================================================
echo KADR FULL TEST: real 180s video, local Whisper/Qwen4B,
echo DeepSeek for story editing, pacing and framing.
echo No application spending limit or API request-count limit.
echo Responses are cached, and reports go to test-reports.
echo The existing DeepSeek API key is loaded automatically.
echo ============================================================
powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -File "%KADR_ROOT%\scripts\verify_project.ps1" -RequireRealModel -FlashStory %*
set "RESULT=%ERRORLEVEL%"
echo.
echo Verification finished. Exit code: %RESULT%
echo Reports: %KADR_ROOT%\temp\verification-reports
if not "%KADR_NONINTERACTIVE%"=="1" pause
exit /b %RESULT%
