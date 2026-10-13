"""비공개 공유: 공동 메모·폴더의 공개 범위(전체/선택한 사람). 목록에 없는 사람에게는 없는 것과 똑같아야 한다."""
import sqlite3
import time

import pytest

from app import db, folders, memos, push, ws
from tests.conftest import as_
from tests.test_activity import edit_ws
from tests.test_memo_ws import Peer, body_in_db, connect, rejected, wait_body, wait_closed
from tests.test_memos import append_body, ids, new

KEY = "k" * 32
MISSING = 99999


@pytest.fixture
def c(client, monkeypatch):
    # boss·boss2는 관리자, a·b·c는 편집자, v·v2는 보기 전용. 접속해 본 사람만 선택할 수 있다(members)
    monkeypatch.delenv("EVAS_OPEN_EDIT", raising=False)
    monkeypatch.setenv("LINK_API_KEY", KEY)
    client.put("/api/users/boss2", json=dict(name="boss2", role="admin"), headers=as_("boss"))
    for uid in ("a", "b", "c"):
        client.put(f"/api/users/{uid}", json=dict(name=uid, role="editor"), headers=as_("boss"))
    for uid in ("boss", "boss2", "a", "b", "c", "v", "v2"):
        client.get("/api/me", headers=as_(uid))
    return client


@pytest.fixture
def pushed(monkeypatch):
    calls = []
    monkeypatch.setattr(push, "notify", lambda *a: calls.append(a))
    return calls


def share(c, mid, uid, visibility, viewers=(), status=200):
    r = c.put(f"/api/memos/{mid}/share-with", json=dict(visibility=visibility, viewers=list(viewers)), headers=as_(uid))
    assert r.status_code == status, r.text
    return r.json()


def fshare(c, fid, uid, visibility, viewers=(), status=200):
    r = c.put(f"/api/folders/{fid}/share-with", json=dict(visibility=visibility, viewers=list(viewers)), headers=as_(uid))
    assert r.status_code == status, r.text
    return r.json()


def folder(c, uid, name="F", parent_id=None, status=201):
    r = c.post("/api/folders", json=dict(kind="shared", name=name, parent_id=parent_id), headers=as_(uid))
    assert r.status_code == status, r.text
    return r.json()


def same(r1, r2):
    """있는 비공개 메모·폴더와 없는 것에 대한 응답이 상태·본문까지 같다."""
    assert (r1.status_code, r1.content) == (r2.status_code, r2.content)
    return r1.status_code


def feed(c, uid="a"):
    return c.get("/api/activity", headers=as_(uid)).json()


def shared_ids(c, uid, qs=""):
    return ids(c.get("/api/memos?kind=shared" + qs, headers=as_(uid)))


def test_outsider_sees_nothing_same_as_missing(c, pushed):
    rf = folder(c, "a", "비공개폴더")["id"]
    fshare(c, rf, "a", "restricted", ["b"])
    public = new(c, "a", "shared", "공개글")["id"]
    m = new(c, "a", "shared", "비밀제목")["id"]
    append_body(m, "비밀본문")
    share(c, m, "a", "restricted", ["b", "v"])
    for uid in ("c", "v2"):  # 목록에 없는 편집자·보기 전용
        h = as_(uid)
        own = new(c, "c", "shared")["id"] if uid == "c" else None
        assert public in shared_ids(c, uid) and m not in shared_ids(c, uid)
        assert shared_ids(c, uid, "&q=비밀") == [] and shared_ids(c, uid, "&q=본문") == []
        assert c.get(f"/api/memos/{public}", headers=h).status_code == 200
        for call in (lambda i: c.get(f"/api/memos/{i}", headers=h),
                     lambda i: c.put(f"/api/memos/{i}", json={"title": "x"}, headers=h),
                     lambda i: c.put(f"/api/memos/{i}", json={"folder_id": None}, headers=h),
                     lambda i: c.delete(f"/api/memos/{i}", headers=h),
                     lambda i: c.post(f"/api/memos/{i}/share", headers=h),
                     lambda i: c.post(f"/api/memos/{i}/copy-to-personal", headers=h),
                     lambda i: c.put(f"/api/memos/{i}/share-with", json=dict(visibility="all"), headers=h),
                     lambda i: c.put(f"/api/memos/{i}/share-with", json=dict(visibility="restricted", viewers=["nobody"]), headers=h),
                     *[lambda i, to=to: c.post(f"/api/memos/{i}/move", json={"to": to}, headers=h)
                       for to in ("personal", "shared", "admin")]):
            assert same(call(m), call(MISSING)) in (403, 404)
        if own:  # 비공개 폴더로 옮기기·하위 만들기·이름 바꾸기·지우기·공개 범위 바꾸기: 없는 폴더와 같다
            for fcall in (lambda f: c.put(f"/api/memos/{own}", json={"folder_id": f}, headers=h),
                          lambda f: c.post("/api/memos", json=dict(kind="shared", folder_id=f), headers=h),
                          lambda f: c.post("/api/folders", json=dict(kind="shared", name="y", parent_id=f), headers=h),
                          lambda f: c.put(f"/api/folders/{f}", json=dict(name="z"), headers=h),
                          lambda f: c.delete(f"/api/folders/{f}", headers=h),
                          lambda f: c.put(f"/api/folders/{f}/share-with", json=dict(visibility="all"), headers=h),
                          lambda f: c.get(f"/api/memos?kind=shared&folder_id={f}", headers=h)):
                got = same(fcall(rf), fcall(MISSING))
                assert got in (200, 404)  # 목록 조회는 두 경우 모두 빈 목록
        assert rf not in [f["id"] for f in c.get("/api/folders?kind=shared", headers=h).json()]
        # 연동·힌트
        for qs in ("?q=비밀", f"?ids={m}", "?q=비밀&scope=all", f"?ids={m}&scope=all"):
            assert c.get("/api/link/memos" + qs, headers=h).json() == []
        # 실시간 연결: 없는 메모와 같은 1008
        with c:
            assert rejected(c, m, uid) == rejected(c, MISSING, uid) == 1008
    assert c.get(f"/internal/link/memos?ids={m}", headers={"X-Link-Key": KEY}).json() == []
    assert c.get("/internal/link/memos?q=비밀", headers={"X-Link-Key": KEY}).json() == []
    # 공개였던 때의 줄('작성', 제한으로 바꿀 때의 '삭제')만 남고 그 뒤의 변경은 기록이 없다
    assert [i["kind"] for i in feed(c, "c")["items"] if i["title"] == "비밀제목"] == ["delete", "add"]


