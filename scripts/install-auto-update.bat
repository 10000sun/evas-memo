@echo off
REM 관리자 권한으로 실행(우클릭 > 관리자 권한으로 실행). 자동 배포 작업(evas-memo-update)만 등록한다. -Logon / -System 옵션은 install-tasks.bat과 같다.
REM git은 필요 없다(파이썬만 있으면 된다). 앱 작업을 등록했던 Windows 계정과 같은 계정으로 실행한다.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-tasks.ps1" -UpdateOnly %*
pause
