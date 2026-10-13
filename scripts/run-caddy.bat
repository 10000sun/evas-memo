@echo off
REM Caddy 실행. DOMAIN을 .env의 PUBLIC_URL에서 뽑아 쓴다.
cd /d "%~dp0.."
for /f "tokens=2 delims==" %%a in ('findstr /b "PUBLIC_URL=" .env') do set URL=%%a
set DOMAIN=%URL:https://=%
caddy run --config Caddyfile
