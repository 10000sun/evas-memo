"""전율(관리자 전용 메모 공간): 비관리자에게 존재가 드러나지 않음, 이동, 연결 종료, 활동·푸시·연동 제외."""
import time

import pytest

from app import db, push, ws
from tests.conftest import as_
from tests.test_activity import edit_ws
from tests.test_memo_ws import Peer, body_in_db, connect, rejected, wait_closed
from tests.test_memos import append_body, ids, new

KEY = "k" * 32
MISSING = 99999


@pytest.fixture
def c(client, monkeypatch):
    # boss·boss2는 관리자, a·b는 편집자, v는 등록 안 된 사람(보기 전용)
    monkeypatch.delenv("EVAS_OPEN_EDIT", raising=False)
    monkeypatch.setenv("LINK_API_KEY", KEY)
    client.put("/api/users/boss2", json=dict(name="boss2", role="admin"), headers=as_("boss"))
    for uid in ("a", "b"):
        client.put(f"/api/users/{uid}", json=dict(name=uid, role="editor"), headers=as_("boss"))
    return client


@pytest.fixture
def pushed(monkeypatch):
    calls = []
    monkeypatch.setattr(push, "notify", lambda *a: calls.append(a))
    return calls


def folder(c, uid, kind, name="F", parent_id=None, status=201):
    r = c.post("/api/folders", json=dict(kind=kind, name=name, parent_id=parent_id), headers=as_(uid))
    assert r.status_code == status, r.text
    return r.json()


def move(c, mid, to, uid):
    return c.post(f"/api/memos/{mid}/move", json={"to": to}, headers=as_(uid))


def same(r1, r2):
    """있는 전율 메모·폴더와 없는 것에 대한 응답이 상태·본문까지 같다."""
    assert (r1.status_code, r1.content) == (r2.status_code, r2.content)
    return r1.status_code


def activity(c, uid="a"):
    return c.get("/api/activity", headers=as_(uid)).json()


def test_non_admin_cannot_see_admin_memo_anywhere(c):
    af = folder(c, "boss", "admin")["id"]
    m = new(c, "boss", "admin", "전율비밀", folder_id=af)["id"]
    append_body(m, "비밀본문")
    for uid in ("a", "v"):
        h = as_(uid)
        own = new(c, "a", "personal")["id"]
        for kind in ("personal", "shared"):
            assert m not in ids(c.get(f"/api/memos?kind={kind}", headers=h))
            assert ids(c.get(f"/api/memos?kind={kind}&q=비밀", headers=h)) == []
            assert ids(c.get(f"/api/memos?kind={kind}&folder_id={af}", headers=h)) == []
        assert c.get("/api/memos?kind=admin", headers=h).status_code == 404
        assert c.get("/api/folders?kind=admin", headers=h).status_code == 404
        assert c.post("/api/memos", json=dict(kind="admin"), headers=h).status_code in (403, 404)
        assert c.post("/api/folders", json=dict(kind="admin", name="x"), headers=h).status_code == 404
        for call in (lambda i: c.get(f"/api/memos/{i}", headers=h),
                     lambda i: c.put(f"/api/memos/{i}", json={"title": "x"}, headers=h),
                     lambda i: c.delete(f"/api/memos/{i}", headers=h),
                     lambda i: c.post(f"/api/memos/{i}/share", headers=h),
                     lambda i: c.post(f"/api/memos/{i}/copy-to-personal", headers=h),
                     *[lambda i, to=to: move(c, i, to, uid) for to in ("personal", "shared", "admin")]):
            assert same(call(m), call(MISSING)) in (403, 404)
        # 전율 폴더: 지정·하위 생성·이름 변경·삭제 모두 없는 폴더와 같다
        for fid_call in (lambda f: c.put(f"/api/memos/{own}", json={"folder_id": f}, headers=as_("a")),
                         lambda f: c.post("/api/folders", json=dict(kind="shared", name="y", parent_id=f), headers=h),
                         lambda f: c.post("/api/folders", json=dict(kind="personal", name="y", parent_id=f), headers=h),
                         lambda f: c.put(f"/api/folders/{f}", json=dict(name="z"), headers=h),
                         lambda f: c.delete(f"/api/folders/{f}", headers=h)):
            assert same(fid_call(af), fid_call(MISSING)) in (403, 404)
        # 연동
        for scope in ("shared", "all"):
            r = c.get(f"/api/link/memos?scope={scope}&q=전율", headers=h)
            assert r.status_code == 200 and r.json() == []
            assert c.get(f"/api/link/memos?scope={scope}&ids={m}", headers=h).json() == []
        assert c.get(f"/api/link/memos?scope=admin&ids={m}", headers=h).status_code == 404
        # WebSocket: 없는 메모와 같은 1008
        with c:
            assert rejected(c, m, uid) == rejected(c, MISSING, uid) == 1008
    assert c.get(f"/internal/link/memos?ids={m}", headers={"X-Link-Key": KEY}).json() == []
    assert c.get("/internal/link/memos?q=전율", headers={"X-Link-Key": KEY}).json() == []
    assert all("전율" not in i["title"] for i in activity(c)["items"])
    # 관리자에게는 그대로 있다
    assert c.get(f"/api/memos/{m}", headers=as_("boss")).json()["body_text"] == "비밀본문"


