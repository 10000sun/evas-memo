@echo off
REM 메모 앱 실행. 포트는 .env의 EVAS_PORT(없으면 8001; 캘린더의 8000과 겹치지 않게). 이 PC 안에서만 열린다(바깥에는 Caddy가 443으로 열어 준다).
cd /d "%~dp0.."
set PORT=8001
for /f "tokens=2 delims==" %%a in ('findstr /b "EVAS_PORT=" .env 2^>nul') do set PORT=%%a
python -m uvicorn app.main:app --host 127.0.0.1 --port %PORT%
