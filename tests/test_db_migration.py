"""폴더 도입 전 스키마의 운영 DB가 db.init으로 데이터 손실 없이 이전된다."""
import sqlite3

from app import db

# 폴더 도입 전 스키마(memos에 folder_id 없음, folders 표 없음)
OLD_SCHEMA = """
CREATE TABLE categories(id INTEGER PRIMARY KEY, name TEXT NOT NULL UNIQUE, color TEXT NOT NULL);
CREATE TABLE memos(
  id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL CHECK(kind IN ('personal','shared')),
  owner_id TEXT, title TEXT NOT NULL DEFAULT '',
  category_id INTEGER REFERENCES categories(id) ON DELETE SET NULL,
  body_text TEXT NOT NULL DEFAULT '', ydoc BLOB,
  created_by TEXT, created_name TEXT, updated_by TEXT, updated_name TEXT,
  created_at TEXT NOT NULL, updated_at TEXT NOT NULL);
CREATE TABLE users(id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','editor')));
"""


def test_old_schema_db_is_upgraded_in_place(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.executescript(OLD_SCHEMA)
    con.execute("INSERT INTO users VALUES('u1','철수','editor')")
    con.execute("INSERT INTO memos(kind,owner_id,title,body_text,created_at,updated_at) "
                "VALUES('shared',NULL,'옛 메모','옛 본문','2026-01-01','2026-01-01')")
    con.commit()
    con.close()
    monkeypatch.setenv("EVAS_DB", str(path))
    monkeypatch.delenv("EVAS_ADMIN_IDS", raising=False)  # 다른 테스트가 심은 시드 관리자가 섞이지 않게

    db.init()
    db.init()  # 두 번째 호출도 오류 없이 멱등

    with db.connect() as con:
        assert [r["name"] for r in con.execute("SELECT name FROM users")] == ["철수"]
        m = con.execute("SELECT title, body_text, folder_id FROM memos").fetchone()
        assert (m["title"], m["body_text"], m["folder_id"]) == ("옛 메모", "옛 본문", None)
        assert "folder_id" in {r["name"] for r in con.execute("PRAGMA table_info(memos)")}
        assert con.execute("SELECT 1 FROM sqlite_master WHERE name='folders'").fetchone()
        # 이전된 열에서도 폴더 삭제 시 메모는 남고 folder_id만 비워진다
        con.execute("INSERT INTO folders(kind,name) VALUES('shared','f')")
        con.execute("UPDATE memos SET folder_id=1")
        con.execute("DELETE FROM folders")
        assert con.execute("SELECT folder_id FROM memos").fetchone()["folder_id"] is None
