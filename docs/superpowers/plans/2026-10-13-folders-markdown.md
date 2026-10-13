# evas-memo 폴더·마크다운·커서 색 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 메모에 마크다운(입력 강조 + 미리보기), 개인/공동 폴더(1단계 하위 폴더), 접속자별 겹치지 않는 커서 색을 추가한다.

**Architecture:** 기존 FastAPI + SQLite + Yjs 구조 위에 `folders` 표와 `memos.folder_id` 열을 더하고(`db.init`에서 운영 DB에 안전하게 이전), REST로 폴더를 관리한다. 마크다운은 클라이언트에서만: 입력 강조는 에디터 번들에 `@codemirror/lang-markdown`, 미리보기는 `marked`+`DOMPurify`를 별도 번들(`static/vendor/markdown.bundle.js`)로 만들어 렌더한다.

**Tech Stack:** 기존 + marked, dompurify, @codemirror/lang-markdown (esbuild로 번들, `tools/`).

**Spec:** `docs/superpowers/specs/2026-10-13-folders-markdown-design.md` (기존 설계 `2026-10-13-evas-memo-design.md`도 유효)

## Global Constraints

- 한글 UI·메시지·주석·커밋 메시지. 브랜치 소문자 영어+하이픈. main 금지(사용자가 "배포하라"고 할 때만), 푸시 금지(이 계획에서는 푸시하지 않는다).
- 폴더 이름 1~30자, 같은 위치(같은 kind·owner·parent)에서 중복 불가. 폴더 깊이 최대 2(폴더 > 하위 폴더).
- 공동 폴더: 생성·이름변경은 `admin|editor`, 삭제는 만든 사람 또는 관리자. 개인 폴더: 본인만(관리자 포함 타인 불가, 존재도 404). 폴더 삭제 시 하위 폴더도 삭제, 그 안의 메모는 `folder_id` NULL로 남는다(메모 삭제 금지).
- 메모의 `folder_id`는 메모와 같은 kind여야 하고 개인이면 본인 폴더여야 한다. 개인→공동 이동·공동→개인 복사 시 새 쪽의 `folder_id`는 NULL.
- 운영 중인 DB(폴더 도입 전 스키마)가 `db.init`으로 안전하게 이전되어야 한다: 기존 메모·사용자·활동 데이터 보존.
- 미리보기는 HTML 무해화 필수. 링크는 `target="_blank" rel="noopener noreferrer"`, 허용 스킴은 http/https/mailto.
- 기존 61개 테스트는 계속 통과해야 한다. 번들은 개발 PC에서 빌드해 커밋(`static/vendor/`), 서버에 Node 불필요.

## Review Focus

1. 폴더 도입 전 스키마의 DB 파일을 `db.init`로 열기 → 데이터 보존, 폴더·`folder_id` 추가됨(Task 1).
2. 다른 사용자의 개인 폴더 id로 폴더 조회/수정/삭제/메모 지정 → 404(존재 숨김) (Task 1).
3. 마크다운에 `<script>`, `<img onerror=…>`, `[x](javascript:…)`, 원시 HTML이 든 메모를 미리보기 → 스크립트 실행 없음(Task 2).
4. 폴더 삭제(하위 폴더 포함) 후 그 안의 메모가 목록에 남음, 폴더를 지운 직후 열려 있던 목록/편집 화면이 깨지지 않음(Task 1·3).
5. 3명이 동시에 접속·퇴장·재접속해도 커서 색이 겹치지 않고 깜빡이지 않음(Task 2).

---

### Task 1: 폴더 백엔드 (스키마 이전·폴더 API·메모의 폴더 지정)

**Files:**
- Modify: `app/db.py`, `app/memos.py`, `app/main.py`(라우터 포함)
- Create: `app/folders.py`, `tests/test_folders.py`, `tests/test_db_migration.py`

**Interfaces:**
- Consumes: `app.auth.user_of`/`main.current_user`·`editor` 의존성, `db.connect()`, 기존 `memos` 라우트·`_get`.
- Produces:
  - 표 `folders(id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT CHECK(kind IN ('personal','shared')), owner_id TEXT NULL(개인일 때만), parent_id INTEGER NULL REFERENCES folders(id) ON DELETE CASCADE, name TEXT NOT NULL, created_by TEXT, created_name TEXT, created_at TEXT)`, 열 `memos.folder_id INTEGER NULL REFERENCES folders(id) ON DELETE SET NULL`. `db.init`이 기존 DB에도 `folders` 표(IF NOT EXISTS)와 `memos.folder_id`(ALTER, 열이 없을 때만)를 만든다.
  - `GET /api/folders?kind=personal|shared` → `[{id, kind, parent_id, name, created_by, created_name}]` (personal은 본인 것만). `POST /api/folders` body `{kind, name, parent_id|null}` → 201 폴더 JSON. `PUT /api/folders/{id}` body `{name}` → 폴더 JSON. `DELETE /api/folders/{id}` → 204.
  - 메모 JSON에 `folder_id`가 추가된다. `PUT /api/memos/{id}`가 `folder_id`(int|null) 를 받는다. `GET /api/memos?folder_id=<int>|none`(none = 폴더 없음, 생략 = 전체; 하위 폴더 메모 포함 여부: 지정 폴더 **직속** 메모만).
  - 메모 목록 JSON에 `folder_id`만 있고 폴더 이름은 클라이언트가 `/api/folders`로 조합한다.

