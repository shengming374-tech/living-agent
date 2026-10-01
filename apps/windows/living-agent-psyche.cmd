@echo off
setlocal
"%~dp0runtime\python.exe" -I -B -m living_agent.cli.psyche %*
exit /b %errorlevel%
