"""메모 API. 개인 메모는 소유자만(관리자 포함 누구에게도 안 보임), 공동 메모는 로그인한 누구나 보고 편집자 이상이 고친다.

전율(admin) 메모는 관리자 역할 전원만 보고 고친다. 비관리자에게는 없는 메모와 똑같이 404다(판정은 ws.can_access 하나).
"""
import sqlite3
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pycrdt import Doc
from pydantic import BaseModel, field_validator

from . import activity, db, folders, push, ws
from .auth import current_user, editor

router = APIRouter(prefix="/api/memos")
FIELDS = "id, kind, owner_id, title, category_id, folder_id, body_text, created_name, updated_name, updated_at"


class MemoEdit(BaseModel):
    title: str = ""
    category_id: int | None = None
    folder_id: int | None = None

    @field_validator("title")
    @classmethod
    def _title(cls, v):
        if len(v) > 100:  # 화면 입력칸(maxlength=100)과 같다
            raise ValueError("제목은 100자까지입니다")
        return v


Kind = Literal["personal", "shared", "admin"]


class MemoIn(MemoEdit):
    kind: Kind


class MoveIn(BaseModel):
    to: Kind


# 이동 API가 맡는 전이. 개인 -> 공동은 /share, 공동 -> 개인은 /copy-to-personal(복사)이 그대로 맡는다
MOVES = {("personal", "admin"), ("shared", "admin"), ("admin", "shared"), ("admin", "personal")}


def need_kind(kind, user):
    """이 종류를 못 쓰는 사람(비관리자의 admin)에게는 종류 자체를 드러내지 않는다: 없는 경로와 같은 404."""
    if not ws.can_use_kind(kind, user):
        raise HTTPException(404)


def _get(con, mid, user):
    m = con.execute("SELECT * FROM memos WHERE id=?", (mid,)).fetchone()
    if not m or not ws.can_access(m, user):
        raise HTTPException(404, "메모가 없습니다")  # 남의 개인 메모는 있는지조차 알리지 않는다
    return m


def _check_folder(con, folder_id, kind, user):
    """메모의 폴더는 같은 종류여야 하고, 개인이면 본인 폴더여야 한다. 남의 개인 폴더는 없는 것처럼 404."""
    if folder_id is not None and folders.get_visible(con, folder_id, user)["kind"] != kind:
        raise HTTPException(422, "메모와 폴더의 종류가 다릅니다")


def _out(con, mid):
    return dict(con.execute(f"SELECT {FIELDS} FROM memos WHERE id=?", (mid,)).fetchone())


def _insert(con, user, kind, title, category_id, body_text="", ydoc=None, folder_id=None):
    t = db.now()
    try:
        return con.execute(
            "INSERT INTO memos(kind,owner_id,title,category_id,folder_id,body_text,ydoc,created_by,created_name,"
            "updated_by,updated_name,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (kind, user["id"], title, category_id, folder_id, body_text, ydoc or Doc().get_update(),
             user["id"], user["name"], user["id"], user["name"], t, t)).lastrowid
    except sqlite3.IntegrityError:
        raise HTTPException(400, "없는 분류입니다")


@router.get("")
def list_memos(kind: Kind, category_id: int | None = None, folder_id: str | None = None,
               q: str = "", user=Depends(current_user)):
    need_kind(kind, user)
    sql, args = f"SELECT {FIELDS} FROM memos WHERE kind=?", [kind]
    if kind == "personal":
        sql += " AND owner_id=?"
        args.append(user["id"])
    if category_id is not None:
        sql += " AND category_id=?"
        args.append(category_id)
    if folder_id == "none":  # 폴더 없음. 숫자면 그 폴더 직속 메모만(하위 폴더 메모는 제외)
        sql += " AND folder_id IS NULL"
    elif folder_id is not None:
        if not folder_id.isdecimal():
            raise HTTPException(422, "folder_id는 숫자 또는 none")
        sql += " AND folder_id=?"
        args.append(int(folder_id))
    if q:  # instr: LIKE와 달리 %, _를 글자 그대로 찾는다
        sql += " AND (instr(lower(title), lower(?)) OR instr(lower(body_text), lower(?)))"
        args += [q, q]
    with db.connect() as con:
        return [dict(r) for r in con.execute(sql + " ORDER BY updated_at DESC, id DESC", args)]


@router.post("", status_code=201)
def add_memo(m: MemoIn, bg: BackgroundTasks, user=Depends(editor)):
    need_kind(m.kind, user)
    with db.connect() as con:
        _check_folder(con, m.folder_id, m.kind, user)
        mid = _insert(con, user, m.kind, m.title, m.category_id, folder_id=m.folder_id)
        if m.kind == "shared":  # 개인·전율 메모는 기록·푸시가 없다
            activity.log(con, "add", mid, m.title, user)
            bg.add_task(push.notify, "add", m.title, user)
        return _out(con, mid)


@router.get("/{mid}")
def get_memo(mid: int, user=Depends(current_user)):
    with db.connect() as con:
        _get(con, mid, user)
        return _out(con, mid)