- [ ] **Step 1: 테스트** `tests/test_db_migration.py::test_old_schema_db_is_upgraded_in_place` — 폴더 도입 전 스키마(현재 `db.SCHEMA`에서 `folders`와 `memos.folder_id`를 뺀 것을 직접 만든 임시 sqlite 파일; 메모 1건·사용자 1건 insert)를 `EVAS_DB`로 지정해 `db.init()` 호출 → 메모·사용자 보존, `PRAGMA table_info(memos)`에 `folder_id`, `folders` 표 존재, `db.init()` 두 번째 호출도 오류 없음. `tests/test_folders.py`: `test_personal_folder_hidden_from_others`(타인 GET 목록에 없음, 타인이 PUT/DELETE/메모 지정 시 404, 관리자도 동일), `test_shared_folder_create_rename_by_editor_delete_by_creator_or_admin`, `test_depth_limit_two_levels`(하위 폴더 아래에 또 만들면 422), `test_name_validation_and_duplicates`(빈 이름·31자·같은 위치 중복 422/409, 다른 위치 같은 이름 OK), `test_delete_folder_keeps_memos_and_removes_subfolders`(하위 폴더 삭제, 메모 `folder_id`가 NULL로 남고 목록에 있음), `test_memo_folder_kind_must_match`(개인 메모에 공동 폴더 지정 422, 타인 개인 폴더 지정 404), `test_filter_memos_by_folder_and_none`, `test_move_and_copy_reset_folder`(share/copy-to-personal 결과의 `folder_id`가 null).
- [ ] **Step 2: 실패 확인** `python -m pytest tests/test_db_migration.py tests/test_folders.py -v` → FAIL.
- [ ] **Step 3: 구현** 위 인터페이스대로. 같은 위치 중복은 앱 코드에서 검사(NULL parent·owner 때문에 UNIQUE 인덱스 대신). 응답 코드: 권한 없음 403, 존재 숨김 404, 검증 실패 422, 중복 409.
- [ ] **Step 4: 통과 확인** `python -m pytest -q` → 기존 61개 포함 전부 PASS.
- [ ] **Step 5: Commit** `feat/folders-api` — "폴더 API: 스키마 이전, 개인/공동 폴더, 메모의 폴더 지정"

### Task 2: 마크다운(입력 강조·미리보기)과 접속자별 커서 색

**Files:**
- Modify: `tools/package.json`, `tools/editor-entry.js`, `static/vendor/editor.bundle.js`(재빌드), `static/index.html`, `static/app.js`, `static/style.css`, `static/common.js`(필요 시), `tests/test_static.py`
- Create: `tools/markdown-entry.js`, `static/vendor/markdown.bundle.js`(빌드 결과 커밋)

**Interfaces:**
- Consumes: 기존 `window.EvasEditor.create({parent, memoId, user}) -> {destroy, view, awareness, provider}`, `app.js`의 `colorOf(id)`·같이 보는 사람 표시.
- Produces: `window.EvasMarkdown.render(text: string): string`(무해화된 HTML 문자열; `marked` GFM + `DOMPurify`, 링크에 `target="_blank" rel="noopener noreferrer"`, 허용 스킴 http/https/mailto, 체크박스는 disabled); 에디터에 마크다운 문법 강조 확장 추가; 편집 화면에 `편집 | 미리보기` 전환(미리보기 중에도 다른 사람의 입력이 실시간 반영); 커서 색 배정: `assignDistinctColor(awareness, myPreferred, palette)` 규칙 — 같은 색을 쓰는 다른 접속자가 있고 그 clientID가 내 것보다 작으면 비어 있는 색(팔레트에서 아무도 안 쓰는 첫 색)으로 바꾸고 `awareness.setLocalStateField("user", …)`로 알린다. 팔레트 12색 이상, 라이트·다크 모두에서 읽히는 색.

