"""폴더 API. 개인 폴더는 소유자만(관리자 포함 누구에게도 존재가 안 보임), 공동 폴더는 로그인한 누구나 본다(비공개 공유 제외).
전율(admin) 폴더는 관리자 전원이 보고 만들고 고치고 지운다. 판정은 메모와 같은 ws.can_access 하나.

비공개 공유: 공동 폴더는 공개 범위(전체/선택한 사람)를 가진다. 제한 폴더 안의 모든 것(하위 폴더·메모)은 그 폴더의 목록을 따른다.
목록에 없는 사람에게는 없는 폴더와 같은 404·목록 제외다.

깊이는 폴더 > 하위 폴더까지. 폴더를 지우면 하위 폴더도 지워지고 메모는 folder_id만 비워진다(FK).
"""
import sqlite3
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from . import activity, db, ws
from .auth import current_user, editor

router = APIRouter(prefix="/api/folders")
COLS = ("id", "kind", "parent_id", "name", "created_by", "created_name")
ROW = ", ".join(COLS) + ", owner_id, visibility"
MAX_VIEWERS = 50
# 폴더와 그 아래(하위 폴더) id
SUBTREE = "WITH RECURSIVE sub(id) AS (SELECT ? UNION SELECT f.id FROM folders f JOIN sub ON f.parent_id=sub.id) "


class FolderName(BaseModel):
    name: str

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        v = v.strip()
        if not 1 <= len(v) <= 30:
            raise ValueError("폴더 이름은 1~30자입니다")
        return v


class FolderIn(FolderName):
    kind: Literal["personal", "shared", "admin"]
    parent_id: int | None = None


class ShareIn(BaseModel):
    """공개 범위 변경 본문(메모·폴더 공통). viewers는 제한일 때만 쓰인다(비어도 된다: 만든 사람과 관리자만 봄)."""
    visibility: Literal["all", "restricted"]
    viewers: list[str] = []

    @field_validator("viewers")
    @classmethod
    def _viewers(cls, v):
        v = list(dict.fromkeys(x.strip() for x in v))  # 중복 제거(순서 유지)
        if len(v) > MAX_VIEWERS:
            raise ValueError(f"선택할 수 있는 사람은 {MAX_VIEWERS}명까지입니다")
        if any(not x or len(x) > 64 for x in v):
            raise ValueError("올바르지 않은 사용자 id입니다")
        return v


def pick_viewers(con, s: ShareIn):
    """저장할 사람 id. 제한일 때 members(한 번이라도 접속한 사람)에 없는 id가 있으면 422. 전체 공개면 목록은 버린다."""
    if s.visibility == "all" or not s.viewers:
        return []
    found = {r[0] for r in con.execute(f"SELECT id FROM members WHERE id IN ({','.join('?' * len(s.viewers))})", s.viewers)}
    if found != set(s.viewers):
        raise HTTPException(422, "접속한 적 없는 사용자가 포함되어 있습니다")
    return s.viewers


def set_viewers(con, table, col, item_id, viewers):
    """선택된 사람 목록을 통째로 바꾼다(table·col은 코드 상수만 넘긴다)."""
    con.execute(f"DELETE FROM {table} WHERE {col}=?", (item_id,))
    con.executemany(f"INSERT OR IGNORE INTO {table}({col}, user_id) VALUES(?,?)", [(item_id, v) for v in viewers])


def get_visible(con, fid, user):
    """보이는 폴더만 돌려준다. 없거나 남의 개인 폴더·비관리자의 전율 폴더·목록에 없는 비공개 폴더면 똑같이 404(존재를 알리지 않는다)."""
    f = con.execute("SELECT * FROM folders WHERE id=?", (fid,)).fetchone()
    if not f or not ws.can_access(f, user, con):
        raise HTTPException(404, "폴더가 없습니다")
    return f


def _shape(con, row, user, cache=None):
    return {**{k: row[k] for k in COLS}, **ws.share_info(con, row, user, cache)}


def _out(con, fid, user):
    return _shape(con, con.execute(f"SELECT {ROW} FROM folders WHERE id=?", (fid,)).fetchone(), user)


