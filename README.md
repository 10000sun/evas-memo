# evas-memo

팀원이 같은 메모를 동시에 열어 함께 고치는 공동 메모 웹앱. 디스코드 계정으로 로그인하고, 서버 한 대(SQLite 파일 하나)로 운영한다.

## 해결하려는 문제
메신저에 흩어지는 공지·할 일·참고 자료를 팀이 한곳에서 같이 쓰고 찾게 한다. 개인 메모와 공동 메모를 나누고, 공동 메모는 전체 공개 또는 선택한 사람에게만 보이게 할 수 있으며, 디스코드 서버 구성원만 들어오게 제한할 수 있다. 별도 계정 가입 없이 팀이 이미 쓰는 디스코드로 로그인한다.

> 화면 캡처·데모 영상은 아직 없습니다.

## 주요 기능
- **실시간 공동 편집**: 메모마다 방이 있어 여러 명이 동시에 고친다. 서로의 커서가 이름과 함께 사용자별 색으로 보인다. 되돌리기(Ctrl+Z)는 내가 한 편집만 되돌린다.
- **마크다운**: 원문을 쓰면서 문법 강조를 보고, `편집 | 미리보기`로 렌더링 결과를 본다. 미리보기는 HTML을 정화(DOMPurify)해서 보여 준다. 목록 이어쓰기, Tab 들여쓰기를 지원한다.
- **메모 종류**: 개인(소유자만), 공동, 전율(관리자 전용). 개인 메모는 관리자도 볼 수 없다. 전율 메모는 관리자가 아니면 목록·검색·주소 어디에서도 없는 것처럼(404) 취급되고, 변경 기록·푸시·캘린더 연동에도 나가지 않는다.
- **공개 범위**: 공동 메모와 공동 폴더를 `전체` 또는 `선택한 사람`으로 제한한다. 제한된 폴더 안의 메모는 폴더의 목록을 따른다. 접근을 잃은 사람의 열린 편집 연결은 서버가 바로 닫는다.
- **폴더·분류·검색**: 폴더 안에 하위 폴더 한 단계(총 2단계), 색 분류, 제목·본문 검색.
- **권한**: 관리자 / 편집자 / 보기 전용. 첫 관리자는 환경변수로 지정하고, 이후 관리 화면(`/admin.html`)에서 사람별 권한을 바꾼다. 처음 로그인한 사람은 편집자로 자동 등록된다.
- **변경 기록과 푸시 알림**: 공동 메모의 추가·수정·삭제를 기록하고(같은 사람의 10분 내 수정은 한 줄로 합침), VAPID 키를 설정하면 웹 푸시를 보낸다. 비공개 메모의 제목은 기록·푸시에 남기지 않는다.
- **@ 태그와 캘린더 연동(선택)**: 본문에서 `@`로 다른 메모를 링크한다. 별도 캘린더 앱과 `LINK_API_KEY`를 공유하면 일정 태그와 권한 동기화도 된다.
- **기타**: 메모 내보내기(공유창 → 클립보드 → `.txt` 순으로 시도), 다크/라이트 테마, 홈 화면에 추가하는 PWA(서비스 워커는 푸시 전용이며 오프라인 캐시는 없음).

## 기술 스택
- 백엔드: Python, FastAPI, uvicorn, SQLite(표준 라이브러리 `sqlite3`), httpx, itsdangerous(세션 쿠키), pywebpush
- 실시간 동기화: Yjs 호환 CRDT. 서버는 `pycrdt` / `pycrdt-websocket`, 브라우저는 `yjs` / `y-websocket` / `y-codemirror.next`
- 프런트엔드: 빌드 단계 없는 정적 파일(바닐라 JS). 에디터는 CodeMirror 6, 미리보기는 marked + DOMPurify이며 `tools/`에서 번들해 `static/vendor/`에 커밋한다
- 배포: Caddy(자동 HTTPS) 리버스 프록시, 선택적으로 DuckDNS, Windows 작업 스케줄러 스크립트

## 아키텍처 요약
```
app/        FastAPI 앱
  main.py     라우터 조립, 세션, 분류·사용자·알림 API, 정적 파일 마운트
  auth.py     디스코드 OAuth2 로그인, 역할 판정
  db.py       스키마와 시작 시 마이그레이션
  memos.py    메모 CRUD, 공유·이동·복사
  folders.py  폴더와 공개 범위
  ws.py       메모별 실시간 방(WebSocket), 접근 판정(can_access)
  activity.py 변경 기록      push.py  웹 푸시
  links.py    @ 태그·캘린더 연동   usersync.py  캘린더와 권한 동기화
static/     화면(HTML/JS/CSS), vendor/ 에디터·마크다운 번들, 서비스 워커
tools/      번들 빌드와 미리보기 테스트 (Node)
tests/      pytest, Node 단위 테스트
scripts/    VAPID 키 생성, 관리자 지정, DuckDNS 갱신, Windows 실행·작업 등록
docs/       배포 가이드(DEPLOY.md), 기능별 설계·계획 문서(superpowers/)
Caddyfile, Caddyfile.shared   HTTPS 리버스 프록시 설정
```
- **동기화·저장**: 메모를 여는 순간 서버가 DB의 Yjs 문서(`memos.ydoc`)를 복원해 방을 만들고, 변경이 생기면 2초 안에, 마지막 접속자가 나갈 때, 서버가 꺼질 때 저장한다. 검색용 평문은 `body_text`에 함께 저장한다. 업데이트 하나와 문서 전체에는 크기 상한(글자 10만, 5MB)이 있다.
- **단일 프로세스 전제**: 방이 프로세스 메모리에 있으므로 uvicorn 워커는 1개로만 띄운다.
- **접근 판정 한 곳**: 목록·REST·WebSocket·활동 기록·연동이 모두 `ws.can_access`를 거친다. 접근 불가는 '없음'과 같은 응답(404, 연결 종료)으로 처리해 존재가 드러나지 않게 한다.
- **스키마 이전**: 시작 시 `db.init()`이 `IF NOT EXISTS`와 `ALTER`로 열을 덧붙이고, `kind` CHECK 제약을 바꾸기 위한 표 재작성은 한 트랜잭션에서 한다. 기존 DB가 있는 서버를 올리기 전 백업 방법은 [docs/DEPLOY.md](docs/DEPLOY.md)에 있다.
- **인증**: 디스코드 토큰은 사용자 확인에만 쓰고 저장하지 않는다. 권한은 디스코드 ID를 키로 자체 DB가 정한다. 로그인 `state` 검사와 `next` 경로 검증이 있고, `DISCORD_GUILD_ID`를 지정하면 그 서버 구성원만 입장한다.
- **앱 간 내부 API**: `/internal/*`은 `X-Link-Key` 헤더(`LINK_API_KEY`)가 맞을 때만 응답하고, Caddy 설정에서도 바깥 요청을 404로 막는다.

