r"""서버 PC 자동 배포: main에 새 커밋이 올라오면 받아서 앱을 다시 켠다.
작업 스케줄러(evas-memo-update)가 5분마다 부른다. 설치: scripts\install-auto-update.bat (관리자 권한, 한 번만).

순서: 새 커밋 확인 -> 패키지 목록이 바뀌었으면 설치 -> DB 사본(backups/pre-update-*.db, 최근 5개) -> git pull --ff-only -> 앱 재시작 -> 켜졌는지 확인.
어느 단계든 실패하면 앱은 그대로 두고 data/update.log에 적으며, 다음 주기에 다시 시도한다.
전제: 서버 PC에서는 코드를 직접 고치지 않는다(고친 파일 때문에 pull이 안 되면 멈추고 기록한다).
"""
import glob
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import datetime, timezone

APP_TASK = "evas-memo-app"  # 앱을 띄우는 작업 스케줄러 작업 이름(scripts\restart-app.bat과 같다)
DEFAULT_PORT = 8001
BRANCH = "main"
KEEP = 5  # 배포 직전 DB 사본을 몇 개 남길지
LOG, FAIL = os.path.join("data", "update.log"), os.path.join("data", "update.fail")
STATUS = os.path.join("data", "update-status.json")  # 관리 화면이 읽는다: 마지막 확인 시각·현재 버전·마지막 배포·오류


def log(msg):
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def write_status(**fields):
    """상태 파일에 값을 합쳐 쓴다. 관리 화면이 '자동 배포가 돌고 있나'를 보는 근거(변화가 없는 확인도 checked_at을 갱신한다)."""
    try:
        with open(STATUS, encoding="utf-8") as f:
            cur = json.load(f)
    except (OSError, ValueError):
        cur = {}
    cur.update(fields)
    with open(STATUS, "w", encoding="utf-8") as f:
        json.dump(cur, f, ensure_ascii=False)


def now_utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def git(*args):
    r = subprocess.run(["git", *args], capture_output=True, text=True, encoding="utf-8")
    if r.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout.strip()


def is_ancestor(a, b):
    return subprocess.run(["git", "merge-base", "--is-ancestor", a, b], capture_output=True).returncode == 0


def env_value(name, default=None):
    """.env의 NAME=값(없으면 환경변수, 그것도 없으면 default). 앱이 읽는 값과 같은 곳에서 읽는다."""
    try:
        with open(".env", encoding="utf-8-sig") as f:
            for line in f:
                k, _, v = line.strip().partition("=")
                if k == name:
                    return v.strip().strip("\"'")
    except OSError:
        pass
    return os.environ.get(name, default)


def snapshot():
    """배포 직전 DB를 한 부 남긴다(새 버전이 DB를 바꾸다 잘못돼도 되돌릴 수 있게). 최근 KEEP개만 둔다."""
    src = env_value("EVAS_DB", os.path.join("data", "evas.db"))
    if not os.path.exists(src):
        return
    d = env_value("EVAS_BACKUP_DIR") or os.path.join(os.path.dirname(src) or ".", "backups")
    os.makedirs(d, exist_ok=True)
    dst = os.path.join(d, f"pre-update-{datetime.now():%Y%m%d-%H%M%S}.db")
    a, b = sqlite3.connect(src, timeout=10), sqlite3.connect(dst)
    try:
        a.backup(b)
    finally:
        a.close()
        b.close()
    for old in sorted(glob.glob(os.path.join(d, "pre-update-*.db")))[:-KEEP]:
        os.remove(old)


def install_requirements(ref):
    """받기 전에 새 requirements.txt로 설치해 둔다(설치가 실패하면 코드는 바뀌지 않는다)."""
    fd, path = tempfile.mkstemp(suffix=".txt")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(git("show", f"{ref}:requirements.txt") + "\n")
        subprocess.run([sys.executable, "-m", "pip", "install", "-r", path], check=True)
    finally:
        os.remove(path)


def restart():
    subprocess.run(["schtasks", "/End", "/TN", APP_TASK], capture_output=True)
    time.sleep(3)
    subprocess.run(["schtasks", "/Run", "/TN", APP_TASK], check=True, capture_output=True)


def healthy(timeout=60):
    """앱이 응답할 때까지 기다린다. 못 켜지면 False."""
    url = f"http://127.0.0.1:{env_value('EVAS_PORT', str(DEFAULT_PORT))}/changes.json"
    end = time.time() + timeout
    while time.time() < end:
        try:
            urllib.request.urlopen(url, timeout=3).close()
            return True
        except Exception:
            time.sleep(2)
    return False


def update():
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    if branch != BRANCH:  # 다른 브랜치는 건드리지 않되, 조용히 넘어가면 '돌고는 있는데 안 올라오는' 상태를 알 수 없으니 실패로 알린다
        raise RuntimeError(f"서버 PC가 {BRANCH}가 아닌 '{branch}' 브랜치를 보고 있어 자동 배포를 건너뜁니다(레포 폴더에서 `git checkout {BRANCH}` 후 `git pull`)")
    git("fetch", "origin", BRANCH)
    old, new = git("rev-parse", "HEAD"), git("rev-parse", f"origin/{BRANCH}")
    if old == new:
        return
    if not is_ancestor(old, new):
        raise RuntimeError("이 PC의 코드가 main과 갈라졌습니다(PC에서 직접 고치거나 커밋한 것이 있나 확인하세요)")
    log(f"새 버전 {old[:7]} -> {new[:7]}")
    if "requirements.txt" in git("diff", "--name-only", old, new).splitlines():
        install_requirements(f"origin/{BRANCH}")
    snapshot()
    git("pull", "--ff-only", "origin", BRANCH)
    restart()
    ok = healthy()
    log("배포 완료: 앱이 켜졌습니다" if ok else "배포했지만 앱이 응답하지 않습니다. 로그를 확인하세요(되돌리기: docs/DEPLOY.md)")
    write_status(deployed_at=now_utc(), deployed_to=new[:7], deployed_ok=ok)


def run(root):
    os.chdir(root)
    os.makedirs("data", exist_ok=True)
    try:
        update()
        if os.path.exists(FAIL):
            os.remove(FAIL)
        write_status(checked_at=now_utc(), head=git("rev-parse", "--short", "HEAD"), error=None)
        return 0
    except Exception as e:
        msg = f"실패(앱은 그대로 둡니다): {e}"
        try:
            write_status(checked_at=now_utc(), error=str(e))
        except Exception:
            pass
        if not (os.path.exists(FAIL) and open(FAIL, encoding="utf-8").read() == msg):  # 같은 실패는 한 번만 적는다
            log(msg)
            with open(FAIL, "w", encoding="utf-8") as f:
                f.write(msg)
        return 1


if __name__ == "__main__":
    sys.exit(run(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
