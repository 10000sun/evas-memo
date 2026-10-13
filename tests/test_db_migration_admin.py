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


# main 브랜치(운영 배포본) 스키마: folders 표도 memos.folder_id도 없다
MAIN_SCHEMA = """
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
CREATE TABLE activity_read(user_id TEXT PRIMARY KEY, last_id INTEGER NOT NULL);
CREATE TABLE push_subs(endpoint TEXT PRIMARY KEY, user_id TEXT NOT NULL, p256dh TEXT NOT NULL, auth TEXT NOT NULL);
CREATE TABLE users(id TEXT PRIMARY KEY, name TEXT NOT NULL, role TEXT NOT NULL CHECK(role IN ('admin','editor')));
"""


def test_main_schema_db_is_migrated(tmp_path, monkeypatch):
    path = tmp_path / "main.db"
    con = sqlite3.connect(path)
    con.row_factory = sqlite3.Row
    con.executescript(MAIN_SCHEMA)
    con.execute("INSERT INTO categories(id,name,color) VALUES(1,'공지','#e57373')")
    for mid, kind, cat in ((3, "shared", 1), (8, "personal", None)):
        con.execute("INSERT INTO memos(id,kind,owner_id,title,category_id,body_text,ydoc,created_at,updated_at) "
                    "VALUES(?,?,'u1',?,?,?,?,'t','t')", (mid, kind, f"메모{mid}", cat, f"본문{mid}", b"\x01\x02"))
    con.execute("INSERT INTO activity(kind,memo_id,title,actor_id,actor_name,at) VALUES('add',3,'메모3','u1','철수','t')")
    con.execute("UPDATE sqlite_sequence SET seq=20 WHERE name='memos'")
    con.commit()
    before = {r["id"]: dict(r) for r in con.execute("SELECT * FROM memos")}
    con.close()
    monkeypatch.setenv("EVAS_DB", str(path))
    monkeypatch.delenv("EVAS_ADMIN_IDS", raising=False)

    db.init()
    db.init()
    with db.connect() as con:
        after = {r["id"]: dict(r) for r in con.execute("SELECT * FROM memos")}
        assert after == {k: {**v, "folder_id": None} for k, v in before.items()}
        assert [dict(r) for r in con.execute("SELECT kind, memo_id, title FROM activity")] == \
            [{"kind": "add", "memo_id": 3, "title": "메모3"}]
        assert seq(con, "memos") == 20
        assert con.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name='memos_kind_owner'").fetchone()
        assert con.execute("PRAGMA foreign_key_check").fetchall() == []
        fid = con.execute("INSERT INTO folders(kind,name) VALUES('admin','전율')").lastrowid
        assert con.execute("INSERT INTO memos(kind,folder_id,created_at,updated_at) VALUES('admin',?,'t','t')",
                           (fid,)).lastrowid == 21


class Inject:
    """_allow_admin_kind에 넘기는 연결 대리: prefix로 시작하는 SQL 직후에 hook을 끼워 넣는다."""

    def __init__(self, con, prefix, hook):
        self.con, self.prefix, self.hook = con, prefix, hook

    def __getattr__(self, name):
        return getattr(self.con, name)

    def execute(self, sql, *a):
        cur = self.con.execute(sql, *a)
        if sql.startswith(self.prefix):
            self.hook(self.con)
        return cur


def table_sql(con, name):
    row = con.execute("SELECT sql FROM sqlite_master WHERE name=?", (name,)).fetchone()
    return row and row[0]


def _boom(_con):
    raise RuntimeError("재작성 중 오류")


@pytest.mark.parametrize("prefix", ["INSERT INTO memos_new", "DROP TABLE memos", "ALTER TABLE memos_new"])
def test_error_mid_rebuild_leaves_original_table(old_db, prefix):
    with db.connect() as con:
        old = table_sql(con, "memos")
        with pytest.raises(RuntimeError):
            db._allow_admin_kind(Inject(con, prefix, _boom), "memos", db.MEMOS)
        assert table_sql(con, "memos") == old and table_sql(con, "memos_new") is None
        assert snapshot(con) == old_db and seq(con, "memos") == 50
        assert con.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    db.init()  # 다음 시작에서는 정상 이전
    with db.connect() as con:
        assert "'admin'" in table_sql(con, "memos") and snapshot(con) == old_db


def test_new_fk_violation_rolls_back(old_db):
    def orphan(con):  # 재작성이 메모가 가리키는 폴더를 잃어버린 상황을 흉내 낸다
        con.execute("DELETE FROM folders WHERE id=2")

    with db.connect() as con:
        old = table_sql(con, "folders")
        with pytest.raises(sqlite3.IntegrityError):
            db._allow_admin_kind(Inject(con, "ALTER TABLE folders_new", orphan), "folders", db.FOLDERS)
        assert table_sql(con, "folders") == old and table_sql(con, "folders_new") is None
        assert snapshot(con) == old_db


def test_preexisting_fk_violation_does_not_block_start(old_db, caplog):
    with db.connect() as con:  # 외래키가 꺼진 채 들어간 옛 고아 행(이 앱의 연결은 늘 켜지만, 수동 수정 등)
        con.execute("PRAGMA foreign_keys=OFF")
        con.execute("UPDATE memos SET folder_id=999, category_id=77 WHERE id=7")
    db.init()
    with db.connect() as con:
        assert "'admin'" in table_sql(con, "memos") and "'admin'" in table_sql(con, "folders")
        m = con.execute("SELECT folder_id, category_id FROM memos WHERE id=7").fetchone()
        assert (m["folder_id"], m["category_id"]) == (999, 77)  # 기존 데이터는 그대로 둔다
    assert "외래키" in caplog.text


def test_begin_immediate_retries_when_locked(old_db, monkeypatch):
    monkeypatch.setattr(db.time, "sleep", lambda s: None)
    tries = []

    class Locked(Inject):
        fail_until = 99

        def execute(self, sql, *a):
            if sql == "BEGIN IMMEDIATE":
                tries.append(1)
                if len(tries) < self.fail_until:
                    raise sqlite3.OperationalError("database is locked")
            return self.con.execute(sql, *a)

    with db.connect() as con:
        p = Locked(con, "", None)
        with pytest.raises(sqlite3.OperationalError):
            db._allow_admin_kind(p, "memos", db.MEMOS)
        assert len(tries) == 5 and "'admin'" not in table_sql(con, "memos")
        tries.clear()
        p.fail_until = 3
        db._allow_admin_kind(p, "memos", db.MEMOS)
        assert len(tries) == 3 and "'admin'" in table_sql(con, "memos")
        assert snapshot(con) == old_db