def test_admin_can_use_admin_space(c):
    m = new(c, "boss", "admin", "회의")["id"]
    assert m in ids(c.get("/api/memos?kind=admin", headers=as_("boss2")))
    assert m in ids(c.get("/api/memos?kind=admin&q=회의", headers=as_("boss2")))
    for kind in ("personal", "shared"):  # 다른 종류 목록에 섞이지 않는다
        assert m not in ids(c.get(f"/api/memos?kind={kind}", headers=as_("boss")))
    assert c.get(f"/api/memos/{m}", headers=as_("boss2")).json()["kind"] == "admin"
    r = c.put(f"/api/memos/{m}", json={"title": "회의2"}, headers=as_("boss2"))
    assert r.status_code == 200 and r.json()["title"] == "회의2"
    edit_ws(c, m, "boss2", "실시간")
    assert body_in_db(m) == "실시간"
    f = folder(c, "boss2", "admin", "전율폴더")
    assert [x["id"] for x in c.get("/api/folders?kind=admin", headers=as_("boss")).json()] == [f["id"]]
    assert c.get("/api/folders?kind=shared", headers=as_("boss")).json() == []
    assert c.delete(f"/api/memos/{m}", headers=as_("boss2")).status_code == 204  # 작성자가 아니어도 관리자면 지운다


def test_move_transitions(c):
    pf, sf = folder(c, "boss", "personal")["id"], folder(c, "a", "shared")["id"]
    p = new(c, "boss", "personal", "개인", folder_id=pf, category_id=1)["id"]
    append_body(p, "본문P")
    r = move(c, p, "admin", "boss")
    assert r.status_code == 200, r.text
    got = r.json()
    assert (got["kind"], got["folder_id"], got["body_text"], got["title"], got["category_id"]) == \
        ("admin", None, "본문P", "개인", 1)
    # personal -> admin은 소유자만(남의 개인 메모는 관리자에게도 없는 메모)
    p2 = new(c, "boss2", "personal")["id"]
    assert move(c, p2, "admin", "boss").status_code == 404
    s = new(c, "a", "shared", "공동", folder_id=sf)["id"]
    append_body(s, "본문S")
    got = move(c, s, "admin", "boss").json()
    assert (got["kind"], got["folder_id"], got["body_text"]) == ("admin", None, "본문S")
    got = move(c, s, "shared", "boss2").json()
    assert (got["kind"], got["body_text"]) == ("shared", "본문S")
    assert s in ids(c.get("/api/memos?kind=shared", headers=as_("b")))
    # admin -> personal: 옮긴 사람이 새 소유자, 다른 관리자에게는 사라진다
    got = move(c, p, "personal", "boss2").json()
    assert (got["kind"], got["owner_id"], got["body_text"]) == ("personal", "boss2", "본문P")
    assert c.get(f"/api/memos/{p}", headers=as_("boss")).status_code == 404
    assert p in ids(c.get("/api/memos?kind=personal", headers=as_("boss2")))
    assert p not in ids(c.get("/api/memos?kind=admin", headers=as_("boss")))
    # 허용되지 않은 전이
    assert move(c, s, "personal", "boss").status_code == 422  # 공동 -> 개인은 복사(/copy-to-personal)
    assert move(c, p, "shared", "boss2").status_code == 422  # 개인 -> 공동은 /share
    assert move(c, p, "personal", "boss2").status_code == 422  # 같은 종류
    assert move(c, s, "x", "boss").status_code == 422
    a = new(c, "boss", "admin")["id"]
    assert move(c, a, "admin", "boss").status_code == 422
    # 전율 메모는 share·copy-to-personal 대상이 아니다
    assert c.post(f"/api/memos/{a}/share", headers=as_("boss")).status_code == 409
    assert c.post(f"/api/memos/{a}/copy-to-personal", headers=as_("boss")).status_code == 409


