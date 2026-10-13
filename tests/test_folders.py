"""폴더 API: 개인 폴더는 본인만(관리자도 404), 공동 폴더는 편집자가 만들고 만든 사람·관리자가 지운다."""
import pytest

from tests.conftest import as_


@pytest.fixture
def c(client, monkeypatch):
    # a, b는 편집자, boss는 관리자, v는 등록 안 된 사람(보기 전용)
    monkeypatch.delenv("EVAS_OPEN_EDIT", raising=False)
    for uid in ("a", "b"):
        client.put(f"/api/users/{uid}", json=dict(name="이름" + uid, role="editor"), headers=as_("boss"))
    return client


def mk(c, uid, kind, name="폴더", parent_id=None, status=201):
    r = c.post("/api/folders", json=dict(kind=kind, name=name, parent_id=parent_id), headers=as_(uid))
    assert r.status_code == status, r.text
    return r.json()


def memo(c, uid, kind, **kw):
    r = c.post("/api/memos", json=dict(kind=kind, title="m", **kw), headers=as_(uid))
    assert r.status_code == 201, r.text
    return r.json()


def listed(c, uid, kind):
    r = c.get("/api/folders", params=dict(kind=kind), headers=as_(uid))
    assert r.status_code == 200, r.text
    return [f["id"] for f in r.json()]


def test_personal_folder_hidden_from_others(c):
    f = mk(c, "a", "personal")
    m = memo(c, "b", "personal")
    for uid in ("b", "boss"):
        assert f["id"] not in listed(c, uid, "personal")
        assert c.put(f"/api/folders/{f['id']}", json=dict(name="x"), headers=as_(uid)).status_code == 404
        assert c.delete(f"/api/folders/{f['id']}", headers=as_(uid)).status_code == 404
        assert c.post("/api/folders", json=dict(kind="personal", name="하위", parent_id=f["id"]),
                      headers=as_(uid)).status_code == 404
    assert c.put(f"/api/memos/{m['id']}", json=dict(folder_id=f["id"]), headers=as_("b")).status_code == 404
    assert listed(c, "a", "personal") == [f["id"]]
    assert set(f) >= {"id", "kind", "parent_id", "name", "created_by", "created_name"}


def test_shared_folder_create_rename_by_editor_delete_by_creator_or_admin(c):
    f = mk(c, "a", "shared")
    assert c.post("/api/folders", json=dict(kind="shared", name="x"), headers=as_("v")).status_code == 403
    assert listed(c, "v", "shared") == [f["id"]]  # 공동 폴더 목록은 누구나
    r = c.put(f"/api/folders/{f['id']}", json=dict(name="바뀜"), headers=as_("b"))  # 다른 편집자도 이름 변경
    assert r.status_code == 200 and r.json()["name"] == "바뀜"
    assert c.put(f"/api/folders/{f['id']}", json=dict(name="v"), headers=as_("v")).status_code == 403
    assert c.delete(f"/api/folders/{f['id']}", headers=as_("b")).status_code == 403
    assert c.delete(f"/api/folders/{f['id']}", headers=as_("a")).status_code == 204
    g = mk(c, "a", "shared", "또")
    assert c.delete(f"/api/folders/{g['id']}", headers=as_("boss")).status_code == 204
    assert listed(c, "a", "shared") == []


def test_depth_limit_two_levels(c):
    top = mk(c, "a", "shared", "상위")
    sub = mk(c, "a", "shared", "하위", top["id"])
    assert sub["parent_id"] == top["id"]
    mk(c, "a", "shared", "더하위", sub["id"], status=422)
    # 종류가 다른 상위
    p = mk(c, "a", "personal", "개인")
    mk(c, "a", "shared", "x", p["id"], status=422)
    mk(c, "a", "shared", "x", 9999, status=404)


def test_name_validation_and_duplicates(c):
    mk(c, "a", "shared", "", status=422)
    mk(c, "a", "shared", "  ", status=422)
    mk(c, "a", "shared", "가" * 31, status=422)
    mk(c, "a", "shared", "가" * 30)
    top = mk(c, "a", "shared", "A")
    mk(c, "b", "shared", "A", status=409)  # 같은 위치 중복(만든 사람이 달라도)
    sub = mk(c, "a", "shared", "A", top["id"])  # 다른 위치(하위)는 OK
    mk(c, "a", "shared", "A", top["id"], status=409)
    other = mk(c, "a", "shared", "B")
    assert c.put(f"/api/folders/{other['id']}", json=dict(name="A"), headers=as_("a")).status_code == 409
    assert c.put(f"/api/folders/{other['id']}", json=dict(name=""), headers=as_("a")).status_code == 422
    assert c.put(f"/api/folders/{top['id']}", json=dict(name="A"), headers=as_("a")).status_code == 200  # 자기 이름 그대로
    # 개인 폴더는 사용자별로 따로 센다
    mk(c, "a", "personal", "A")
    mk(c, "b", "personal", "A")
    mk(c, "a", "personal", "A", status=409)
    assert sub["parent_id"] == top["id"]