def test_listed_creator_and_admin_have_full_access(c):
    m = new(c, "a", "shared", "비밀제목")["id"]
    append_body(m, "비밀본문")
    out = share(c, m, "a", "restricted", ["b", "v"])
    assert (out["visibility"], out["inherited"], out["can_share"]) == ("restricted", False, True)
    assert out["viewers"] == [{"id": "b", "name": "b"}, {"id": "v", "name": "v"}]
    for uid in ("a", "b", "v", "boss", "boss2"):
        r = c.get(f"/api/memos/{m}", headers=as_(uid))
        assert r.status_code == 200 and r.json()["body_text"] == "비밀본문" and r.json()["viewers"] == out["viewers"]
        assert m in shared_ids(c, uid) and shared_ids(c, uid, "&q=비밀본문") == [m]
        assert [x["visibility"] for x in c.get("/api/memos?kind=shared", headers=as_(uid)).json() if x["id"] == m] == ["restricted"]
        assert [x["id"] for x in c.get(f"/api/link/memos?q=비밀&scope=shared", headers=as_(uid)).json()] == [m]
    # 선택된 편집자는 고치고(PUT·실시간) 보기 전용은 읽기만(역할 그대로)
    assert c.put(f"/api/memos/{m}", json={"title": "b가 고침"}, headers=as_("b")).status_code == 200
    assert c.put(f"/api/memos/{m}", json={"title": "v가 고침"}, headers=as_("v")).status_code == 403
    edit_ws(c, m, "b", "!")
    assert body_in_db(m) == "비밀본문!"
    with c:
        with connect(c, m, "v") as w:
            p = Peer(w)
            assert str(p.text) == "비밀본문!"  # 읽기는 된다
            p.text += "v의 편집"
            p.push()
            time.sleep(0.5)
    assert body_in_db(m) == "비밀본문!"
    # 지우기는 작성자·관리자만: 선택된 편집자는 403(존재는 이미 보인다)
    assert c.delete(f"/api/memos/{m}", headers=as_("b")).status_code == 403
    assert c.delete(f"/api/memos/{m}", headers=as_("boss2")).status_code == 204
    # 선택된 사람은 목록을 보되 공개 범위는 바꾸지 못한다 / 목록에 없는 사람에게는 viewers가 없다
    m2 = new(c, "a", "shared")["id"]
    share(c, m2, "a", "restricted", ["b"])
    share(c, m2, "b", "all", status=403)
    share(c, m2, "b", "restricted", ["b", "c"], status=403)
    assert share(c, m2, "boss", "restricted", ["c"])["viewers"] == [{"id": "c", "name": "c"}]  # 관리자는 고칠 수 있다
    assert "viewers" not in c.get(f"/api/memos/{new(c, 'a', 'shared')['id']}", headers=as_("c")).json()  # 전체 공개에는 없다


