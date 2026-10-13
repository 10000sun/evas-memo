@echo off
REM Run as administrator. Pass -Logon to skip the password prompt: install-tasks.bat -Logon
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-tasks.ps1" %*
pause