def test_move_to_admin_requires_admin_role(c):
    p, s = new(c, "a", "personal")["id"], new(c, "a", "shared")["id"]
    for mid, uid in ((p, "a"), (s, "a"), (s, "v")):
        assert move(c, mid, "admin", uid).status_code == 404  # 전율이라는 종류 자체를 드러내지 않는다
    assert c.get(f"/api/memos/{p}", headers=as_("a")).json()["kind"] == "personal"
    assert c.get(f"/api/memos/{s}", headers=as_("a")).json()["kind"] == "shared"


def test_shared_to_admin_closes_non_admin_connections(c, monkeypatch):
    monkeypatch.setattr(ws, "SAVE_DELAY", 30)  # 자동 저장이 끼어들지 않게: 저장은 이동이 한다
    s = new(c, "a", "shared")["id"]
    with c:
        with connect(c, s, "a") as wa, connect(c, s, "boss2") as wb:
            pa, pb = Peer(wa), Peer(wb)
            pa.text += "저장 전"
            pa.push()
            pa.pump()
            pb.pump()
            r = move(c, s, "admin", "boss")
            assert r.status_code == 200 and r.json()["body_text"] == "저장 전"  # 열린 방의 편집을 먼저 저장
            assert wait_closed(pa) == 4404
            pb.text += "!"
            pb.push()
            pb.pump()
            assert pb.closed is None  # 관리자 연결은 유지
        assert rejected(c, s, "a") == 1008
    assert body_in_db(s) == "저장 전!"


def test_admin_to_personal_closes_other_admins(c):
    m = new(c, "boss", "admin")["id"]
    with c:
        with connect(c, m, "boss") as w1, connect(c, m, "boss2") as w2:
            p1, p2 = Peer(w1), Peer(w2)
            assert move(c, m, "personal", "boss2").status_code == 200
            assert wait_closed(p1) == 4404
            time.sleep(0.3)
            assert p2.closed is None
        assert rejected(c, m, "boss") == 1008


def test_join_racing_with_move_is_closed_before_any_data(c, monkeypatch):
    """접속 확인은 통과했는데 방에 들어가기 전에 전율로 옮겨진 경우: 문서를 한 바이트도 받지 못하고 닫힌다."""
    s = new(c, "a", "shared")["id"]
    append_body(s, "비밀")
    orig = ws._Server.get_room

    async def racing(self, name):
        with db.connect() as con:
            con.execute("UPDATE memos SET kind='admin' WHERE id=?", (s,))
        return await orig(self, name)

    monkeypatch.setattr(ws._Server, "get_room", racing)
    with c:
        assert rejected(c, s, "a") == 1008
        with connect(c, s, "boss") as w:
            assert str(Peer(w).text) == "비밀"


def test_demoted_admin_connection_closed_4403(c):
    m, s = new(c, "boss", "admin")["id"], new(c, "boss", "shared")["id"]
    with c:
        with connect(c, m, "boss2") as w1, connect(c, s, "boss2") as w2, connect(c, m, "boss") as w3:
            p1, p2, p3 = Peer(w1), Peer(w2), Peer(w3)
            r = c.put("/api/users/boss2", json=dict(name="boss2", role="editor"), headers=as_("boss"))
            assert r.status_code == 200
            assert wait_closed(p1) == 4403
            time.sleep(0.3)
            assert p2.closed is None and p3.closed is None  # 다른 종류 방·다른 관리자는 그대로
        assert rejected(c, m, "boss2") == 1008
        c.put("/api/users/boss2", json=dict(name="boss2", role="admin"), headers=as_("boss"))
        with connect(c, m, "boss2") as w:
            p = Peer(w)
            assert c.delete("/api/users/boss2", headers=as_("boss")).status_code == 204
            assert wait_closed(p) == 4403