def test_share_with_validation(c):
    m = new(c, "a", "shared")["id"]
    personal = new(c, "a", "personal")["id"]
    share(c, m, "a", "restricted", ["ghost"], status=422)  # members에 없는 id
    share(c, m, "a", "restricted", ["b", "ghost"], status=422)
    for bad in ("", " ", "x" * 65):
        share(c, m, "a", "restricted", [bad], status=422)
    r = c.put(f"/api/memos/{m}/share-with", json={"visibility": "weird", "viewers": []}, headers=as_("a"))
    assert r.status_code == 422
    assert c.put(f"/api/memos/{m}/share-with", json={"viewers": []}, headers=as_("a")).status_code == 422
    # 중복은 한 번으로, 비어 있어도 된다(만든 사람과 관리자만 봄), 만든 사람·관리자는 목록에 없어도 된다
    assert share(c, m, "a", "restricted", ["b", "b", "c"])["viewers"] == [{"id": "b", "name": "b"}, {"id": "c", "name": "c"}]
    assert share(c, m, "a", "restricted", [])["viewers"] == []
    assert shared_ids(c, "b") == [] and shared_ids(c, "a") == [m] and shared_ids(c, "boss") == [m]
    # 50명까지(중복 제거 뒤). 사람을 51명 만들어 본다
    for i in range(51):
        c.get("/api/me", headers=as_(f"u{i}"))
    assert len(share(c, m, "a", "restricted", [f"u{i}" for i in range(50)] * 2)["viewers"]) == 50
    share(c, m, "a", "restricted", [f"u{i}" for i in range(51)], status=422)
    # 전체 공개로 두면 목록은 버려진다(남았다가 되살아나지 않게)
    share(c, m, "a", "all", ["b"])
    with db.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM memo_viewers WHERE memo_id=?", (m,)).fetchone()[0] == 0
    # 공동 메모만
    assert c.put(f"/api/memos/{personal}/share-with", json=dict(visibility="restricted"), headers=as_("a")).status_code == 409
    # 보기 전용은 못 바꾼다
    assert c.put(f"/api/memos/{m}/share-with", json=dict(visibility="all"), headers=as_("v")).status_code == 403
    assert c.put(f"/api/memos/{m}/share-with", json=dict(visibility="all")).status_code == 401


def test_removing_a_person_closes_their_connection_4404(c):
    m = new(c, "a", "shared")["id"]
    share(c, m, "a", "restricted", ["b", "c"])
    with c:
        with connect(c, m, "b") as wb, connect(c, m, "c") as wc, connect(c, m, "a") as wa, connect(c, m, "boss") as wo:
            pb, pc, pa, po = Peer(wb), Peer(wc), Peer(wa), Peer(wo)
            share(c, m, "a", "restricted", ["c"])
            assert wait_closed(pb) == 4404
            assert pb.closed.reason == ws.GONE_REASON == "메모가 삭제되었습니다"  # 삭제와 같은 사유
            time.sleep(0.3)
            assert pc.closed is None and pa.closed is None and po.closed is None  # 남은 사람·만든 사람·관리자는 그대로
            pc.text += "계속 편집"
            pc.push()
            pc.pump()
        assert rejected(c, m, "b") == 1008
    assert wait_body(m, "계속 편집", 3) == "계속 편집"


def test_restricting_a_public_memo_closes_outsiders_but_going_back_to_all_closes_nobody(c):
    m = new(c, "a", "shared")["id"]
    with c:
        with connect(c, m, "b") as wb, connect(c, m, "c") as wc:
            pb, pc = Peer(wb), Peer(wc)
            share(c, m, "a", "restricted", ["b"])
            assert wait_closed(pc) == 4404
            time.sleep(0.3)
            assert pb.closed is None
            share(c, m, "a", "all")
            time.sleep(0.3)
            assert pb.closed is None
        with connect(c, m, "c") as w:  # 전체로 돌리면 다시 붙을 수 있다
            assert Peer(w).closed is None


