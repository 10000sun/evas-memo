"""관리 기록: 차단·해제·복구가 남고 관리자만 본다."""
from tests.conftest import as_

ADMIN = as_("boss")
K = {"X-Link-Key": "k" * 32}


def test_audit_log(client, monkeypatch):
    monkeypatch.setenv("LINK_API_KEY", "k" * 32)
    client.put("/api/blocked/bad", headers=ADMIN)
    client.delete("/api/blocked/bad", headers=ADMIN)
    client.delete("/api/blocked/bad", headers=ADMIN)  # 이미 풀린 사람: 기록하지 않는다
    client.put("/internal/sync/blocked/peer", json={"name": "동기화"}, headers=K)
    snap = client.get("/api/backup", headers=ADMIN).content
    client.post("/api/restore", content=snap, headers=ADMIN)
    log = client.get("/api/audit", headers=ADMIN).json()
    assert [(a["action"], a["target_id"], a["actor_name"]) for a in log][:1] == [("restore", None, "boss")]
    assert [(a["action"], a["target_id"]) for a in log[1:]] == [("block", "peer"), ("unblock", "bad"), ("block", "bad")]
    assert log[1]["actor_name"] == "다른 앱(동기화)"
    assert client.get("/api/audit", headers=as_("kim")).status_code == 403
