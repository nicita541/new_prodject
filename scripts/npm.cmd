@echo off
setlocal
rem Workspace-owned entry point for the existing portable Node/npm runtime.
set "KADR_NODE=%~dp0..\tools\node\node.exe"
set "KADR_NPM_CLI=%~dp0..\tools\node\node_modules\npm\bin\npm-cli.js"
if not exist "%KADR_NODE%" (
  echo [ERROR] Portable Node.js is missing in tools\node.
  exit /b 1
)
if not exist "%KADR_NPM_CLI%" (
  echo [ERROR] Portable npm CLI is missing in tools\node\node_modules\npm.
  exit /b 1
)
set "npm_config_cache=%~dp0..\cache\npm"
set "PATH=%~dp0..\tools\node;%PATH%"
"%KADR_NODE%" "%KADR_NPM_CLI%" %*
exit /b %errorlevel%
