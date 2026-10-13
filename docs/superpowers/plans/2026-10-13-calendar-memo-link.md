# 메모 ↔ 캘린더 연동 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 메모와 캘린더(별도 서버·레포)를 `@` 태그, 연결 칩, 딥링크, 앱 전환 링크로 잇는다.

**Architecture:** 각 앱이 서버 내부 경로(`/internal/link/*`, 공유 비밀키)와 브라우저용 프록시 경로(`/api/link/*`, 로그인 세션)를 제공하고, 화면은 자기 서버의 프록시만 부른다. 태그는 본문에 `[@제목](주소)` 마크다운 링크로 저장한다.

**Tech Stack:** FastAPI, httpx(이미 사용), 순수 JS, CodeMirror 6 autocompletion(메모 화면).

**Spec:** `E:/폴더/개발/evas-memo/docs/superpowers/specs/2026-10-13-calendar-memo-link-design.md` ("계약" 절이 두 레포 공통 기준. 읽고 그대로 따른다)

## Global Constraints

- 두 레포: 메모 `E:/폴더/개발/evas-memo`, 캘린더 `E:/폴더/개발/evas-calendar`. 각자 `CLAUDE.md` 규칙(작업 → develop → main, **main 금지: 사용자가 "배포하라"고 할 때만**)을 따른다. 푸시 금지(이 계획에서는 푸시하지 않는다). 한글 메시지·주석·커밋, 브랜치 소문자 영어+하이픈.
- 캘린더 레포 주 체크아웃은 사용자가 쓰는 곳(`feat/filter-reset` 브랜치에 스테이징된 변경이 있다): **그 체크아웃을 건드리지 않는다.** 캘린더 작업은 `develop`에서 `git worktree add`로 만든 별도 작업 폴더에서 한다.
- 개인 메모 제목·존재가 캘린더로 나가는 모든 길을 만들지 않는다. `/internal/*`은 `X-Link-Key`(`secrets.compare_digest`) 없이는 404. `LINK_API_KEY` 미설정이면 연동 기능 전부 꺼지고 앱은 정상 동작.
- 상대 서버 호출은 타임아웃 3초, 실패해도 자기 앱 기능에 영향 없음(502 `{"detail":"연결할 수 없습니다"}`).
- 태그·칩·힌트의 제목은 항상 textContent(HTML로 해석 금지). `next` 리디렉션은 같은 사이트 경로만.
- 기존 테스트는 계속 통과해야 한다(메모 현재 70+개, 캘린더 기존 전체).

## Review Focus

1. `X-Link-Key` 없음/틀림/미설정으로 `/internal/link/*` 호출 → 404, 개인 메모 id를 `ids=`로 물어도 응답에 없음(Task 1).
2. `next=//evil.com`, `next=https://evil.com`, `next=/\evil` → `/`로 정규화(Task 1·2).
3. 상대 서버가 꺼져 있을 때 `/api/link/*` → 3초 안에 502, 자기 앱의 다른 API는 정상(Task 1·2).
4. 제목에 `<img onerror>`·`]`·`)`가 든 일정/메모를 태그 → 칩·힌트·본문에서 스크립트 실행 없음, 링크 형식이 깨지지 않음(Task 3·4).
5. 지워진 일정/메모를 가리키는 링크 칩 → "삭제됨" 표시, 클릭 시 상대 앱이 깨지지 않고 안내(Task 3·4).

---

### Task 1: 메모 서버 연동 API

**Files (메모 레포):** Create `app/links.py`, `tests/test_links.py`; Modify `app/main.py`(라우터 포함, `/api/config`), `app/auth.py`(`next`), `Caddyfile`, `Caddyfile.shared`, `.env.example`, `docs/DEPLOY.md`, `README.md`

**Interfaces:**
- Produces: 스펙 "메모 서버" 계약의 엔드포인트 전부(`/internal/link/memos`, `/api/link/events`, `/api/link/memos`, `/api/config`, 로그인 `next`). `app.links.memo_title_rows(...)` 같은 내부 헬퍼 이름은 자유. 환경변수 `LINK_API_KEY`, `CALENDAR_URL`(없으면 `SHARED_CALENDAR_URL`), `CALENDAR_INTERNAL_URL`.
- Consumes: 기존 `memos` 표(개인/공동·owner 필터는 `/api/link/memos` 쪽 기존 접근 규칙과 같게), 기존 `user_of`/`current_user`.