def test_folder_restriction_applies_to_everything_inside(c):
    top = folder(c, "a", "상위")["id"]
    sub = folder(c, "a", "하위", top)["id"]
    m_top = new(c, "a", "shared", "상위메모", folder_id=top)["id"]
    m_sub = new(c, "a", "shared", "하위메모", folder_id=sub)["id"]
    m_free = new(c, "a", "shared", "밖")["id"]
    with c:
        with connect(c, m_sub, "b") as wb, connect(c, m_sub, "c") as wc, connect(c, m_free, "c") as wf:
            pb, pc, pf = Peer(wb), Peer(wc), Peer(wf)
            out = fshare(c, top, "a", "restricted", ["b"])
            assert (out["visibility"], out["viewers"]) == ("restricted", [{"id": "b", "name": "b"}])
            assert wait_closed(pc) == 4404 and pc.closed.reason == ws.GONE_REASON  # 안의 메모 연결이 즉시 닫힌다
            time.sleep(0.3)
            assert pb.closed is None and pf.closed is None  # 선택된 사람·폴더 밖 메모는 그대로
        for mid in (m_top, m_sub):
            assert rejected(c, mid, "c") == rejected(c, MISSING, "c") == 1008
    # c에게는 폴더도 하위 폴더도 메모도 없다
    assert [f["id"] for f in c.get("/api/folders?kind=shared", headers=as_("c")).json()] == []
    assert shared_ids(c, "c") == [m_free] and shared_ids(c, "c", f"&folder_id={sub}") == []
    for mid in (m_top, m_sub):
        assert same(c.get(f"/api/memos/{mid}", headers=as_("c")), c.get(f"/api/memos/{MISSING}", headers=as_("c"))) == 404
    # b·만든 사람·관리자에게는 보이고, 하위 폴더·메모는 이어받은 것으로 표시된다
    fl = {f["id"]: f for f in c.get("/api/folders?kind=shared", headers=as_("b")).json()}
    assert set(fl) == {top, sub} and (fl[top]["inherited"], fl[sub]["inherited"]) == (False, True)
    assert fl[sub]["visibility"] == "restricted" and fl[sub]["viewers"] == [{"id": "b", "name": "b"}]
    for uid in ("b", "a", "boss"):
        assert {m_top, m_sub} <= set(shared_ids(c, uid))
    got = c.get(f"/api/memos/{m_sub}", headers=as_("b")).json()
    assert (got["visibility"], got["inherited"], got["viewers"]) == ("restricted", True, [{"id": "b", "name": "b"}])
    # 하위 폴더·그 안의 메모는 자신의 공개 범위를 따로 못 정한다
    fshare(c, sub, "a", "restricted", ["c"], status=409)
    share(c, m_top, "a", "restricted", ["c"], status=409)
    share(c, m_sub, "boss", "all", status=409)
    # 목록 변경이 즉시 반영된다: c를 넣고 b를 뺀다
    fshare(c, top, "a", "restricted", ["b", "c"])
    assert {m_top, m_sub} <= set(shared_ids(c, "c"))
    with c:
        with connect(c, m_top, "b") as wb2, connect(c, m_sub, "c") as wc2:
            pb2, pc2 = Peer(wb2), Peer(wc2)
            fshare(c, top, "a", "restricted", ["c"])
            assert wait_closed(pb2) == 4404
            time.sleep(0.3)
            assert pc2.closed is None
    assert m_top not in shared_ids(c, "b") and m_sub not in shared_ids(c, "b")
    # 전체로 되돌리면(선택한 사람 -> 전체, 서버는 묻지 않는다) 모두에게 다시 보인다
    fshare(c, top, "a", "all")
    assert {m_top, m_sub} <= set(shared_ids(c, "b"))


def test_moving_memo_in_and_out_of_restricted_folder(c):
    rf = folder(c, "a", "비공개")["id"]
    fshare(c, rf, "a", "restricted", ["c"])
    pub = folder(c, "a", "공개")["id"]
    m = new(c, "a", "shared", "옮길메모")["id"]
    share(c, m, "a", "restricted", ["b"])  # 메모 자신의 설정은 b
    with c:
        with connect(c, m, "b") as wb, connect(c, m, "a") as wa:
            pb, pa = Peer(wb), Peer(wa)
            assert c.put(f"/api/memos/{m}", json={"folder_id": rf}, headers=as_("a")).status_code == 200
            assert wait_closed(pb) == 4404  # 폴더 목록(c)이 우선: 메모 자신의 설정(b)은 무시된다
            time.sleep(0.3)
            assert pa.closed is None  # 만든 사람(폴더도 만든 사람)은 그대로
        assert rejected(c, m, "b") == 1008
    assert m in shared_ids(c, "c") and m not in shared_ids(c, "b")
    # 제한 폴더에 못 들어가는 사람은 옮기지도 못한다(없는 폴더와 같은 404)
    mine = new(c, "b", "shared")["id"]
    assert c.put(f"/api/memos/{mine}", json={"folder_id": rf}, headers=as_("b")).status_code == 404
    # 공개 폴더로 옮기면 메모 자신의 설정(b)으로 돌아간다
    with c:
        with connect(c, m, "c") as wc:
            pc = Peer(wc)
            assert c.put(f"/api/memos/{m}", json={"folder_id": pub}, headers=as_("c")).status_code == 200
            assert wait_closed(pc) == 4404
    assert m in shared_ids(c, "b") and m not in shared_ids(c, "c")
    # 제한 폴더로 새 메모를 만들면 폴더 목록을 따른다(작성자가 목록에 없으면 만들 수 없다)
    assert c.post("/api/memos", json=dict(kind="shared", folder_id=rf), headers=as_("b")).status_code == 404
    n = new(c, "c", "shared", "c의 글", folder_id=rf)["id"]
    assert n in shared_ids(c, "c") and n not in shared_ids(c, "b")
    # 목록에서 빠진 작성자는 자기가 쓴 글도 못 본다(폴더 목록을 따른다)
    fshare(c, rf, "a", "restricted", ["b"])
    assert n not in shared_ids(c, "c") and n in shared_ids(c, "a")


