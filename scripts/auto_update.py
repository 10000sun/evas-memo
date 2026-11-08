r"""서버 PC 자동 배포: GitHub의 main에 새 버전이 올라오면 내려받아 파일을 바꾸고 앱을 다시 켠다. git이 필요 없다(파이썬만 있으면 된다).
작업 스케줄러(evas-memo-update)가 5분마다 부른다. 설치: scripts\install-auto-update.bat (관리자 권한, 한 번만).

순서: 최신 커밋 확인 -> (새 버전이면) zip 내려받기 -> 패키지 목록이 바뀌었으면 설치 -> DB 사본(backups/pre-update-*.db, 최근 5개)
      -> 파일 교체(data·.env는 건드리지 않는다) -> 앱 재시작 -> 켜졌는지 확인.
어느 단계든 실패하면 앱은 그대로 두고 data/update.log·data/update-status.json에 적으며, 다음 주기에 다시 시도한다.
설정(.env, 선택): GITHUB_REPO(기본 10000sun/evas-memo), GITHUB_TOKEN(비공개 레포일 때만. 읽기 전용 토큰).
shortcut: 레포가 공개라는 전제로 인증 없이 받는다(시간당 60번 제한: 5분 주기는 충분). 비공개로 바꾸면 GITHUB_TOKEN을 넣을 것.
"""
import glob
import hashlib
import io
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
import urllib.request
import zipfile
from datetime import datetime, timezone

DEFAULT_REPO = "10000sun/evas-memo"
APP_TASK = "evas-memo-app"  # 앱을 띄우는 작업 스케줄러 작업 이름(scripts\restart-app.bat과 같다)
DEFAULT_PORT = 8001
BRANCH = "main"
KEEP = 5  # 배포 직전 DB 사본을 몇 개 남길지
DATA = "data"
LOG, FAIL = os.path.join(DATA, "update.log"), os.path.join(DATA, "update.fail")
STATUS = os.path.join(DATA, "update-status.json")  # 관리 화면이 읽는다: 마지막 확인 시각·현재 버전·마지막 배포·오류
VERSION = os.path.join(DATA, "version.json")  # 지금 설치된 버전 {sha, date}. 앱도 이것으로 '실행 중인 버전'을 보여 준다
MANIFEST = os.path.join(DATA, "deployed-files.json")  # 지난 배포가 깐 파일 목록(새 버전에서 없어진 파일을 지우려고)


def now_utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def log(msg):
    line = f"{datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def read_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def write_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False)


def write_status(**fields):
    """상태 파일에 값을 합쳐 쓴다. 관리 화면이 '자동 배포가 돌고 있나'를 보는 근거(변화가 없는 확인도 checked_at을 갱신한다)."""
    cur = read_json(STATUS) or {}
    cur.update(fields)
    write_json(STATUS, cur)


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


def http_get(url, accept=None):
    headers = {"User-Agent": "evas-auto-update"}
    if accept:
        headers["Accept"] = accept
    token = env_value("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"Bearer {token}"
    with urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60) as r:
        return r.read()


def latest():
    """GitHub main의 최신 커밋 {sha, date}."""
    repo = env_value("GITHUB_REPO", DEFAULT_REPO)
    d = json.loads(http_get(f"https://api.github.com/repos/{repo}/commits/{BRANCH}", "application/vnd.github+json"))
    return {"sha": d["sha"], "date": d["commit"]["committer"]["date"]}


def download(sha):
    """그 커밋의 소스 zip(바이트)."""
    return http_get(f"https://api.github.com/repos/{env_value('GITHUB_REPO', DEFAULT_REPO)}/zipball/{sha}")


def skipped(rel):
    """교체하지 않는 파일: 운영 데이터·설정·캐시."""
    parts = rel.replace("\\", "/").split("/")
    return parts[0] in ("data", ".git") or rel == ".env" or "__pycache__" in parts or "node_modules" in parts or rel.endswith(".pyc")


def extract(zbytes, dest):
    """zip을 dest에 푼다(맨 위 폴더 한 겹은 벗긴다). 폴더 밖으로 나가는 경로가 있으면 거부한다."""
    dest = os.path.abspath(dest)
    with zipfile.ZipFile(io.BytesIO(zbytes)) as z:
        top = z.namelist()[0].split("/")[0] + "/"
        for info in z.infolist():
            if info.is_dir() or not info.filename.startswith(top):
                continue
            target = os.path.abspath(os.path.join(dest, info.filename[len(top):]))
            if not target.startswith(dest + os.sep):
                raise RuntimeError(f"zip 안에 이상한 경로가 있습니다: {info.filename}")
            os.makedirs(os.path.dirname(target), exist_ok=True)
            with open(target, "wb") as f:
                f.write(z.read(info))


def sha256(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        return None


def snapshot():
    """배포 직전 DB를 한 부 남긴다(새 버전이 DB를 바꾸다 잘못돼도 되돌릴 수 있게). 최근 KEEP개만 둔다."""
    src = env_value("EVAS_DB", os.path.join(DATA, "evas.db"))
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


def install_requirements(path):
    """새 requirements.txt로 설치한다(실패하면 파일은 바뀌지 않는다)."""
    subprocess.run([sys.executable, "-m", "pip", "install", "-r", path], check=True)


def apply_files(src):
    """src의 파일을 이 폴더로 복사하고, 지난 배포에는 있었는데 새 버전에서 없어진 파일은 지운다."""
    new = []
    for base, _dirs, names in os.walk(src):
        for n in names:
            rel = os.path.relpath(os.path.join(base, n), src).replace("\\", "/")
            if skipped(rel):
                continue
            os.makedirs(os.path.dirname(rel) or ".", exist_ok=True)
            shutil.copyfile(os.path.join(base, n), rel)
            new.append(rel)
    for rel in set(read_json(MANIFEST) or []) - set(new):
        if not skipped(rel) and os.path.isfile(rel):
            os.remove(rel)
    write_json(MANIFEST, sorted(new))


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
    new, cur = latest(), read_json(VERSION)
    if cur and cur.get("sha") == new["sha"]:
        return
    log(f"새 버전 {(cur or {}).get('sha', '알 수 없음')[:7]} -> {new['sha'][:7]}")
    zbytes = download(new["sha"])
    with tempfile.TemporaryDirectory() as tmp:
        extract(zbytes, tmp)
        req = "requirements.txt"
        if sha256(os.path.join(tmp, req)) != sha256(req):
            install_requirements(os.path.join(tmp, req))
        snapshot()
        apply_files(tmp)
    write_json(VERSION, new)
    restart()
    ok = healthy()
    log("배포 완료: 앱이 켜졌습니다" if ok else "배포했지만 앱이 응답하지 않습니다. 로그를 확인하세요(되돌리기: docs/DEPLOY.md)")
    write_status(deployed_at=now_utc(), deployed_to=new["sha"][:7], deployed_ok=ok)


def run(root):
    os.chdir(root)
    os.makedirs(DATA, exist_ok=True)
    try:
        update()
        if os.path.exists(FAIL):
            os.remove(FAIL)
        write_status(checked_at=now_utc(), head=((read_json(VERSION) or {}).get("sha") or "")[:7] or None, error=None)
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
