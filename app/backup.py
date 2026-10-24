"""백업·복구(관리자). 데이터는 DB 파일 하나라서 SQLite 스냅샷을 내려받고, 올린 파일로 덮어쓴다.

하루 한 번 자동 백업(`<DB 폴더>/backups/auto-날짜.db`)도 만들고 최근 7개만 남긴다(넘으면 오래된 것부터 지운다).
복구하기 전에 지금 DB를 `<DB>.before-restore`로 한 부 남긴다(되돌릴 길). 올린 파일은 SQLite 무결성과 필수 표를 확인한 뒤에만 쓰고,
옛 백업이면 db.init()이 빠진 표·열을 채운다. 복구한 관리자 본인은 백업에 없어도 관리자로 남긴다(잠기지 않게).
"""
import asyncio
import glob
import logging
import os
import re
import sqlite3
import tempfile
from contextlib import asynccontextmanager
from datetime import date, datetime

from fastapi import Depends, HTTPException, Request
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from . import db, ws

log = logging.getLogger(__name__)
KEEP = 7
AUTO = re.compile(r"^auto-\d{4}-\d{2}-\d{2}\.db$")
MAX = 200 * 1024 * 1024  # shortcut: 요청 본문을 통째로 메모리에 읽는다(팀 규모), DB가 이보다 커지면 스트리밍으로
NEED = {"memos", "categories", "users"}


def _copy(src_path, dst_path):
    src, dst = sqlite3.connect(src_path, timeout=10), sqlite3.connect(dst_path, timeout=10)
    try:
        src.backup(dst)  # 쓰는 중에도 일관된 스냅샷
    finally:
        src.close()
        dst.close()


def _check(path):
    """올린 파일이 쓸 수 있는 에바스 DB인지. 아니면 422."""
    bad = HTTPException(422, "에바스 메모 백업 파일이 아닙니다")
    try:
        con = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
        try:
            if con.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                raise HTTPException(422, "백업 파일이 손상되었습니다")
            tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        finally:
            con.close()
    except sqlite3.DatabaseError:
        raise bad
    if not NEED <= tables:
        raise bad


async def _drop_rooms():
    for name in list(ws.rooms.server.rooms):
        await ws.rooms.drop(name, 4404, "백업에서 복구되었습니다")


def backup_dir():
    return os.environ.get("EVAS_BACKUP_DIR") or os.path.join(os.path.dirname(db.db_path()) or ".", "backups")


def run_daily():
    """오늘 자동 백업이 없으면 만들고, 최근 KEEP개만 남긴다. 몇 번 불러도 같은 결과다."""
    d = backup_dir()
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, f"auto-{date.today():%Y-%m-%d}.db")
    if not os.path.exists(path):
        _copy(db.db_path(), path + ".tmp")
        os.replace(path + ".tmp", path)  # 만드는 중인 파일이 백업 목록에 보이지 않게
    for old in _autos()[KEEP:]:
        os.remove(os.path.join(d, old))


def _autos():
    """자동 백업 파일 이름, 최신 순. 이름에 날짜가 있어 이름순이 곧 날짜순이다."""
    return sorted((n for n in os.listdir(backup_dir()) if AUTO.match(n)), reverse=True) if os.path.isdir(backup_dir()) else []


@asynccontextmanager
async def daily(_app=None):
    """앱이 떠 있는 동안 한 시간마다 확인한다(재시작해도 그날 것이 없으면 바로 만든다). shortcut: 정각 예약이 아니라 점검 주기, 정확한 시각이 필요하면 cron으로."""
    async def loop():
        while True:
            try:
                await asyncio.to_thread(run_daily)
            except Exception:
                log.exception("자동 백업 실패(한 시간 뒤 다시 시도)")
            await asyncio.sleep(3600)
    task = asyncio.create_task(loop())
    try:
        yield
    finally:
        task.cancel()


def register(app, admin):
    @app.get("/api/backup")
    def download(_=Depends(admin)):
        fd, tmp = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        _copy(db.db_path(), tmp)
        return FileResponse(tmp, media_type="application/octet-stream", filename=f"evas-memo-{datetime.now():%Y%m%d-%H%M}.db",
                            background=BackgroundTask(os.remove, tmp))

    async def restore_from(src, me):
        path = db.db_path()
        _check(src)
        _copy(path, path + ".before-restore")
        await _drop_rooms()  # 열린 편집 방이 복구한 내용을 옛 내용으로 덮어쓰지 않게 저장 없이 내린다
        _copy(src, path)
        await _drop_rooms()  # 열린 편집 방이 복구한 내용을 옛 내용으로 덮어쓰지 않게 저장 없이 내린다
        db.init()
        with db.connect() as con:
            con.execute("INSERT INTO users(id,name,role) VALUES(?,?, 'admin') ON CONFLICT(id) DO UPDATE SET role='admin'",
                        (me["id"], me["name"] or me["id"]))
            con.execute("DELETE FROM blocked WHERE id=?", (me["id"],))

    def auto_path(name):
        p = os.path.join(backup_dir(), name)
        if not AUTO.match(name) or not os.path.exists(p):
            raise HTTPException(404, "백업이 없습니다")
        return p

    @app.get("/api/backups")
    def list_backups(_=Depends(admin)):
        return [{"name": n, "size": os.path.getsize(os.path.join(backup_dir(), n))} for n in _autos()]

    @app.get("/api/backups/{name}")
    def download_auto(name: str, _=Depends(admin)):
        return FileResponse(auto_path(name), media_type="application/octet-stream", filename=name)

    @app.post("/api/backups/{name}/restore")
    async def restore_auto(name: str, me=Depends(admin)):
        await restore_from(auto_path(name), me)
        return {"ok": True}

    @app.post("/api/restore")
    async def restore(request: Request, me=Depends(admin)):
        if int(request.headers.get("content-length") or 0) > MAX:
            raise HTTPException(413, "파일이 너무 큽니다")
        data = await request.body()
        if len(data) > MAX:
            raise HTTPException(413, "파일이 너무 큽니다")
        fd, tmp = tempfile.mkstemp(suffix=".db", dir=os.path.dirname(db.db_path()) or ".")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            await restore_from(tmp, me)
        finally:
            os.remove(tmp)
        return {"ok": True}
