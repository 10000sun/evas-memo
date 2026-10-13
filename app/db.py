import logging
import os
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime

log = logging.getLogger(__name__)

DEFAULT_CATEGORIES = [
    ("공지", "#e57373"), ("아이디어", "#ffb74d"), ("할 일", "#64b5f6"), ("참고", "#81c784"),
]

# 종류: personal(개인)·shared(공동)·admin(전율, 관리자 전용). 아래 두 표는 옛 CHECK를 고치려고 init에서 다시 만들 수 있다
# 폴더: 상위 폴더가 지워지면 하위도 함께 지워지고, 메모는 folder_id만 NULL로 남는다
FOLDERS = """CREATE TABLE IF NOT EXISTS folders(
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL CHECK(kind IN ('personal','shared','admin')),
  owner_id TEXT, parent_id INTEGER REFERENCES folders(id) ON DELETE CASCADE, name TEXT NOT NULL,
  created_by TEXT, created_name TEXT, created_at TEXT,
  visibility TEXT NOT NULL DEFAULT 'all' CHECK(visibility IN ('all','restricted')))"""
# AUTOINCREMENT: 지운 메모의 id를 다시 쓰지 않는다(아직 열려 있는 옛 메모의 실시간 방에 새 메모가 섞이지 않게)
MEMOS = """CREATE TABLE IF NOT EXISTS memos(
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL CHECK(kind IN ('personal','shared','admin')),
  owner_id TEXT, title TEXT NOT NULL DEFAULT '',
  category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
  folder_id INTEGER REFERENCES folders(id) ON DELETE SET NULL,
  body_text TEXT NOT NULL DEFAULT '', ydoc BLOB,
  created_by TEXT, created_name TEXT, updated_by TEXT, updated_name TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
  visibility TEXT NOT NULL DEFAULT 'all' CHECK(visibility IN ('all','restricted')))"""

SCHEMA = f"""
CREATE TABLE IF NOT EXISTS categories(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, color TEXT NOT NULL);
{FOLDERS};
{MEMOS};
CREATE INDEX IF NOT EXISTS memos_kind_owner ON memos(kind, owner_id);
CREATE TABLE IF NOT EXISTS activity(
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('add','edit','delete')), memo_id INTEGER,
  title TEXT NOT NULL, actor_id TEXT NOT NULL, actor_name TEXT NOT NULL, at TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS activity_read(user_id TEXT PRIMARY KEY, last_id INTEGER NOT NULL);
CREATE TABLE IF NOT EXISTS push_subs(
  endpoint TEXT PRIMARY KEY, user_id TEXT NOT NULL, p256dh TEXT NOT NULL, auth TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS users(
  id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','editor')));
-- 접속 기록일 뿐 권한과 무관하다(권한은 users). 운영 DB에는 IF NOT EXISTS로 표만 더해진다
CREATE TABLE IF NOT EXISTS members(
  id TEXT PRIMARY KEY, name TEXT NOT NULL, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL);
-- 비공개 공유: visibility='restricted'인 공동 메모·폴더를 볼 수 있는 사람(만든 사람·관리자는 목록과 무관하게 항상 본다)
CREATE TABLE IF NOT EXISTS memo_viewers(
  memo_id INTEGER NOT NULL REFERENCES memos(id) ON DELETE CASCADE, user_id TEXT NOT NULL, PRIMARY KEY(memo_id, user_id));
CREATE TABLE IF NOT EXISTS folder_viewers(
  folder_id INTEGER NOT NULL REFERENCES folders(id) ON DELETE CASCADE, user_id TEXT NOT NULL, PRIMARY KEY(folder_id, user_id));
"""


def now():
    return datetime.now().isoformat(timespec="seconds")


def touch_member(uid, name):
    """접속한 사람을 members에 등록·갱신한다. 최선 노력: 실패(DB 잠금 등)해도 로그만 남기고 요청을 막지 않는다."""
    try:
        _touch(uid, name or uid)
    except Exception:
        log.warning("members 등록 실패(무시하고 계속): %s", uid, exc_info=True)


def _touch(uid, name):
    t = now()
    with connect() as con:
        # 먼저 읽어 보고, 행이 없거나 이름·날짜가 다를 때만 쓴다(매 요청마다 쓰기 잠금을 잡지 않게)
        row = con.execute("SELECT name, last_seen FROM members WHERE id=?", (uid,)).fetchone()
        if row and row["name"] == name and row["last_seen"][:10] == t[:10]:
            return
        _upsert_member(con, uid, name, t)


def _upsert_member(con, uid, name, t):
    con.execute(
        "INSERT INTO members(id,name,first_seen,last_seen) VALUES(?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
        "name=excluded.name, last_seen=CASE WHEN substr(last_seen,1,10)<>substr(excluded.last_seen,1,10) "
        "THEN excluded.last_seen ELSE last_seen END", (uid, name, t, t))


def db_path():
    # 호출 때마다 읽는다: 테스트가 환경변수로 임시 파일을 지정하기 때문
    return os.environ.get("EVAS_DB", "data/evas.db")


@contextmanager
def connect():
    path = db_path()
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA foreign_keys=ON")  # 분류 삭제 시 ON DELETE SET NULL이 동작하려면 필요
    try:
        yield con
        con.commit()
    finally:
        con.close()


