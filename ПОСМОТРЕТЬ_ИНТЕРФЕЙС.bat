@echo off
setlocal
chcp 65001 >nul
cd /d "%~dp0"
echo KADR Studio Edition - isolated visual demo (port 8766).
echo Your original project on port 8765 will NOT be touched.
if not exist ".venv\Scripts\python.exe" (
 echo Missing .venv Python in fixed worktree.
 pause
 exit /b 1
)
if not exist "tools\ffmpeg\bin\ffmpeg.exe" (
 echo Missing portable FFmpeg inside fixed worktree.
 pause
 exit /b 1
)
if not exist "frontend\dist\index.html" (
 pushd frontend
 call npm run build
 if errorlevel 1 (popd & pause & exit /b 1)
 popd
)
".venv\Scripts\python.exe" "scripts\create_studio_demo.py"
if errorlevel 1 (
 echo Demo preparation failed. Please share the console error.
 pause
 exit /b 1
)
start "" powershell.exe -NoProfile -Command "$d=Get-Content -Raw 'data\studio-demo.json' | ConvertFrom-Json; $url=$d.url; for($i=0;$i -lt 40;$i++){try{Invoke-WebRequest -Uri 'http://127.0.0.1:8766/api/health' -UseBasicParsing -TimeoutSec 1 | Out-Null; Start-Process $url; break}catch{Start-Sleep -Milliseconds 500}}"
echo Starting separate UI/backend on http://127.0.0.1:8766/studio
echo Press Ctrl+C in THIS window to stop demo server.
".venv\Scripts\python.exe" -m uvicorn app.server:app --host 127.0.0.1 --port 8766
if errorlevel 1 (echo Port 8766 is busy or server error. & pause)
