import os
import sqlite3
from contextlib import contextmanager

DEFAULT_CATEGORIES = [
    ("공지", "#e57373"), ("아이디어", "#ffb74d"), ("할 일", "#64b5f6"), ("참고", "#81c784"),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS categories(
  id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, color TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS memos(
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('personal','shared')),
  owner_id TEXT, title TEXT NOT NULL DEFAULT '',
  category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
  body_text TEXT NOT NULL DEFAULT '', ydoc BLOB,
  created_by TEXT, created_name TEXT, updated_by TEXT, updated_name TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
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
        if not con.execute("SELECT 1 FROM categories").fetchone():
            con.executemany("INSERT INTO categories(name,color) VALUES(?,?)", DEFAULT_CATEGORIES)
        # 첫 관리자는 웹에서 만들 수 없으니(닭과 달걀) 환경변수로 시드한다
        for uid in filter(None, os.environ.get("EVAS_ADMIN_IDS", "").split(",")):
            con.execute("INSERT OR IGNORE INTO users(id,name,role) VALUES(?,?, 'admin')", (uid.strip(),) * 2)
