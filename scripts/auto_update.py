r"""서버 PC 자동 배포: GitHub의 main에 새 버전이 올라오면 받아서 앱을 다시 켠다.
작업 스케줄러(evas-memo-update)가 5분마다 부른다. 설치: scripts\install-auto-update.bat (관리자 권한, 한 번만).

받는 방법은 자동으로 고른다.
 - git 방식: 레포 폴더가 git 저장소(SourceTree·GitHub Desktop·Git for Windows로 받은 폴더)이고 git.exe를 찾으면 `git pull --ff-only`로 받는다.
   PATH에 없어도 SourceTree·GitHub Desktop이 안에 넣어 둔 git.exe를 찾아 쓴다(못 찾으면 .env에 GIT_EXE=경로). SourceTree 화면과 어긋나지 않는다.
 - zip 방식: git이 없거나 저장소가 아닌 폴더면 GitHub에서 zip을 내려받아 파일을 바꾼다(data·.env는 건드리지 않는다).
순서: 새 버전 확인 -> (패키지 목록이 바뀌었으면 설치) -> DB 사본(backups/pre-update-*.db, 최근 5개) -> 파일 갱신 -> 앱 재시작 -> 켜졌는지 확인.
어느 단계든 실패하면 앱은 그대로 두고 data/update.log·data/update-status.json에 적으며, 다음 주기에 다시 시도한다.
설정(.env, 선택): GIT_EXE, GITHUB_REPO(zip 방식, 기본 10000sun/evas-memo), GITHUB_TOKEN(zip 방식, 비공개 레포일 때만).
shortcut: zip 방식은 레포가 공개라는 전제로 인증 없이 받는다(시간당 60번 제한: 5분 주기는 충분).
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


def find_git():
    """git.exe 경로. PATH에 없어도 SourceTree·GitHub Desktop 내장 git을 찾는다. 없으면 None."""
    cands = [env_value("GIT_EXE"), shutil.which("git")]
    local, pf, pf86 = (os.environ.get(k, "") for k in ("LOCALAPPDATA", "ProgramFiles", "ProgramFiles(x86)"))
    for pat in (os.path.join(local, "Atlassian", "SourceTree", "git_local", "**", "git.exe"),
                os.path.join(local, "GitHubDesktop", "app-*", "resources", "app", "git", "cmd", "git.exe"),
                os.path.join(pf, "Git", "cmd", "git.exe"), os.path.join(pf86, "Git", "cmd", "git.exe")):
        if pat.startswith(os.sep) or ":" in pat:  # 빈 환경변수로 상대 경로가 되는 것은 건너뛴다
            cands += sorted(glob.glob(pat, recursive=True), reverse=True)
    return next((c for c in cands if c and os.path.isfile(c)), None)


GIT = None  # run()에서 정한다


def git(*args):
    r = subprocess.run([GIT, *args], capture_output=True, text=True, encoding="utf-8")
    if r.returncode:
        raise RuntimeError(f"git {' '.join(args)}: {r.stderr.strip()}")
    return r.stdout.strip()


def is_ancestor(a, b):
    return subprocess.run([GIT, "merge-base", "--is-ancestor", a, b], capture_output=True).returncode == 0


def record_version(sha):
    """설치된 버전 파일(data/version.json)을 git HEAD에 맞춘다: 앱이 '실행 중인 버전'을 git 없이도 보여 주게."""
    if (read_json(VERSION) or {}).get("sha") != sha:
        write_json(VERSION, {"sha": sha, "date": git("log", "-1", "--format=%cI", sha)})


def update_git():
    branch = git("rev-parse", "--abbrev-ref", "HEAD")
    if branch != BRANCH:  # 다른 브랜치는 건드리지 않되, 조용히 넘어가면 '돌고는 있는데 안 올라오는' 상태를 알 수 없으니 실패로 알린다
        raise RuntimeError(f"서버 PC가 {BRANCH}가 아닌 '{branch}' 브랜치를 보고 있어 자동 배포를 건너뜁니다(SourceTree에서 {BRANCH} 브랜치로 체크아웃한 뒤 Pull)")
    git("fetch", "origin", BRANCH)
    old, new = git("rev-parse", "HEAD"), git("rev-parse", f"origin/{BRANCH}")
    record_version(old)
    if old == new:
        return
    if not is_ancestor(old, new):
        raise RuntimeError("이 PC의 코드가 main과 갈라졌습니다(PC에서 직접 고치거나 커밋한 것이 있나 확인하세요)")
    log(f"새 버전 {old[:7]} -> {new[:7]}")
    if "requirements.txt" in git("diff", "--name-only", old, new).splitlines():
        fd, path = tempfile.mkstemp(suffix=".txt")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(git("show", f"origin/{BRANCH}:requirements.txt") + "\n")
            install_requirements(path)
        finally:
            os.remove(path)
    snapshot()
    git("pull", "--ff-only", "origin", BRANCH)
    record_version(new)
    restart()
    ok = healthy()
    log("배포 완료: 앱이 켜졌습니다" if ok else "배포했지만 앱이 응답하지 않습니다. 로그를 확인하세요(되돌리기: docs/DEPLOY.md)")
    write_status(deployed_at=now_utc(), deployed_to=new[:7], deployed_ok=ok)


def update():
    update_git() if GIT else update_zip()


def update_zip():
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
    global GIT
    os.chdir(root)
    os.makedirs(DATA, exist_ok=True)
    GIT = find_git() if os.path.isdir(".git") else None
    try:
        update()
        if os.path.exists(FAIL):
            os.remove(FAIL)
        write_status(checked_at=now_utc(), head=((read_json(VERSION) or {}).get("sha") or "")[:7] or None, mode="git" if GIT else "zip", error=None)
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
