"""서버 PC 자동 배포 스크립트(scripts/auto_update.py): 임시 git 저장소로 받기·재시작·실패 처리를 확인한다. 재시작·패키지 설치는 가짜로 바꾼다."""
import importlib.util
import os
import sqlite3
import subprocess
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parent.parent / "scripts" / "auto_update.py"


def sh(cwd, *a):
    return subprocess.run(a, cwd=cwd, check=True, capture_output=True, text=True).stdout.strip()


@pytest.fixture
def env(tmp_path, monkeypatch):
    for k in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{k}_NAME", "t")
        monkeypatch.setenv(f"GIT_{k}_EMAIL", "t@t")
    origin, dev, server = tmp_path / "origin.git", tmp_path / "dev", tmp_path / "server"
    sh(tmp_path, "git", "init", "-q", "--bare", "-b", "main", str(origin))
    sh(tmp_path, "git", "clone", "-q", str(origin), str(dev))
    (dev / "a.txt").write_text("1")
    (dev / "requirements.txt").write_text("fastapi\n")
    sh(dev, "git", "add", "-A")
    sh(dev, "git", "commit", "-q", "-m", "첫 커밋")
    sh(dev, "git", "push", "-q", "origin", "main")
    sh(tmp_path, "git", "clone", "-q", str(origin), str(server))
    (server / "data").mkdir()
    sqlite3.connect(server / "data" / "evas.db").execute("CREATE TABLE t(a)").connection.commit()  # 운영 DB 대역
    m = importlib.util.module_from_spec(importlib.util.spec_from_file_location("auto_update", SCRIPT))
    m.__spec__.loader.exec_module(m)
    calls = []
    monkeypatch.setattr(m, "restart", lambda: calls.append("restart"))
    monkeypatch.setattr(m, "healthy", lambda *a, **k: True)
    monkeypatch.setattr(m, "install_requirements", lambda ref: calls.append("pip"))
    monkeypatch.chdir(tmp_path)  # run()이 알아서 server로 옮긴다
    return m, dev, server, calls


def push(dev, name="a.txt", text="2"):
    (dev / name).write_text(text)
    sh(dev, "git", "add", "-A")
    sh(dev, "git", "commit", "-q", "-m", "변경")
    sh(dev, "git", "push", "-q", "origin", "main")


def backups(server):
    return sorted(p.name for p in (server / "data" / "backups").glob("pre-update-*.db")) if (server / "data" / "backups").exists() else []


def test_nothing_new_does_nothing(env):
    m, dev, server, calls = env
    assert m.run(str(server)) == 0 and calls == [] and backups(server) == []


def test_new_commit_is_pulled_snapshotted_and_restarted(env):
    m, dev, server, calls = env
    push(dev)
    assert m.run(str(server)) == 0
    assert (server / "a.txt").read_text() == "2" and calls == ["restart"] and len(backups(server)) == 1
    assert "배포 완료" in (server / "data" / "update.log").read_text(encoding="utf-8")
    assert m.run(str(server)) == 0 and calls == ["restart"]  # 같은 버전이면 다시 하지 않는다


def test_requirements_change_installs_before_restart(env):
    m, dev, server, calls = env
    push(dev, "requirements.txt", "fastapi\nicalendar\n")
    m.run(str(server))
    assert calls == ["pip", "restart"]


def test_conflicting_local_edit_stops_and_logs_once(env):
    m, dev, server, calls = env
    (server / "a.txt").write_text("서버에서 직접 고침")
    push(dev)
    head = sh(server, "git", "rev-parse", "HEAD")
    assert m.run(str(server)) == 1 and m.run(str(server)) == 1
    assert calls == [] and sh(server, "git", "rev-parse", "HEAD") == head and (server / "a.txt").read_text() == "서버에서 직접 고침"
    assert (server / "data" / "update.log").read_text(encoding="utf-8").count("실패") == 1  # 같은 실패는 한 번만


def test_diverged_server_is_not_overwritten(env):
    m, dev, server, calls = env
    (server / "local.txt").write_text("x")
    sh(server, "git", "add", "-A")
    sh(server, "git", "commit", "-q", "-m", "서버에서 한 커밋")
    push(dev)
    assert m.run(str(server)) == 1 and calls == []
    assert "갈라졌습니다" in (server / "data" / "update.log").read_text(encoding="utf-8")


def test_only_latest_five_snapshots_are_kept(env):
    m, dev, server, calls = env
    d = server / "data" / "backups"
    d.mkdir()
    for i in range(7):
        (d / f"pre-update-2020010{i + 1}-000000.db").write_bytes(b"x")
    (d / "auto-2020-01-01.db").write_bytes(b"x")  # 자동 백업은 건드리지 않는다
    push(dev)
    m.run(str(server))
    kept = backups(server)
    assert len(kept) == 5 and kept[0] == "pre-update-20200104-000000.db" and kept[-1] > "pre-update-2021"
    assert (d / "auto-2020-01-01.db").exists()


def test_other_branch_is_left_alone(env):
    m, dev, server, calls = env
    sh(server, "git", "checkout", "-q", "-b", "work")
    push(dev)
    assert m.run(str(server)) == 0 and calls == [] and (server / "a.txt").read_text() == "1"


def test_unhealthy_app_is_reported(env, monkeypatch):
    m, dev, server, calls = env
    monkeypatch.setattr(m, "healthy", lambda *a, **k: False)
    push(dev)
    m.run(str(server))
    assert "응답하지 않습니다" in (server / "data" / "update.log").read_text(encoding="utf-8")
