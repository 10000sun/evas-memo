# 전율 탭(관리자 전용 메모 공간) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 관리자만 쓰는 세 번째 메모 종류 `admin`(화면 라벨 "전율")을 추가하고, 개인·공동 메모를 오가며 옮길 수 있게 한다.

**Architecture:** 기존 `memos.kind`/`folders.kind`에 `admin`을 더한다(CHECK 제약 때문에 `db.init`에서 테이블 재작성 이전). 모든 접근 경로가 한 곳의 접근 함수를 거치게 하고(관리자가 아니면 404), 이동 API와 열려 있는 편집 방 정리, 권한 상실 시 연결 종료를 추가한다. 화면은 별도 작업.

**Tech Stack:** FastAPI, SQLite, pycrdt rooms(`app/ws.py`), 기존 테스트 구조.

**Spec:** `docs/superpowers/specs/2026-10-13-admin-space-design.md` (이전 설계 문서들도 유효, 충돌 시 이 문서 우선)

## Global Constraints

- 한글 메시지·주석·커밋, 브랜치 소문자 영어+하이픈, 푸시 금지, **main 금지(사용자가 "배포하라"고 할 때만)**.
- 비관리자에게 전율 메모·폴더의 존재가 드러나는 경로가 하나도 없어야 한다: 목록·검색(`q`)·`GET/PUT/DELETE /api/memos/{id}`·`share`·`copy-to-personal`·`move`·폴더 API·`/api/link/*`·`/internal/link/*`·활동/rev/푸시·WebSocket·오류 응답 차이(없음과 권한 없음이 같은 404).
- 기존 테스트(현재 111개 이상)는 계속 통과. 운영 DB(기존 스키마)가 `db.init`으로 안전하게 이전된다(멱등, 데이터 보존).
- 이동 중 데이터 유실·중복 금지, 이동으로 권한이 줄어든 접속자는 즉시 연결 종료(메모 삭제와 같은 4404), 관리자 권한을 잃은 사용자의 전율 메모 연결은 4403으로 종료.

## Review Focus

1. 비관리자가 전율 메모 id를 직접 요청(조회·수정·삭제·이동·복사·폴더 지정·WS)해도 응답이 "없는 메모"와 구별되지 않는다(Task 1).
2. 기존 스키마의 운영 DB(메모·폴더·활동 데이터 포함, `sqlite_sequence` 값 포함)를 이전한 뒤 데이터·id·외래키·AUTOINCREMENT가 보존되고, 이전을 두 번 해도 무해하다(Task 1).
3. 관리자 A가 전율 메모를 편집 중일 때 A가 강등되거나 삭제되면 그 연결이 끊긴다. 공동 메모를 열어 둔 비관리자가 있는 상태에서 관리자가 전율로 옮기면 그 비관리자의 연결이 끊긴다(Task 1).
4. 전율 메모 제목이 `/api/activity`의 항목·`rev`, 푸시, `/internal/link/memos`, 캘린더 프록시 어디에도 나오지 않는다(Task 1).
5. `scope=admin` 힌트가 공동 + 본인 개인 + 전율만 주고 타인의 개인 메모는 절대 주지 않는다(Task 1).

---

### Task 1: 전율 백엔드 (스키마 이전·접근 규칙·이동·연결 종료)

**Files:** Modify `app/db.py`, `app/memos.py`, `app/folders.py`, `app/ws.py`, `app/links.py`, `app/activity.py`(필요 시), `app/main.py`(사용자 역할 변경 훅); Create `tests/test_admin_space.py`, `tests/test_db_migration_admin.py`

**Interfaces:**
- Produces: `memos.kind`·`folders.kind` 값 `admin`; `POST /api/memos/{id}/move` body `{"to": "personal"|"shared"|"admin"}` → 이동한 메모 JSON(폴더 NULL); `GET /api/memos?kind=admin`, `GET /api/folders?kind=admin`, `POST /api/folders {kind:"admin"}`; `GET /api/link/memos?scope=admin`; WebSocket 닫기 코드 4404(접근 상실)·4403(관리자 권한 상실); 내부 접근 함수(이름 자유, 예: `can_access(user, row)`)가 모든 종류 판정을 한 곳에서 한다.
- Consumes: 기존 `memos`/`folders`/`ws.rooms`/`activity`/`links` 모듈, `current_user`(role).

