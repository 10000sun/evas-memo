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

## 배포 전 체크리스트 (폴더·전율 버전으로 올릴 때)
이 버전은 시작할 때 `memos`·`folders` 표를 **한 번 다시 만든다**(전율 종류를 허용하도록 `kind` 제약을 바꾼다. 폴더 이전의 운영 DB면 `folder_id` 열도 덧붙인다). 한 트랜잭션이라 실패하면 롤백되고, 이미 끝났으면 다시 해도 아무것도 안 하지만, **실제 운영 DB로는 시험하지 못했다**(테스트용 DB로만 확인). 그래서 먼저 백업한다.
1. 앱을 끈다: 작업 스케줄러면 `schtasks /End /TN evas-memo-app`, 창으로 띄웠다면 창을 닫는다.
2. **백업**: `data\evas.db` 파일 하나를 `data` 밖의 다른 폴더(가능하면 다른 드라이브)에 복사한다. 이 앱은 WAL을 쓰지 않아 파일 하나면 된다. **첫 시작 전에 꼭.**
3. `git pull`, `python -m pip install -r requirements.txt`
4. 앱을 켠다(`scripts\restart-app.bat` 또는 `scripts\run-app.bat`).
5. **로그 확인**: 정상이면 이전 성공 메시지는 따로 없다(조용히 끝난다). 경고만 남는다 — `이전 전부터 있던 외래키 위반 N건(그대로 둔다)`: 옛 데이터에 원래 있던 문제라 막지는 않는다, `DB가 잠겨 있어 이전을 1초 뒤 다시 시도합니다`: 다른 프로세스가 DB를 쥐고 있다는 뜻이니 앱이 둘 떠 있지 않은지 본다. 시작이 오류(`IntegrityError` 등)로 멈추면 아래 되돌리기를 한다. 이전이 됐는지는 `python -c "import sqlite3;print('admin' in sqlite3.connect('data/evas.db').execute(\"select sql from sqlite_master where name='memos'\").fetchone()[0])"`가 `True`면 된다.
6. **동작 확인**: 로그인이 되는가, 메모 목록·폴더가 예전과 같이 보이는가(개수 확인), 공동 메모를 **브라우저 두 개**(다른 계정)에서 열어 서로의 입력이 바로 보이는가, `전율` 탭이 **관리자에게만** 보이는가(일반 계정에는 탭이 없어야 한다).
7. **Caddy 설정 확인**: `Caddyfile.shared`는 개발 PC에서 한 번도 검증하지 못했다. 서버 PC에서 `caddy validate --config Caddyfile.shared`로 확인한다. 이 파일은 환경변수를 쓰므로 먼저 지정한다: PowerShell `$env:DOMAIN="메모주소"; $env:CAL_DOMAIN="캘린더주소"; caddy validate --config Caddyfile.shared`(`run-caddy.bat`이 `.env`에서 같은 값을 뽑아 준다). `Valid configuration`이 나와야 한다. 한 앱만 쓰면 `Caddyfile`을 같은 방식으로(`DOMAIN`만) 확인한다.

**되돌리기**: 앱을 끈다 → 백업한 `evas.db`로 `data\evas.db`를 덮어쓴다 → `git checkout <이전 커밋>` → 앱을 켠다. (백업 뒤에 쓴 메모는 사라진다.)

## 운영 주의사항
- **워커 1개**: 앱은 uvicorn 워커 **1개**로만 실행한다(`run-app.bat`·작업 스케줄러가 이미 그렇게 등록한다). 공동 편집 문서를 프로세스 메모리에 들고 있어서 워커를 늘리면 사람마다 다른 문서를 보게 된다.
- **시간대는 한국(KST)**: 서버 PC의 시간대가 KST여야 화면의 시각이 맞는다.
- **`SESSION_SECRET`은 `.env`에 고정**: 비우면 재시작할 때마다 새 값이 만들어져 모두 로그아웃되고 편집 중이던 입력을 잃을 수 있다.
- **`EVAS_DEV_AUTH`는 운영 `.env`에 넣지 않는다**: 이 값이 `1`이면 로그인 없이 `X-User-Id` 헤더로 아무 사용자나 될 수 있고 `/auth/dev`로 로그인된다. 그 경로는 테스트 전용이다.
- **휴대폰 내보내기(공유·저장)는 HTTPS에서만** 동작한다. 운영은 Caddy HTTPS로 접속한다.
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
4. 메모 앱 실행(`scripts\run-app.bat` 또는 `install-tasks.bat`)과 Caddy 실행(`scripts\run-caddy.bat`). 메모 쪽 작업 이름은 `evas-memo-*`라 캘린더와 겹치지 않는다.
5. 두 주소에 각각 접속해 확인한다. 한쪽 Caddy를 재시작하면 두 서비스가 같이 잠깐 끊긴다.
6. 메모의 디스코드 Redirects는 메모 주소만 추가하면 된다(캘린더 Redirect는 그대로).

