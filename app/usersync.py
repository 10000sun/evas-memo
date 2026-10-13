"""관리자·편집자 권한을 메모와 캘린더가 같게 맞춘다. 서버끼리만(X-Link-Key) 주고받는다.

- 이 앱에서 권한을 바꾸면(PUT/DELETE /api/users) 상대 앱에 같은 변경을 최선 노력으로 알린다(실패해도 이 앱의 변경은 그대로).
- 상대 앱이 보내는 변경은 /internal/sync/users/{id}로 받아 적용만 한다(다시 상대에게 되돌려 보내지 않는다).
- 처음 맞출 때는 관리 화면의 '상대 앱에 적용'(POST /api/users/sync)으로 이 앱의 목록을 한 번에 보낸다.
키가 새면 남이 관리자를 만들 수 있으니 LINK_API_KEY는 두 서버에서만 쓴다.
"""
import asyncio
import logging
from urllib.parse import quote

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from . import db, links, ws

log = logging.getLogger(__name__)
router = APIRouter()
LOST_ADMIN = (4403, "관리자 권한이 없어졌습니다")


class SyncIn(BaseModel):
    name: str
    role: str

    @field_validator("role")
    @classmethod
    def _role(cls, v):
        if v not in ("admin", "editor"):
            raise ValueError("role은 admin 또는 editor")
        return v

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        v = v.strip()
        if not v or len(v) > 100:
            raise ValueError("이름이 비었거나 너무 깁니다")
        return v


def _peer(path):
    return links.calendar_internal_url() + path


def push(method, uid, body=None):
    """상대 앱에 같은 변경을 알린다. None: 연동이 꺼짐(키 없음), True: 반영됨, False: 실패(로그만 남긴다). 동기 호출이라 스레드에서 부른다."""
    key = links.link_key()
    if not key:
        return None
    try:
        with httpx.Client(timeout=3, trust_env=False) as h:
            r = h.request(method, _peer("/internal/sync/users/" + quote(uid, safe="")), json=body, headers={"X-Link-Key": key})
        if r.status_code in (200, 204):
            return True
        log.warning("권한 동기화 거절(%s): %s %s", r.status_code, method, uid)
    except Exception:
        log.warning("권한 동기화 실패: %s %s", method, uid, exc_info=True)
    return False


async def push_async(method, uid, body=None):
    return await asyncio.to_thread(push, method, uid, body)


def _admins(con):
    return con.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0]


@router.put("/internal/sync/users/{uid}", status_code=204)
async def apply_user(uid: str, s: SyncIn, _=Depends(links.need_key)):
    """상대 앱이 알려 온 권한을 그대로 적용한다. 마지막 관리자를 내리는 변경은 이 앱의 규칙대로 거절한다(409)."""
    if not uid.strip() or len(uid) > 64:
        raise HTTPException(422, "사용자 ID가 올바르지 않습니다")
    with db.connect() as con:
        row = con.execute("SELECT role FROM users WHERE id=?", (uid,)).fetchone()
        if row and row["role"] == "admin" and s.role != "admin" and _admins(con) == 1:
            raise HTTPException(409, "마지막 관리자는 강등할 수 없습니다")
        con.execute("INSERT INTO users(id,name,role) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET name=excluded.name, role=excluded.role",
                    (uid, s.name, s.role))
    if s.role != "admin":
        await ws.rooms.revoke(*LOST_ADMIN, user_id=uid)


@router.delete("/internal/sync/users/{uid}", status_code=204)
async def remove_user(uid: str, _=Depends(links.need_key)):
    with db.connect() as con:
        row = con.execute("SELECT role FROM users WHERE id=?", (uid,)).fetchone()
        if not row:
            return  # 이미 없으면 같은 결과
        if row["role"] == "admin" and _admins(con) == 1:
            raise HTTPException(409, "마지막 관리자는 지울 수 없습니다")
        con.execute("DELETE FROM users WHERE id=?", (uid,))
    await ws.rooms.revoke(*LOST_ADMIN, user_id=uid)


def register(app, admin):
    app.include_router(router)

    @app.post("/api/users/sync")
    async def sync_all(_=Depends(admin)):
        """이 앱의 사용자 권한 목록을 상대 앱에 적용한다(상대 앱에만 있는 사람은 그대로 둔다)."""
        if not links.link_key():
            raise HTTPException(404)
        with db.connect() as con:
            users = [dict(r) for r in con.execute("SELECT id, name, role FROM users ORDER BY id")]
        ok = failed = 0
        for u in users:
            if await push_async("PUT", u["id"], {"name": u["name"], "role": u["role"]}):
                ok += 1
            else:
                failed += 1
        return {"ok": ok, "failed": failed}
