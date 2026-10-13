"""메모 API: 개인 메모는 본인만, 공동 메모는 누구나 보고 편집자 이상이 고친다. 이동·복사·검색."""
import pytest
from pycrdt import Doc, Text

from app import db
from tests.conftest import as_


@pytest.fixture
def c(client, monkeypatch):
    # a, b는 편집자, boss는 관리자, v는 등록 안 된 사람(보기 전용)
    monkeypatch.delenv("EVAS_OPEN_EDIT", raising=False)
    for uid in ("a", "b"):
        client.put(f"/api/users/{uid}", json=dict(name="이름" + uid, role="editor"), headers=as_("boss"))
    return client


def new(c, uid, kind, title="제목", **kw):
    r = c.post("/api/memos", json=dict(kind=kind, title=title, **kw), headers=as_(uid))
    assert r.status_code == 201, r.text
    return r.json()


def ids(r):
    assert r.status_code == 200, r.text
    return [m["id"] for m in r.json()]


def append_body(mid, text):
    """실시간 편집이 저장한 것처럼 DB의 ydoc/body_text에 글을 덧붙인다."""
    doc = Doc()
    with db.connect() as con:
        row = con.execute("SELECT ydoc FROM memos WHERE id=?", (mid,)).fetchone()
        if row["ydoc"]:
            doc.apply_update(row["ydoc"])
        t = doc.get("text", type=Text)
        t += text
        con.execute("UPDATE memos SET ydoc=?, body_text=? WHERE id=?", (doc.get_update(), str(t), mid))


def ydoc_text(mid):
    doc = Doc()
    with db.connect() as con:
        doc.apply_update(con.execute("SELECT ydoc FROM memos WHERE id=?", (mid,)).fetchone()["ydoc"])
    return str(doc.get("text", type=Text))


def test_personal_memo_invisible_to_others(c):
    m = new(c, "a", "personal")
    u = f"/api/memos/{m['id']}"
    for uid in ("b", "boss", "v"):  # 관리자도 못 본다
        h = as_(uid)
        assert m["id"] not in ids(c.get("/api/memos?kind=personal", headers=h))
        assert m["id"] not in ids(c.get("/api/memos?kind=shared", headers=h))
        assert c.get(u, headers=h).status_code in (403, 404)
        assert c.put(u, json=dict(title="x"), headers=h).status_code in (403, 404)
        assert c.delete(u, headers=h).status_code in (403, 404)
    assert ids(c.get("/api/memos?kind=personal", headers=as_("a"))) == [m["id"]]
    assert c.get(u, headers=as_("a")).json()["title"] == "제목"
    assert c.get("/api/memos?kind=personal").status_code == 401


def test_shared_visible_and_editable_by_anyone(c):
    m = new(c, "a", "shared", title="공지")
    assert set(m) == {"id", "kind", "owner_id", "title", "category_id", "folder_id", "body_text",
                      "created_name", "updated_name", "updated_at",
                      "visibility", "inherited", "can_share"}
    assert m["kind"] == "shared" and m["visibility"] == "all" and m["created_name"] == "a" and m["body_text"] == ""
    u = f"/api/memos/{m['id']}"
    for uid in ("b", "boss", "v"):
        assert m["id"] in ids(c.get("/api/memos?kind=shared", headers=as_(uid)))
        assert c.get(u, headers=as_(uid)).json()["title"] == "공지"
    r = c.put(u, json=dict(title="공지2", category_id=1), headers=as_("b"))
    assert r.status_code == 200 and r.json()["title"] == "공지2" and r.json()["updated_name"] == "b"
    assert c.put(u, json=dict(category_id=None), headers=as_("boss")).json()["category_id"] is None
    assert c.get(u, headers=as_("a")).json()["title"] == "공지2"  # 안 보낸 필드는 그대로
    # 보기 전용(v)은 읽기만
    assert c.put(u, json=dict(title="x"), headers=as_("v")).status_code == 403
    assert c.post("/api/memos", json=dict(kind="shared", title="x"), headers=as_("v")).status_code == 403
    assert c.put(u, json=dict(category_id=9999), headers=as_("b")).status_code == 400  # 없는 분류


def test_delete_shared_only_author_or_admin(c):
    m1, m2 = new(c, "a", "shared"), new(c, "a", "shared")
    for uid in ("b", "v"):
        assert c.delete(f"/api/memos/{m1['id']}", headers=as_(uid)).status_code == 403
    assert c.delete(f"/api/memos/{m1['id']}", headers=as_("a")).status_code == 204
    assert c.delete(f"/api/memos/{m2['id']}", headers=as_("boss")).status_code == 204
    assert c.get(f"/api/memos/{m1['id']}", headers=as_("a")).status_code == 404
    assert c.delete(f"/api/memos/{m2['id']}", headers=as_("boss")).status_code == 404


