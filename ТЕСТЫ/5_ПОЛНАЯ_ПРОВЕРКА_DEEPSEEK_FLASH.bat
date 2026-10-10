@echo off
setlocal EnableDelayedExpansion
for %%D in ("%~dp0..") do set "KADR_ROOT=%%~fD"
cd /d "%KADR_ROOT%"
echo ============================================================
echo KADR FULL 180s TEST: LOCAL QWEN 4B + DEEPSEEK FLASH STORY
echo.
echo Source audio and early frame analysis remain LOCAL.
echo Story text and selected image pages are SENT to DeepSeek.
echo This uses your paid DeepSeek API balance.
echo At most 8 new HTTP attempts per job, including failed calls.
echo This is a REQUEST cap, NOT an exact USD spending cap.
echo KADR response-cache hit: free, NO network call.
echo DeepSeek API context-cache hit: lower price, still billed.
echo On cap/remote error, story reverts to local Qwen 9B.
echo Shared test deadline: 2200s (36m40s); TIMEOUT is FAIL.
echo Reports are automatically published in test-reports.
echo ============================================================
if not "%KADR_NONINTERACTIVE%"=="1" (
  set /p "KADR_CONFIRM=Type YES to authorize DeepSeek API usage: "
  if /I not "!KADR_CONFIRM!"=="YES" (
    echo Cancelled. No API requests started.
    pause
    exit /b 2
  )
)
powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -File "%KADR_ROOT%\scripts\verify_project.ps1" -RequireRealModel -FlashStory %*
set "RESULT=%ERRORLEVEL%"
echo.
echo DeepSeek Flash experiment finished. Exit code: %RESULT%
echo Reports: temp\verification-reports and GitHub test-reports
if not "%KADR_NONINTERACTIVE%"=="1" pause
exit /b %RESULT%