- [ ] **Step 1: 테스트** `tests/test_links.py`: `test_internal_requires_key`(헤더 없음/틀림/`LINK_API_KEY` 미설정 → 404, 맞으면 200), `test_internal_returns_only_shared_memos`(개인 메모 제목 검색·`ids=`에 개인 id 포함해도 결과에 없음), `test_internal_search_title_substring_and_limit`, `test_api_link_memos_scope`(`scope=shared`는 공동만, `scope=all`은 공동+본인 개인, 타인 개인 제외, `ids=` 지원), `test_api_link_events_proxies_with_key`(httpx를 가짜로 바꿔 끼워 `X-Link-Key`가 붙고 결과가 그대로 전달, 키는 응답에 없음), `test_api_link_events_upstream_down_is_502_fast`, `test_config_endpoint`, `test_login_next_sanitized`(`/auth/login?next=/?memo=5`는 세션에 보관, `//evil.com`·`https://evil.com`·`/\x` 는 `/`), `test_login_callback_redirects_to_next`(기존 로그인 콜백 테스트 방식으로).
- [ ] **Step 2: 실패 확인** `python -m pytest tests/test_links.py -v` → FAIL.
- [ ] **Step 3: 구현** 스펙 계약대로. 상대 호출은 `httpx.Client(timeout=3)`(동기 라우트이면 스레드풀 사용, async면 AsyncClient). Caddy 두 파일에 `/internal/*`을 바깥에 404로 돌려주는 matcher(`@internal path /internal/*` → `respond @internal 404`)를 `reverse_proxy` 앞에 넣는다. `.env.example`·README·DEPLOY에 `LINK_API_KEY`, `CALENDAR_URL`, `CALENDAR_INTERNAL_URL` 설명(비밀키 생성 명령 포함).
- [ ] **Step 4: 통과 확인** `python -m pytest -q` 전체 PASS.
- [ ] **Step 5: Commit** `feat/link-api` — "메모 연동 API: 내부 조회·프록시·설정·로그인 next"

### Task 2: 캘린더 서버 연동 API

**Files (캘린더 레포, 별도 worktree):** Create `app/links.py`, `tests/test_links.py`; Modify `app/main.py`(라우터·`/api/config`·단일 일정 조회), `app/auth.py`(`next`), `Caddyfile`, `.env.example`, `docs/DEPLOY.md`, `README.md`

**Interfaces:**
- Produces: 스펙 "캘린더 서버" 계약 전부(`/internal/link/events`, `/api/link/memos`, `/api/config`, `GET /api/events/{id}`(없으면 추가, 로그인 필요, 404), 로그인 `next`). 환경변수 `LINK_API_KEY`, `MEMO_URL`, `MEMO_INTERNAL_URL`.
- Consumes: 캘린더 기존 `events`/`categories`·`current_user`·로그인 콜백.

- [ ] **Step 1: 테스트** Task 1과 같은 모양: 키 없는/틀린/미설정 → 404, 일정 제목 부분 일치·limit·`ids=`·정렬, 프록시가 `X-Link-Key`를 붙이고 키를 노출하지 않음, 상대 서버 다운 시 502 빠르게, `/api/config`, `next` 정규화와 콜백 이동, `GET /api/events/{id}` 존재/없음/비로그인 401.
- [ ] **Step 2: 실패 확인** → **Step 3 구현** → **Step 4 통과 확인**(`python -m pytest -q` 캘린더 전체).
- [ ] **Step 5: Commit**(캘린더 worktree 브랜치 `feat/link-api`) — "캘린더 연동 API: 내부 조회·프록시·설정·단일 일정·로그인 next"

### Task 3: 캘린더 화면 (딥링크·앱 전환·메모 태그)

**Files (캘린더 레포, 별도 worktree, Task 2 위):** Modify `static/index.html`, `static/app.js`, `static/style.css`, 필요 시 `static/common.js`, `README.md`/도움말; Create/Modify tests가 필요하면 `tests/test_pwa.py` 등

**Interfaces:**
- Consumes: Task 2의 `/api/config`, `/api/link/memos`, `/api/events/{id}`.
- Produces: 헤더 `에바스 캘린더 | 에바스 메모` 전환(상대 주소가 `/api/config`에 있을 때만 링크, 현재 앱 강조, 모바일 폭에서 줄바꿈 안전); 일정 모달의 메모 칸에서 `@`+글자 → 입력칸 아래/위에 힌트 목록(공동 메모 제목, 최대 8개, 디바운스 250ms, 키보드 ↑↓ Enter Esc, 터치 가능, 실패 시 "연결할 수 없습니다")이 뜨고 선택하면 `[@제목](MEMO_URL/?memo=<id>)`로 치환(제목 이스케이프); 일정 목록/상세의 메모 표시에서 같은 형식의 링크를 칩(링크)으로 렌더(textContent, 새 탭이 아니라 같은 탭, 주소가 `MEMO_URL`로 시작하는 것만 칩, 그 밖은 일반 텍스트); 칩은 `ids=` 배치 조회로 최신 제목·삭제 여부 갱신; 딥링크 `/?event=<id>`(달 이동·날짜 선택·일정 강조, 없으면 토스트).
- 제한: 일정 제목 칸에는 `@` 힌트를 넣지 않는다.

