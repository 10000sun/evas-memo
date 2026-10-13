import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime

DEFAULT_CATEGORIES = [
    ("공지", "#e57373"), ("아이디어", "#ffb74d"), ("할 일", "#64b5f6"), ("참고", "#81c784"),
]

# 종류: personal(개인)·shared(공동)·admin(전율, 관리자 전용). 아래 두 표는 옛 CHECK를 고치려고 init에서 다시 만들 수 있다
# 폴더: 상위 폴더가 지워지면 하위도 함께 지워지고, 메모는 folder_id만 NULL로 남는다
FOLDERS = """CREATE TABLE IF NOT EXISTS folders(
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL CHECK(kind IN ('personal','shared','admin')),
  owner_id TEXT, parent_id INTEGER REFERENCES folders(id) ON DELETE CASCADE, name TEXT NOT NULL,
  created_by TEXT, created_name TEXT, created_at TEXT)"""
# AUTOINCREMENT: 지운 메모의 id를 다시 쓰지 않는다(아직 열려 있는 옛 메모의 실시간 방에 새 메모가 섞이지 않게)
MEMOS = """CREATE TABLE IF NOT EXISTS memos(
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL CHECK(kind IN ('personal','shared','admin')),
  owner_id TEXT, title TEXT NOT NULL DEFAULT '',
  category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
  folder_id INTEGER REFERENCES folders(id) ON DELETE SET NULL,
  body_text TEXT NOT NULL DEFAULT '', ydoc BLOB,
  created_by TEXT, created_name TEXT, updated_by TEXT, updated_name TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL)"""

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
"""


def now():
    return datetime.now().isoformat(timespec="seconds")


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
        for name, create in (("folders", FOLDERS), ("memos", MEMOS)):
            _allow_admin_kind(con, name, create)
        if not con.execute("SELECT 1 FROM categories").fetchone():
            con.executemany("INSERT INTO categories(name,color) VALUES(?,?)", DEFAULT_CATEGORIES)
        # 첫 관리자는 웹에서 만들 수 없으니(닭과 달걀) 환경변수로 시드한다
        for uid in filter(None, os.environ.get("EVAS_ADMIN_IDS", "").split(",")):
            con.execute("INSERT OR IGNORE INTO users(id,name,role) VALUES(?,?, 'admin')", (uid.strip(),) * 2)


def _allow_admin_kind(con, name, create):
    """kind CHECK에 'admin'이 없는 옛 표를 새 정의로 다시 만든다(SQLite는 CHECK를 고칠 수 없다). 이미 새 표면 아무것도 안 한다.

    한 트랜잭션: 외래키 OFF -> 새 표 생성 -> 열 이름으로 복사 -> 옛 표 삭제 -> 이름 바꾸기 -> 인덱스·AUTOINCREMENT 시퀀스 복원
    -> foreign_key_check -> 커밋 -> 외래키 ON. 중간에 실패하면 롤백되어 옛 표가 그대로 남는다.
    """
    if "'admin'" in con.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (name,)).fetchone()[0]:
        return
    con.commit()
    con.execute("PRAGMA foreign_keys=OFF")  # 트랜잭션 밖에서만 바뀐다. 옛 표를 지울 때 참조 행이 건드려지지 않게
    try:
        con.execute("BEGIN")
        indexes = [r[0] for r in con.execute(
            "SELECT sql FROM sqlite_master WHERE type='index' AND tbl_name=? AND sql IS NOT NULL", (name,))]
        old_seq = con.execute("SELECT seq FROM sqlite_sequence WHERE name=?", (name,)).fetchone()
        new = name + "_new"
        con.execute(create.replace(f"EXISTS {name}(", f"EXISTS {new}(", 1))
        cols = ", ".join(r["name"] for r in con.execute(f"PRAGMA table_info({new})"))  # 옛 표는 ALTER로 붙은 열 순서가 다르다
        con.execute(f"INSERT INTO {new}({cols}) SELECT {cols} FROM {name}")
        con.execute(f"DROP TABLE {name}")
        con.execute(f"ALTER TABLE {new} RENAME TO {name}")
        for sql in indexes:
            con.execute(sql)
        if old_seq:  # 복사로는 '현재 최대 id'까지만 남는다: 지운 행의 id를 다시 쓰지 않게 옛 값을 되살린다
            con.execute("DELETE FROM sqlite_sequence WHERE name=?", (name,))
            con.execute("INSERT INTO sqlite_sequence(name, seq) VALUES(?, MAX(?, COALESCE((SELECT MAX(id) FROM {0}), 0)))"
                        .format(name), (name, old_seq[0]))
        if con.execute("PRAGMA foreign_key_check").fetchall():
            raise sqlite3.IntegrityError(f"{name} 이전 뒤 외래키 검사 실패")
        con.commit()
    except Exception:
        con.rollback()
        raise
    finally:
        con.execute("PRAGMA foreign_keys=ON")
