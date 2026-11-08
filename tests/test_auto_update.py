"""서버 PC 자동 배포(scripts/auto_update.py): GitHub 대신 가짜 latest()/download()로 받기·교체·재시작·실패 처리를 확인한다. git은 쓰지 않는다."""
import importlib.util
import io
import json
import os
import sqlite3
import zipfile
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "scripts" / "auto_update.py"


def make_zip(files, top="10000sun-evas-memo-abc1234"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for name, text in files.items():
            z.writestr(f"{top}/{name}", text)
    return buf.getvalue()


@pytest.fixture
def env(tmp_path, monkeypatch):
    for k in ("EVAS_DB", "EVAS_BACKUP_DIR", "EVAS_PORT", "GITHUB_REPO", "GITHUB_TOKEN"):  # 다른 테스트가 남긴 값이 서버 PC의 .env 대신 읽히지 않게
        monkeypatch.delenv(k, raising=False)
    server = tmp_path / "server"
    (server / "data").mkdir(parents=True)
    (server / "app").mkdir()
    (server / "app" / "main.py").write_text("옛 코드")
    (server / "requirements.txt").write_text("fastapi\n")
    (server / ".env").write_text("SECRET=1\n")
    sqlite3.connect(server / "data" / "evas.db").execute("CREATE TABLE t(a)").connection.commit()  # 운영 DB 대역
    m = importlib.util.module_from_spec(importlib.util.spec_from_file_location("auto_update", SCRIPT))
    m.__spec__.loader.exec_module(m)
    st = {"sha": "a" * 40, "date": "2026-11-08T00:00:00Z", "files": {"app/main.py": "새 코드", "requirements.txt": "fastapi\n", "static/new.js": "x"}}
    calls = []
    monkeypatch.setattr(m, "latest", lambda: {"sha": st["sha"], "date": st["date"]})
    monkeypatch.setattr(m, "download", lambda sha: calls.append("download") or make_zip(st["files"]))
    monkeypatch.setattr(m, "restart", lambda: calls.append("restart"))
    monkeypatch.setattr(m, "healthy", lambda *a, **k: True)
    monkeypatch.setattr(m, "install_requirements", lambda path: calls.append("pip"))
    return m, server, st, calls


def status(server):
    return json.loads((server / "data" / "update-status.json").read_text(encoding="utf-8"))


def backups(server):
    d = server / "data" / "backups"
    return sorted(p.name for p in d.glob("pre-update-*.db")) if d.exists() else []


def test_first_run_installs_latest_and_keeps_data_and_env(env):
    m, server, st, calls = env
    assert m.run(str(server)) == 0
    assert calls == ["download", "restart"]
    assert (server / "app" / "main.py").read_text() == "새 코드" and (server / "static" / "new.js").exists()
    assert (server / ".env").read_text() == "SECRET=1\n" and (server / "data" / "evas.db").exists()  # 설정·데이터는 그대로
    assert json.loads((server / "data" / "version.json").read_text())["sha"] == "a" * 40
    assert len(backups(server)) == 1  # 배포 직전 DB 사본
    s = status(server)
    assert s["head"] == "aaaaaaa" and s["deployed_ok"] is True and s["error"] is None and s["checked_at"]
    assert "배포 완료" in (server / "data" / "update.log").read_text(encoding="utf-8")


def test_same_version_only_records_the_check(env):
    m, server, st, calls = env
    m.run(str(server))
    calls.clear()
    assert m.run(str(server)) == 0 and calls == []  # 새 버전이 없으면 내려받지도 재시작하지도 않는다
    assert status(server)["checked_at"]  # 하지만 확인한 시각은 남는다(돌고 있는지 알 수 있게)


def test_new_version_replaces_files_and_deletes_removed_ones(env):
    m, server, st, calls = env
    m.run(str(server))
    calls.clear()
    st.update(sha="b" * 40, files={"app/main.py": "더 새 코드", "requirements.txt": "fastapi\n"})  # static/new.js는 새 버전에서 사라짐
    assert m.run(str(server)) == 0 and calls == ["download", "restart"]
    assert (server / "app" / "main.py").read_text() == "더 새 코드" and not (server / "static" / "new.js").exists()
    assert (server / ".env").exists() and status(server)["head"] == "bbbbbbb"


def test_requirements_change_installs_before_files_change(env):
    m, server, st, calls = env
    st["files"]["requirements.txt"] = "fastapi\nicalendar\n"
    m.run(str(server))
    assert calls == ["download", "pip", "restart"]


def test_failed_pip_leaves_files_unchanged(env, monkeypatch):
    m, server, st, calls = env
    st["files"]["requirements.txt"] = "fastapi\nnope\n"

    def boom(path):
        raise RuntimeError("pip 실패")
    monkeypatch.setattr(m, "install_requirements", boom)
    assert m.run(str(server)) == 1 and calls == ["download"]
    assert (server / "app" / "main.py").read_text() == "옛 코드" and not (server / "data" / "version.json").exists()  # 다음 주기에 다시 시도한다
    assert "pip 실패" in status(server)["error"]


def test_network_error_is_logged_once_and_app_untouched(env, monkeypatch):
    m, server, st, calls = env

    def down():
        raise OSError("연결 안 됨")
    monkeypatch.setattr(m, "latest", down)
    assert m.run(str(server)) == 1 and m.run(str(server)) == 1
    assert calls == [] and (server / "app" / "main.py").read_text() == "옛 코드"
    assert (server / "data" / "update.log").read_text(encoding="utf-8").count("실패") == 1  # 같은 실패는 한 번만
    assert "연결 안 됨" in status(server)["error"] and status(server)["checked_at"]


def test_zip_with_path_escape_is_rejected(env, monkeypatch):
    m, server, st, calls = env
    monkeypatch.setattr(m, "download", lambda sha: make_zip({"../../evil.txt": "x", "app/main.py": "y"}))
    assert m.run(str(server)) == 1 and calls == []
    assert not (server.parent / "evil.txt").exists() and (server / "app" / "main.py").read_text() == "옛 코드"


def test_only_latest_five_snapshots_are_kept(env):
    m, server, st, calls = env
    d = server / "data" / "backups"
    d.mkdir()
    for i in range(7):
        (d / f"pre-update-2020010{i + 1}-000000.db").write_bytes(b"x")
    (d / "auto-2020-01-01.db").write_bytes(b"x")  # 자동 백업은 건드리지 않는다
    m.run(str(server))
    kept = backups(server)
    assert len(kept) == 5 and kept[0] == "pre-update-20200104-000000.db" and kept[-1] > "pre-update-2021"
    assert (d / "auto-2020-01-01.db").exists()


def test_unhealthy_app_is_reported(env, monkeypatch):
    m, server, st, calls = env
    monkeypatch.setattr(m, "healthy", lambda *a, **k: False)
    m.run(str(server))
    assert "응답하지 않습니다" in (server / "data" / "update.log").read_text(encoding="utf-8") and status(server)["deployed_ok"] is False
