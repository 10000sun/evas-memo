"""메모 <-> 캘린더 관리자·편집자 권한 맞추기."""
import pytest

from app import db, usersync
from tests.conftest import as_

KEY = "sync-test-key"
K = {"X-Link-Key": KEY}


@pytest.fixture
def c(client, monkeypatch):
    monkeypatch.setenv("LINK_API_KEY", KEY)
    monkeypatch.delenv("EVAS_OPEN_EDIT", raising=False)
    return client


@pytest.fixture
def sent(monkeypatch):
    calls = []

    def fake(method, uid, body=None):
        calls.append((method, uid, body))
        return True
    monkeypatch.setattr(usersync, "push", fake)
    return calls


def role(uid):
    with db.connect() as con:
        r = con.execute("SELECT role FROM users WHERE id=?", (uid,)).fetchone()
    return r["role"] if r else None


def test_내부_경로는_키가_있어야_하고_적용만_한다(c, sent):
    body = dict(name="새사람", role="editor")
    for headers in ({}, {"X-Link-Key": "wrong-key"}):
        assert c.put("/internal/sync/users/u1", json=body, headers=headers).status_code == 404
    assert role("u1") is None
    assert c.put("/internal/sync/users/u1", json=body, headers=K).status_code == 204
    assert role("u1") == "editor"
    assert c.put("/internal/sync/users/u1", json=dict(name="새사람", role="admin"), headers=K).status_code == 204
    assert role("u1") == "admin"
    assert sent == []  # 받은 변경을 상대에게 되돌려 보내지 않는다(무한 반복 방지)


def test_내부_경로_검증(c):
    assert c.put("/internal/sync/users/u1", json=dict(name="x", role="viewer"), headers=K).status_code == 422
    assert c.put("/internal/sync/users/u1", json=dict(name="  ", role="editor"), headers=K).status_code == 422
    assert c.put("/internal/sync/users/" + "9" * 65, json=dict(name="x", role="editor"), headers=K).status_code == 422


def test_마지막_관리자는_내부_경로로도_못_내린다(c):
    assert role("boss") == "admin"
    assert c.put("/internal/sync/users/boss", json=dict(name="boss", role="editor"), headers=K).status_code == 409
    assert c.delete("/internal/sync/users/boss", headers=K).status_code == 409
    assert role("boss") == "admin"
    c.put("/internal/sync/users/boss2", json=dict(name="b2", role="admin"), headers=K)
    assert c.put("/internal/sync/users/boss", json=dict(name="boss", role="editor"), headers=K).status_code == 204  # 관리자가 둘이면 가능


def test_내부_삭제는_없어도_같은_결과(c):
    assert c.delete("/internal/sync/users/nobody", headers=K).status_code == 204
    assert c.delete("/internal/sync/users/nobody").status_code == 404  # 키 없으면 경로가 없는 것처럼


def test_권한을_바꾸면_캘린더에도_알린다(c, sent):
    r = c.put("/api/users/u2", json=dict(name="이름", role="editor"), headers=as_("boss"))
    assert r.status_code == 200 and r.json()["synced"] is True
    assert sent == [("PUT", "u2", {"name": "이름", "role": "editor"})]
    d = c.delete("/api/users/u2", headers=as_("boss"))
    assert d.status_code == 204 and d.headers["X-Synced"] == "1"
    assert sent[-1][:2] == ("DELETE", "u2")


def test_캘린더에_못_알려도_이_앱의_변경은_남고_실패를_알려_준다(c, monkeypatch):
    monkeypatch.setattr(usersync, "push", lambda *a: False)
    r = c.put("/api/users/u3", json=dict(name="이름", role="admin"), headers=as_("boss"))
    assert r.status_code == 200 and r.json()["synced"] is False
    assert role("u3") == "admin"
    d = c.delete("/api/users/u3", headers=as_("boss"))
    assert d.status_code == 204 and d.headers["X-Synced"] == "0" and role("u3") is None


def test_연동이_꺼져_있으면_알리지_않고_synced는_null(client, monkeypatch):
    monkeypatch.delenv("LINK_API_KEY", raising=False)
    r = client.put("/api/users/u4", json=dict(name="이름", role="editor"), headers=as_("boss"))
    assert r.status_code == 200 and r.json()["synced"] is None
    assert client.delete("/api/users/u4", headers=as_("boss")).headers.get("X-Synced") is None
    assert client.post("/api/users/sync", headers=as_("boss")).status_code == 404
    assert client.put("/internal/sync/users/u5", json=dict(name="x", role="editor"), headers=K).status_code == 404


def test_한_번에_맞추기는_관리자만_하고_전체를_보낸다(c, sent):
    c.put("/api/users/u6", json=dict(name="여섯", role="editor"), headers=as_("boss"))
    sent.clear()
    assert c.post("/api/users/sync", headers=as_("u6")).status_code in (401, 403)
    r = c.post("/api/users/sync", headers=as_("boss"))
    assert r.status_code == 200 and r.json() == {"ok": 2, "failed": 0}
    assert {(m, u) for m, u, _ in sent} == {("PUT", "boss"), ("PUT", "u6")}


def test_상대_앱_호출은_키와_알맞은_주소로_나간다(c, monkeypatch):
    """push 자체: 상대 내부 주소·X-Link-Key·본문·시스템 프록시 무시(trust_env=False)를 확인한다. 응답 코드별 결과도."""
    import importlib
    real = importlib.reload(usersync).push  # conftest가 바꿔 끼운 push를 되돌려 진짜 함수를 쓴다
    monkeypatch.setenv("CALENDAR_INTERNAL_URL", "http://peer.invalid:8000")
    seen = {}

    class FakeResp:
        def __init__(self, code): self.status_code = code

    class FakeClient:
        code = 204

        def __init__(self, **kw): seen["init"] = kw
        def __enter__(self): return self
        def __exit__(self, *a): return False

        def request(self, method, url, json=None, headers=None):
            seen.update(method=method, url=url, json=json, headers=headers)
            return FakeResp(FakeClient.code)

    monkeypatch.setattr(usersync.httpx, "Client", FakeClient)
    assert real("PUT", "한글 id/1", {"name": "n", "role": "admin"}) is True
    assert seen["url"] == "http://peer.invalid:8000/internal/sync/users/%ED%95%9C%EA%B8%80%20id%2F1"
    assert seen["headers"] == K and seen["json"] == {"name": "n", "role": "admin"}
    assert seen["init"] == {"timeout": 3, "trust_env": False}
    FakeClient.code = 409
    assert real("DELETE", "x") is False  # 상대가 거절(마지막 관리자 등)하면 실패로 본다
    monkeypatch.delenv("LINK_API_KEY")
    assert real("PUT", "x", {}) is None  # 연동 꺼짐
