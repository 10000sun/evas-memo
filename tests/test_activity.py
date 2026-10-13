"""활동 기록·푸시: 공동 메모만 기록하고, 개인 메모는 기록·알림이 없다."""
import time
from datetime import datetime, timedelta

import pytest

from app import db, push
from tests.conftest import as_
from tests.test_memo_ws import Peer, body_in_db, connect
from tests.test_memos import new


@pytest.fixture
def c(client, monkeypatch):
    monkeypatch.delenv("EVAS_OPEN_EDIT", raising=False)
    for uid in ("a", "b"):
        client.put(f"/api/users/{uid}", json=dict(name="이름" + uid, role="editor"), headers=as_("boss"))
    return client


@pytest.fixture
def pushed(monkeypatch):
    calls = []
    monkeypatch.setattr(push, "notify", lambda *a: calls.append(a))
    return calls


def act(c, uid="a"):
    r = c.get("/api/activity", headers=as_(uid))
    assert r.status_code == 200, r.text
    return r.json()


def kinds(c, uid="a"):
    return [i["kind"] for i in act(c, uid)["items"]]


def edit_ws(c, mid, uid, text):
    with c:
        with connect(c, mid, uid) as w:
            p = Peer(w)
            p.text += text
            p.push()
            end = time.time() + 4
            while not body_in_db(mid).endswith(text) and time.time() < end:
                time.sleep(0.05)
            assert body_in_db(mid).endswith(text)
            time.sleep(0.1)  # 저장 직후 활동 기록까지 끝나도록


def test_shared_create_logs_add(c, pushed):
    m = new(c, "a", "shared", "공지글")
    [i] = act(c, "b")["items"]
    assert (i["kind"], i["memo_id"], i["title"], i["actor_id"], i["actor_name"]) == ("add", m["id"], "공지글", "a", "a")


def test_personal_actions_not_logged(c, pushed):
    m = new(c, "a", "personal", "비밀")
    mid = m["id"]
    c.put(f"/api/memos/{mid}", json=dict(title="비밀2"), headers=as_("a"))
    edit_ws(c, mid, "a", "본문")
    assert c.delete(f"/api/memos/{mid}", headers=as_("a")).status_code == 204
    assert act(c, "b")["items"] == [] and pushed == []


def test_personal_not_in_rev(c):
    before = act(c, "b")["rev"]
    m = new(c, "a", "personal", "비밀")
    c.put(f"/api/memos/{m['id']}", json=dict(title="x"), headers=as_("a"))
    assert act(c, "b")["rev"] == before
    new(c, "a", "shared")
    assert act(c, "b")["rev"] != before


def test_move_to_shared_logs_add(c, pushed):
    m = new(c, "a", "personal", "옮길 글")
    assert c.post(f"/api/memos/{m['id']}/share", headers=as_("a")).status_code == 200
    [i] = act(c, "b")["items"]
    assert (i["kind"], i["title"], i["memo_id"]) == ("add", "옮길 글", m["id"])
    assert [p[0] for p in pushed] == ["add"]


def test_copy_to_personal_logs_nothing(c, pushed):
    m = new(c, "a", "shared", "공동글")
    n = len(act(c)["items"])
    pushed.clear()
    assert c.post(f"/api/memos/{m['id']}/copy-to-personal", headers=as_("b")).status_code == 201
    assert len(act(c)["items"]) == n and pushed == []


def test_shared_delete_logs_delete(c, pushed):
    m = new(c, "a", "shared", "지울 글")
    assert c.delete(f"/api/memos/{m['id']}", headers=as_("a")).status_code == 204
    assert kinds(c, "b") == ["delete", "add"]
    assert act(c, "b")["items"][0]["title"] == "지울 글"


def test_consecutive_edits_coalesce_within_10_minutes(c, monkeypatch):
    t = [datetime(2026, 1, 1, 12, 0, 0)]
    monkeypatch.setattr(db, "now", lambda: t[0].isoformat(timespec="seconds"))
    mid = new(c, "a", "shared", "글")["id"]
    edit_ws(c, mid, "a", "하나")
    [e] = [i for i in act(c)["items"] if i["kind"] == "edit"]
    t[0] += timedelta(minutes=5)
    edit_ws(c, mid, "a", "둘")
    [e2] = [i for i in act(c)["items"] if i["kind"] == "edit"]
    assert e2["id"] == e["id"] and e2["at"] == t[0].isoformat(timespec="seconds") != e["at"]
    t[0] += timedelta(minutes=11)  # 마지막 편집에서 10분을 넘기면 새 기록
    edit_ws(c, mid, "a", "셋")
    assert kinds(c).count("edit") == 2
    edit_ws(c, mid, "b", "넷")  # 다른 사람이면 곧바로 새 기록
    items = act(c)["items"]
    assert [(i["kind"], i["actor_id"]) for i in items][:2] == [("edit", "b"), ("edit", "a")]


def test_unread_excludes_own_actions(c):
    act(c, "b")  # b의 읽음 위치를 지금으로
    new(c, "a", "shared")
    assert act(c, "a")["unread"] == 0  # 내 것은 안 읽음에 세지 않는다
    assert act(c, "b")["unread"] == 1
    assert c.post("/api/activity/read", headers=as_("b")).status_code == 204
    assert act(c, "b")["unread"] == 0


def test_push_only_for_add_and_delete(c, pushed):
    m = new(c, "a", "shared", "글")
    c.put(f"/api/memos/{m['id']}", json=dict(title="글2"), headers=as_("a"))
    edit_ws(c, m["id"], "a", "본문")
    c.post(f"/api/memos/{m['id']}/copy-to-personal", headers=as_("b"))
    c.delete(f"/api/memos/{m['id']}", headers=as_("a"))
    assert [(p[0], p[1], p[2]["id"]) for p in pushed] == [("add", "글", "a"), ("delete", "글2", "a")]


def test_push_subscribe_and_key(c, monkeypatch):
    monkeypatch.delenv("VAPID_PRIVATE_KEY", raising=False)
    assert c.get("/api/push/key", headers=as_("a")).json() == {"key": None}
    sub = dict(endpoint="https://fcm.googleapis.com/x", keys=dict(p256dh="p", auth="q"))
    assert c.post("/api/push/subscribe", json=sub, headers=as_("a")).status_code == 204
    assert c.post("/api/push/subscribe", json=dict(sub, endpoint="https://evil.example/x"), headers=as_("a")).status_code == 422
    assert c.post("/api/push/unsubscribe", json=sub, headers=as_("a")).status_code == 204
    with db.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM push_subs").fetchone()[0] == 0