def test_share_moves_personal_to_shared(c):
    m = new(c, "a", "personal", title="초안", category_id=2)
    append_body(m["id"], "본문")
    with db.connect() as con:
        before = con.execute("SELECT ydoc FROM memos WHERE id=?", (m["id"],)).fetchone()["ydoc"]
    r = c.post(f"/api/memos/{m['id']}/share", headers=as_("a"))
    assert r.status_code == 200, r.text
    s = r.json()
    assert (s["id"], s["kind"], s["owner_id"], s["title"], s["category_id"], s["body_text"]) == \
           (m["id"], "shared", "a", "초안", 2, "본문")
    assert m["id"] not in ids(c.get("/api/memos?kind=personal", headers=as_("a")))
    assert m["id"] in ids(c.get("/api/memos?kind=shared", headers=as_("b")))
    assert c.get(f"/api/memos/{m['id']}", headers=as_("b")).json()["body_text"] == "본문"
    with db.connect() as con:  # Yjs 문서를 새로 만들지 않는다
        assert con.execute("SELECT ydoc FROM memos WHERE id=?", (m["id"],)).fetchone()["ydoc"] == before
    assert c.post(f"/api/memos/{m['id']}/share", headers=as_("a")).status_code == 409  # 이미 공동


def test_copy_to_personal_leaves_original(c):
    o = new(c, "a", "shared", title="회의", category_id=3)
    append_body(o["id"], "원본")
    # 보기 전용은 새 메모를 못 만드므로 복사도 못 한다
    assert c.post(f"/api/memos/{o['id']}/copy-to-personal", headers=as_("v")).status_code == 403
    r = c.post(f"/api/memos/{o['id']}/copy-to-personal", headers=as_("b"))
    assert r.status_code == 201, r.text
    cp = r.json()
    assert cp["id"] != o["id"]
    assert (cp["kind"], cp["owner_id"], cp["title"], cp["category_id"], cp["body_text"], cp["created_name"]) == \
           ("personal", "b", "회의", 3, "원본", "b")
    # 원본은 그대로
    orig = c.get(f"/api/memos/{o['id']}", headers=as_("a")).json()
    assert (orig["kind"], orig["owner_id"], orig["body_text"]) == ("shared", "a", "원본")
    # 복사본은 복사한 사람만
    for uid in ("a", "boss"):
        assert c.get(f"/api/memos/{cp['id']}", headers=as_(uid)).status_code in (403, 404)
    assert cp["id"] in ids(c.get("/api/memos?kind=personal", headers=as_("b")))
    # 이후 원본을 고쳐도 복사본에 번지지 않는다
    append_body(o["id"], " 추가")
    c.put(f"/api/memos/{o['id']}", json=dict(title="회의2"), headers=as_("a"))
    got = c.get(f"/api/memos/{cp['id']}", headers=as_("b")).json()
    assert (got["title"], got["body_text"]) == ("회의", "원본")
    assert ydoc_text(cp["id"]) == "원본" and ydoc_text(o["id"]) == "원본 추가"
    # 개인 메모는 복사 대상이 아니다
    assert c.post(f"/api/memos/{cp['id']}/copy-to-personal", headers=as_("b")).status_code == 409


def test_cannot_share_others_personal(c):
    m = new(c, "a", "personal")
    for uid in ("b", "boss"):
        assert c.post(f"/api/memos/{m['id']}/share", headers=as_(uid)).status_code in (403, 404)
    assert c.get(f"/api/memos/{m['id']}", headers=as_("a")).json()["kind"] == "personal"


def test_search_matches_title_and_body(c):
    m1 = new(c, "a", "shared", title="회의록")
    m2 = new(c, "a", "shared", title="점심", category_id=1)
    append_body(m2["id"], "김밥 100%")
    m3 = new(c, "a", "personal", title="회의 준비")

    def q(params, uid="a"):
        return sorted(ids(c.get("/api/memos", params=params, headers=as_(uid))))

    assert q(dict(kind="shared", q="회의")) == [m1["id"]]
    assert q(dict(kind="shared", q="김밥")) == [m2["id"]]
    assert q(dict(kind="shared", q="없는말")) == []
    assert q(dict(kind="shared", q="_")) == []  # 와일드카드 문자도 글자 그대로
    assert q(dict(kind="shared", q="0%")) == [m2["id"]]
    assert q(dict(kind="personal", q="회의")) == [m3["id"]]
    assert q(dict(kind="personal", q="회의"), uid="b") == []
    assert q(dict(kind="shared", category_id=1)) == [m2["id"]]
    assert q(dict(kind="shared")) == sorted([m1["id"], m2["id"]])


def test_title_max_100(c):
    assert new(c, "a", "shared", title="가" * 100)["title"] == "가" * 100
    r = c.post("/api/memos", json=dict(kind="shared", title="가" * 101), headers=as_("a"))
    assert r.status_code == 422 and "제목은 100자까지입니다" in r.text
    m = new(c, "a", "personal")
    r = c.put(f"/api/memos/{m['id']}", json=dict(title="가" * 101), headers=as_("a"))
    assert r.status_code == 422 and "제목은 100자까지입니다" in r.text
