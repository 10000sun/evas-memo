"""메모 API. 개인 메모는 소유자만(관리자 포함 누구에게도 안 보임), 공동 메모는 로그인한 누구나 보고 편집자 이상이 고친다.

전율(admin) 메모는 관리자 역할 전원만 보고 고친다. 비관리자에게는 없는 메모와 똑같이 404다(판정은 ws.can_access 하나).
비공개 공유: 공동 메모는 공개 범위(전체/선택한 사람)를 가진다. 목록에 없는 사람(관리자·만든 사람 제외)에게도 똑같이 404다.
"""
import sqlite3
from typing import Literal

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pycrdt import Doc
from pydantic import BaseModel, field_validator

from . import activity, db, folders, push, ws
from .auth import current_user, editor

router = APIRouter(prefix="/api/memos")
COLS = ("id", "kind", "owner_id", "title", "category_id", "folder_id", "body_text", "created_name", "updated_name", "updated_at")
FIELDS = ", ".join(COLS)
ROW = FIELDS + ", created_by, visibility"  # 접근 판정(ws.can_access)과 응답(공개 범위)에 필요한 열까지


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
    if not m or not ws.can_access(m, user, con):
        raise HTTPException(404, "메모가 없습니다")  # 남의 개인 메모·목록에 없는 비공개 메모는 있는지조차 알리지 않는다
    return m


# 쓰기는 _get으로 확인한 종류·소유자·공개 범위·폴더가 그대로일 때만 한다: 그 사이 다른 요청(스레드)이 이동·공유했으면 0행
SAME = " AND kind=? AND owner_id IS ? AND visibility=? AND folder_id IS ?"


def _same(m):
    return m["kind"], m["owner_id"], m["visibility"], m["folder_id"]


def _changed(con, mid, user):
    """쓰기가 0행(확인 뒤 메모가 바뀜): 이제 못 보면 없는 메모와 같은 404, 아직 보이면 409."""
    _get(con, mid, user)
    raise HTTPException(409, "메모가 바뀌었습니다. 다시 열어 주세요")


def _lock(con, mid, user, m):
    """확인한 상태(SAME) 그대로일 때만 쓰기 잠금을 잡고, 그 잠금 안에서 접근을 다시 판정해 새 행을 돌려준다.

    폴더·선택한 사람 목록처럼 이 행 밖의 변경도 이 시점 이후에는 커밋까지 끼어들 수 없다: 확인 뒤 접근을 잃었으면 404.
    """
    if not con.execute(f"UPDATE memos SET id=id WHERE id=?{SAME}", (mid, *_same(m))).rowcount:
        _changed(con, mid, user)
    return _get(con, mid, user)


def _check_folder(con, folder_id, kind, user):
    """메모의 폴더는 같은 종류여야 하고, 개인이면 본인 폴더여야 한다. 남의 개인 폴더·못 보는 비공개 폴더는 없는 것처럼 404."""
    if folder_id is not None and folders.get_visible(con, folder_id, user)["kind"] != kind:
        raise HTTPException(422, "메모와 폴더의 종류가 다릅니다")


def _shape(con, row, user, cache=None):
    return {**{k: row[k] for k in COLS}, **ws.share_info(con, row, user, cache)}


def _out(con, mid, user):
    return _shape(con, con.execute(f"SELECT {ROW} FROM memos WHERE id=?", (mid,)).fetchone(), user)


def _public(con, mid):
    """지금 누구에게나 보이는 공동 메모인가(활동 기록·푸시를 만들어도 되는가)."""
    return ws.is_public(con.execute(f"SELECT {ws.MEMO_ACCESS} FROM memos WHERE id=?", (mid,)).fetchone(), con)


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


def _no_widening(con, mid, memo, before, user):
    """폴더 이동으로 이 메모를 볼 수 있는 사람이 늘면(비공개 -> 공개, 또는 새 목록에 새 사람이 있음) 메모를 만든 사람·옛/새
    제한을 건 항목의 만든 사람·관리자만 할 수 있다. 목록에 있다는 이유만으로 공개 범위를 우회해 넓히지 못하게 하는 규칙으로,
    share-with(만든 사람·관리자만)와 같은 수준이다. 쓰기 직후 같은 트랜잭션에서 판정하고, 막으면 예외로 롤백한다."""
    after = ws.restrictor(con, con.execute(f"SELECT {ws.MEMO_ACCESS} FROM memos WHERE id=?", (mid,)).fetchone())

    def audience(r):  # None = 모두
        return None if r is None else ws.viewer_ids(con, r) | {r[2]}

    old, new = audience(before), audience(after)
    if old is not None and (new is None or not new <= old):
        allowed = {memo["created_by"], before and before[2], after and after[2]}
        if user["role"] != "admin" and user["id"] not in allowed:
            raise HTTPException(403, "공개 범위를 넓히는 이동은 만든 사람과 관리자만 할 수 있습니다")


