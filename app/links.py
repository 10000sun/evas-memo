"""캘린더 연동 API. 개인·전율 메모는 어떤 경로로도 캘린더에 나가지 않는다.

- /internal/link/memos: 캘린더 서버가 부르는 내부 경로. X-Link-Key가 맞을 때만 응답하고 공동 메모만 돌려준다.
- /api/link/events: 브라우저 -> 이 서버(로그인 세션) -> 캘린더 내부 경로. 비밀키는 이 서버 안에서만 붙는다.
- /api/link/memos: 브라우저가 쓰는 메모 힌트·칩 조회(공동 + scope=all이면 본인 개인 + scope=admin이면 전율도).
"""
import os
import secrets
from typing import Literal

import httpx
from fastapi import APIRouter, Depends, Header, HTTPException

from . import db, ws
from .auth import current_user

router = APIRouter()
MAX_IDS = 50
MAX_TOKENS = 100  # 변환 전에 토큰 수부터 자른다


def _env(name):
    return os.environ.get(name, "").strip()


def link_key():
    # 호출 때마다 읽는다(테스트가 환경변수를 바꿔 끼운다). 비어 있으면 연동 전부 꺼짐
    return _env("LINK_API_KEY")


def calendar_url():
    return (_env("CALENDAR_URL") or _env("SHARED_CALENDAR_URL")).rstrip("/") or None


def calendar_internal_url():
    return (_env("CALENDAR_INTERNAL_URL") or f"http://127.0.0.1:{_env('SHARED_CALENDAR_PORT') or 8000}").rstrip("/")


def need_key(x_link_key: str | None = Header(default=None)):
    """내부 경로 보호: 키가 없거나 틀리거나 서버에 미설정이면 경로가 없는 것처럼 404."""
    key = link_key()
    # bytes로 비교: 한글 같은 비ASCII 헤더 값이 와도 compare_digest가 예외를 내지 않게
    if not key or not x_link_key or not secrets.compare_digest(x_link_key.encode(), key.encode()):
        raise HTTPException(404)


def need_link(_=Depends(current_user)):
    if not link_key():
        raise HTTPException(404)


def parse_ids(ids: str):
    # 숫자(ASCII 0-9) 18자리 이하만: 거대한 수는 sqlite가 OverflowError를 내고, 유니코드 숫자(٣, ²)는 int()가 다르게 읽는다
    toks = (t.strip() for t in ids.split(",")[:MAX_TOKENS])
    return [int(t) for t in toks if t.isascii() and t.isdigit() and len(t) <= 18][:MAX_IDS]


def memo_rows(q: str = "", limit: int = 8, ids: str | None = None, user_id: str | None = None, admin=False):
    """공동 메모 + (user_id를 주면) 그 사람의 개인 메모 + (admin이면) 전율 메모.

    기본값으로 부르면 공동만 나온다: 개인·전율 메모는 호출하는 쪽이 권한을 확인하고 명시해야만 나온다.
    """
    where, args, limit = "kind='shared'", [], max(1, min(limit, 20))
    if user_id:
        where, args = "(kind='shared' OR (kind='personal' AND owner_id=?))", [user_id]
    if admin:
        where = f"({where} OR kind='admin')"
    if ids is not None:
        ids = parse_ids(ids)
        if not ids:
            return []
        where += f" AND id IN ({','.join('?' * len(ids))})"
        args += ids
        limit = len(ids)
    elif q:  # instr: LIKE와 달리 %, _를 글자 그대로 찾는다
        where += " AND instr(lower(title), lower(?))"
        args.append(q)
    with db.connect() as con:
        return [dict(r) for r in con.execute(
            f"SELECT id, title, updated_at, kind FROM memos WHERE {where} ORDER BY updated_at DESC, id DESC LIMIT ?",
            (*args, limit))]


@router.get("/internal/link/memos")
def internal_memos(q: str = "", limit: int = 8, ids: str | None = None, _=Depends(need_key)):
    return memo_rows(q, limit, ids)  # for(개인 허용)를 받지 않는다: 캘린더로 개인 메모가 나갈 길을 만들지 않는다


@router.get("/api/link/memos")
def link_memos(q: str = "", limit: int = 8, ids: str | None = None,
               scope: Literal["shared", "all", "admin"] = "shared", user=Depends(current_user)):
    """scope: shared=공동, all=공동+본인 개인, admin=공동+본인 개인+전율(관리자만, 아니면 없는 경로처럼 404)."""
    if scope == "admin" and not ws.can_use_kind("admin", user):
        raise HTTPException(404)
    return memo_rows(q, limit, ids, user["id"] if scope != "shared" else None, admin=scope == "admin")


@router.get("/api/link/events")
def link_events(q: str | None = None, limit: int | None = None, ids: str | None = None, _=Depends(need_link)):
    """캘린더 일정 힌트·칩 조회 프록시. 캘린더가 꺼져 있어도 3초 안에 502로 끝나고 이 앱의 다른 기능엔 영향이 없다."""
    params = {"ids": ids} if ids is not None else {k: v for k, v in (("q", q), ("limit", limit)) if v is not None}
    try:
        with httpx.Client(timeout=3, trust_env=False) as h:
            r = h.get(calendar_internal_url() + "/internal/link/events", params=params, headers={"X-Link-Key": link_key()})
            r.raise_for_status()
            data = r.json()
        if not isinstance(data, list):
            raise ValueError
    except Exception:
        raise HTTPException(502, "연결할 수 없습니다")
    return data


@router.get("/api/config")
def config():
    return {"app": "memo", "memo_url": _env("PUBLIC_URL").rstrip("/") or None, "calendar_url": calendar_url(),
            "link": bool(link_key())}
