@echo off
setlocal
"%~dp0runtime\python.exe" -I -m living_agent.cli.psyche %*
exit /b %errorlevel%