def test_subfolder_can_be_restricted_under_public_parent(c):
    top = folder(c, "a", "상위")["id"]
    sub = folder(c, "a", "하위", top)["id"]
    m = new(c, "a", "shared", folder_id=sub)["id"]
    fshare(c, sub, "a", "restricted", ["b"])
    assert m in shared_ids(c, "b") and m not in shared_ids(c, "c")
    assert sub in [f["id"] for f in c.get("/api/folders?kind=shared", headers=as_("b")).json()]
    assert sub not in [f["id"] for f in c.get("/api/folders?kind=shared", headers=as_("c")).json()]
    assert top in [f["id"] for f in c.get("/api/folders?kind=shared", headers=as_("c")).json()]
    # 상위를 제한으로 바꾸면 하위는 상위 목록을 따른다
    fshare(c, top, "a", "restricted", ["c"])
    assert m in shared_ids(c, "c") and m not in shared_ids(c, "b")
    # 새 하위 폴더도 이어받는다
    sub2 = folder(c, "a", "둘째", top)["id"]
    m2 = new(c, "a", "shared", folder_id=sub2)["id"]
    assert m2 in shared_ids(c, "c") and m2 not in shared_ids(c, "b")


def test_folder_share_with_permissions(c):
    f = folder(c, "a", "폴더")["id"]
    fshare(c, f, "b", "restricted", ["b"], status=403)  # 만든 사람이 아님
    fshare(c, f, "v", "restricted", status=403)
    fshare(c, f, "a", "restricted", ["ghost"], status=422)
    fshare(c, f, "a", "restricted", [str(i) for i in range(51)], status=422)
    assert c.put(f"/api/folders/{MISSING}/share-with", json=dict(visibility="all"), headers=as_("a")).status_code == 404
    out = fshare(c, f, "boss2", "restricted", ["b"])  # 관리자는 만든 사람이 아니어도 바꾼다
    assert out["viewers"] == [{"id": "b", "name": "b"}] and out["can_share"] is True
    fshare(c, f, "b", "all", status=403)  # 선택된 사람은 보되 못 바꾼다
    assert c.get("/api/folders?kind=shared", headers=as_("b")).json()[0]["can_share"] is False
    pf = c.post("/api/folders", json=dict(kind="personal", name="개인"), headers=as_("a")).json()["id"]
    fshare(c, pf, "a", "restricted", status=409)
    # 폴더 이름 바꾸기·지우기도 목록에 없는 사람에게는 없는 폴더
    assert c.put(f"/api/folders/{f}", json=dict(name="z"), headers=as_("c")).status_code == 404
    assert c.delete(f"/api/folders/{f}", headers=as_("c")).status_code == 404
    assert c.put(f"/api/folders/{f}", json=dict(name="z"), headers=as_("b")).status_code == 200


def test_activity_push_rev_and_internal_link(c, pushed):
    m = new(c, "a", "shared", "제목1")["id"]
    base = feed(c, "c")
    assert [(i["kind"], i["title"]) for i in base["items"][:1]] == [("add", "제목1")] and [p[0] for p in pushed] == ["add"]
    pushed.clear()
    # 전체 -> 제한: '삭제' 한 줄만, 푸시 없음
    share(c, m, "a", "restricted", ["b"])
    items = feed(c, "c")["items"]
    assert [(i["kind"], i["title"]) for i in items[:1]] == [("delete", "제목1")] and len(items) == len(base["items"]) + 1
    assert pushed == []
    # 이후 변경(PUT·실시간·제한 폴더 안 새 메모·지우기)은 기록·푸시가 없고, 목록에 없는 사람의 rev도 안 바뀐다
    time.sleep(1.1)  # updated_at이 초 단위라 표식이 확실히 달라지게
    revs = {u: feed(c, u)["rev"] for u in ("c", "b", "boss")}
    c.put(f"/api/memos/{m}", json={"title": "제목2"}, headers=as_("a"))
    edit_ws(c, m, "b", "본문")
    rf = folder(c, "a", "폴더")["id"]
    fshare(c, rf, "a", "restricted", ["b"])
    inside = new(c, "b", "shared", "폴더 안 비밀", folder_id=rf)["id"]
    edit_ws(c, inside, "b", "x")
    c.put(f"/api/memos/{m}", json={"title": "제목3"}, headers=as_("a"))
    c.delete(f"/api/memos/{inside}", headers=as_("b"))
    after = feed(c, "c")
    assert [i["title"] for i in after["items"]] == [i["title"] for i in items]  # 새 줄 없음
    assert pushed == [] and after["rev"] == revs["c"]
    for uid in ("b", "boss"):  # 볼 수 있는 사람에게는 변경 표식이 바뀐다
        assert feed(c, uid)["rev"] != revs[uid]
    # 내부 연동·브라우저 연동에서 빠진다
    for qs in (f"?ids={m}", "?q=제목", "?limit=20"):
        assert m not in [x["id"] for x in c.get("/internal/link/memos" + qs, headers={"X-Link-Key": KEY}).json()]
    assert [x["id"] for x in c.get(f"/api/link/memos?ids={m}", headers=as_("b")).json()] == [m]
    assert [x["id"] for x in c.get(f"/api/link/memos?ids={m}", headers=as_("boss")).json()] == [m]
    assert c.get(f"/api/link/memos?ids={m}", headers=as_("c")).json() == []
    # limit이 안 보이는 메모에 먹히지 않는다
    for i in range(3):
        new(c, "a", "shared", f"공개{i}")
    got = c.get("/api/link/memos?limit=2&scope=shared", headers=as_("c")).json()
    assert len(got) == 2 and m not in [x["id"] for x in got]
    # 제한 -> 전체: '작성' 한 줄 + 푸시, 내부 연동에 나간다
    pushed.clear()
    share(c, m, "a", "all")
    top = feed(c, "c")["items"][0]
    assert (top["kind"], top["title"]) == ("add", "제목3") and [p[0] for p in pushed] == ["add"]
    assert m in [x["id"] for x in c.get(f"/internal/link/memos?ids={m}", headers={"X-Link-Key": KEY}).json()]
    # 제한 메모를 지워도 기록·푸시는 없다
    share(c, m, "a", "restricted", ["b"])
    pushed.clear()
    n_items = len(feed(c, "c")["items"])
    assert c.delete(f"/api/memos/{m}", headers=as_("a")).status_code == 204
    assert len(feed(c, "c")["items"]) == n_items and pushed == []


