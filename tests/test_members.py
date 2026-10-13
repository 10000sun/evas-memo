import pytest

from app import auth, db
from tests.conftest import as_


@pytest.fixture(autouse=True)
def _no_open_edit(monkeypatch):
    monkeypatch.delenv("EVAS_OPEN_EDIT", raising=False)  # 자동 등록이 권한을 주면 안 된다


def members(client):
    client.cookies.clear()  # 세션이 있으면 헤더보다 앞서므로 관리자 헤더가 먹도록 비운다
    return {m["id"]: m for m in client.get("/api/members", headers=as_("boss")).json()}


def test_first_visit_registers_but_stays_viewer(client):
    assert client.get("/api/me", headers=as_("newbie")).json()["role"] == "viewer"
    m = members(client)["newbie"]
    assert m["role"] == "viewer" and m["first_seen"] and m["last_seen"]
    # 등록돼도 메모를 만들 수 없고 권한도 그대로다
    assert client.post("/api/memos", json=dict(kind="shared", title="x"), headers=as_("newbie")).status_code == 403
    assert client.get("/api/me", headers=as_("newbie")).json()["role"] == "viewer"


def test_dev_login_registers_and_name_updates(client):
    client.get("/auth/dev?uid=u1&name=옛이름", follow_redirects=False)
    first = members(client)["u1"]["first_seen"]
    assert members(client)["u1"]["name"] == "옛이름"
    client.get("/auth/dev?uid=u1&name=새이름", follow_redirects=False)
    m = members(client)["u1"]
    assert m["name"] == "새이름" and m["first_seen"] == first


def test_callback_registers(client, monkeypatch):
    for k, v in dict(PUBLIC_URL="http://x", DISCORD_CLIENT_ID="c", DISCORD_CLIENT_SECRET="s").items():
        monkeypatch.setenv(k, v)
    monkeypatch.setattr(auth, "fetch_discord_profile", lambda *a: {"id": "d1", "name": "디스", "in_guild": True})
    loc = client.get("/auth/login", follow_redirects=False).headers["location"]
    state = loc.split("state=")[1].split("&")[0]
    client.get(f"/auth/callback?code=c&state={state}", follow_redirects=False)
    assert members(client)["d1"]["name"] == "디스"


def test_members_admin_only(client):
    client.get("/api/me", headers=as_("eve"))
    assert client.get("/api/members", headers=as_("eve")).status_code == 403
    assert client.get("/api/members").status_code == 401


def test_merged_list_includes_seeded_admin_without_row(client):
    m = members(client)["boss"]
    assert m["role"] == "admin" and m["last_seen"] is None and m["first_seen"] is None
    client.get("/api/me", headers=as_("boss"))
    assert members(client)["boss"]["last_seen"]


def test_effective_role_follows_users_table(client):
    client.get("/api/me", headers=as_("ed"))
    client.put("/api/users/ed", json=dict(name="ed", role="editor"), headers=as_("boss"))
    assert members(client)["ed"]["role"] == "editor"
    client.delete("/api/users/ed", headers=as_("boss"))
    assert members(client)["ed"]["role"] == "viewer"


def test_pick_only_id_and_name_and_respects_q_limit(client):
    for i in range(25):
        client.get("/api/me", headers=as_(f"p{i:02d}"))
    client.get("/auth/dev?uid=zz&name=Alice", follow_redirects=False)
    client.cookies.clear()
    v = as_("viewer1")  # 보기 전용 사용자도 부를 수 있다
    r = client.get("/api/members/pick", headers=v)
    assert r.status_code == 200 and len(r.json()) == 20
    assert all(set(x) == {"id", "name"} for x in r.json())
    assert [x["id"] for x in client.get("/api/members/pick?q=aLi", headers=v).json()] == ["zz"]
    assert len(client.get("/api/members/pick?limit=3", headers=v).json()) == 3
    assert len(client.get("/api/members/pick?limit=999", headers=v).json()) == 20
    assert client.get("/api/members/pick?q=없는이름", headers=v).json() == []
    assert client.get("/api/members/pick").status_code == 401


def test_upsert_idempotent_and_last_seen_not_rewritten(client):
    client.get("/api/me", headers=as_("a"))
    today = db.now()[:10]
    with db.connect() as con:
        con.execute("UPDATE members SET last_seen=? WHERE id='a'", (today + "T00:00:01",))
    for _ in range(3):
        client.get("/api/me", headers=as_("a"))
    with db.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM members WHERE id='a'").fetchone()[0] == 1
        assert con.execute("SELECT last_seen FROM members WHERE id='a'").fetchone()[0] == today + "T00:00:01"
        con.execute("UPDATE members SET last_seen='2000-01-01T00:00:00' WHERE id='a'")  # 날짜가 지나면 갱신된다
    client.get("/api/me", headers=as_("a"))
    with db.connect() as con:
        assert con.execute("SELECT last_seen FROM members WHERE id='a'").fetchone()[0][:10] == today


def test_init_adds_members_to_existing_db(client):
    with db.connect() as con:
        con.execute("DROP TABLE members")
        con.execute("INSERT INTO categories(name,color) VALUES('보존','#000000')")
    db.init()
    db.init()
    with db.connect() as con:
        assert con.execute("SELECT COUNT(*) FROM members").fetchone()[0] == 0
        assert con.execute("SELECT 1 FROM categories WHERE name='보존'").fetchone()


def test_touch_failure_does_not_break_requests(client, monkeypatch):
    def boom(*a):
        raise RuntimeError("database is locked")
    monkeypatch.setattr(db, "_touch", boom)
    assert client.get("/api/me", headers=as_("a")).status_code == 200
    assert client.get("/auth/dev?uid=b", follow_redirects=False).status_code in (302, 307)
    monkeypatch.setenv("PUBLIC_URL", "http://x")
    monkeypatch.setenv("DISCORD_CLIENT_ID", "c")
    monkeypatch.setenv("DISCORD_CLIENT_SECRET", "s")
    monkeypatch.setattr(auth, "fetch_discord_profile", lambda *a: {"id": "d1", "name": "디스", "in_guild": True})
    state = client.get("/auth/login", follow_redirects=False).headers["location"].split("state=")[1].split("&")[0]
    assert client.get(f"/auth/callback?code=c&state={state}", follow_redirects=False).status_code in (302, 307)


def test_no_write_when_nothing_changed(client, monkeypatch):
    client.get("/api/me", headers=as_("a"))
    calls = []
    monkeypatch.setattr(db, "_upsert_member", lambda *a: calls.append(a))
    client.get("/api/me", headers=as_("a"))
    assert calls == []
    client.get("/auth/dev?uid=a&name=바뀐이름", follow_redirects=False)  # 이름이 다르면 쓴다
    assert len(calls) == 1
