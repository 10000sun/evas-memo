"""종류가 두 개뿐인(전율 이전) 스키마의 운영 DB가 db.init으로 테이블 재작성 이전된다: 데이터·id·외래키·AUTOINCREMENT 보존, 멱등."""
import sqlite3

import pytest

from app import db

# 운영 DB와 같은 상태: kind CHECK가 두 값, memos는 AUTOINCREMENT, folder_id는 나중에 ALTER로 붙어 맨 뒤 열
OLD_SCHEMA = """
CREATE TABLE categories(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, color TEXT NOT NULL);
CREATE TABLE memos(
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL CHECK(kind IN ('personal','shared')),
  owner_id TEXT, title TEXT NOT NULL DEFAULT '',
  category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
  body_text TEXT NOT NULL DEFAULT '', ydoc BLOB,
  created_by TEXT, created_name TEXT, updated_by TEXT, updated_name TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX memos_kind_owner ON memos(kind, owner_id);
CREATE TABLE activity(
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('add','edit','delete')), memo_id INTEGER,
  title TEXT NOT NULL, actor_id TEXT NOT NULL, actor_name TEXT NOT NULL, at TEXT NOT NULL);
CREATE TABLE users(id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','editor')));
CREATE TABLE folders(
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL CHECK(kind IN ('personal','shared')),
  owner_id TEXT, parent_id INTEGER REFERENCES folders(id) ON DELETE CASCADE, name TEXT NOT NULL,
  created_by TEXT, created_name TEXT, created_at TEXT);
ALTER TABLE memos ADD COLUMN folder_id INTEGER REFERENCES folders(id) ON DELETE SET NULL;
"""


def snapshot(con):
    return {t: [dict(r) for r in con.execute(f"SELECT * FROM {t} ORDER BY id")]
            for t in ("categories", "memos", "folders", "activity")}


def seq(con, name):
    return con.execute("SELECT seq FROM sqlite_sequence WHERE name=?", (name,)).fetchone()[0]


@pytest.fixture
def old_db(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(OLD_SCHEMA)
    con.executemany("INSERT INTO categories(id,name,color) VALUES(?,?,?)", [(1, "공지", "#e57373"), (2, "참고", "#81c784")])
    con.execute("INSERT INTO users VALUES('u1','철수','admin')")
    con.execute("INSERT INTO folders(id,kind,owner_id,parent_id,name) VALUES(1,'shared',NULL,NULL,'상위')")
    con.execute("INSERT INTO folders(id,kind,owner_id,parent_id,name) VALUES(2,'shared',NULL,1,'하위')")
    con.execute("INSERT INTO folders(id,kind,owner_id,parent_id,name) VALUES(4,'personal','u1',NULL,'내 폴더')")
    for mid, kind, cat, folder in ((2, "shared", 1, 2), (5, "personal", 2, 4), (7, "shared", None, None)):
        con.execute("INSERT INTO memos(id,kind,owner_id,title,category_id,folder_id,body_text,ydoc,created_at,updated_at) "
                    "VALUES(?,?,'u1',?,?,?,?,?,'2026-01-01','2026-01-02')",
                    (mid, kind, f"메모{mid}", cat, folder, f"본문{mid}", bytes([mid, 0, 1])))
    con.execute("INSERT INTO activity(kind,memo_id,title,actor_id,actor_name,at) VALUES('add',2,'메모2','u1','철수','t')")
    # 지운 메모·폴더가 있었던 상태: 시퀀스가 현재 최대 id보다 크다
    con.execute("UPDATE sqlite_sequence SET seq=50 WHERE name='memos'")
    con.execute("UPDATE sqlite_sequence SET seq=9 WHERE name='folders'")
    con.commit()
    before = snapshot(con)
    con.close()
    monkeypatch.setenv("EVAS_DB", str(path))
    monkeypatch.delenv("EVAS_ADMIN_IDS", raising=False)
    return before


def test_old_schema_is_rebuilt_in_place(old_db):
    db.init()
    with db.connect() as con:
        assert snapshot(con) == old_db  # 모든 행·id·folder_id·category_id·ydoc 보존
        for t in ("memos", "folders"):
            assert "'admin'" in con.execute("SELECT sql FROM sqlite_master WHERE name=?", (t,)).fetchone()[0]
            assert not con.execute("SELECT 1 FROM sqlite_master WHERE name=?", (t + "_new",)).fetchone()
        assert con.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name='memos_kind_owner'").fetchone()
        assert (seq(con, "memos"), seq(con, "folders")) == (50, 9)
        assert con.execute("PRAGMA foreign_key_check").fetchall() == []
        assert con.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        # 전율 종류를 넣을 수 있고, 엉뚱한 종류는 여전히 막힌다
        fid = con.execute("INSERT INTO folders(kind,name) VALUES('admin','전율')").lastrowid
        mid = con.execute("INSERT INTO memos(kind,title,folder_id,created_at,updated_at) "
                          "VALUES('admin','전율',?,'t','t')", (fid,)).lastrowid
        assert (fid, mid) == (10, 51)  # 옛 id를 다시 쓰지 않는다(AUTOINCREMENT 유지)
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("INSERT INTO memos(kind,created_at,updated_at) VALUES('x','t','t')")
        with pytest.raises(sqlite3.IntegrityError):  # 외래키도 살아 있다
            con.execute("INSERT INTO memos(kind,folder_id,created_at,updated_at) VALUES('shared',999,'t','t')")
        con.execute("DELETE FROM memos WHERE id=?", (mid,))
        assert con.execute("INSERT INTO memos(kind,created_at,updated_at) VALUES('admin','t','t')").lastrowid == 52
        # 폴더 삭제: 하위 폴더는 함께, 메모는 folder_id만 비워진다
        con.execute("DELETE FROM folders WHERE id=1")
        assert [r[0] for r in con.execute("SELECT id FROM folders ORDER BY id")] == [4, 10]
        assert con.execute("SELECT folder_id FROM memos WHERE id=2").fetchone()[0] is None
        con.execute("DELETE FROM categories WHERE id=2")
        assert con.execute("SELECT category_id FROM memos WHERE id=5").fetchone()[0] is None
        after = snapshot(con)

    db.init()  # 두 번째 호출은 아무것도 바꾸지 않는다
    with db.connect() as con:
        assert snapshot(con) == after
        assert seq(con, "memos") == 52
        assert con.execute("PRAGMA foreign_key_check").fetchall() == []


def test_new_db_has_admin_kind_without_rebuild(tmp_path, monkeypatch):
    monkeypatch.setenv("EVAS_DB", str(tmp_path / "new.db"))
    db.init()
    db.init()
    with db.connect() as con:
        con.execute("INSERT INTO memos(kind,created_at,updated_at) VALUES('admin','t','t')")
        con.execute("INSERT INTO folders(kind,name) VALUES('admin','f')")
