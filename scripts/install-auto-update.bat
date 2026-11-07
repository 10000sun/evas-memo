@echo off
REM 관리자 권한으로 실행(우클릭 > 관리자 권한으로 실행). 자동 배포 작업(evas-memo-update)만 등록한다. -Logon / -System 옵션은 install-tasks.bat과 같다.
REM 서버 PC에서 이 레포를 git pull로 받아 둔 Windows 계정으로 등록해야 한다(깃 로그인 정보가 그 계정에 있다).
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0install-tasks.ps1" -UpdateOnly %*
pause
