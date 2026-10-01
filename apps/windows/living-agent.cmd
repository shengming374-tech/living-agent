@echo off
setlocal
"%~dp0runtime\python.exe" -I -m living_agent %*
exit /b %errorlevel%