@router.get("")
def list_memos(kind: Kind, category_id: int | None = None, folder_id: str | None = None,
               q: str = "", user=Depends(current_user)):
    need_kind(kind, user)
    sql, args = f"SELECT {ROW} FROM memos WHERE kind=?", [kind]
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
        cache = {}
        rows = con.execute(sql + " ORDER BY updated_at DESC, id DESC", args).fetchall()
        return [_shape(con, r, user, cache) for r in rows if ws.can_access(r, user, con, cache)]


@router.post("", status_code=201)
def add_memo(m: MemoIn, bg: BackgroundTasks, user=Depends(editor)):
    need_kind(m.kind, user)
    with db.connect() as con:
        _check_folder(con, m.folder_id, m.kind, user)
        mid = _insert(con, user, m.kind, m.title, m.category_id, folder_id=m.folder_id)
        _get(con, mid, user)  # 쓰기 잠금 안에서 다시: 확인 뒤 폴더가 제한으로 바뀌어 내가 빠졌으면 만들지 않는다(롤백)
        activity.publicity(con, mid, m.title, False, m.kind == "shared" and _public(con, mid), user, bg)
        return _out(con, mid, user)


@router.get("/{mid}")
def get_memo(mid: int, user=Depends(current_user)):
    with db.connect() as con:
        _get(con, mid, user)
        return _out(con, mid, user)


@router.put("/{mid}")
async def edit_memo(mid: int, m: MemoEdit, bg: BackgroundTasks, user=Depends(current_user)):
    # async: 폴더를 옮겨 접근을 잃은 접속자를 같은 이벤트 루프에서 닫는다
    fields = m.model_dump(exclude_unset=True)  # 보낸 필드만 바꾼다(category_id: null은 분류 해제)
    with db.connect() as con:
        memo = _lock(con, mid, user, _get(con, mid, user))  # 잠금 안에서 접근을 다시 판정한 뒤에야 권한(403)을 따진다
        if not ws.can_edit(memo, user, con):
            raise HTTPException(403, "권한이 없습니다")
        if fields.get("folder_id") is not None:
            _check_folder(con, fields["folder_id"], memo["kind"], user)
        was_public = memo["kind"] == "shared" and _public(con, mid)
        before = ws.restrictor(con, memo) if memo["kind"] == "shared" else None
        sets = "".join(f"{k}=?, " for k in fields)
        try:
            n = con.execute(f"UPDATE memos SET {sets}updated_by=?, updated_name=?, updated_at=? WHERE id=?{SAME}",
                            (*fields.values(), user["id"], user["name"], db.now(), mid, *_same(memo))).rowcount
        except sqlite3.IntegrityError:
            raise HTTPException(400, "없는 분류입니다")
        if not n:
            _changed(con, mid, user)
        if memo["kind"] == "shared" and "folder_id" in fields:
            _no_widening(con, mid, memo, before, user)
        out = _out(con, mid, user)
        if memo["kind"] == "shared":  # 폴더 이동으로 공개 여부가 바뀌면 그만큼만, 아니면 공개 메모의 수정만 기록
            # '삭제' 줄에는 바꾸기 전 제목(마지막으로 공개돼 있던 제목)을 쓴다: 새 제목은 한 번도 공개된 적이 없다
            activity.publicity(con, mid, out["title"], was_public, _public(con, mid), user, bg, edit=True,
                               old_title=memo["title"])
    if "folder_id" in fields:
        await ws.rooms.revoke(4404, ws.GONE_REASON, memo_id=mid)  # 새 폴더 목록에 없는 접속자는 닫는다
    return out


@router.delete("/{mid}", status_code=204)
async def del_memo(mid: int, bg: BackgroundTasks, user=Depends(current_user)):
    # async: 열린 방(이벤트 루프 소유)을 같은 루프에서 내린다
    with db.connect() as con:
        m = _get(con, mid, user)  # 개인 메모는 여기서 이미 소유자만 남는다
        if m["kind"] == "shared" and m["created_by"] != user["id"] and user["role"] != "admin":
            raise HTTPException(403, "작성자와 관리자만 지울 수 있습니다")
        m = _lock(con, mid, user, m)
        public = m["kind"] == "shared" and _public(con, mid)
        if not con.execute(f"DELETE FROM memos WHERE id=?{SAME}", (mid, *_same(m))).rowcount:
            _changed(con, mid, user)
        if public:  # 비공개 공유 메모는 기록·푸시가 없다(제한으로 바뀔 때 이미 '삭제' 한 줄이 남았다)
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
        m = _lock(con, mid, user, m)  # 그 사이 전율로 옮겨졌으면 덮어쓰지 않는다
        if not con.execute(f"UPDATE memos SET kind='shared', folder_id=NULL WHERE id=?{SAME}", (mid, *_same(m))).rowcount:
            _changed(con, mid, user)
        activity.publicity(con, mid, m["title"], False, True, user, bg)  # 개인 메모의 공개 범위는 항상 '전체'
        return _out(con, mid, user)