- [ ] **Step 1~4**: 가능한 곳은 테스트(정적 파일에 요소 존재 등), 나머지는 브라우저 수동 확인(두 서버를 임시 DB·임시 포트로 띄우고 서로의 URL·같은 `LINK_API_KEY`를 환경변수로 넣어 확인; 로그인은 `EVAS_DEV_AUTH=1` 개발용 경로 사용). 못 확인한 것은 보고서에 그대로.
- [ ] **Step 5: Commit** `feat/link-ui` — "캘린더 화면: 메모 태그 힌트·칩, 딥링크, 앱 전환"

### Task 4: 메모 화면 (@ 태그·칩 줄·딥링크·앱 전환)

**Files (메모 레포; 폴더 화면(이전 계획 Task 3)이 develop에 합쳐진 뒤 시작):** Modify `tools/editor-entry.js`(자동완성 확장), `static/vendor/editor.bundle.js`(재빌드), `static/index.html`, `static/app.js`, `static/style.css`, `tests/test_static.py`, 도움말 문구

**Interfaces:**
- Consumes: Task 1의 `/api/link/events`, `/api/link/memos`, `/api/config`, 기존 `EvasEditor.create`.
- Produces: 에디터에 `@` 자동완성(`@codemirror/autocomplete`): `@`+글자(공백 없이)를 입력하면 힌트에 **일정**(날짜 표시)과 **메모**(공동 메모 본문에서는 공동만, 개인 메모 본문에서는 `scope=all`)가 구분 표시되어 뜨고, 선택하면 입력한 `@글자`를 `[@제목](주소)`로 치환(일정 주소 `CALENDAR_URL/?event=<id>`, 메모 주소 `PUBLIC_URL/?memo=<id>`; 제목의 `[]()`는 `\` 이스케이프); `EvasEditor.create`에 옵션 `linkSource: async (kind, q) => [...]`를 받아 번들이 네트워크를 모르게 한다; 자동완성 목록은 자기 메모 자신은 제외; 편집 화면 본문 위 "연결된 일정·메모" 칩 줄(본문의 해당 형식 링크를 파싱해 중복 제거, 본문 변경 시 디바운스 갱신, 칩은 일정이면 `CALENDAR_URL` 같은 탭 이동, 메모면 `?memo=` 또는 `#id`로 같은 탭 이동, 배치 조회로 최신 제목·삭제됨 표시, 실패 무시); 딥링크 `/?memo=<id>` → `#<id>`로 바꿔 편집 화면; 헤더 앱 전환(캘린더와 같은 규칙).

- [ ] **Step 1~4**: `tests/test_static.py`에 칩 줄·헤더 전환 요소 존재, 번들 재빌드(`cd tools && npx esbuild editor-entry.js --bundle --minify --outfile=../static/vendor/editor.bundle.js`), `python -m pytest -q`. 브라우저 수동: 힌트·칩·딥링크·로그인 뒤 복귀, 상대 서버를 껐을 때 입력이 막히지 않음, 개인 메모 본문의 힌트에만 본인 개인 메모가 보이고 공동 메모 본문에는 안 보임, 375px, 다크/라이트. 못 확인한 것은 그대로 적는다.
- [ ] **Step 5: Commit** `feat/link-ui` — "메모 화면: @ 태그 힌트, 연결 칩, 딥링크, 앱 전환"

### Task 5: 두 앱 통합 확인

- [ ] **Step 1:** 두 레포의 `develop`을 각각 임시 DB·임시 포트(메모 8791, 캘린더 8792)로 띄우고 같은 `LINK_API_KEY`·서로의 `*_URL`/`*_INTERNAL_URL`을 환경변수로 준다.
- [ ] **Step 2:** 브라우저로 확인: 메모에서 `@`로 일정·메모 태그 → 칩 → 캘린더 이동(일정 강조), 캘린더 메모 칸에서 `@`로 공동 메모 태그 → 칩 → 메모 열림, 두 앱 헤더 전환, 로그아웃 상태에서 딥링크 → 로그인 → 딥링크 복귀(`EVAS_DEV_AUTH` 경로로 대체 가능), 개인 메모 제목이 캘린더 힌트·내부 경로에 안 나옴, `/internal/link/*` 키 없이 404, 한쪽 서버 중지 후 다른 쪽 입력 정상.
- [ ] **Step 3:** 결과와 못 한 것을 사용자에게 보고. **여기서 멈춘다**(`main` 금지).
