"""폴더 API. 개인 폴더는 소유자만(관리자 포함 누구에게도 존재가 안 보임), 공동 폴더는 로그인한 누구나 본다.
전율(admin) 폴더는 관리자 전원이 보고 만들고 고치고 지운다. 판정은 메모와 같은 ws.can_access 하나.

깊이는 폴더 > 하위 폴더까지. 폴더를 지우면 하위 폴더도 지워지고 메모는 folder_id만 비워진다(FK).
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, field_validator

from . import db, ws
from .auth import current_user

router = APIRouter(prefix="/api/folders")
FIELDS = "id, kind, parent_id, name, created_by, created_name"


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


def get_visible(con, fid, user):
    """보이는 폴더만 돌려준다. 없거나 남의 개인 폴더·비관리자의 전율 폴더면 똑같이 404(존재를 알리지 않는다)."""
    f = con.execute("SELECT * FROM folders WHERE id=?", (fid,)).fetchone()
    if not f or not ws.can_access(f, user):
        raise HTTPException(404, "폴더가 없습니다")
    return f


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


@router.get("")
def list_folders(kind: Literal["personal", "shared", "admin"], user=Depends(current_user)):
    _need_kind(kind, user)
    sql, args = f"SELECT {FIELDS} FROM folders WHERE kind=?", [kind]
    if kind == "personal":
        sql += " AND owner_id=?"
        args.append(user["id"])
    with db.connect() as con:
        return [dict(r) for r in con.execute(sql + " ORDER BY name, id", args)]


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
        fid = con.execute(
            "INSERT INTO folders(kind,owner_id,parent_id,name,created_by,created_name,created_at) VALUES(?,?,?,?,?,?,?)",
            (f.kind, owner, f.parent_id, f.name, user["id"], user["name"], db.now())).lastrowid
        return dict(con.execute(f"SELECT {FIELDS} FROM folders WHERE id=?", (fid,)).fetchone())


@router.put("/{fid}")
def rename_folder(fid: int, f: FolderName, user=Depends(current_user)):
    with db.connect() as con:
        cur = get_visible(con, fid, user)  # 남의 개인 폴더는 여기서 404
        if cur["kind"] == "shared":
            _need_editor(user)
        _check_dup(con, cur["kind"], cur["owner_id"], cur["parent_id"], f.name, fid)
        con.execute("UPDATE folders SET name=? WHERE id=?", (f.name, fid))
        return dict(con.execute(f"SELECT {FIELDS} FROM folders WHERE id=?", (fid,)).fetchone())


@router.delete("/{fid}", status_code=204)
def del_folder(fid: int, user=Depends(current_user)):
    with db.connect() as con:
        f = get_visible(con, fid, user)
        if f["kind"] == "shared" and f["created_by"] != user["id"] and user["role"] != "admin":
            raise HTTPException(403, "만든 사람과 관리자만 지울 수 있습니다")
        con.execute("DELETE FROM folders WHERE id=?", (fid,))
