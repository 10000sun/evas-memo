# 서버 PC 배포 (포트포워딩 + 동적 DNS + Caddy)

구성: 인터넷 → 공유기(80/443 전달) → Caddy(HTTPS) → 메모 앱(127.0.0.1:8001)

## 0. 먼저 확인: 포트포워딩이 되는 인터넷인가
공유기 관리 화면의 **WAN(인터넷) IP**와 "내 IP 확인" 사이트의 IP가 **같아야** 한다. 다르면 통신사 공유 IP라 이 방식은 불가능(→ Cloudflare Tunnel).

## 1. 주소(도메인) 만들기 — 둘 중 하나
집 IP가 바뀌어도 따라가는 이름이 필요하다.

**A. 공유기 동적 DNS (공유기에 메뉴가 있으면 이쪽, 가장 간단)**
1. 공유기 관리 화면 > 동적 DNS(DDNS)에서 서비스(TP-Link, No-IP 등)를 고르고 이름을 만든다 (예: `mymemo.tplinkdns.com`)
2. 상태가 "연결됨/성공"으로 바뀌면 끝. IP 갱신은 공유기가 알아서 한다 (스크립트·스케줄러 불필요)
3. `.env`의 `PUBLIC_URL=https://만든주소`

**B. DuckDNS (공유기에 DDNS가 없을 때)**
1. https://www.duckdns.org 에서 구글/깃허브로 로그인, 이름 생성 후 **token** 복사
2. `.env`에 `DUCKDNS_DOMAIN=이름`, `DUCKDNS_TOKEN=...` 추가
3. `python scripts\duckdns_update.py` → `OK` 확인
4. 작업 스케줄러에 "5분마다 반복", 동작 `python scripts\duckdns_update.py`(시작 위치: 레포 폴더) 등록

## 2. 공유기 포트포워딩
1. 서버 PC에 **고정 내부 IP**를 준다(공유기의 DHCP 고정 할당). 안 하면 PC가 바뀐 IP를 받아 전달이 끊긴다.
2. 포트포워딩: 외부 **80**, **443** → 서버 PC 내부 IP의 80, 443 (TCP). 80은 인증서 발급에 필요하다.
3. 8001번(캘린더는 8000번)은 **열지 않는다**(앱은 PC 안에서만 받는다).

## 3. Caddy 설치
1. https://caddyserver.com/download 에서 Windows용 `caddy.exe`를 받아 PATH가 잡힌 폴더에 둔다
2. `.env`의 `PUBLIC_URL=https://mymemo.duckdns.org`
3. `scripts\run-caddy.bat` 실행(처음 Windows 방화벽 창이 뜨면 허용). 인증서는 자동 발급된다.

## 4. 앱 실행과 디스코드 설정
1. `.env` 채우기(`.env.example` 참고), `python -m pip install -r requirements.txt`
2. `scripts\run-app.bat`
3. 디스코드 포털 > OAuth2 > Redirects에 `https://mymemo.duckdns.org/auth/callback` 추가
4. 브라우저로 `https://mymemo.duckdns.org` 접속
5. **WebSocket(`/ws`)이 Caddy를 통과하는지 확인**: 같은 메모를 두 창(PC와 휴대폰 등)에서 열어 한쪽에 입력한 글자가 다른 쪽에 바로 보이면 통과다. 개발자 도구 > 네트워크 > WS에 `/ws/memos/…` 연결이 "101 Switching Protocols"로 열려 있어야 한다. 입력이 서로 안 보이면 Caddy 설정(`Caddyfile`의 `reverse_proxy`)과 방화벽을 확인한다.

