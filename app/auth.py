"""디스코드 로그인(OAuth2). 봇은 필요 없고 개발자 포털의 애플리케이션만 있으면 된다.

디스코드 토큰은 사용자 확인에만 쓰고 저장하지 않는다. 권한(편집자/관리자)은 우리 DB가 정하고
디스코드 ID를 키로 쓴다.
"""
import os
import secrets
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from . import db

router = APIRouter()
DISCORD = "https://discord.com"


def user_of(session, x_user_id: str | None = None):
    """세션(또는 개발용 헤더) -> {id, name, role}, 로그인 안 했으면 None. HTTP와 WebSocket이 같이 쓴다.

    shortcut: 개발용 헤더 인증(EVAS_DEV_AUTH=1일 때만 켜짐)이 남아 있다. 운영 .env에는 넣지 말 것.
    """
    uid, name = session.get("uid"), session.get("name")
    if not uid and os.environ.get("EVAS_DEV_AUTH") == "1" and x_user_id:
        uid, name = x_user_id, x_user_id
    if not uid:
        return None
    with db.connect() as con:
        row = con.execute("SELECT role FROM users WHERE id=?", (uid,)).fetchone()
    # 팀 방침에 따라 EVAS_OPEN_EDIT=1이면 로그인한 누구나 편집자. 분류·권한 관리는 계속 관리자만
    default = "editor" if os.environ.get("EVAS_OPEN_EDIT") == "1" else "viewer"
    return {"id": uid, "name": name, "role": row["role"] if row else default}


def current_user(request: Request, x_user_id: str | None = Header(default=None)):
    """로그인한 사용자 {id, name, role}. role: admin / editor / viewer."""
    user = user_of(request.session, x_user_id)
    if not user:
        raise HTTPException(401, "로그인이 필요합니다")
    return user


def need(*roles):
    def dep(user=Depends(current_user)):
        if user["role"] not in roles:
            raise HTTPException(403, "권한이 없습니다")
        return user
    return dep


editor = need("admin", "editor")
admin = need("admin")


def cfg():
    # 호출 때마다 읽는다(테스트가 환경변수를 바꿔 끼운다)
    return {k: os.environ.get(k, "") for k in
            ("DISCORD_CLIENT_ID", "DISCORD_CLIENT_SECRET", "PUBLIC_URL", "DISCORD_GUILD_ID")}


def display_name(user: dict, member: dict | None = None) -> str:
    """서버 닉네임 > 디스코드 표시 이름 > 계정 이름 순. 팀원이 서로 알아보는 이름이 닉네임이라서."""
    return (member or {}).get("nick") or user.get("global_name") or user["username"]


def fetch_discord_profile(code: str, redirect_uri: str, guild_id: str):
    """인가 코드 -> {id, name, in_guild}. 테스트는 이 함수를 바꿔 끼운다."""
    c = cfg()
    with httpx.Client(timeout=10) as h:
        t = h.post(f"{DISCORD}/api/oauth2/token", data={
            "client_id": c["DISCORD_CLIENT_ID"], "client_secret": c["DISCORD_CLIENT_SECRET"],
            "grant_type": "authorization_code", "code": code, "redirect_uri": redirect_uri})
        t.raise_for_status()
        auth = {"Authorization": f"Bearer {t.json()['access_token']}"}
        me = h.get(f"{DISCORD}/api/users/@me", headers=auth)
        me.raise_for_status()
        me = me.json()
        member = None
        if guild_id:
            # 구성원이 아니면 디스코드가 404/403을 준다 -> '구성원 아님'. 그 밖의 오류는 로그인 실패로 올린다
            m = h.get(f"{DISCORD}/api/users/@me/guilds/{guild_id}/member", headers=auth)
            if m.status_code not in (403, 404):
                m.raise_for_status()
                member = m.json()
    return {"id": me["id"], "name": display_name(me, member), "in_guild": member is not None if guild_id else True}


def fail(msg, status=400):
    return HTMLResponse(f'<meta charset="utf-8"><p>{msg}</p><a href="/auth/login">다시 로그인</a>', status)


def safe_next(n) -> str:
    """로그인 뒤 돌아갈 곳. 같은 사이트의 경로+쿼리만 허용하고 그 밖(외부 주소·`//`·`\\`·제어문자·`://`)은 `/`로 돌린다."""
    if (not isinstance(n, str) or not n.startswith("/") or len(n) > 200 or "//" in n or "\\" in n or "://" in n
            or any(ord(ch) < 32 or ord(ch) == 127 for ch in n)):
        return "/"
    return n


@router.get("/auth/login")
def login(request: Request, next: str = "/"):
    c = cfg()
    if not (c["DISCORD_CLIENT_ID"] and c["DISCORD_CLIENT_SECRET"] and c["PUBLIC_URL"]):
        raise HTTPException(503, "디스코드 로그인이 설정되지 않았습니다")
    state = request.session["state"] = secrets.token_urlsafe(16)
    request.session["next"] = safe_next(next)  # 콜백에서 쓴다. 이전 시도의 값은 덮어써 남지 않는다
    # 서버 닉네임과 구성원 확인은 guilds.members.read 권한이 필요하다(서버를 지정했을 때만 요청)
    scope = "identify guilds.members.read" if c["DISCORD_GUILD_ID"] else "identify"
    return RedirectResponse(f"{DISCORD}/oauth2/authorize?" + urlencode({
        "client_id": c["DISCORD_CLIENT_ID"], "response_type": "code", "scope": scope, "state": state,
        "redirect_uri": c["PUBLIC_URL"].rstrip("/") + "/auth/callback"}))


@router.get("/auth/callback")
def callback(request: Request, code: str = "", state: str = ""):
    expected = request.session.pop("state", None)
    # state가 다르면 남이 만든 로그인 링크로 끌려온 것(로그인 CSRF)이라 거절한다
    if not code or not expected or not secrets.compare_digest(state, expected):
        return fail("로그인 요청이 올바르지 않습니다")
    c = cfg()
    try:
        p = fetch_discord_profile(code, c["PUBLIC_URL"].rstrip("/") + "/auth/callback", c["DISCORD_GUILD_ID"])
    except Exception:
        return fail("디스코드 로그인에 실패했습니다", 502)
    if not p["in_guild"]:
        return fail("이 메모는 서버 구성원만 볼 수 있습니다", 403)
    nxt = safe_next(request.session.get("next"))  # 세션 값도 한 번 더 걸러서 쓴다
    request.session.clear()
    request.session.update(uid=p["id"], name=p["name"])
    return RedirectResponse(nxt)


@router.get("/auth/dev")
def dev_login(request: Request, uid: str, name: str = ""):
    """개발용 로그인(EVAS_DEV_AUTH=1일 때만). 브라우저 WebSocket은 X-User-Id 헤더를 못 붙여 세션이 필요하다."""
    if os.environ.get("EVAS_DEV_AUTH") != "1":
        raise HTTPException(404)
    request.session.clear()
    request.session.update(uid=uid, name=name or uid)
    return RedirectResponse("/")


@router.post("/auth/logout", status_code=204)
def logout(request: Request):
    request.session.clear()
