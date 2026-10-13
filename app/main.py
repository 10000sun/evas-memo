import os
import re
import secrets
import sqlite3
from pathlib import Path

from dotenv import load_dotenv
from fastapi import Depends, FastAPI, HTTPException
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator
from starlette.middleware.sessions import SessionMiddleware

load_dotenv()  # .env의 토큰·비밀값을 읽는다(깃에는 올리지 않는다)

from . import auth, db, memos, push, ws  # noqa: E402  (db.init이 EVAS_ADMIN_IDS를 읽기 전에 .env를 불러와야 한다)
from .auth import admin, current_user  # noqa: E402

app = FastAPI(title="evas-memo", lifespan=ws.lifespan)
# shortcut: SESSION_SECRET이 없으면 실행할 때마다 새로 만든다 -> 서버를 재시작하면 모두 로그아웃. 운영에서는 .env에 고정할 것
app.add_middleware(SessionMiddleware, secret_key=os.environ.get("SESSION_SECRET") or secrets.token_hex(32),
                   https_only=os.environ.get("PUBLIC_URL", "").startswith("https"),
                   same_site="lax", max_age=60 * 60 * 24 * 30)
app.include_router(auth.router)
app.include_router(memos.router)
app.include_router(ws.router)
db.init()

COLOR = re.compile(r"^#[0-9a-fA-F]{6}$")


class CategoryIn(BaseModel):
    name: str
    color: str

    @field_validator("color")
    @classmethod
    def _color(cls, v):
        if not COLOR.match(v):
            raise ValueError("색상은 #rrggbb 형식이어야 합니다")
        return v.lower()

    @field_validator("name")
    @classmethod
    def _name(cls, v):
        if not v.strip():
            raise ValueError("이름이 비었습니다")
        return v.strip()


class UserIn(BaseModel):
    name: str
    role: str

    @field_validator("role")
    @classmethod
    def _role(cls, v):
        if v not in ("admin", "editor"):
            raise ValueError("role은 admin 또는 editor")
        return v


def rows(con, sql, *a):
    return [dict(r) for r in con.execute(sql, a).fetchall()]


@app.get("/api/me")
def me(user=Depends(current_user)):
    return user


# --- 분류 ---
@app.get("/api/categories")
def list_categories(_=Depends(current_user)):
    with db.connect() as con:
        return rows(con, "SELECT * FROM categories ORDER BY id")


@app.post("/api/categories", status_code=201)
def add_category(c: CategoryIn, _=Depends(admin)):
    with db.connect() as con:
        try:
            cur = con.execute("INSERT INTO categories(name,color) VALUES(?,?)", (c.name, c.color))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "이미 있는 분류 이름입니다")
        return {"id": cur.lastrowid, **c.model_dump()}


@app.put("/api/categories/{cid}")
def edit_category(cid: int, c: CategoryIn, _=Depends(admin)):
    with db.connect() as con:
        try:
            cur = con.execute("UPDATE categories SET name=?, color=? WHERE id=?", (c.name, c.color, cid))
        except sqlite3.IntegrityError:
            raise HTTPException(409, "이미 있는 분류 이름입니다")
        if not cur.rowcount:
            raise HTTPException(404)
    return {"id": cid, **c.model_dump()}


@app.delete("/api/categories/{cid}", status_code=204)
def del_category(cid: int, _=Depends(admin)):
    # 메모는 남고 분류만 비워진다(memos.category_id ON DELETE SET NULL)
    with db.connect() as con:
        if not con.execute("DELETE FROM categories WHERE id=?", (cid,)).rowcount:
            raise HTTPException(404)


# --- 편집 권한 관리 (관리자) ---
@app.get("/api/users")
def list_users(_=Depends(admin)):
    with db.connect() as con:
        return rows(con, "SELECT * FROM users ORDER BY role, name")


@app.put("/api/users/{uid}")
def set_user(uid: str, u: UserIn, me=Depends(admin)):
    with db.connect() as con:
        if uid == me["id"] and u.role != "admin" and _admin_count(con) == 1:
            raise HTTPException(409, "마지막 관리자는 강등할 수 없습니다")
        con.execute("INSERT INTO users(id,name,role) VALUES(?,?,?) ON CONFLICT(id) DO UPDATE SET name=?, role=?",
                    (uid, u.name, u.role, u.name, u.role))
    return {"id": uid, **u.model_dump()}