## 실행 방법
요구 사항: Python 3.10 이상 권장(코드에 `X | None` 타입 문법을 쓴다). Node.js는 테스트와 번들 빌드에만 필요하다.

1. 의존성 설치
   ```
   python -m pip install -r requirements.txt
   ```
2. 설정: `.env.example`을 `.env`로 복사해 채운다(`.env`는 깃에 올라가지 않는다). 디스코드 개발자 포털에서 애플리케이션을 만들고 OAuth2 > Redirects에 `<PUBLIC_URL>/auth/callback`을 등록한다. 봇은 필요 없다.
3. 실행
   ```
   python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
   ```
   워커는 1개로만 띄운다(`--workers` 금지). 서버 시간대가 한국(KST)이어야 화면의 시각이 맞는다.
4. 바깥에서 접속(포트포워딩, DuckDNS, Caddy HTTPS, 부팅 시 자동 실행): [docs/DEPLOY.md](docs/DEPLOY.md). 휴대폰의 내보내기·푸시는 HTTPS에서만 동작한다.

데이터는 `data/evas.db` 한 파일이다(깃 제외). 백업은 앱을 끈 뒤 이 파일을 복사한다.

푸시 알림(선택): `python scripts/make_vapid.py` 출력 세 줄을 `.env`에 붙여 넣는다. 한 번 정하면 바꾸지 않는다(바꾸면 기존 구독이 모두 무효).

## 환경변수
| 이름 | 필수 | 설명 |
|---|---|---|
| `DISCORD_CLIENT_ID`, `DISCORD_CLIENT_SECRET` | 필수 | 디스코드 OAuth2 애플리케이션 값. 비면 로그인이 503 |
| `PUBLIC_URL` | 필수 | 사용자가 접속하는 주소(끝에 `/` 없이). https면 쿠키가 https 전용이 된다 |
| `SESSION_SECRET` | 운영 필수 | 쿠키 서명 값. 비우면 재시작할 때마다 새로 만들어져 모두 로그아웃된다 |
| `EVAS_ADMIN_IDS` | 권장 | 첫 관리자의 디스코드 ID(쉼표로 여러 명). 시작 시 등록 |
| `DISCORD_GUILD_ID` | 권장 | 지정하면 그 디스코드 서버 구성원만 입장. 비우면 디스코드 계정이 있는 누구나 로그인해 편집자가 될 수 있다 |
| `EVAS_OPEN_EDIT` | 선택 | `1`이면 권한 기록이 없는 로그인 사용자의 기본 역할이 편집자(비우면 보기 전용) |
| `EVAS_PORT` | 선택 | `scripts/run-app.bat`·Caddy 설정이 쓰는 포트. 기본 8001 |
| `EVAS_DB` | 선택 | DB 파일 경로. 기본 `data/evas.db` |
| `VAPID_PRIVATE_KEY`, `VAPID_PUBLIC_KEY`, `VAPID_SUBJECT` | 선택 | 웹 푸시. 비우면 푸시만 꺼진다 |
| `DUCKDNS_DOMAIN`, `DUCKDNS_TOKEN` | 선택 | DuckDNS 주소 갱신 스크립트용(`scripts/duckdns_update.py`) |
| `LINK_API_KEY` | 선택 | 캘린더 앱과 같은 값. 비면 두 앱 사이 기능만 꺼진다 |
| `CALENDAR_URL`, `CALENDAR_INTERNAL_URL` | 선택 | 캘린더 공개 주소 / 서버가 캘린더를 부르는 내부 주소 |
| `SHARED_CALENDAR_URL`, `SHARED_CALENDAR_PORT` | 선택 | 캘린더와 Caddy 하나를 같이 쓸 때(`Caddyfile.shared`) |
| `EVAS_DEV_AUTH` | 개발 전용 | `1`이면 헤더로 신원을 지정하는 로그인 우회가 켜진다. **운영 `.env`에는 절대 넣지 않는다** |

## 테스트
```
python -m pytest
```
서버 테스트에 더해 `static/memolink.js`의 Node 단위 테스트(`node --test tests/memolink.test.js`)도 실행하며, node가 없으면 그 테스트만 건너뛴다. 미리보기 번들 테스트와 번들 빌드는 `tools/`에서 한다.
```
cd tools && npm ci && node test-markdown.mjs
npm run build      # static/vendor/*.bundle.js 재생성(결과물은 커밋)
```