def test_folder_change_logs_only_publicity_changes(c, pushed):
    f = folder(c, "a", "폴더")["id"]
    m1 = new(c, "a", "shared", "메모하나", folder_id=f)["id"]
    m2 = new(c, "a", "shared", "메모둘", folder_id=f)["id"]
    share(c, m2, "a", "restricted", ["b"])  # 이미 비공개
    pushed.clear()
    n = len(feed(c, "c")["items"])
    fshare(c, f, "a", "restricted", ["b"])
    items = feed(c, "c")["items"]
    assert sorted((i["kind"], i["title"]) for i in items[:1]) == [("delete", "메모하나")] and len(items) == n + 1
    assert pushed == []
    fshare(c, f, "a", "all")  # m1은 다시 공개, m2는 자기 설정(제한)으로 남는다
    items = feed(c, "c")["items"]
    assert [(i["kind"], i["title"]) for i in items[:1]] == [("add", "메모하나")] and len(items) == n + 2
    assert m1 in shared_ids(c, "c") and m2 not in shared_ids(c, "c")


def test_move_to_admin_or_personal_drops_viewers_and_visibility(c, pushed):
    m = new(c, "a", "shared", "옮길글")["id"]
    share(c, m, "a", "restricted", ["b"])
    n_items = len(feed(c, "c")["items"])
    with c:
        with connect(c, m, "b") as wb, connect(c, m, "boss") as wo:
            pb, po = Peer(wb), Peer(wo)
            r = c.post(f"/api/memos/{m}/move", json={"to": "admin"}, headers=as_("boss"))
            assert r.status_code == 200 and (r.json()["kind"], r.json()["visibility"]) == ("admin", "all")
            assert wait_closed(pb) == 4404
            time.sleep(0.3)
            assert po.closed is None
    with db.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM memo_viewers WHERE memo_id=?", (m,)).fetchone()[0] == 0
        assert con.execute("SELECT visibility FROM memos WHERE id=?", (m,)).fetchone()[0] == "all"
    assert len(feed(c, "c")["items"]) == n_items  # 비공개였으니 옮기며 남는 기록 없음(제한으로 바꿀 때의 '삭제' 한 줄뿐)
    # 다시 공동으로 돌려놓으면 '전체'로 시작하고 작성 기록·푸시가 나간다
    pushed.clear()
    assert c.post(f"/api/memos/{m}/move", json={"to": "shared"}, headers=as_("boss")).json()["visibility"] == "all"
    assert m in shared_ids(c, "c") and (feed(c, "c")["items"][0]["kind"], [p[0] for p in pushed]) == ("add", ["add"])
    # 전율 -> 개인
    share(c, m, "a", "restricted", ["b"])
    c.post(f"/api/memos/{m}/move", json={"to": "admin"}, headers=as_("boss"))
    got = c.post(f"/api/memos/{m}/move", json={"to": "personal"}, headers=as_("boss")).json()
    assert (got["kind"], got["visibility"]) == ("personal", "all")
    with db.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM memo_viewers").fetchone()[0] == 0


def test_copy_to_personal_only_if_caller_can_access(c):
    m = new(c, "a", "shared", "복사글")["id"]
    append_body(m, "본문")
    share(c, m, "a", "restricted", ["b"])
    assert c.post(f"/api/memos/{m}/copy-to-personal", headers=as_("c")).status_code == 404
    r = c.post(f"/api/memos/{m}/copy-to-personal", headers=as_("b"))
    assert r.status_code == 201 and r.json()["kind"] == "personal" and r.json()["body_text"] == "본문"
    assert r.json()["visibility"] == "all" and "viewers" not in r.json()  # 복사본은 개인 메모
    assert c.post(f"/api/memos/{m}/copy-to-personal", headers=as_("boss")).status_code == 201