def init():
    with connect() as con:
        con.executescript(SCHEMA)
        # 폴더 도입 전 운영 DB: memos가 이미 있어 CREATE가 건너뛰어지므로 열만 덧붙인다(데이터 그대로)
        if "folder_id" not in {r["name"] for r in con.execute("PRAGMA table_info(memos)")}:
            con.execute("ALTER TABLE memos ADD COLUMN folder_id INTEGER REFERENCES folders(id) ON DELETE SET NULL")
        # 반드시 표 재작성(_allow_admin_kind)보다 먼저: 재작성은 새 정의의 열 이름으로 복사하므로 옛 표에도 열이 있어야 한다
        for t in ("memos", "folders"):
            _add_visibility(con, t)
        for name, create in (("folders", FOLDERS), ("memos", MEMOS)):
            _allow_admin_kind(con, name, create)
        if not con.execute("SELECT 1 FROM categories").fetchone():
            con.executemany("INSERT INTO categories(name,color) VALUES(?,?)", DEFAULT_CATEGORIES)
        # 첫 관리자는 웹에서 만들 수 없으니(닭과 달걀) 환경변수로 시드한다
        for uid in filter(None, os.environ.get("EVAS_ADMIN_IDS", "").split(",")):
            con.execute("INSERT OR IGNORE INTO users(id,name,role) VALUES(?,?, 'admin')", (uid.strip(),) * 2)


def _add_visibility(con, table):
    """공개 범위 열을 ALTER로 덧붙인다(운영 DB 데이터 그대로, 기본 'all'). 멱등: 이미 있으면 아무것도 안 한다."""
    def has():
        return "visibility" in {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}
    if has():
        return
    try:
        con.execute(f"ALTER TABLE {table} ADD COLUMN visibility TEXT NOT NULL DEFAULT 'all' "
                    "CHECK(visibility IN ('all','restricted'))")
    except sqlite3.OperationalError:
        if not has():  # 다른 프로세스가 동시에 먼저 붙인 경우만 넘어간다
            raise


def _allow_admin_kind(con, name, create):
    """kind CHECK에 'admin'이 없는 옛 표를 새 정의로 다시 만든다(SQLite는 CHECK를 고칠 수 없다). 이미 새 표면 아무것도 안 한다.

    한 트랜잭션(BEGIN IMMEDIATE): 외래키 OFF -> 새 표 생성 -> 열 이름으로 복사 -> 옛 표 삭제 -> 이름 바꾸기 -> 인덱스·
    AUTOINCREMENT 시퀀스 복원 -> foreign_key_check -> 커밋 -> 외래키 ON. 중간에 실패하면 롤백되어 옛 표가 그대로 남는다.
    """
    if _has_admin_kind(con, name):
        return
    con.commit()
    con.execute("PRAGMA foreign_keys=OFF")  # 트랜잭션 밖에서만 바뀐다. 옛 표를 지울 때 참조 행이 건드려지지 않게
    try:
        _begin_immediate(con)
        if _has_admin_kind(con, name):  # 잠금을 기다리는 사이 다른 프로세스가 이미 이전했다
            con.commit()
            return
        # 재작성과 무관하게 이미 있던 위반(외래키를 끈 채 넣은 옛 행)은 시작을 막지 않는다: 새로 생긴 것만 실패로 본다
        before = _fk_violations(con)
        if before:
            log.warning("%s 이전 전부터 있던 외래키 위반 %d건(그대로 둔다): %s", name, len(before), sorted(before)[:10])
        indexes = [r[0] for r in con.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL", (name,))]
        old_seq = con.execute("SELECT seq FROM sqlite_sequence WHERE name=?", (name,)).fetchone()
        new = name + "_new"
        con.execute(create.replace(f"EXISTS {name}(", f"EXISTS {new}(", 1))
        # 옛 표는 ALTER로 붙은 열 순서가 다르다. 옛 표에 아직 없는 열(visibility)은 새 표의 기본값으로 채운다
        have = {r["name"] for r in con.execute(f"PRAGMA table_info({name})")}
        cols = ", ".join(r["name"] for r in con.execute(f"PRAGMA table_info({new})") if r["name"] in have)
        con.execute(f"INSERT INTO {new}({cols}) SELECT {cols} FROM {name}")
        con.execute(f"DROP TABLE {name}")
        con.execute(f"ALTER TABLE {new} RENAME TO {name}")
        for sql in indexes:
            con.execute(sql)
        if old_seq:  # 복사로는 '현재 최대 id'까지만 남는다: 지운 행의 id를 다시 쓰지 않게 옛 값을 되살린다
            con.execute("DELETE FROM sqlite_sequence WHERE name=?", (name,))
            con.execute("INSERT INTO sqlite_sequence(name, seq) VALUES(?, MAX(?, COALESCE((SELECT MAX(id) FROM {0}), 0)))"
                        .format(name), (name, old_seq[0]))
        new_violations = _fk_violations(con) - before
        if new_violations:
            raise sqlite3.IntegrityError(f"{name} 이전 뒤 새 외래키 위반: {sorted(new_violations)[:10]}")
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.execute("PRAGMA foreign_keys=ON")


def _has_admin_kind(con, name):
    return "'admin'" in con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()[0]


def _fk_violations(con):
    # (표, rowid, 부모 표): fkid는 표를 다시 만들면 순서가 달라질 수 있어 비교에서 뺀다
    return {(r[0], r[1], r[2]) for r in con.execute("PRAGMA foreign_key_check")}


def _begin_immediate(con, tries=5):
    """쓰기 잠금을 처음부터 잡는다(읽다가 쓰기로 올리며 막히지 않게). 다른 연결이 쥐고 있으면 1초 간격으로 다시 시도."""
    for i in range(tries):
        try:
            con.execute("BEGIN IMMEDIATE")
            return
        except sqlite3.OperationalError:
            if i == tries - 1:
                raise
            log.warning("DB가 잠겨 있어 이전을 1초 뒤 다시 시도합니다(%d/%d)", i + 1, tries)
            time.sleep(1)