@app.delete("/api/users/{uid}", status_code=204)
def del_user(uid: str, _=Depends(admin)):
    with db.connect() as con:
        row = con.execute("SELECT role FROM users WHERE id=?", (uid,)).fetchone()
        if not row:
            raise HTTPException(404)
        if row["role"] == "admin" and _admin_count(con) == 1:
            raise HTTPException(409, "마지막 관리자는 지울 수 없습니다")
        con.execute("DELETE FROM users WHERE id=?", (uid,))


def _admin_count(con):
    return con.execute("SELECT COUNT(*) FROM users WHERE role='admin'").fetchone()[0]


# --- 알림 (변경 내역·읽음 표시·폰 푸시 구독) ---
@app.get("/api/activity")
def list_activity(user=Depends(current_user)):
    """최근 변경 50건과 안 읽은 개수, 공동 메모 변경 표식(rev). 내가 한 변경은 목록엔 보이지만 안 읽음에 세지 않는다."""
    with db.connect() as con:
        # 처음 보는 사람은 지금까지의 내역을 전부 안 읽음으로 쏟아내지 않도록 현재 위치부터 센다
        con.execute("INSERT OR IGNORE INTO activity_read(user_id,last_id) SELECT ?, COALESCE(MAX(id),0) FROM activity", (user["id"],))
        last = con.execute("SELECT last_id FROM activity_read WHERE user_id=?", (user["id"],)).fetchone()[0]
        items = rows(con, "SELECT * FROM activity ORDER BY id DESC LIMIT 50")
        # 공동 메모가 바뀌었는지 화면이 값 비교로 알아채도록 하는 표식. 개인 메모는 섞이지 않는다
        rev = con.execute("SELECT COALESCE((SELECT MAX(id) FROM activity),0) || ':' || COUNT(*) || ':' || COALESCE(MAX(updated_at),'') "
                          "FROM memos WHERE kind='shared'").fetchone()[0]
    for i in items:
        i["unread"] = i["id"] > last and i["actor_id"] != user["id"]
    return {"items": items, "unread": sum(i["unread"] for i in items), "rev": rev}


@app.post("/api/activity/read", status_code=204)
def read_activity(user=Depends(current_user)):
    with db.connect() as con:
        con.execute("INSERT OR REPLACE INTO activity_read(user_id,last_id) SELECT ?, COALESCE(MAX(id),0) FROM activity", (user["id"],))


class SubKeys(BaseModel):
    p256dh: str
    auth: str


class SubIn(BaseModel):
    endpoint: str
    keys: SubKeys

    @field_validator("endpoint")
    @classmethod
    def _endpoint(cls, v):
        if not push.allowed(v):
            raise ValueError("지원하지 않는 푸시 주소입니다")
        return v


@app.get("/api/push/key")
def push_key(_=Depends(current_user)):
    # 서버에 VAPID 키가 없으면 null -> 화면이 폰 알림 버튼을 숨긴다
    return {"key": os.environ.get("VAPID_PUBLIC_KEY") if os.environ.get("VAPID_PRIVATE_KEY") else None}


@app.post("/api/push/subscribe", status_code=204)
def push_subscribe(s: SubIn, user=Depends(current_user)):
    with db.connect() as con:
        con.execute("INSERT OR REPLACE INTO push_subs(endpoint,user_id,p256dh,auth) VALUES(?,?,?,?)",
                    (s.endpoint, user["id"], s.keys.p256dh, s.keys.auth))


@app.post("/api/push/unsubscribe", status_code=204)
def push_unsubscribe(s: SubIn, user=Depends(current_user)):
    with db.connect() as con:
        con.execute("DELETE FROM push_subs WHERE endpoint=? AND user_id=?", (s.endpoint, user["id"]))


# 화면 파일은 사이트 루트에서 낸다(캘린더와 같다). 모든 API·WebSocket 라우트보다 뒤에 둬야 그것들을 가리지 않는다
app.mount("/", StaticFiles(directory=Path(__file__).parent.parent / "static", html=True))