def test_deleting_restricted_folder_does_not_expose_its_memos(c):
    top = folder(c, "a", "상위")["id"]
    sub = folder(c, "a", "하위", top)["id"]
    m = new(c, "a", "shared", "숨은글", folder_id=sub)["id"]
    own = new(c, "a", "shared", "자기설정", folder_id=sub)["id"]
    fshare(c, top, "a", "restricted", ["b"])
    assert c.delete(f"/api/folders/{top}", headers=as_("c")).status_code == 404
    assert c.delete(f"/api/folders/{top}", headers=as_("b")).status_code == 403  # 선택된 사람은 지우지 못한다
    assert c.delete(f"/api/folders/{top}", headers=as_("a")).status_code == 204
    # 폴더가 사라져도 메모는 폴더 목록 그대로 비공개로 남는다(전체 공개로 쏟아지지 않는다)
    for mid in (m, own):
        assert mid in shared_ids(c, "b") and mid in shared_ids(c, "a") and mid in shared_ids(c, "boss")
        assert mid not in shared_ids(c, "c")
        assert c.get(f"/api/memos/{mid}", headers=as_("c")).status_code == 404
    assert c.get(f"/api/memos/{m}", headers=as_("b")).json()["folder_id"] is None
    assert [x["id"] for x in c.get(f"/api/link/memos?ids={m}", headers=as_("c")).json()] == []
    # 이제 메모 자신의 설정이므로 만든 사람이 바꿀 수 있다
    share(c, m, "a", "all")
    assert m in shared_ids(c, "c")


def test_deleting_memo_or_folder_cascades_viewers(c):
    m = new(c, "a", "shared")["id"]
    share(c, m, "a", "restricted", ["b"])
    f = folder(c, "a")["id"]
    fshare(c, f, "a", "restricted", ["b"])
    c.delete(f"/api/memos/{m}", headers=as_("a"))
    c.delete(f"/api/folders/{f}", headers=as_("a"))
    with db.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM memo_viewers").fetchone()[0] == 0
        assert con.execute("SELECT COUNT(*) FROM folder_viewers").fetchone()[0] == 0


def race_after_get(monkeypatch, sql, *args):
    """memos._get(확인)이 통과한 직후 다른 요청이 같은 메모·목록을 바꾼 상황을 만든다(한 번만)."""
    orig, done = memos._get, []

    def racing(con, mid, user):
        m = orig(con, mid, user)
        if not done:
            done.append(1)
            with db.connect() as other:
                other.execute(sql, args)
        return m

    monkeypatch.setattr(memos, "_get", racing)


def test_write_rechecks_after_person_removed_meanwhile(c, monkeypatch):
    """b가 확인을 통과한 뒤 목록에서 빠지면 b의 쓰기는 하지 않고 없는 메모와 같은 404다."""
    m = new(c, "a", "shared", "원래제목")["id"]
    share(c, m, "a", "restricted", ["b"])
    for call in (lambda: c.put(f"/api/memos/{m}", json={"title": "b가 고침"}, headers=as_("b")),
                 lambda: c.post(f"/api/memos/{m}/copy-to-personal", headers=as_("b")),
                 lambda: c.put(f"/api/memos/{m}", json={"folder_id": None}, headers=as_("b"))):
        with db.connect() as con:
            con.execute("INSERT OR IGNORE INTO memo_viewers VALUES(?, 'b')", (m,))
        race_after_get(monkeypatch, "DELETE FROM memo_viewers WHERE memo_id=?", m)
        assert call().status_code == 404
    assert c.get(f"/api/memos/{m}", headers=as_("a")).json()["title"] == "원래제목"
    with db.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM memos WHERE kind='personal'").fetchone()[0] == 0


def test_write_blocked_when_visibility_flips_after_check(c, monkeypatch):
    """확인한 뒤 공개 범위가 제한으로 바뀌면: 목록에 없는 사람의 쓰기는 일어나지 않고(없는 메모와 같은 404),
    만든 사람의 쓰기도 확인한 상태와 달라졌으니 하지 않는다(409). 쓰기 조건에 확인한 visibility가 들어 있다."""
    flip = "UPDATE memos SET visibility='restricted' WHERE id=?"
    m = new(c, "a", "shared", "원래")["id"]
    race_after_get(monkeypatch, flip, m)
    assert c.put(f"/api/memos/{m}", json={"title": "c가 고침"}, headers=as_("c")).status_code == 404
    assert c.get(f"/api/memos/{m}", headers=as_("a")).json()["title"] == "원래"
    m = new(c, "a", "shared", "원래2")["id"]
    race_after_get(monkeypatch, flip, m)
    assert c.delete(f"/api/memos/{m}", headers=as_("a")).status_code == 409
    with db.connect() as con:
        assert con.execute("SELECT 1 FROM memos WHERE id=?", (m,)).fetchone()  # 지워지지 않았다
    m = new(c, "a", "shared", "원래3")["id"]
    race_after_get(monkeypatch, flip, m)
    assert c.post(f"/api/memos/{m}/move", json={"to": "admin"}, headers=as_("boss")).status_code == 409


