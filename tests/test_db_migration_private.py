"""비공개 공유 이전: 공개 범위 열·선택한 사람 표가 없는 운영 모양 DB가 데이터 손실 없이 멱등하게 이전된다."""
import sqlite3

import pytest

from app import db

# 멤버 병합 직후 운영 DB 모양: 전율 종류·folder_id·members까지 있고 visibility 열과 *_viewers 표만 없다
PROD_SCHEMA = """
CREATE TABLE categories(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, color TEXT NOT NULL);
CREATE TABLE folders(
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL CHECK(kind IN ('personal','shared','admin')),
  owner_id TEXT, parent_id INTEGER REFERENCES folders(id) ON DELETE CASCADE, name TEXT NOT NULL,
  created_by TEXT, created_name TEXT, created_at TEXT);
CREATE TABLE memos(
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL CHECK(kind IN ('personal','shared','admin')),
  owner_id TEXT, title TEXT NOT NULL DEFAULT '',
  category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
  folder_id INTEGER REFERENCES folders(id) ON DELETE SET NULL,
  body_text TEXT NOT NULL DEFAULT '', ydoc BLOB,
  created_by TEXT, created_name TEXT, updated_by TEXT, updated_name TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE INDEX memos_kind_owner ON memos(kind, owner_id);
CREATE TABLE activity(
  id INTEGER PRIMARY KEY, kind TEXT NOT NULL CHECK(kind IN ('add','edit','delete')), memo_id INTEGER,
  title TEXT NOT NULL, actor_id TEXT NOT NULL, actor_name TEXT NOT NULL, at TEXT NOT NULL);
CREATE TABLE users(id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','editor')));
CREATE TABLE members(id TEXT PRIMARY KEY, name TEXT NOT NULL, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL);
"""


def cols(con, table):
    return {r["name"] for r in con.execute(f"PRAGMA table_info({table})")}


@pytest.fixture
def prod_db(tmp_path, monkeypatch):
    path = tmp_path / "prod.db"
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(PROD_SCHEMA)
    con.execute("INSERT INTO members VALUES('u1','철수','t','t')")
    con.execute("INSERT INTO folders(id,kind,parent_id,name,created_by) VALUES(1,'shared',NULL,'상위','u1')")
    con.execute("INSERT INTO folders(id,kind,parent_id,name,created_by) VALUES(2,'shared',1,'하위','u1')")
    for mid, kind, folder in ((3, "shared", 2), (4, "personal", None), (5, "admin", None)):
        con.execute("INSERT INTO memos(id,kind,owner_id,title,folder_id,body_text,ydoc,created_by,created_at,updated_at) "
                    "VALUES(?,?,'u1',?,?,?,?,'u1','t','t')", (mid, kind, f"메모{mid}", folder, f"본문{mid}", bytes([mid])))
    con.execute("UPDATE sqlite_sequence SET seq=40 WHERE name='memos'")
    con.commit()
    before = {t: [dict(r) for r in con.execute(f"SELECT * FROM {t} ORDER BY id")] for t in ("memos", "folders")}
    con.close()
    monkeypatch.setenv("EVAS_DB", str(path))
    monkeypatch.delenv("EVAS_ADMIN_IDS", raising=False)
    return before


def test_production_shaped_db_gets_columns_and_tables_idempotently(prod_db):
    db.init()
    db.init()  # 두 번째도 오류 없이
    with db.connect() as con:
        for t in ("memos", "folders"):
            assert "visibility" in cols(con, t)
            now = [{k: v for k, v in dict(r).items() if k != "visibility"} for r in con.execute(f"SELECT * FROM {t} ORDER BY id")]
            assert now == prod_db[t]  # 기존 행은 그대로
            assert {r[0] for r in con.execute(f"SELECT visibility FROM {t}")} == {"all"}  # 전부 '전체'로 시작
        assert cols(con, "memo_viewers") == {"memo_id", "user_id"} and cols(con, "folder_viewers") == {"folder_id", "user_id"}
        assert con.execute("SELECT seq FROM sqlite_sequence WHERE name='memos'").fetchone()[0] == 40
        assert con.execute("PRAGMA foreign_key_check").fetchall() == []
        assert con.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name='memos_kind_owner'").fetchone()
        # 값 제한
        with pytest.raises(sqlite3.IntegrityError):
            con.execute("UPDATE memos SET visibility='x' WHERE id=3")


def test_viewer_rows_cascade_with_memo_and_folder(prod_db):
    db.init()
    with db.connect() as con:  # 외래키가 켜진 연결(db.connect)에서 지우면 목록도 함께 지워진다
        con.execute("INSERT INTO memo_viewers VALUES(3,'u1')")
        con.execute("INSERT INTO folder_viewers VALUES(1,'u1')")
        con.execute("INSERT INTO folder_viewers VALUES(2,'u1')")
        con.execute("DELETE FROM memos WHERE id=3")
        assert con.execute("SELECT COUNT(*) FROM memo_viewers").fetchone()[0] == 0
        con.execute("DELETE FROM folders WHERE id=1")  # 상위를 지우면 하위(2)까지 지워진다
        assert con.execute("SELECT COUNT(*) FROM folder_viewers").fetchone()[0] == 0


def test_pre_admin_schema_gets_visibility_before_rebuild(tmp_path, monkeypatch):
    """전율 이전의 옛 표(kind CHECK 두 값)도 열이 먼저 붙은 뒤 재작성되어 데이터가 그대로이고 열이 하나만 있다."""
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.executescript(PROD_SCHEMA.replace("'personal','shared','admin'", "'personal','shared'"))
    con.execute("INSERT INTO memos(id,kind,owner_id,title,created_at,updated_at) VALUES(1,'shared','u1','옛','t','t')")
    con.commit()
    con.close()
    monkeypatch.setenv("EVAS_DB", str(path))
    monkeypatch.delenv("EVAS_ADMIN_IDS", raising=False)
    db.init()
    db.init()
    with db.connect() as con:
        assert [list(r) for r in con.execute("SELECT id, title, visibility FROM memos")] == [[1, "옛", "all"]]
        assert "'admin'" in con.execute("SELECT sql FROM sqlite_master WHERE name='memos'").fetchone()[0]
        assert [r["name"] for r in con.execute("PRAGMA table_info(memos)")].count("visibility") == 1
        assert con.execute("PRAGMA foreign_key_check").fetchall() == []