## 5. PC가 켜질 때 자동 실행 (작업 스케줄러)
먼저 `run-app.bat`, `run-caddy.bat` 창을 닫는다. 그다음 `scripts\install-tasks.bat`을 **우클릭 > 관리자 권한으로 실행**한다.
- Windows 로그인 비밀번호를 한 번 묻는다(파일에 저장하지 않는다). 컴퓨터가 켜지면 로그인 없이도 실행된다.
- **Windows 계정에 비밀번호가 없으면** 위 방식은 막혀 있다. 대신 `scripts\install-tasks-system.bat`을 우클릭 > 관리자 권한으로 실행한다(SYSTEM 계정으로, 컴퓨터가 켜지면 실행). 조건: 레포를 **OneDrive 밖**(예: `C:\evas-memo`)에 두고, caddy 폴더를 **시스템 변수** Path에 넣어 둘 것(스크립트가 확인하고 안내한다).
- 비밀번호 없이 로그인할 때만 실행하려면 관리자 명령창에서 `scripts\install-tasks.bat -Logon`. 이 경우 재부팅 뒤 자동 로그인이 설정돼 있어야 한다.
- 등록되는 작업: `evas-memo-app`, `evas-memo-caddy`, `evas-memo-duckdns`(.env에 DUCKDNS_TOKEN이 있을 때만, 5분마다).
- 작업은 실행 시간 제한이 없고, 죽으면 1분 뒤 3번까지 다시 켜진다.
- 확인: 작업 스케줄러 라이브러리에서 세 작업이 "준비/실행 중"인지 보고 PC를 재부팅해서 접속을 확인한다.
- 제거: `schtasks /Delete /TN evas-memo-app /F` (evas-memo-caddy, evas-memo-duckdns도 같은 방식)

## 주의
- 앱은 **워커 1개**로만 실행한다(`run-app.bat`·작업 스케줄러가 이미 그렇게 등록한다). 워커를 늘리면 공동 편집이 어긋난다.
- 서버 시간대는 한국(KST)으로 둔다. `SESSION_SECRET`은 `.env`에 고정하고, `EVAS_DEV_AUTH`는 운영 `.env`에 넣지 않는다.
- 캘린더와 같은 PC에 올릴 때는 아래 "캘린더와 같은 PC에 올리기"를 따른다.

## 캘린더와 같은 PC에 올리기
메모 앱은 기본 포트가 **8001**이라 캘린더(8000)와 겹치지 않는다. 문제는 Caddy다: 80/443은 한 프로그램만 쓸 수 있으므로 **Caddy를 하나만** 띄워 두 주소를 받게 한다. 캘린더 레포는 고치지 않는다.
1. 주소를 하나 더 만든다(메모용). 캘린더 주소와 달라야 한다. 포트포워딩(80/443)은 그대로 한 번만.
2. 메모 `.env`에 아래를 추가한다.
   ```
   PUBLIC_URL=https://메모주소
   SHARED_CALENDAR_URL=https://캘린더주소
   # (선택) 포트를 바꿨다면: EVAS_PORT=8001, SHARED_CALENDAR_PORT=8000
   ```
   `SHARED_CALENDAR_URL`이 있으면 `run-caddy.bat`이 `Caddyfile.shared`를 써서 두 주소를 각각 8001(메모)·8000(캘린더)로 넘긴다.
3. **캘린더의 Caddy를 끈다**: 캘린더의 `run-caddy.bat` 창을 닫고, 작업 스케줄러에 등록했다면 `schtasks /Delete /TN evas-caddy /F`. (메모의 Caddy가 캘린더 주소도 받는다. 캘린더 앱 자체와 `evas-app` 작업은 그대로 둔다.)
4. 메모 앱 실행(`scripts
un-app.bat` 또는 `install-tasks.bat`)과 Caddy 실행(`scripts
un-caddy.bat`). 메모 쪽 작업 이름은 `evas-memo-*`라 캘린더와 겹치지 않는다.
5. 두 주소에 각각 접속해 확인한다. 한쪽 Caddy를 재시작하면 두 서비스가 같이 잠깐 끊긴다.
6. 메모의 디스코드 Redirects는 메모 주소만 추가하면 된다(캘린더 Redirect는 그대로).

## 문제가 생기면
- `No module named uvicorn`(또는 fastapi 등): 패키지를 설치하지 않았거나 **다른 파이썬에 설치**된 것. 레포 폴더에서 `python -m pip install -r requirements.txt`를 다시 실행(`pip` 대신 `python -m pip`로 실행해야 `run-app.bat`이 쓰는 파이썬과 같은 곳에 설치된다)
- 접속이 안 됨: 바깥(LTE 등)에서 시도 → 같은 집 와이파이에서는 공유기가 막는 경우(헤어핀)가 있다
- Caddy 인증서 오류: 80/443 포워딩, 방화벽, 통신사 차단 여부 확인. 공유기 DDNS 주소에서만 발급이 거절되면(공용 도메인 발급 횟수 제한 등) DuckDNS(B)로 바꿔 본다
- `.env`를 고친 뒤에는 앱을 다시 실행
