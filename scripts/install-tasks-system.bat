@echo off
REM Run as administrator. For Windows accounts WITHOUT a password: runs the tasks as SYSTEM at boot.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-tasks.ps1" -System
pause