## 캘린더 연동 설정(선택)
메모 `@` 태그(캘린더 일정)·캘린더에서의 메모 태그를 쓰려면 두 앱을 서로 알려 준다. 브라우저는 상대 서버를 직접 부르지 않고, 서버끼리 비밀키로 통신한다. **연동 설정은 여기에만 둔다.**

| 앱 | `.env` 항목 | 값 |
|---|---|---|
| 둘 다 | `LINK_API_KEY` | **같은 값**. 만들기: `python -c "import secrets;print(secrets.token_urlsafe(32))"` |
| 메모 | `CALENDAR_URL` | 캘린더 공개 주소(끝에 `/` 없이). 없으면 `SHARED_CALENDAR_URL`을 쓴다 |
| 메모 | `CALENDAR_INTERNAL_URL` | 이 서버가 캘린더를 부르는 내부 주소. 기본 `http://127.0.0.1:8000`(`SHARED_CALENDAR_PORT`가 있으면 그 포트) |
| 캘린더 | `MEMO_URL` | 메모 공개 주소(끝에 `/` 없이). 메모 앱 자신은 `PUBLIC_URL`을 쓴다 |
| 캘린더 | `MEMO_INTERNAL_URL` | 캘린더가 메모를 부르는 내부 주소. 기본 `http://127.0.0.1:8001` |

두 앱 `.env`를 채우고 **둘 다 다시 실행**한다.
- `/internal/*`은 앱끼리만 쓰는 경로다. `Caddyfile`·`Caddyfile.shared`가 바깥 요청에 404를 돌려주고(직접 만든 Caddy 설정이라면 같은 `@internal` 규칙을 넣는다), 앱도 `X-Link-Key`가 `LINK_API_KEY`와 같을 때만 응답한다(키가 없거나 틀리거나 서버에 설정이 없으면 404).
- **`LINK_API_KEY`가 비어 있으면** 두 앱 사이 기능(메모 쪽 캘린더 일정 태그, 캘린더 쪽 메모 태그)만 꺼진다. 메모끼리의 `@` 태그와 헤더의 앱 전환 링크, 편집·저장은 그대로 동작한다.
- 헤더의 앱 전환(`에바스 캘린더 | 에바스 메모`)은 각 앱의 `/api/config`가 알려 주는 상대 앱 주소(메모는 `CALENDAR_URL`, 캘린더는 `MEMO_URL`)가 있을 때 나타난다. 키와는 상관없다.
- 상대 앱이 꺼져 있어도 이 앱의 편집·저장은 영향이 없다(상대 호출은 3초 안에 끝나고 "연결할 수 없습니다"만 보인다).

## 문제가 생기면
- `No module named uvicorn`(또는 fastapi 등): 패키지를 설치하지 않았거나 **다른 파이썬에 설치**된 것. 레포 폴더에서 `python -m pip install -r requirements.txt`를 다시 실행(`pip` 대신 `python -m pip`로 실행해야 `run-app.bat`이 쓰는 파이썬과 같은 곳에 설치된다)
- 접속이 안 됨: 바깥(LTE 등)에서 시도 → 같은 집 와이파이에서는 공유기가 막는 경우(헤어핀)가 있다
- Caddy 인증서 오류: 80/443 포워딩, 방화벽, 통신사 차단 여부 확인. 공유기 DDNS 주소에서만 발급이 거절되면(공용 도메인 발급 횟수 제한 등) DuckDNS(B)로 바꿔 본다
- `.env`를 고친 뒤에는 앱을 다시 실행