def test_move_into_folder_rechecks_folder_access_under_lock(c, monkeypatch):
    """폴더 지정은 쓰기 잠금을 잡은 뒤에 대상 폴더 접근을 확인한다: 그 이후에는 목록이 바뀔 수 없다."""
    f = folder(c, "a", "대상")["id"]
    fshare(c, f, "a", "restricted", ["c"])
    mine = new(c, "c", "shared")["id"]
    seen = []
    orig = folders.get_visible

    def spy(con, fid, user):
        seen.append(con.in_transaction)  # 쓰기 잠금(트랜잭션) 안에서 부르는가
        return orig(con, fid, user)

    monkeypatch.setattr(folders, "get_visible", spy)
    assert c.put(f"/api/memos/{mine}", json={"folder_id": f}, headers=as_("c")).status_code == 200
    assert seen == [True]


def test_share_with_is_conditioned_on_checked_state(c, monkeypatch):
    m = new(c, "a", "shared", "공유중")["id"]
    race_after_get(monkeypatch, "UPDATE memos SET visibility='restricted' WHERE id=?", m)
    # a가 '전체'로 보았다가 그 사이 제한으로 바뀜: a는 만든 사람이라 여전히 보지만 확인한 상태와 달라 409
    assert c.put(f"/api/memos/{m}/share-with", json=dict(visibility="restricted", viewers=["b"]), headers=as_("a")).status_code == 409
    with db.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM memo_viewers WHERE memo_id=?", (m,)).fetchone()[0] == 0


def test_single_access_function_decides_every_path(c, monkeypatch):
    """ws.can_access가 공동 행을 모두 거부하면 목록·조회·쓰기·연동·활동·rev·실시간 연결이 전부 같이 닫힌다(다른 곳에서 따로 판정하지 않는다)."""
    f = folder(c, "a", "폴더")["id"]
    m = new(c, "a", "shared", "공개글", folder_id=f)["id"]
    orig = ws.can_access
    monkeypatch.setattr(ws, "can_access", lambda row, user, con=None, cache=None:
                        False if row["kind"] == "shared" and row["id"] else orig(row, user, con, cache))  # id 없는 행 = can_use_kind의 종류 확인
    for uid in ("a", "boss"):  # 만든 사람·관리자도 이 함수가 거부하면 거부된다
        h = as_(uid)
        assert shared_ids(c, uid) == [] and c.get("/api/folders?kind=shared", headers=h).json() == []
        for r in (c.get(f"/api/memos/{m}", headers=h), c.put(f"/api/memos/{m}", json={"title": "x"}, headers=h),
                  c.delete(f"/api/memos/{m}", headers=h), c.post(f"/api/memos/{m}/copy-to-personal", headers=h),
                  c.put(f"/api/memos/{m}/share-with", json=dict(visibility="all"), headers=h),
                  c.put(f"/api/folders/{f}", json=dict(name="z"), headers=h),
                  c.put(f"/api/folders/{f}/share-with", json=dict(visibility="all"), headers=h),
                  c.delete(f"/api/folders/{f}", headers=h)):
            assert r.status_code == 404
        assert c.get(f"/api/link/memos?ids={m}", headers=h).json() == []
        with c:
            assert rejected(c, m, uid) == 1008
    assert c.get(f"/internal/link/memos?ids={m}", headers={"X-Link-Key": KEY}).json() == []
    assert feed(c, "boss")["rev"].split(":")[1] == "0"


def test_connection_closed_when_access_cannot_be_rechecked(c, monkeypatch):
    """접근을 다시 확인하다 DB 오류가 나면 열린 연결은 닫히고(fail-closed) 새 연결도 거절된다."""
    m = new(c, "a", "shared")["id"]
    share(c, m, "a", "restricted", ["b"])
    with c:
        with connect(c, m, "b") as w:
            p = Peer(w)

            def locked(*_a, **_k):
                raise sqlite3.OperationalError("database is locked")

            with monkeypatch.context() as mp:
                mp.setattr(ws, "viewer_ids", locked)
                c.portal.call(ws.rooms.revoke, 4404, ws.GONE_REASON, m)
                assert wait_closed(p) == 4404
        with monkeypatch.context() as mp:
            mp.setattr(ws, "restrictor", locked)
            assert rejected(c, m, "b") == 1008
        with connect(c, m, "b") as w:  # 오류가 사라지면 다시 붙을 수 있다
            assert Peer(w).closed is None


def test_role_demotion_closes_restricted_connection_of_ex_admin(c):
    """관리자라서 보던 비공개 메모는 강등되면 닫힌다(목록에 없을 때)."""
    m = new(c, "a", "shared")["id"]
    share(c, m, "a", "restricted", ["b"])
    with c:
        with connect(c, m, "boss2") as w, connect(c, m, "b") as wb:
            p, pb = Peer(w), Peer(wb)
            assert c.put("/api/users/boss2", json=dict(name="boss2", role="editor"), headers=as_("boss")).status_code == 200
            assert wait_closed(p) in (4403, 4404)
            time.sleep(0.3)
            assert pb.closed is None
        assert rejected(c, m, "boss2") == 1008
