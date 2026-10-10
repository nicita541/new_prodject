@echo off
setlocal EnableDelayedExpansion
for %%D in ("%~dp0..") do set "KADR_ROOT=%%~fD"
cd /d "%KADR_ROOT%"
echo ============================================================
echo KADR 180s REAL AI TEST: QWEN4B LOCAL + BUDGETED DEEPSEEK
echo Existing DeepSeek API key is loaded by KADR automatically.
echo Selected story frames and text will be sent to DeepSeek.
echo.
echo NEW explicit paid experiment: up to 96 HTTP attempts.
echo Estimated PEAK rate spending guard: 0.05 USD per test job.
echo In-flight requests reserve worst-case spend before dispatch.
echo On errors with unknown usage, the full reservation is retained.
echo WARNING: estimates are not billing guarantees.
echo After the guard/limit: conservative LOCAL 4B story analysis.
echo Standard 8-call DeepSeek BAT remains unchanged.
echo KADR response-cache hits do not create paid calls.
echo Hard deadline: 2200 seconds. All reports auto-published.
echo ============================================================
if not "%KADR_NONINTERACTIVE%"=="1" (
  set /p "KADR_CONFIRM=Type YES to authorize up to estimated 0.05 USD API use: "
  if /I not "!KADR_CONFIRM!"=="YES" (
    echo Cancelled before API use.
    pause
    exit /b 2
  )
)
powershell.exe -NoProfile -STA -ExecutionPolicy Bypass -File "%KADR_ROOT%\scripts\verify_project.ps1" -RequireRealModel -FlashBudgeted %*
set "RESULT=%ERRORLEVEL%"
echo.
echo Budgeted Flash verification finished. Exit code: %RESULT%
echo Reports: GitHub test-reports and temp\verification-reports
if not "%KADR_NONINTERACTIVE%"=="1" pause
exit /b %RESULT%