def test_no_activity_or_push_for_admin_kind(c, pushed):
    s0 = new(c, "a", "shared", "공동제목")["id"]
    base = activity(c)
    pushed.clear()
    m = new(c, "boss", "admin", "전율제목")["id"]
    c.put(f"/api/memos/{m}", json={"title": "전율수정"}, headers=as_("boss"))
    edit_ws(c, m, "boss", "본문")
    p = new(c, "boss", "personal", "개인제목")["id"]
    move(c, p, "admin", "boss")
    move(c, p, "personal", "boss2")
    assert c.delete(f"/api/memos/{m}", headers=as_("boss2")).status_code == 204
    after = activity(c)
    assert (after["items"], after["rev"]) == (base["items"], base["rev"]) and pushed == []
    # shared -> admin: '삭제' 한 줄만(푸시 없음), 전율인 동안의 편집은 기록 없음
    move(c, s0, "admin", "boss")
    items = activity(c)["items"]
    assert [(i["kind"], i["title"]) for i in items[:1]] == [("delete", "공동제목")] and len(items) == len(base["items"]) + 1
    c.put(f"/api/memos/{s0}", json={"title": "전율 안에서 바꾼 제목"}, headers=as_("boss"))
    edit_ws(c, s0, "boss", "몰래")
    rev = activity(c)["rev"]
    assert len(activity(c)["items"]) == len(items) and pushed == []
    # admin -> shared: '작성' + 푸시
    move(c, s0, "shared", "boss")
    items = activity(c)["items"]
    assert (items[0]["kind"], items[0]["title"]) == ("add", "전율 안에서 바꾼 제목")
    assert [a[0] for a in pushed] == ["add"] and activity(c)["rev"] != rev


def test_link_scope_admin(c):
    s = new(c, "a", "shared", "공동")["id"]
    pa = new(c, "boss", "personal", "보스개인")["id"]
    pb = new(c, "boss2", "personal", "보스2개인")["id"]
    pc = new(c, "a", "personal", "a개인")["id"]
    m = new(c, "boss2", "admin", "전율")["id"]

    def got(qs, uid="boss"):
        r = c.get("/api/link/memos" + qs, headers=as_(uid))
        assert r.status_code == 200, r.text
        return sorted(x["id"] for x in r.json())

    assert got("?scope=admin") == sorted([s, pa, m])
    assert got(f"?scope=admin&ids={s},{pa},{pb},{pc},{m}") == sorted([s, pa, m])
    assert got("?scope=admin&q=개인") == [pa]
    assert {x["id"]: x["kind"] for x in c.get("/api/link/memos?scope=admin", headers=as_("boss")).json()}[m] == "admin"
    assert got("?scope=all") == sorted([s, pa]) and got("?scope=shared") == [s]  # 다른 scope엔 전율이 없다
    for uid in ("a", "v"):
        assert c.get("/api/link/memos?scope=admin", headers=as_(uid)).status_code == 404


def test_internal_link_never_returns_admin_kind(c):
    m = new(c, "boss", "admin", "전율 회의")["id"]
    s = new(c, "a", "shared", "공동 회의")["id"]
    for qs in ("", "?q=회의", f"?ids={m},{s}", "?limit=20"):
        r = c.get("/internal/link/memos" + qs, headers={"X-Link-Key": KEY})
        assert [x["id"] for x in r.json()] == [s]


def test_admin_folders_kind_match_and_permissions(c):
    af = folder(c, "boss", "admin", "전율폴더")["id"]
    sub = folder(c, "boss2", "admin", "하위", af)["id"]
    folder(c, "boss", "shared", "x", af, status=422)  # 상위 폴더와 종류가 다르다
    folder(c, "boss", "admin", "전율폴더", status=409)  # 같은 위치 같은 이름
    sf = folder(c, "a", "shared", "공동폴더")["id"]
    folder(c, "boss", "admin", "y", sf, status=422)
    assert c.put(f"/api/folders/{af}", json=dict(name="바꿈"), headers=as_("boss2")).status_code == 200
    # 메모의 폴더는 같은 종류여야 한다
    assert c.post("/api/memos", json=dict(kind="admin", folder_id=sf), headers=as_("boss")).status_code == 422
    s = new(c, "a", "shared")["id"]
    assert c.put(f"/api/memos/{s}", json={"folder_id": af}, headers=as_("boss")).status_code == 422
    m = new(c, "boss", "admin", folder_id=sub)["id"]
    assert ids(c.get(f"/api/memos?kind=admin&folder_id={sub}", headers=as_("boss2"))) == [m]
    # 비관리자에게는 없는 폴더
    for uid in ("a", "v"):
        assert c.put(f"/api/folders/{af}", json=dict(name="z"), headers=as_(uid)).status_code == 404
        assert c.delete(f"/api/folders/{sub}", headers=as_(uid)).status_code == 404
    assert c.delete(f"/api/folders/{sub}", headers=as_("boss")).status_code == 204  # 만든 사람이 아니어도 관리자
    assert c.get(f"/api/memos/{m}", headers=as_("boss")).json()["folder_id"] is None
    assert c.delete(f"/api/folders/{af}", headers=as_("boss2")).status_code == 204
