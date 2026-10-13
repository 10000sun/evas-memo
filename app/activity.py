"""공동 메모 변경 기록. 개인 메모는 호출하는 쪽에서 걸러 절대 기록하지 않는다(제목이 새지 않게)."""
from datetime import datetime, timedelta

from . import db

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