def _lock(con, fid, user, f):
    """확인한 상태(종류·소유자·공개 범위·상위) 그대로일 때만 쓰기 잠금을 잡고, 그 잠금 안에서 접근을 다시 판정한다.

    잠금을 잡은 뒤에는 다른 쓰기가 끼어들 수 없으므로(commit까지) 확인과 쓰기 사이의 변경(TOCTOU)이 없다.
    """
    if not con.execute("UPDATE folders SET id=id WHERE id=? AND kind=? AND owner_id IS ? AND visibility=? AND parent_id IS ?",
                       (fid, f["kind"], f["owner_id"], f["visibility"], f["parent_id"])).rowcount:
        get_visible(con, fid, user)  # 이제 못 보거나 지워졌으면 404
        raise HTTPException(409, "폴더가 바뀌었습니다. 다시 열어 주세요")
    return get_visible(con, fid, user)


def _check_dup(con, kind, owner_id, parent_id, name, self_id=None):
    # IS: parent_id·owner_id가 NULL일 수 있어 =로는 비교가 안 된다
    if con.execute("SELECT 1 FROM folders WHERE kind=? AND owner_id IS ? AND parent_id IS ? AND name=? AND id IS NOT ?",
                   (kind, owner_id, parent_id, name, self_id)).fetchone():
        raise HTTPException(409, "같은 위치에 같은 이름의 폴더가 있습니다")


def _need_kind(kind, user):
    if not ws.can_use_kind(kind, user):
        raise HTTPException(404)  # 비관리자에게는 전율 종류 자체를 드러내지 않는다


def _need_editor(user):
    if user["role"] not in ("admin", "editor"):
        raise HTTPException(403, "권한이 없습니다")


def _publicity(con, fid):
    """폴더 아래 공동 메모의 {id: (제목, 누구에게나 보이는가)}. 폴더 설정이 바뀌기 전후를 비교해 활동 기록에 쓴다."""
    cache = {}
    rows = con.execute(SUBTREE + f"SELECT {ws.MEMO_ACCESS}, title FROM memos WHERE kind='shared' "
                       "AND folder_id IN (SELECT id FROM sub)", (fid,)).fetchall()
    return {m["id"]: (m["title"], ws.is_public(m, con, cache)) for m in rows}


def _keep_restricted(con, fid):
    """폴더(와 하위)를 지우면 메모의 folder_id가 비어 메모 자신의 설정(기본 '전체')으로 돌아간다. 폴더 제한 덕에 숨겨져 있던
    메모가 그대로 전체 공개로 드러나지 않게, 지우기 전에 폴더의 목록(과 폴더 만든 사람)을 메모 자신의 제한으로 옮겨 둔다."""
    ids = {r[0] for r in con.execute(SUBTREE + "SELECT id FROM sub", (fid,))}
    cache = {}
    for m in con.execute(SUBTREE + f"SELECT {ws.MEMO_ACCESS} FROM memos WHERE kind='shared' "
                         "AND folder_id IN (SELECT id FROM sub)", (fid,)).fetchall():
        r = ws.restrictor(con, m, cache)
        if r and r[0] == "folder_viewers" and r[1] in ids:
            con.execute("UPDATE memos SET visibility='restricted' WHERE id=?", (m["id"],))
            set_viewers(con, "memo_viewers", "memo_id", m["id"],
                        sorted((ws.viewer_ids(con, r, cache) | {r[2]}) - {None}))


@router.get("")
def list_folders(kind: Literal["personal", "shared", "admin"], user=Depends(current_user)):
    _need_kind(kind, user)
    sql, args = f"SELECT {ROW} FROM folders WHERE kind=?", [kind]
    if kind == "personal":
        sql += " AND owner_id=?"
        args.append(user["id"])
    with db.connect() as con:
        cache = {}
        rows = con.execute(sql + " ORDER BY name, id", args).fetchall()
        return [_shape(con, r, user, cache) for r in rows if ws.can_access(r, user, con, cache)]


