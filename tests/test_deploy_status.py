"""관리 화면의 '서버 상태·자동 배포': 관리자만, 기록 파일이 없으면 null."""
import json
import os

from app import backup
from tests.conftest import as_

ADMIN = as_("boss")


def test_deploy_status(client, monkeypatch, tmp_path):
    monkeypatch.setattr(backup, "ROOT", str(tmp_path))
    r = client.get("/api/deploy-status", headers=ADMIN).json()
    assert r["update"] is None and "running" in r  # 자동 배포 기록 없음(설치 전)
    os.makedirs(tmp_path / "data")
    (tmp_path / "data" / "update-status.json").write_text(json.dumps({"checked_at": "2026-11-08T01:00:00+00:00", "head": "abc1234", "error": None}), encoding="utf-8")
    assert client.get("/api/deploy-status", headers=ADMIN).json()["update"]["head"] == "abc1234"
    (tmp_path / "data" / "update-status.json").write_text("깨진 파일", encoding="utf-8")
    assert client.get("/api/deploy-status", headers=ADMIN).json()["update"] is None  # 깨져도 화면이 죽지 않는다
    assert client.get("/api/deploy-status", headers=as_("kim")).status_code == 403
    assert client.get("/api/deploy-status").status_code == 401


def test_admin_page_fills_audit_and_deploy_sections():
    # 화면 코드가 이 영역들을 실제로 채우는지(과거에 연결이 빠진 채 배포된 적이 있다)
    from pathlib import Path
    js = (Path(__file__).parent.parent / "static" / "admin.js").read_text(encoding="utf-8")
    html = (Path(__file__).parent.parent / "static" / "admin.html").read_text(encoding="utf-8")
    for el_id in ("audit", "deploy"):
        assert f'id="{el_id}"' in html and f'$("{el_id}").replaceChildren' in js