@router.put("/{mid}/share-with")
async def share_with(mid: int, s: folders.ShareIn, bg: BackgroundTasks, user=Depends(editor)):
    """공동 메모의 공개 범위(전체/선택한 사람). 만든 사람과 관리자만. 접근을 잃은 접속자는 삭제와 같은 사유(4404)로 닫힌다.

    제한 폴더 안의 메모는 폴더 목록을 따르므로 409. 전체 -> 제한은 활동에 '삭제' 한 줄만, 제한 -> 전체는 '작성' + 푸시.
    async: 닫기를 이벤트 루프에서 커밋 직후 이어서 한다.
    """
    with db.connect() as con:
        m = _get(con, mid, user)  # 목록에 없는 사람은 여기서 없는 메모와 같은 404
        if m["kind"] != "shared":
            raise HTTPException(409, "공동 메모만 공개 범위를 정할 수 있습니다")
        if user["role"] != "admin" and m["created_by"] != user["id"]:
            raise HTTPException(403, "만든 사람과 관리자만 바꿀 수 있습니다")
        viewers = folders.pick_viewers(con, s)
        m = _lock(con, mid, user, m)
        r = ws.restrictor(con, m)
        if r and r[0] == "folder_viewers":
            raise HTTPException(409, "폴더의 공개 범위를 따릅니다")
        was_public = r is None
        if not con.execute(f"UPDATE memos SET visibility=? WHERE id=?{SAME}", (s.visibility, mid, *_same(m))).rowcount:
            _changed(con, mid, user)
        folders.set_viewers(con, "memo_viewers", "memo_id", mid, viewers)
        activity.publicity(con, mid, m["title"], was_public, _public(con, mid), user, bg)
        out = _out(con, mid, user)
    await ws.rooms.revoke(4404, ws.GONE_REASON, memo_id=mid)
    return out


@router.post("/{mid}/copy-to-personal", status_code=201)
async def copy_to_personal(mid: int, user=Depends(editor)):
    """공동 -> 개인 '복사': 호출자 소유의 새 메모. ydoc 바이트를 복사하므로 이후 둘은 서로 무관하다.

    async: 열린 방의 저장(타이머·Yjs 문서)은 이벤트 루프에서만 만진다.
    편집자 이상만: 보기 전용은 새 메모를 만들 수 없으므로 복사로도 못 만든다. 볼 수 없는 비공개 메모는 복사도 못 한다(404).
    """
    with db.connect() as con:
        if _get(con, mid, user)["kind"] != "shared":
            raise HTTPException(409, "공동 메모만 개인으로 복사할 수 있습니다")
    room = ws.rooms.get(mid)
    if room:
        room.save()  # 열려 있는 방의 아직 저장 안 된 편집까지 복사한다
    with db.connect() as con:
        m = _get(con, mid, user)  # 다시 확인: 그 사이 전율로 옮겨졌거나 목록에서 빠졌으면 복사해 가지 못한다
        if m["kind"] != "shared":
            raise HTTPException(409, "공동 메모만 개인으로 복사할 수 있습니다")
        return _out(con, _insert(con, user, "personal", m["title"], m["category_id"], m["body_text"], m["ydoc"]), user)


@router.post("/{mid}/move")
async def move_memo(mid: int, mv: MoveIn, bg: BackgroundTasks, user=Depends(current_user)):
    """개인·공동 <-> 전율 '이동': 같은 행·같은 Yjs 문서. 종류(전율 -> 개인이면 소유자도)만 바뀌고 폴더는 비운다.

    허용되는 전이는 모두 전율이 끼므로 관리자만 할 수 있다(전율에서: _get이, 전율로: need_kind가 막는다).
    공개 범위와 선택한 사람 목록은 버린다(공동에서 나가면 의미가 없고, 다시 공동이 되면 '전체'로 시작한다).
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
        # 확인한 뒤 다른 요청(스레드)이 먼저 종류·소유자·공개 범위를 바꿨으면 옮기지 않는다
        m = _lock(con, mid, user, m)
        was_public = m["kind"] == "shared" and _public(con, mid)
        if not con.execute(f"UPDATE memos SET kind=?, owner_id=?, folder_id=NULL, visibility='all' WHERE id=?{SAME}",
                           (mv.to, owner, mid, *_same(m))).rowcount:
            _changed(con, mid, user)
        con.execute("DELETE FROM memo_viewers WHERE memo_id=?", (mid,))
        out = _out(con, mid, user)
        # 공동에서 사라짐: 삭제처럼 기록하되 푸시는 보내지 않는다(비공개 공유였으면 기록 없음). 공동이 됨: 작성 + 푸시
        activity.publicity(con, mid, out["title"], was_public, mv.to == "shared", user, bg)
    # 커밋 뒤 await 없이 이어서: 계속 볼 수 있는 접속자는 두고 나머지만 닫는다
    await ws.rooms.revoke(4404, ws.GONE_REASON, memo_id=mid)  # 삭제와 같은 사유: 옮겨졌다는 사실을 알리지 않는다
    return out
