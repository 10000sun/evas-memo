# 사용자 자동 등록 · 비공개 공유 · 사용자 태그 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 접속한 사용자를 자동 등록(메모·캘린더), 공동 메모·폴더의 선택한 사람만 공개, 본문의 사용자 태그.

**Architecture:** `members` 표(접속 기록)는 권한과 분리. 비공개 공유는 공동 kind 위의 공개 범위 속성(`visibility` + `memo_viewers`/`folder_viewers`)이고 모든 접근 판정은 기존 단일 접근 함수(`ws.can_access`)에 모은다.

**Tech Stack:** 기존(FastAPI, SQLite, pycrdt, 순수 JS, CodeMirror).

**Spec:** `docs/superpowers/specs/2026-10-14-members-private-design.md`

## Global Constraints

- 한글, 브랜치 소문자 영어+하이픈, 푸시 금지(배포 지시 전), main 금지. 운영 DB는 `ALTER`/`CREATE TABLE IF NOT EXISTS`로 안전하게 이전(기존 데이터 보존, 멱등).
- `members`는 권한을 바꾸지 않는다. 비공개 공유 메모·폴더는 대상이 아닌 사람(관리자 제외)에게 존재가 드러나는 경로가 없어야 한다(전율과 같은 수준).
- 기존 테스트는 계속 통과(메모 143개, 캘린더 90개).

## Review Focus

1. `EVAS_OPEN_EDIT=0`에서 새 사용자가 접속해도 `members`에만 등록되고 편집 권한은 생기지 않는다(Task 1·2).
2. 비공개 공유 메모 id를 목록에 없는 사람이 직접 요청(조회·수정·삭제·WS·검색·폴더 지정·이동·복사·링크 API)해도 없는 메모와 같은 응답(Task 3).
3. 폴더를 비공개로 하거나 사람 목록을 바꾸면 안의 메모(하위 폴더 포함)에 즉시 반영되고 빠진 사람의 연결이 끊긴다(Task 3).

---

### Task 1: 메모 — 사용자 자동 등록 + 관리자 화면 목록
**Files:** `app/db.py`, `app/auth.py`, `app/main.py`, `static/admin.html`, `static/admin.js`, `static/admin.css`, 테스트
- [ ] 스펙 "1. 사용자 자동 등록"대로: `members` 표(`CREATE TABLE IF NOT EXISTS`), 로그인 콜백·`/auth/dev`·`GET /api/me`에서 upsert(이름 갱신, last_seen은 하루 한 번 수준), `GET /api/members`(관리자만, members ∪ users 합쳐 유효 권한 포함), `GET /api/members/pick?q=`(로그인 누구나, `{id,name}`만, 최대 20개), 관리자 화면 "접속한 사용자" 목록 + 권한 변경·기본값 복귀. 테스트: 첫 접속 등록, 이름 갱신, `EVAS_OPEN_EDIT=0`에서 권한 불변, 비관리자의 `/api/members` 403, pick이 id 외 정보를 안 줌, 기존 users와 합쳐 표시. Commit `feat/members` — "접속한 사용자 자동 등록과 관리자 화면 목록".

### Task 2: 캘린더 — 사용자 자동 등록 + 관리자 화면 목록 (캘린더 레포, 별도 worktree)
**Files (캘린더):** `app/db.py`, `app/auth.py`, `app/main.py`, `static/admin.html`, `static/admin.js`, 테스트
- [ ] Task 1과 같은 동작(캘린더의 기존 구조에 맞춰): `members` 표, 로그인 콜백·`/api/me` upsert, `GET /api/members`(관리자만), 관리자 화면 "접속한 사용자" 목록, 권한 불변. 캘린더에는 `members/pick`을 만들지 않는다. Commit `feat/members` — "접속한 사용자 자동 등록과 관리자 화면 목록".

