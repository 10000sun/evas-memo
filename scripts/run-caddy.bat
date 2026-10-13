@echo off
REM Caddy 실행. DOMAIN·PORT를 .env에서 뽑아 쓴다(PORT는 EVAS_PORT, 없으면 Caddyfile 기본값 8001).
REM .env에 SHARED_CALENDAR_URL이 있으면 캘린더와 한 Caddy로 두 주소를 받는다(Caddyfile.shared, 캘린더 포트는 SHARED_CALENDAR_PORT, 기본 8000).
cd /d "%~dp0.."
set CONF=Caddyfile
for /f "tokens=2 delims==" %%a in ('findstr /b "PUBLIC_URL=" .env') do set URL=%%a
for /f "tokens=2 delims==" %%a in ('findstr /b "EVAS_PORT=" .env 2^>nul') do set PORT=%%a
for /f "tokens=2 delims==" %%a in ('findstr /b "SHARED_CALENDAR_PORT=" .env 2^>nul') do set CAL_PORT=%%a
for /f "tokens=2 delims==" %%a in ('findstr /b "SHARED_CALENDAR_URL=" .env 2^>nul') do (set CAL_URL=%%a& set CONF=Caddyfile.shared)
set DOMAIN=%URL:https://=%
set CAL_DOMAIN=%CAL_URL:https://=%
caddy run --config %CONF%
