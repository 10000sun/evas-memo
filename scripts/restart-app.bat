@echo off
REM 작업 스케줄러에 등록된 앱(evas-memo-app)을 껐다가 다시 켠다. git pull 뒤에 실행한다. 관리자 권한이 필요할 수 있다.
schtasks /End /TN evas-memo-app
schtasks /Run /TN evas-memo-app
