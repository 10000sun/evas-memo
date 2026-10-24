"""백업 내려받기·복구: 왕복, 잘못된 파일 거절, 관리자 전용, 복구 직전 사본."""
import os
import sqlite3

from app import db
from tests.conftest import as_

ADMIN = as_("boss")


def _cats(client):
    return {c["name"] for c in client.get("/api/categories", headers=ADMIN).json()}


def test_roundtrip_and_safety_copy(client):
    client.post("/api/categories", json={"name": "복구시험", "color": "#112233"}, headers=ADMIN)
    r = client.get("/api/backup", headers=ADMIN)
    assert r.status_code == 200 and r.content.startswith(b"SQLite format 3")
    snap = r.content
    cid = next(c["id"] for c in client.get("/api/categories", headers=ADMIN).json() if c["name"] == "복구시험")
    client.delete(f"/api/categories/{cid}", headers=ADMIN)
    assert "복구시험" not in _cats(client)
    assert client.post("/api/restore", content=snap, headers=ADMIN).json() == {"ok": True}
    assert "복구시험" in _cats(client)
    assert os.path.exists(db.db_path() + ".before-restore")  # 복구 직전 데이터가 남는다


def test_restore_rejects_bad_files_and_keeps_data(client):
    before = _cats(client)
    assert client.post("/api/restore", content=b"not a database", headers=ADMIN).status_code == 422
    other = os.path.join(os.path.dirname(db.db_path()), "other.db")
    sqlite3.connect(other).execute("CREATE TABLE x(a)").connection.commit()
    assert client.post("/api/restore", content=open(other, "rb").read(), headers=ADMIN).status_code == 422
    assert _cats(client) == before


def test_restore_keeps_restoring_admin_and_is_admin_only(client, tmp_path):
    snap = client.get("/api/backup", headers=ADMIN).content
    client.put("/api/users/ed", json={"name": "ed", "role": "editor"}, headers=ADMIN)
    assert client.get("/api/backup", headers=as_("ed")).status_code == 403
    assert client.post("/api/restore", content=snap, headers=as_("ed")).status_code == 403
    f = tmp_path / "no-admin.db"  # 복구하는 관리자가 없는 백업
    f.write_bytes(snap)
    con = sqlite3.connect(f)
    con.execute("DELETE FROM users WHERE id='boss'")
    con.commit()
    con.close()
    assert client.post("/api/restore", content=f.read_bytes(), headers=ADMIN).status_code == 200
    assert client.get("/api/users", headers=ADMIN).status_code == 200  # 잠기지 않는다
