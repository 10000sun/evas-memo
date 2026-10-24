"""백업·복구(관리자). 데이터는 DB 파일 하나라서 SQLite 스냅샷을 내려받고, 올린 파일로 덮어쓴다.

복구하기 전에 지금 DB를 `<DB>.before-restore`로 한 부 남긴다(되돌릴 길). 올린 파일은 SQLite 무결성과 필수 표를 확인한 뒤에만 쓰고,
옛 백업이면 db.init()이 빠진 표·열을 채운다. 복구한 관리자 본인은 백업에 없어도 관리자로 남긴다(잠기지 않게).
"""
import os
import sqlite3
import tempfile
from datetime import datetime

from fastapi import Depends, HTTPException, Request
from fastapi.responses import FileResponse
from starlette.background import BackgroundTask

from . import db, ws

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


def register(app, admin):
    @app.get("/api/backup")
    def download(_=Depends(admin)):
        fd, tmp = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        _copy(db.db_path(), tmp)
        return FileResponse(tmp, media_type="application/octet-stream", filename=f"evas-memo-{datetime.now():%Y%m%d-%H%M}.db",
                            background=BackgroundTask(os.remove, tmp))

    @app.post("/api/restore")
    async def restore(request: Request, me=Depends(admin)):
        if int(request.headers.get("content-length") or 0) > MAX:
            raise HTTPException(413, "파일이 너무 큽니다")
        data = await request.body()
        if len(data) > MAX:
            raise HTTPException(413, "파일이 너무 큽니다")
        path = db.db_path()
        fd, tmp = tempfile.mkstemp(suffix=".db", dir=os.path.dirname(path) or ".")
        try:
            with os.fdopen(fd, "wb") as f:
                f.write(data)
            _check(tmp)
            _copy(path, path + ".before-restore")
            await _drop_rooms()  # 열린 편집 방이 복구한 내용을 옛 내용으로 덮어쓰지 않게 저장 없이 내린다
            _copy(tmp, path)
            await _drop_rooms()  # 열린 편집 방이 복구한 내용을 옛 내용으로 덮어쓰지 않게 저장 없이 내린다
            db.init()
            with db.connect() as con:
                con.execute("INSERT INTO users(id,name,role) VALUES(?,?, 'admin') ON CONFLICT(id) DO UPDATE SET role='admin'",
                            (me["id"], me["name"] or me["id"]))
                con.execute("DELETE FROM blocked WHERE id=?", (me["id"],))
        finally:
            os.remove(tmp)
        return {"ok": True}