@router.post("", status_code=201)
def add_folder(f: FolderIn, user=Depends(current_user)):
    _need_kind(f.kind, user)
    if f.kind == "shared":
        _need_editor(user)
    owner = user["id"] if f.kind == "personal" else None
    with db.connect() as con:
        if f.parent_id is not None:
            parent = get_visible(con, f.parent_id, user)
            if parent["kind"] != f.kind:
                raise HTTPException(422, "상위 폴더의 종류가 다릅니다")
            if parent["parent_id"] is not None:
                raise HTTPException(422, "하위 폴더 아래에는 만들 수 없습니다")
        _check_dup(con, f.kind, owner, f.parent_id, f.name)
        try:
            fid = con.execute(
                "INSERT INTO folders(kind,owner_id,parent_id,name,created_by,created_name,created_at) VALUES(?,?,?,?,?,?,?)",
                (f.kind, owner, f.parent_id, f.name, user["id"], user["name"], db.now())).lastrowid
        except sqlite3.IntegrityError:  # 확인 뒤 상위 폴더가 지워짐(외래키)
            raise HTTPException(404, "폴더가 없습니다")
        row = con.execute(f"SELECT {ROW} FROM folders WHERE id=?", (fid,)).fetchone()
        if not ws.can_access(row, user, con):  # 쓰기 잠금 안에서 다시: 확인 뒤 상위 폴더가 제한으로 바뀌어 내가 빠졌다
            raise HTTPException(404, "폴더가 없습니다")
        return _shape(con, row, user)


@router.put("/{fid}")
def rename_folder(fid: int, f: FolderName, user=Depends(current_user)):
    with db.connect() as con:
        cur = get_visible(con, fid, user)  # 남의 개인 폴더는 여기서 404
        if cur["kind"] == "shared":
            _need_editor(user)
        _check_dup(con, cur["kind"], cur["owner_id"], cur["parent_id"], f.name, fid)
        _lock(con, fid, user, cur)
        if not con.execute("UPDATE folders SET name=? WHERE id=?", (f.name, fid)).rowcount:
            raise HTTPException(404, "폴더가 없습니다")
        return _out(con, fid, user)


@router.put("/{fid}/share-with")
async def share_folder(fid: int, s: ShareIn, user=Depends(editor)):
    """공동 폴더의 공개 범위(전체/선택한 사람). 만든 사람과 관리자만. 안의 메모(하위 포함)에 곧바로 적용되고,
    접근을 잃은 접속자는 삭제와 같은 사유(4404)로 닫힌다. async: 닫기를 이벤트 루프에서 커밋 직후 이어서 한다."""
    with db.connect() as con:
        f = get_visible(con, fid, user)
        if f["kind"] != "shared":
            raise HTTPException(409, "공동 폴더만 공개 범위를 정할 수 있습니다")
        if user["role"] != "admin" and f["created_by"] != user["id"]:
            raise HTTPException(403, "만든 사람과 관리자만 바꿀 수 있습니다")
        viewers = pick_viewers(con, s)
        f = _lock(con, fid, user, f)
        r = ws.restrictor(con, f)
        if r and r[1] != fid:  # 제한된 상위 폴더가 있으면 그 목록을 따른다
            raise HTTPException(409, "상위 폴더의 공개 범위를 따릅니다")
        before = _publicity(con, fid)
        if not con.execute("UPDATE folders SET visibility=? WHERE id=? AND visibility=?", (s.visibility, fid, f["visibility"])).rowcount:
            raise HTTPException(409, "폴더가 바뀌었습니다. 다시 열어 주세요")
        set_viewers(con, "folder_viewers", "folder_id", fid, viewers)
        for mid, (title, public) in _publicity(con, fid).items():  # 이 폴더 때문에 숨겨지거나 드러난 메모만 기록
            activity.publicity(con, mid, title, before[mid][1], public, user)
        out = _out(con, fid, user)
    await ws.rooms.revoke(4404, ws.GONE_REASON)  # 지금 DB 기준으로 접근을 잃은 접속자(어느 방이든)만 닫는다
    return out


@router.delete("/{fid}", status_code=204)
def del_folder(fid: int, user=Depends(current_user)):
    with db.connect() as con:
        f = get_visible(con, fid, user)
        if f["kind"] == "shared" and f["created_by"] != user["id"] and user["role"] != "admin":
            raise HTTPException(403, "만든 사람과 관리자만 지울 수 있습니다")
        f = _lock(con, fid, user, f)
        _keep_restricted(con, fid)
        con.execute("DELETE FROM folders WHERE id=?", (fid,))
