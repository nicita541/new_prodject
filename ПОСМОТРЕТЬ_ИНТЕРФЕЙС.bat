@echo off
setlocal
cd /d "%~dp0"
rem Compatibility launcher: the real studio uses the same server and data as start.bat.
call "%~dp0start.bat"
exit /b %errorlevel%
