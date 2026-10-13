"""공동 메모 변경 기록. 개인 메모는 호출하는 쪽에서 걸러 절대 기록하지 않는다(제목이 새지 않게)."""
from datetime import datetime, timedelta

from . import db, push

COALESCE = timedelta(minutes=10)


def log(con, kind, memo_id, title, user):
    """한 줄 남긴다. 메모 저장과 같은 트랜잭션이라 둘 중 하나만 남지 않는다.

    'edit'는 같은 사람이 같은 메모를 10분 안에 또 고치면 새 줄 대신 마지막 'edit'의 시각만 갱신한다.
    """
    t = db.now()
    if kind == "edit":
        last = con.execute("SELECT id, kind, actor_id, at FROM activity WHERE memo_id=? ORDER BY id DESC LIMIT 1",
                           (memo_id,)).fetchone()
        if (last and last["kind"] == "edit" and last["actor_id"] == user["id"]
                and datetime.fromisoformat(t) - datetime.fromisoformat(last["at"]) < COALESCE):
            con.execute("UPDATE activity SET at=?, title=? WHERE id=?", (t, title, last["id"]))
            return
    con.execute("INSERT INTO activity(kind,memo_id,title,actor_id,actor_name,at) VALUES(?,?,?,?,?,?)",
                (kind, memo_id, title, user["id"], user["name"], t))


def publicity(con, memo_id, title, before, after, user, bg=None, edit=False, old_title=None):
    """공개 여부(ws.is_public)가 바뀐 만큼만 남긴다. 비공개 공유 메모는 기록·푸시를 만들지 않는다(제목이 새지 않게).

    공개 -> 비공개: '삭제' 한 줄만(푸시 없음, 전율로 옮길 때와 같다). 비공개 -> 공개: '작성' 한 줄 + 푸시(bg가 있을 때).
    그대로 공개이고 edit이면 '수정'을 남긴다. title은 바뀐 뒤 제목, old_title은 바뀌기 전(마지막으로 공개돼 있던) 제목:
    '삭제' 줄에는 한 번도 공개된 적 없는 새 제목이 들어가면 안 되므로 old_title을 쓴다.
    """
    if before and not after:
        log(con, "delete", memo_id, title if old_title is None else old_title, user)
    elif after and not before:
        log(con, "add", memo_id, title, user)
        if bg:
            bg.add_task(push.notify, "add", title, user)
    elif after and edit:
        log(con, "edit", memo_id, title, user)