- [ ] **Step 1: 테스트** `tests/test_db_migration_admin.py::test_old_schema_is_rebuilt_in_place`(현재 스키마에서 `kind` CHECK가 두 값뿐인 `memos`·`folders`를 가진 임시 DB를 직접 만들어 메모·폴더·활동·`sqlite_sequence`를 채움 → `db.init()` 후 모든 행·id·`folder_id`·`category_id` 보존, `INSERT ... kind='admin'` 가능, 인덱스/AUTOINCREMENT 유지(삭제 후 새 행이 옛 id 재사용 안 함), `PRAGMA foreign_key_check` 비어 있음, `db.init()` 두 번째 호출 무해). `tests/test_admin_space.py`: `test_non_admin_cannot_see_admin_memo_anywhere`(관리자가 전율 메모 생성 → 비관리자(editor)가 목록·`q` 검색·GET·PUT·DELETE·share·copy-to-personal·move·폴더 지정·`kind=admin` 조회·`/api/link/memos` 모든 scope·`/internal/link/memos`(키 있음)·`/api/activity`·`rev` 확인: 전부 없는 메모와 같은 404 또는 결과에 없음, `kind=admin` 목록·폴더 조회는 404), `test_admin_can_use_admin_space`(두 관리자가 서로의 전율 메모 열람·편집·삭제, 폴더 생성), `test_move_transitions`(personal→admin 소유자만, shared→admin, admin→shared(활동 '작성'), admin→personal(이동한 사람이 소유자, 다른 관리자에게는 사라짐), 허용되지 않은 전이 422, 폴더는 NULL, 본문 보존), `test_move_to_admin_requires_admin_role`, `test_shared_to_admin_closes_non_admin_connections`(비관리자가 연결해 둔 공동 메모를 전율로 이동 → 4404로 닫힘, 관리자 연결은 유지), `test_admin_to_personal_closes_other_admins`, `test_demoted_admin_connection_closed_4403`(관리자 A가 전율 메모에 WS 연결 → 관리자가 `PUT /api/users/A` role=editor → A 연결 종료, 삭제도 동일), `test_no_activity_or_push_for_admin_kind`(전율 생성·편집·삭제·이동 중 `shared→admin`('삭제' 한 줄 외)·`admin→personal`에서 활동 기록·푸시 없음), `test_link_scope_admin`(`scope=admin`: 관리자만, 공동 + 본인 개인 + 전율, 타인 개인 제외, 비관리자 404), `test_internal_link_never_returns_admin_kind`, `test_admin_folders_kind_match_and_permissions`.
- [ ] **Step 2: 실패 확인** `python -m pytest tests/test_db_migration_admin.py tests/test_admin_space.py -v` → FAIL.
- [ ] **Step 3: 구현** 스펙 "결정"대로. 접근 판정은 한 함수에 모으고 모든 라우트·WS·링크·폴더가 그 함수를 쓰게 한다(복붙 금지). 테이블 재작성은 새 표 생성→`INSERT INTO new SELECT … FROM old`→DROP→RENAME, 인덱스 재생성, `sqlite_sequence` 복사, 외래키 OFF/ON과 `foreign_key_check`.
- [ ] **Step 4: 통과 확인** `python -m pytest -q` 전체 PASS.
- [ ] **Step 5: Commit** `feat/admin-space-api` — "전율 탭 백엔드: 관리자 전용 종류, 스키마 이전, 이동 API, 접근 종료"

### Task 2: 전율 화면 (탭·이동 버튼·폴더·힌트 범위)

**Files:** Modify `static/index.html`, `static/app.js`, `static/style.css`, 도움말·README, `tests/test_static.py` (폴더 화면·마크다운·연동 화면 작업이 develop에 합쳐진 뒤 시작)

**Interfaces:** Consumes Task 1의 `/api/memos?kind=admin`, `/api/folders?kind=admin`, `POST /api/memos/{id}/move`, `/api/link/memos?scope=admin`, `/api/me`의 `role`. Produces: 스펙 "화면" 절의 동작.

- [ ] **Step 1~4**: 정적 테스트(관리자에게만 전율 탭 DOM 생성은 클라이언트 로직이라 수동), 수동 확인(관리자/비관리자 두 사용자: 비관리자에게 탭·버튼·메시지 흔적 없음, 이동 확인창 문구, 이동 뒤 열린 화면 처리(4404 안내 후 목록), 전율 탭 폴더·분류·검색, `@` 힌트 범위, 375px, 다크/라이트). 못 확인한 것은 보고서에 그대로.
- [ ] **Step 5: Commit** `feat/admin-space-ui` — "전율 탭 화면: 탭, 이동 버튼, 폴더, 태그 범위"
