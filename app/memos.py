"""메모 API. 개인 메모는 소유자만(관리자 포함 누구에게도 안 보임), 공동 메모는 로그인한 누구나 보고 편집자 이상이 고친다."""
import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pycrdt import Doc
from pydantic import BaseModel

from . import db, ws
from .auth import current_user, editor

router = APIRouter(prefix="/api/memos")
FIELDS = "id, kind, owner_id, title, category_id, body_text, created_name, updated_name, updated_at"


class MemoIn(BaseModel):
    kind: Literal["personal", "shared"]
    title: str = ""
    category_id: int | None = None


class MemoEdit(BaseModel):
    title: str = ""
    category_id: int | None = None


def _get(con, mid, user):
    m = con.execute("SELECT * FROM memos WHERE id=?", (mid,)).fetchone()
    if not m or not ws.can_access(m, user):
        raise HTTPException(404, "메모가 없습니다")  # 남의 개인 메모는 있는지조차 알리지 않는다
    return m


def _out(con, mid):
    return dict(con.execute(f"SELECT {FIELDS} FROM memos WHERE id=?", (mid,)).fetchone())


def _insert(con, user, kind, title, category_id, body_text="", ydoc=None):
    t = db.now()
    try:
        return con.execute(
            "INSERT INTO memos(kind,owner_id,title,category_id,body_text,ydoc,created_by,created_name,"
            "updated_by,updated_name,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
            (kind, user["id"], title, category_id, body_text, ydoc or Doc().get_update(),
             user["id"], user["name"], user["id"], user["name"], t, t)).lastrowid
    except sqlite3.IntegrityError:
        raise HTTPException(400, "없는 분류입니다")


@router.get("")
def list_memos(kind: Literal["personal", "shared"], category_id: int | None = None, q: str = "",
               user=Depends(current_user)):
    sql, args = f"SELECT {FIELDS} FROM memos WHERE kind=?", [kind]
    if kind == "personal":
        sql += " AND owner_id=?"
        args.append(user["id"])
    if category_id is not None:
        sql += " AND category_id=?"
        args.append(category_id)
    if q:  # instr: LIKE와 달리 %, _를 글자 그대로 찾는다
        sql += " AND (instr(lower(title), lower(?)) OR instr(lower(body_text), lower(?)))"
        args += [q, q]
    with db.connect() as con:
        return [dict(r) for r in con.execute(sql + " ORDER BY updated_at DESC, id DESC", args)]


@router.post("", status_code=201)
def add_memo(m: MemoIn, user=Depends(editor)):
    with db.connect() as con:
        return _out(con, _insert(con, user, m.kind, m.title, m.category_id))


@router.get("/{mid}")
def get_memo(mid: int, user=Depends(current_user)):
    with db.connect() as con:
        _get(con, mid, user)
        return _out(con, mid)


@router.put("/{mid}")
def edit_memo(mid: int, m: MemoEdit, user=Depends(current_user)):
    fields = m.model_dump(exclude_unset=True)  # 보낸 필드만 바꾼다(category_id: null은 분류 해제)
    with db.connect() as con:
        if not ws.can_edit(_get(con, mid, user), user):
            raise HTTPException(403, "권한이 없습니다")
        sets = "".join(f"{k}=?, " for k in fields)
        try:
            con.execute(f"UPDATE memos SET {sets}updated_by=?, updated_name=?, updated_at=? WHERE id=?",
                        (*fields.values(), user["id"], user["name"], db.now(), mid))
        except sqlite3.IntegrityError:
            raise HTTPException(400, "없는 분류입니다")
        return _out(con, mid)


@router.delete("/{mid}", status_code=204)
async def del_memo(mid: int, user=Depends(current_user)):
    # async: 열린 방(이벤트 루프 소유)을 같은 루프에서 내린다
    with db.connect() as con:
        m = _get(con, mid, user)  # 개인 메모는 여기서 이미 소유자만 남는다
        if m["kind"] == "shared" and m["created_by"] != user["id"] and user["role"] != "admin":
            raise HTTPException(403, "작성자와 관리자만 지울 수 있습니다")
        con.execute("DELETE FROM memos WHERE id=?", (mid,))
    await ws.rooms.drop(mid)


@router.post("/{mid}/share")
def share_memo(mid: int, user=Depends(editor)):
    """개인 -> 공동 '이동': 같은 행, 같은 Yjs 문서. 종류만 바뀐다."""
    with db.connect() as con:
        if _get(con, mid, user)["kind"] != "personal":
            raise HTTPException(409, "이미 공동 메모입니다")
        con.execute("UPDATE memos SET kind='shared' WHERE id=?", (mid,))
        return _out(con, mid)


@router.post("/{mid}/copy-to-personal", status_code=201)
async def copy_to_personal(mid: int, user=Depends(current_user)):
    """공동 -> 개인 '복사': 호출자 소유의 새 메모. ydoc 바이트를 복사하므로 이후 둘은 서로 무관하다.

    async: 열린 방의 저장(타이머·Yjs 문서)은 이벤트 루프에서만 만진다.
    """
    with db.connect() as con:
        if _get(con, mid, user)["kind"] != "shared":
            raise HTTPException(409, "공동 메모만 개인으로 복사할 수 있습니다")
    room = ws.rooms.get(mid)
    if room:
        room.save()  # 열려 있는 방의 아직 저장 안 된 편집까지 복사한다
    with db.connect() as con:
        m = con.execute("SELECT * FROM memos WHERE id=?", (mid,)).fetchone()
        return _out(con, _insert(con, user, "personal", m["title"], m["category_id"], m["body_text"], m["ydoc"]))