### Task 3: 메모 — 비공개 공유 백엔드 (Task 1이 develop에 합쳐진 뒤)
**Files:** `app/db.py`, `app/memos.py`, `app/folders.py`, `app/ws.py`(접근 함수·연결 종료), `app/links.py`, `app/activity.py`, 테스트 `tests/test_private_share.py`, `tests/test_db_migration_private.py`
**Interfaces:**
- Produces: `memos.visibility`·`folders.visibility` 열(`TEXT NOT NULL DEFAULT 'all'`, 값 `all|restricted`, `ALTER TABLE ADD COLUMN`으로 추가, 멱등), 표 `memo_viewers(memo_id, user_id, PRIMARY KEY(memo_id,user_id))`·`folder_viewers(folder_id, user_id, PRIMARY KEY(folder_id,user_id))`(`CREATE TABLE IF NOT EXISTS`, memo/folder 삭제 시 `ON DELETE CASCADE`); `PUT /api/memos/{id}/share-with` body `{"visibility":"all"|"restricted","viewers":["<id>",...]}` 와 `PUT /api/folders/{id}/share-with` 같은 모양(만든 사람·관리자만, viewers는 `members`에 있는 id만(없는 id는 422), 최대 50명, 제한 모드에서 viewers가 비어 있어도 허용(만든 사람+관리자만 봄)); `GET /api/memos/{id}`·`GET /api/folders` 응답에 `visibility`와(권한 있는 사람에게만) `viewers: [{id,name}]`; 목록 필터는 단일 접근 함수(`ws.can_access`)가 `kind=shared`일 때 `visibility`·`memo_viewers`·폴더 상속·`role=admin`·작성자를 판정.
- 규칙(스펙 2절): 선택된 사람은 보기+편집(편집은 기존 editor/admin 역할 규칙을 따른다: 역할이 viewer면 읽기 전용 그대로), 만든 사람·관리자 항상 접근, 폴더가 제한이면 안의 모든 메모(하위 폴더 포함)는 폴더 목록을 따른다(메모 자신의 설정은 무시; 제한 폴더의 메모에 `share-with`를 호출하면 409), 메모를 제한 폴더로 옮기거나 폴더를 제한으로 바꾸거나 목록에서 사람을 빼면 해당 방의 접근을 잃은 접속자를 즉시 닫는다(코드 4404, 사유는 삭제와 같은 문구), 제한 → 전체 전환은 허용, 제한 메모·폴더는 `/internal/link/*`·활동 기록·푸시·`rev`에 나오지 않는다(공동 메모가 제한으로 바뀌면 활동에 '삭제' 한 줄만, 전율로 옮길 때와 같은 방식), 제한 메모를 전율/개인으로 이동하면 viewers 정리, 공동 → 개인 복사·`/api/link/memos`·검색·태그 힌트는 접근 함수를 통과한 것만, 존재 숨김은 404 동일 응답.
- [ ] 테스트(RED→GREEN): 선택된 사람만 보임/편집, 목록에 없는 editor는 목록·검색·GET·PUT·DELETE·WS·폴더 지정·이동·복사·링크 API에서 없는 것과 같은 404, 관리자는 항상 접근, 만든 사람 접근, 사람 제거 시 연결 4404, 폴더 제한 상속(하위 폴더 포함, 목록 변경 즉시 반영, 폴더로 옮기기), `members`에 없는 id 422, 활동·rev·푸시·내부 링크에 안 나옴, 제한→전체 전환, 운영 모양 DB(두 열·두 표 없음)의 멱등 이전, TOCTOU(쓰기 조건에 현재 visibility 검증), 접근 함수가 모든 경로의 유일한 판정.
- [ ] Commit `feat/private-share-api` — "비공개 공유 백엔드: 공개 범위, 선택한 사람, 폴더 상속"

### Task 4: 메모 — 비공개 공유 화면 + 사용자 태그 (Task 3 이후)
**Files:** `static/index.html`, `static/app.js`, `static/style.css`, `tools/editor-entry.js`(+번들), `static/memolink.js`, 테스트
**Interfaces:** Consumes Task 3 API, `GET /api/members/pick`. Produces: 편집 화면·폴더 줄의 자물쇠 표시와 "공개 범위" 창(전체/선택한 사람, 이름 검색, 체크, 선택된 사람 칩, 저장, 전체로 되돌릴 때 확인창), 카드의 자물쇠+"N명"(권한 있는 사람에게만 인원), 제한 폴더 안 메모의 설정 비활성+안내, 접근 상실 시 4404 처리(기존), `@` 힌트의 사람 항목(`pick` 호출, 사람은 일정·메모와 구분 표시)과 `[@이름](user:<id>)` 삽입 → 미리보기·에디터·칩 줄에서 클릭 불가 "사람 칩"(스펙 3절; DOMPurify 링크 규칙에 `user:` 스킴 추가는 하지 말고 미리보기 렌더 단계에서 `user:` 링크를 `<span class="md-user">@이름</span>`로 치환, 이름 최신화는 `members/pick`이 아니라 배치 조회가 필요하면 `GET /api/members/pick?ids=`를 추가(이 경우 Task 1과 호환되게)). 전율·개인 탭에는 공개 범위 UI가 없다.
- [ ] 수동 확인(브라우저): 두 사용자+관리자로 비공개 메모·폴더 만들기, 선택된 사람만 보임, 관리자는 전부 보임, 사람 빼면 연결 끊김, `@` 사람 태그, 375px, 다크. 못 확인한 것은 보고서에.
- [ ] Commit `feat/private-share-ui` — "비공개 공유 화면과 사용자 태그"
