"""차단: 디스코드 계정과 그 사람이 쓴 기기(쿠키)를 함께 막는다. 로그인·API·실시간 편집이 모두 거절된다.

권한(users)은 그대로 둬서 해제하면 이전 권한으로 돌아온다. 캘린더에도 같은 차단을 알린다(usersync와 같은 방식).
캘린더가 받으면 그쪽에서 이 사람이 쓴 기기를 막는다(기기 쿠키는 앱마다 따로 기록한다).
"""
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from . import db, links, usersync, ws

BLOCKED = (4405, "차단되었습니다")  # 4000번대: 화면은 '볼 권한이 없습니다'로 닫는다


class NameIn(BaseModel):
    name: str = Field(min_length=1, max_length=100)


async def _add(uid, name):
    with db.connect() as con:
        row = con.execute("SELECT role FROM users WHERE id=?", (uid,)).fetchone()
        if row and row["role"] == "admin":
            raise HTTPException(409, "관리자는 차단할 수 없습니다. 먼저 권한을 내려 주세요")
        con.execute("INSERT INTO blocked(id,name) VALUES(?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name", (uid, name))
        con.execute("INSERT OR IGNORE INTO blocked_devices SELECT device FROM devices WHERE user_id=?", (uid,))
        con.execute("DELETE FROM push_subs WHERE user_id=?", (uid,))  # 알림도 끊는다
    await _kick(uid)


async def _kick(uid):
    """열려 있는 실시간 편집 연결을 닫는다(allowed()가 차단을 보고 거절한다)."""
    await ws.rooms.revoke(*BLOCKED, user_id=uid)


def _remove(uid):
    with db.connect() as con:
        con.execute("DELETE FROM blocked_devices WHERE device IN (SELECT device FROM devices WHERE user_id=?)", (uid,))
        con.execute("DELETE FROM blocked WHERE id=?", (uid,))


def register(app, admin):
    r = APIRouter()

    @r.get("/api/blocked")
    def list_blocked(_=Depends(admin)):
        with db.connect() as con:
            return [dict(x) for x in con.execute("SELECT id, name FROM blocked ORDER BY name")]

    @r.put("/api/blocked/{uid}")
    async def block(uid: str, _=Depends(admin)):
        with db.connect() as con:
            row = con.execute("SELECT name FROM members WHERE id=? UNION ALL SELECT name FROM users WHERE id=?", (uid, uid)).fetchone()
        name = row["name"] if row else uid
        await _add(uid, name)
        return {"id": uid, "name": name, "synced": await usersync.push_async("PUT", uid, {"name": name}, "blocked")}

    @r.delete("/api/blocked/{uid}")
    async def unblock(uid: str, _=Depends(admin)):
        _remove(uid)  # 이미 풀려 있어도 성공: 캘린더에 못 알렸을 때 다시 눌러 맞출 수 있게
        return {"id": uid, "synced": await usersync.push_async("DELETE", uid, None, "blocked")}

    @r.put("/internal/sync/blocked/{uid}", status_code=204)
    async def apply_block(uid: str, s: NameIn, _=Depends(links.need_key)):
        await _add(uid, s.name)

    @r.delete("/internal/sync/blocked/{uid}", status_code=204)
    async def apply_unblock(uid: str, _=Depends(links.need_key)):
        _remove(uid)

    app.include_router(r)
