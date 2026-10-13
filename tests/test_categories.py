from app import db

from .conftest import as_


def test_non_admin_cannot_change_categories(client, monkeypatch):
    monkeypatch.setenv("EVAS_OPEN_EDIT", "1")  # 편집자여도 분류는 못 바꾼다
    assert client.get("/api/categories", headers=as_("eve")).status_code == 200
    assert client.post("/api/categories", json=dict(name="x", color="#000000"), headers=as_("eve")).status_code == 403
    assert client.put("/api/categories/1", json=dict(name="x", color="#000000"), headers=as_("eve")).status_code == 403
    assert client.delete("/api/categories/1", headers=as_("eve")).status_code == 403


def test_admin_crud_category(client):
    names = [c["name"] for c in client.get("/api/categories", headers=as_("boss")).json()]
    assert names == ["공지", "아이디어", "할 일", "참고"]
    r = client.post("/api/categories", json=dict(name=" 회의 ", color="#ABCDEF"), headers=as_("boss"))
    assert r.status_code == 201 and r.json()["name"] == "회의" and r.json()["color"] == "#abcdef"
    cid = r.json()["id"]
    assert client.post("/api/categories", json=dict(name="회의", color="#000000"), headers=as_("boss")).status_code == 409
    assert client.put(f"/api/categories/{cid}", json=dict(name="미팅", color="#111111"), headers=as_("boss")).status_code == 200
    assert client.put("/api/categories/999", json=dict(name="z", color="#111111"), headers=as_("boss")).status_code == 404
    assert client.delete(f"/api/categories/{cid}", headers=as_("boss")).status_code == 204
    assert client.delete(f"/api/categories/{cid}", headers=as_("boss")).status_code == 404


def test_color_must_be_hex(client):
    for bad in ("red", "#fff", "#gggggg", "000000"):
        assert client.post("/api/categories", json=dict(name="c", color=bad), headers=as_("boss")).status_code == 422


def test_delete_category_leaves_memos_uncategorized(client):
    cid = client.post("/api/categories", json=dict(name="임시", color="#123456"), headers=as_("boss")).json()["id"]
    with db.connect() as con:  # 메모 API는 Task 3에서 생긴다 -> 직접 insert
        mid = con.execute("INSERT INTO memos(kind,owner_id,title,category_id,created_at,updated_at) "
                          "VALUES('shared',NULL,'m',?,'t','t')", (cid,)).lastrowid
    assert client.delete(f"/api/categories/{cid}", headers=as_("boss")).status_code == 204
    with db.connect() as con:
        row = con.execute("SELECT category_id FROM memos WHERE id=?", (mid,)).fetchone()
    assert row is not None and row["category_id"] is None


def test_users_admin_only_and_last_admin_protected(client):
    assert client.get("/api/users", headers=as_("eve")).status_code == 403
    assert client.put("/api/users/eve", json=dict(name="이브", role="editor"), headers=as_("boss")).status_code == 200
    assert [u["id"] for u in client.get("/api/users", headers=as_("boss")).json()] == ["boss", "eve"]
    assert client.put("/api/users/boss", json=dict(name="b", role="editor"), headers=as_("boss")).status_code == 409
    assert client.delete("/api/users/boss", headers=as_("boss")).status_code == 409
    assert client.delete("/api/users/eve", headers=as_("boss")).status_code == 204
