@echo off
REM 메모 앱 실행. 8000번은 이 PC 안에서만 열린다(바깥에는 Caddy가 443으로 열어 준다).
cd /d "%~dp0.."
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
