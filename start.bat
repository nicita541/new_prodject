@echo off
setlocal
cd /d "%~dp0"
if not exist "%~dp0logs" mkdir "%~dp0logs"
echo [%date% %time%] KADR start.bat launched >> "%~dp0logs\startup.log"
set "TEMP=%~dp0temp"
set "TMP=%~dp0temp"
set "PYTHONUTF8=1"
set "PYTHONPYCACHEPREFIX=%~dp0cache\pycache"

if not exist "%~dp0tools\python\python.exe" (
  echo [ERROR] Portable Python is missing in tools\python.
  echo Run setup.bat once. No demo or separate Python environment is required.
  echo [%date% %time%] ERROR: Portable Python missing >> "%~dp0logs\startup.log"
  pause
  exit /b 1
)

if not exist "%~dp0frontend\dist\studio-edition.html" goto build_ui
if not exist "%~dp0frontend\dist\studio-live-bridge.js" goto build_ui
if not exist "%~dp0frontend\dist\studio-edition.css" goto build_ui
if not exist "%~dp0frontend\dist\studio-edition-app.js" goto build_ui
rem Vite copies these files verbatim. Compare source with dist so an old build
rem never silently survives a successful git update.
fc /b "%~dp0frontend\public\studio-edition.html" "%~dp0frontend\dist\studio-edition.html" >nul 2>&1
if errorlevel 1 goto build_ui
fc /b "%~dp0frontend\public\studio-live-bridge.js" "%~dp0frontend\dist\studio-live-bridge.js" >nul 2>&1
if errorlevel 1 goto build_ui
fc /b "%~dp0frontend\public\studio-edition.css" "%~dp0frontend\dist\studio-edition.css" >nul 2>&1
if errorlevel 1 goto build_ui
fc /b "%~dp0frontend\public\studio-edition-app.js" "%~dp0frontend\dist\studio-edition-app.js" >nul 2>&1
if errorlevel 1 goto build_ui
goto launch

:build_ui
echo Production Studio interface is not built; preparing it now.
if not exist "%~dp0frontend\node_modules" (
  echo [ERROR] Frontend dependencies are missing. Run setup.bat first.
  pause
  exit /b 1
)
where npm.cmd >nul 2>&1
if errorlevel 1 (
  echo [ERROR] npm.cmd is not available. Install Node.js LTS or run setup.bat to check requirements.
  pause
  exit /b 1
)
pushd "%~dp0frontend"
call npm.cmd run build
set "BUILD_RESULT=%errorlevel%"
popd
if not "%BUILD_RESULT%"=="0" (
  echo [ERROR] Production Studio build failed.
  pause
  exit /b %BUILD_RESULT%
)
if not exist "%~dp0frontend\dist\studio-edition.html" (
  echo [ERROR] Studio HTML was not produced by the build.
  pause
  exit /b 1
)
if not exist "%~dp0frontend\dist\studio-live-bridge.js" (
  echo [ERROR] Studio API bridge was not produced by the build.
  pause
  exit /b 1
)
if not exist "%~dp0frontend\dist\studio-edition.css" (
  echo [ERROR] Studio CSS was not produced by the build.
  pause
  exit /b 1
)
if not exist "%~dp0frontend\dist\studio-edition-app.js" (
  echo [ERROR] Studio JavaScript was not produced by the build.
  pause
  exit /b 1
)

:launch
echo Opening the real KADR Studio at http://127.0.0.1:8765
"%~dp0tools\python\python.exe" -m app.launcher
if errorlevel 1 (
  echo [ERROR] KADR Studio failed to start.
  echo [%date% %time%] ERROR: KADR Studio launcher exited with error >> "%~dp0logs\startup.log"
  pause
  exit /b 1
)
exit /b 0