@router.put("/{mid}")
def edit_memo(mid: int, m: MemoEdit, user=Depends(current_user)):
    fields = m.model_dump(exclude_unset=True)  # 보낸 필드만 바꾼다(category_id: null은 분류 해제)
    with db.connect() as con:
        memo = _get(con, mid, user)
        if not ws.can_edit(memo, user):
            raise HTTPException(403, "권한이 없습니다")
        if fields.get("folder_id") is not None:
            _check_folder(con, fields["folder_id"], memo["kind"], user)
        sets = "".join(f"{k}=?, " for k in fields)
        try:
            con.execute(f"UPDATE memos SET {sets}updated_by=?, updated_name=?, updated_at=? WHERE id=?",
                        (*fields.values(), user["id"], user["name"], db.now(), mid))
        except sqlite3.IntegrityError:
            raise HTTPException(400, "없는 분류입니다")
        out = _out(con, mid)
        if memo["kind"] == "shared":
            activity.log(con, "edit", mid, out["title"], user)
        return out


@router.delete("/{mid}", status_code=204)
async def del_memo(mid: int, bg: BackgroundTasks, user=Depends(current_user)):
    # async: 열린 방(이벤트 루프 소유)을 같은 루프에서 내린다
    with db.connect() as con:
        m = _get(con, mid, user)  # 개인 메모는 여기서 이미 소유자만 남는다
        if m["kind"] == "shared" and m["created_by"] != user["id"] and user["role"] != "admin":
            raise HTTPException(403, "작성자와 관리자만 지울 수 있습니다")
        con.execute("DELETE FROM memos WHERE id=?", (mid,))
        if m["kind"] == "shared":
            activity.log(con, "delete", mid, m["title"], user)
            bg.add_task(push.notify, "delete", m["title"], user)
    await ws.rooms.drop(mid)


@router.post("/{mid}/share")
def share_memo(mid: int, bg: BackgroundTasks, user=Depends(editor)):
    """개인 -> 공동 '이동': 같은 행, 같은 Yjs 문서. 종류만 바뀐다."""
    with db.connect() as con:
        m = _get(con, mid, user)
        if m["kind"] != "personal":
            raise HTTPException(409, "개인 메모만 공동으로 옮길 수 있습니다")
        con.execute("UPDATE memos SET kind='shared', folder_id=NULL WHERE id=?", (mid,))
        activity.log(con, "add", mid, m["title"], user)
        bg.add_task(push.notify, "add", m["title"], user)
        return _out(con, mid)


@router.post("/{mid}/copy-to-personal", status_code=201)
async def copy_to_personal(mid: int, user=Depends(editor)):
    """공동 -> 개인 '복사': 호출자 소유의 새 메모. ydoc 바이트를 복사하므로 이후 둘은 서로 무관하다.

    async: 열린 방의 저장(타이머·Yjs 문서)은 이벤트 루프에서만 만진다.
    편집자 이상만: 보기 전용은 새 메모를 만들 수 없으므로 복사로도 못 만든다.
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


@router.post("/{mid}/move")
async def move_memo(mid: int, mv: MoveIn, bg: BackgroundTasks, user=Depends(current_user)):
    """개인·공동 <-> 전율 '이동': 같은 행·같은 Yjs 문서. 종류(전율 -> 개인이면 소유자도)만 바뀌고 폴더는 비운다.

    허용되는 전이는 모두 전율이 끼므로 관리자만 할 수 있다(전율에서: _get이, 전율로: need_kind가 막는다).
    async: 열린 방 저장(이동 전 편집 포함) -> 종류 변경 -> 권한을 잃은 접속자 종료를 이벤트 루프에서 이어서 한다.
    """
    with db.connect() as con:
        m = _get(con, mid, user)
    need_kind(mv.to, user)
    if (m["kind"], mv.to) not in MOVES:
        raise HTTPException(422, "이 메모는 그 종류로 옮길 수 없습니다")
    room = ws.rooms.get(mid)
    if room and not room.save():  # 저장 안 된 편집은 옛 종류일 때의 것이다(공동이었다면 기록도 공동으로 남는다)
        raise HTTPException(503, "저장하지 못했습니다. 잠시 후 다시 시도해 주세요")
    owner = user["id"] if mv.to == "personal" else m["owner_id"]
    with db.connect() as con:
        # 확인한 뒤 다른 요청(스레드)이 먼저 종류를 바꿨으면 옮기지 않는다
        if not con.execute("UPDATE memos SET kind=?, owner_id=?, folder_id=NULL WHERE id=? AND kind=?",
                           (mv.to, owner, mid, m["kind"])).rowcount:
            raise HTTPException(409, "메모가 바뀌었습니다. 다시 열어 주세요")
        out = _out(con, mid)
        if m["kind"] == "shared":  # 공동에서 사라짐: 삭제처럼 기록하되 푸시는 보내지 않는다
            activity.log(con, "delete", mid, out["title"], user)
        if mv.to == "shared":  # 모두에게 새로 보임: 개인 -> 공동 이동(/share)과 같다
            activity.log(con, "add", mid, out["title"], user)
            bg.add_task(push.notify, "add", out["title"], user)
    # 커밋 뒤 await 없이 이어서: 계속 볼 수 있는 접속자는 두고 나머지만 닫는다
    await ws.rooms.revoke(4404, "메모가 옮겨졌습니다", memo_id=mid)
    return out
