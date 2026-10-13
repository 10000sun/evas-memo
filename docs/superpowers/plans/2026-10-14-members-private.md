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

### Task 3: 메모 — 비공개 공유 백엔드 (Task 1 이후, 사용자 확인 후 시작)
### Task 4: 메모 — 비공개 공유·사용자 태그 화면 (Task 3 이후)
(두 작업은 사용자 답변 후 세부화한다.)