- [ ] **Step 1: 테스트** `tests/test_static.py`에 `test_markdown_bundle_served`(`/vendor/markdown.bundle.js` 200, `EvasMarkdown` 포함)와 `test_index_has_preview_toggle`(`index.html`에 미리보기 전환 요소). XSS·색 배정 로직은 브라우저 동작이라 단위 테스트 대신 아래 수동 확인 + 번들을 Node로 불러 `EvasMarkdown.render`를 호출하는 스크립트 테스트(`tools/test-markdown.mjs`, `node tools/test-markdown.mjs`가 종료 코드 0): 입력 `<script>alert(1)</script>`, `<img src=x onerror=alert(1)>`, `[x](javascript:alert(1))`, `**굵게**`, `- [ ] 할 일`, 표 → 출력에 `<script`·`onerror`·`javascript:`가 없고 `<strong>`·체크박스·`<table>`이 있다(DOM이 필요하면 jsdom을 `tools/`의 devDependency로 쓴다).
- [ ] **Step 2: 실패 확인** `python -m pytest tests/test_static.py -v`, `node tools/test-markdown.mjs` → FAIL.
- [ ] **Step 3: 구현** `tools/package.json`에 marked, dompurify, @codemirror/lang-markdown(+jsdom dev) 추가. `tools/markdown-entry.js`가 `window.EvasMarkdown`을 노출. 빌드: `cd tools && npm i && npx esbuild editor-entry.js --bundle --minify --outfile=../static/vendor/editor.bundle.js && npx esbuild markdown-entry.js --bundle --minify --outfile=../static/vendor/markdown.bundle.js`. 에디터에 `markdown()` 확장 추가. 미리보기는 `e-body` 옆 `e-preview` 영역에 렌더하고 Yjs 텍스트 변경 시 갱신(디바운스). 커서 색 배정은 `app.js`에서 awareness `change` 때 실행(깜빡임 방지: 이미 겹치지 않으면 바꾸지 않는다). 스타일: 미리보기·강조의 다크/라이트, 표·코드·인용 스타일.
- [ ] **Step 4: 통과 확인** `python -m pytest -q`, `node tools/test-markdown.mjs`.
- [ ] **Step 5: 수동 확인(브라우저 pane)** 마크다운 작성 후 미리보기 전환, 두 탭에서 동시 입력 중 미리보기가 따라옴, 3개 탭(서로 다른 사용자)에서 커서 색이 모두 다름(같은 선호 색이 겹치도록 id를 골라 시험), 다크/라이트·375px. 못 확인한 것은 보고서에 그대로 적는다.
- [ ] **Step 6: Commit** `feat/markdown-cursor` — "마크다운 입력 강조·미리보기와 접속자별 커서 색 배정"

### Task 3: 폴더 화면

**Files:**
- Modify: `static/index.html`, `static/app.js`, `static/style.css`, `static/common.js`(필요 시), `README.md`, 도움말 문구(`index.html` 안), `tests/test_static.py`

**Interfaces:**
- Consumes: Task 1 API(`/api/folders`, 메모의 `folder_id`, `GET /api/memos?folder_id=`), Task 2의 편집 화면.
- Produces: 목록 위 폴더 줄(`전체 · 폴더 없음 · 폴더들(칩) · + 새 폴더`), 폴더를 고르면 그 하위 폴더 줄이 이어 나오고 하위 폴더에서는 `+ 새 폴더`가 없다; 선택한 폴더에 이름 바꾸기·삭제(삭제 확인창에 "안의 메모는 '폴더 없음'으로 남습니다"; 공동 폴더는 만든 사람·관리자가 아니면 삭제 버튼 숨김); 메모 카드에 폴더 경로(`폴더 / 하위 폴더`); 편집 화면의 폴더 선택(현재 kind의 폴더만, 하위 폴더는 들여쓰기); 개인/공동 탭 전환 시 폴더 선택 초기화; 폴더 삭제로 보고 있던 폴더가 사라지면 "전체"로 복귀; 20초 자동 갱신 때 폴더 목록도 갱신(선택 중인 폴더가 그대로 유지되고, 사라졌으면 전체로); 도움말과 README에 마크다운·폴더 설명 추가.

- [ ] **Step 1: 테스트** `tests/test_static.py`에 `test_index_has_folder_ui`(폴더 줄·폴더 선택 요소 id 존재). 나머지는 수동.
- [ ] **Step 2: 실패 확인 → Step 3 구현 → Step 4 통과 확인** (`python -m pytest -q`).
- [ ] **Step 5: 수동 확인(브라우저 pane)** 개인/공동 각각 폴더·하위 폴더 생성, 메모를 폴더로 지정·이동, 폴더 이름 바꾸기, 폴더 삭제 후 메모가 "폴더 없음"에 남음, 두 번째 사용자에게 개인 폴더가 안 보임·공동 폴더는 보임, 다른 탭에서 폴더를 지웠을 때 목록이 깨지지 않음, 375px, 다크/라이트. 못 확인한 것은 보고서에 적는다.
- [ ] **Step 6: Commit** `feat/folders-ui` — "폴더 화면: 폴더 줄, 폴더 선택, 이름 변경·삭제"
