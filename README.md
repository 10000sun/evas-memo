# evas-memo

팀이 함께 쓰는 공동 메모 웹앱. 메모별 실시간 공동 편집, 분류(색), 디스코드 로그인, 웹에서 편집 권한 관리, 활동 기록·푸시 알림, 메모 내보내기.

## 실행 (Windows 서버)
1. `python -m pip install -r requirements.txt`
2. `.env.example`을 `.env`로 복사해 채운다 (`.env`는 깃에 안 올라가므로 수동 복사)
3. `python -m uvicorn app.main:app --host 127.0.0.1 --port 8001`
4. 바깥에서 접속: [docs/DEPLOY.md](docs/DEPLOY.md) (포트포워딩 + DuckDNS + Caddy HTTPS)

데이터는 `data/evas.db`(깃 제외). 백업은 이 파일을 복사하면 된다.

## 꼭 지킬 것
- **단일 프로세스**: uvicorn 워커는 **1개**로만 띄운다(`--workers` 금지). 공동 편집 문서를 프로세스 메모리에 들고 있어서, 워커가 여러 개면 사람마다 다른 문서를 보게 된다.
- **서버 시간대는 한국(KST)** 이어야 화면의 시각이 맞는다.
- **`SESSION_SECRET`은 `.env`에 반드시 고정**한다. 비우면 재시작할 때마다 새 값이 만들어져 모두 로그아웃되고 편집 중이던 입력을 잃을 수 있다.
- **`EVAS_DEV_AUTH`는 운영 `.env`에 넣지 않는다.** 로그인 없이 신원을 헤더로 지정할 수 있는 개발·테스트용 우회 수단이다.
- 휴대폰에서의 내보내기(공유·저장)는 **HTTPS에서만** 동작한다. 운영은 Caddy HTTPS로 접속한다.

## 디스코드 로그인 설정
개발자 포털에서 애플리케이션을 만들고 OAuth2 > Redirects에 `PUBLIC_URL/auth/callback`을 등록한다. 봇은 필요 없다.

## 푸시 알림(선택)
`python scripts/make_vapid.py` 출력 세 줄을 `.env`에 붙여 넣는다. 한 번 정하면 바꾸지 않는다(바꾸면 기존 구독이 모두 무효).

## 테스트
`python -m pytest`
