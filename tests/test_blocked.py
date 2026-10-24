"""차단: 계정·기기 단위, 관리자는 차단 불가, 해제하면 복구."""
import pytest

from app import usersync
from tests.conftest import as_

DEV = {"Cookie": "evas_dev=dev1"}


@pytest.fixture
def sent(monkeypatch):
    calls = []

    async def fake(method, uid, body=None, kind="users"):
        calls.append((method, uid, kind))
        return True
    monkeypatch.setattr(usersync, "push_async", fake)
    return calls


def test_block_account_and_device(client, sent):
    assert client.get("/api/me", headers={**as_("bad"), **DEV}).status_code == 200  # 기기가 계정과 묶인다
    assert client.put("/api/blocked/bad", headers=as_("boss")).json()["synced"] is True
    assert sent == [("PUT", "bad", "blocked")]
    assert client.get("/api/me", headers=as_("bad")).status_code == 401  # 계정 차단
    assert client.get("/api/me", headers={**as_("other"), **DEV}).status_code == 401  # 같은 기기의 다른 계정도 차단
    assert client.get("/api/me", headers=as_("other")).status_code == 200  # 무관한 기기·계정은 영향 없음
    assert client.get("/api/blocked", headers=as_("boss")).json() == [{"id": "bad", "name": "bad"}]


def test_unblock_restores(client, sent):
    client.get("/api/me", headers={**as_("bad"), **DEV})
    client.put("/api/blocked/bad", headers=as_("boss"))
    assert client.delete("/api/blocked/bad", headers=as_("boss")).status_code == 200
    assert client.get("/api/me", headers={**as_("bad"), **DEV}).status_code == 200
    assert client.get("/api/blocked", headers=as_("boss")).json() == []


def test_admin_only_and_no_admin_block(client, sent):
    client.get("/api/me", headers=as_("ed"))
    assert client.put("/api/blocked/ed", headers=as_("ed")).status_code == 403
    assert client.put("/api/blocked/boss", headers=as_("boss")).status_code == 409


def test_internal_sync(client, monkeypatch):
    monkeypatch.setenv("LINK_API_KEY", "k")
    K = {"X-Link-Key": "k"}
    assert client.put("/internal/sync/blocked/bad", json={"name": "나쁜"}, headers=K).status_code == 204
    assert client.get("/api/me", headers=as_("bad")).status_code == 401
    assert client.delete("/internal/sync/blocked/bad", headers=K).status_code == 204
    assert client.get("/api/me", headers=as_("bad")).status_code == 200