def test_delete_folder_keeps_memos_and_removes_subfolders(c):
    top = mk(c, "a", "shared", "상위")
    sub = mk(c, "a", "shared", "하위", top["id"])
    m1 = memo(c, "a", "shared", folder_id=top["id"])
    m2 = memo(c, "a", "shared", folder_id=sub["id"])
    assert c.delete(f"/api/folders/{top['id']}", headers=as_("a")).status_code == 204
    assert listed(c, "a", "shared") == []
    r = c.get("/api/memos", params=dict(kind="shared", folder_id="none"), headers=as_("a"))
    assert sorted(m["id"] for m in r.json()) == [m1["id"], m2["id"]]
    assert all(m["folder_id"] is None for m in r.json())


def test_memo_folder_kind_must_match(c):
    pf = mk(c, "a", "personal")
    sf = mk(c, "a", "shared")
    pm = memo(c, "a", "personal")
    sm = memo(c, "a", "shared")
    assert c.put(f"/api/memos/{pm['id']}", json=dict(folder_id=sf["id"]), headers=as_("a")).status_code == 422
    assert c.put(f"/api/memos/{sm['id']}", json=dict(folder_id=pf["id"]), headers=as_("a")).status_code == 422
    assert c.put(f"/api/memos/{pm['id']}", json=dict(folder_id=9999), headers=as_("a")).status_code == 404
    assert c.post("/api/memos", json=dict(kind="shared", title="t", folder_id=pf["id"]),
                  headers=as_("a")).status_code == 422
    r = c.put(f"/api/memos/{pm['id']}", json=dict(folder_id=pf["id"]), headers=as_("a"))
    assert r.status_code == 200 and r.json()["folder_id"] == pf["id"]
    r = c.put(f"/api/memos/{pm['id']}", json=dict(folder_id=None), headers=as_("a"))  # 폴더 해제
    assert r.json()["folder_id"] is None
    r = c.put(f"/api/memos/{sm['id']}", json=dict(folder_id=sf["id"]), headers=as_("b"))  # 다른 편집자도 공동 메모 폴더 지정
    assert r.status_code == 200 and r.json()["folder_id"] == sf["id"]
    # 제목만 바꾸면 폴더는 그대로
    r = c.put(f"/api/memos/{sm['id']}", json=dict(title="새"), headers=as_("a"))
    assert r.json()["folder_id"] == sf["id"]


def test_filter_memos_by_folder_and_none(c):
    top = mk(c, "a", "shared", "상위")
    sub = mk(c, "a", "shared", "하위", top["id"])
    in_top = memo(c, "a", "shared", folder_id=top["id"])
    in_sub = memo(c, "a", "shared", folder_id=sub["id"])
    loose = memo(c, "a", "shared")

    def ids(**params):
        r = c.get("/api/memos", params=dict(kind="shared", **params), headers=as_("a"))
        assert r.status_code == 200, r.text
        return [m["id"] for m in r.json()]

    assert sorted(ids()) == sorted([in_top["id"], in_sub["id"], loose["id"]])
    assert ids(folder_id=top["id"]) == [in_top["id"]]  # 하위 폴더 메모는 포함하지 않는다
    assert ids(folder_id=sub["id"]) == [in_sub["id"]]
    assert ids(folder_id="none") == [loose["id"]]
    assert c.get("/api/memos", params=dict(kind="shared", folder_id="abc"), headers=as_("a")).status_code == 422


def test_move_and_copy_reset_folder(c):
    pf = mk(c, "a", "personal")
    pm = memo(c, "a", "personal", folder_id=pf["id"])
    r = c.post(f"/api/memos/{pm['id']}/share", headers=as_("a"))
    assert r.status_code == 200 and r.json()["folder_id"] is None
    sf = mk(c, "a", "shared")
    c.put(f"/api/memos/{pm['id']}", json=dict(folder_id=sf["id"]), headers=as_("a"))
    r = c.post(f"/api/memos/{pm['id']}/copy-to-personal", headers=as_("b"))
    assert r.status_code == 201 and r.json()["folder_id"] is None and r.json()["kind"] == "personal"
