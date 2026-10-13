"""메모 ↔ 캘린더 연동 API: 내부 조회(공동 메모만), 프록시, 설정, 로그인 next."""
import time
from urllib.parse import parse_qs, quote, urlparse

import httpx
import pytest

from app import auth
from tests.conftest import as_

KEY = "k" * 32


@pytest.fixture
def c(client, monkeypatch):
    monkeypatch.delenv("EVAS_OPEN_EDIT", raising=False)
    monkeypatch.setenv("LINK_API_KEY", KEY)
    for uid in ("a", "b"):
        client.put(f"/api/users/{uid}", json=dict(name="이름" + uid, role="editor"), headers=as_("boss"))
    return client


def new(c, uid, kind, title):
    r = c.post("/api/memos", json=dict(kind=kind, title=title), headers=as_(uid))
    assert r.status_code == 201, r.text
    return r.json()["id"]


def internal(c, qs="", key=KEY):
    return c.get("/internal/link/memos" + qs, headers={} if key is None else {"X-Link-Key": key})


def test_internal_requires_key(c, monkeypatch):
    new(c, "a", "shared", "공지")
    assert internal(c, key=None).status_code == 404
    assert internal(c, key="틀림".encode()).status_code == 404  # 비ASCII 헤더여도 500이 아니라 404
    assert internal(c, key="wrong").status_code == 404
    assert internal(c, key="").status_code == 404
    r = internal(c)
    assert r.status_code == 200 and [m["title"] for m in r.json()] == ["공지"]
    monkeypatch.delenv("LINK_API_KEY")  # 키가 미설정이면 빈 헤더로도 못 연다
    assert internal(c).status_code == 404
    assert internal(c, key="").status_code == 404
    assert internal(c, key=None).status_code == 404


def test_internal_returns_only_shared_memos(c):
    s = new(c, "a", "shared", "공동 회의")
    p = new(c, "a", "personal", "비밀 회의")
    assert [m["id"] for m in internal(c, "?q=회의").json()] == [s]
    assert [m["id"] for m in internal(c, f"?ids={s},{p},9999").json()] == [s]
    assert internal(c, f"?ids={p}").json() == []
    assert internal(c).json()[0].keys() == {"id", "title", "updated_at", "kind"}
    assert {m["kind"] for m in internal(c).json()} == {"shared"}
    # for 같은 파라미터로 개인 메모를 열 길은 없다
    assert internal(c, "?q=비밀&for=a").json() == []
    assert internal(c, f"?ids={p}&for=a").json() == []


def test_internal_search_title_substring_and_limit(c):
    for t in ("Alpha 회의", "회의록", "점심", "ALPHA test"):
        new(c, "a", "shared", t)
    assert sorted(m["title"] for m in internal(c, "?q=alpha").json()) == ["ALPHA test", "Alpha 회의"]  # 대소문자 무시
    assert internal(c, "?q=%25").json() == []  # %는 글자 그대로
    assert len(internal(c, "?limit=2").json()) == 2
    assert [m["title"] for m in internal(c).json()][0] == "ALPHA test"  # q가 비면 최근 순(같은 시각이면 id 큰 순)
    for i in range(25):
        new(c, "a", "shared", f"많음{i}")
    assert len(internal(c).json()) == 8
    assert len(internal(c, "?limit=999").json()) == 20
    assert len(internal(c, "?limit=0").json()) == 1


def test_api_link_memos_scope(c):
    s = new(c, "a", "shared", "공동")
    pa = new(c, "a", "personal", "a의 개인")
    pb = new(c, "b", "personal", "b의 개인")
    got = lambda qs: sorted(m["id"] for m in c.get("/api/link/memos" + qs, headers=as_("a")).json())
    assert got("") == [s]  # 기본은 공동만
    assert got("?scope=shared") == [s]
    assert got("?scope=all") == sorted([s, pa])  # 타인(b)의 개인은 없다
    assert got(f"?scope=all&ids={s},{pa},{pb}") == sorted([s, pa])
    assert got(f"?scope=shared&ids={s},{pa}") == [s]
    assert got("?scope=all&q=개인") == [pa]
    assert got("?scope=all&q=" + quote("b의")) == []
    kinds = {m["id"]: m["kind"] for m in c.get("/api/link/memos?scope=all", headers=as_("a")).json()}
    assert kinds == {s: "shared", pa: "personal"}
    assert c.get("/api/link/memos").status_code == 401  # 로그인 필요
    assert c.get("/api/link/memos?scope=x", headers=as_("a")).status_code == 422


def fake_calendar(monkeypatch, handler):
    real = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))


def test_api_link_events_proxies_with_key(c, monkeypatch):
    monkeypatch.setenv("CALENDAR_INTERNAL_URL", "http://cal.internal:9")
    seen = []
    events = [{"id": 3, "title": "회식", "start": "2026-10-20", "end": "2026-10-20", "all_day": True, "category_color": "#fff"}]

    def handler(req):
        seen.append(req)
        return httpx.Response(200, json=events)
    fake_calendar(monkeypatch, handler)
    r = c.get("/api/link/events?q=" + quote("회") + "&limit=5", headers=as_("a"))
    assert r.status_code == 200 and r.json() == events
    assert str(seen[0].url).startswith("http://cal.internal:9/internal/link/events?")
    assert seen[0].headers["X-Link-Key"] == KEY
    assert seen[0].url.params["q"] == "회" and seen[0].url.params["limit"] == "5"
    assert KEY not in r.text and KEY not in str(r.headers)
    c.get("/api/link/events?ids=1,2", headers=as_("a"))
    assert seen[1].url.params["ids"] == "1,2" and "q" not in seen[1].url.params
    assert c.get("/api/link/events").status_code == 401


def test_api_link_events_default_internal_url(c, monkeypatch):
    monkeypatch.delenv("CALENDAR_INTERNAL_URL", raising=False)
    monkeypatch.delenv("SHARED_CALENDAR_PORT", raising=False)
    seen = []
    fake_calendar(monkeypatch, lambda req: (seen.append(str(req.url)), httpx.Response(200, json=[]))[1])
    c.get("/api/link/events", headers=as_("a"))
    monkeypatch.setenv("SHARED_CALENDAR_PORT", "8123")
    c.get("/api/link/events", headers=as_("a"))
    assert seen[0].startswith("http://127.0.0.1:8000/internal/link/events")
    assert seen[1].startswith("http://127.0.0.1:8123/internal/link/events")


@pytest.mark.parametrize("fail", ["down", "timeout", "404", "500", "html"])
def test_api_link_events_upstream_down_is_502_fast(c, monkeypatch, fail):
    def handler(req):
        if fail == "down":
            raise httpx.ConnectError("refused")
        if fail == "timeout":
            raise httpx.ReadTimeout("slow")
        if fail == "html":
            return httpx.Response(200, text="<html>")
        return httpx.Response(int(fail))
    fake_calendar(monkeypatch, handler)
    t = time.time()
    r = c.get("/api/link/events?q=x", headers=as_("a"))
    assert r.status_code == 502 and r.json() == {"detail": "연결할 수 없습니다"}
    assert time.time() - t < 3
    assert c.get("/api/me", headers=as_("a")).status_code == 200  # 자기 앱은 정상


def test_api_link_off_without_key(c, monkeypatch):
    monkeypatch.delenv("LINK_API_KEY")  # 캘린더 연동은 꺼짐, 앱의 나머지는 정상
    assert c.get("/api/link/events", headers=as_("a")).status_code == 404
    assert c.get("/api/memos?kind=shared", headers=as_("a")).status_code == 200


def test_api_link_memos_works_without_key(c, monkeypatch):
    # 메모->메모 @ 태그는 로컬 기능이라 키와 무관하다. scope 규칙·개인 비노출은 그대로
    s = new(c, "a", "shared", "공동")
    pa = new(c, "a", "personal", "a의 개인")
    pb = new(c, "b", "personal", "b의 개인")
    monkeypatch.delenv("LINK_API_KEY")
    got = lambda qs: sorted(m["id"] for m in c.get("/api/link/memos" + qs, headers=as_("a")).json())
    assert c.get("/api/link/memos", headers=as_("a")).status_code == 200
    assert got("") == [s] and got("?scope=shared") == [s]
    assert got("?scope=all") == sorted([s, pa])
    assert got(f"?scope=all&ids={s},{pa},{pb}") == sorted([s, pa])
    assert c.get("/api/link/memos").status_code == 401
    assert internal(c).status_code == 404  # 내부 경로는 키 없이는 계속 닫혀 있다


@pytest.mark.parametrize("ids", ["9" * 30, "9" * 5000, "٣", "²", "2,3," + "9" * 19, "-2,+2, ,2.5,0x2"],
                         ids=["9x30", "9x5000", "arabic-digit", "superscript", "19digits", "signs"])
def test_ids_garbage_is_skipped_not_500(c, ids):
    s = new(c, "a", "shared", "공동")
    for r in (internal(c, f"?ids={ids},{s}"), c.get(f"/api/link/memos?scope=all&ids={ids},{s}", headers=as_("a"))):
        assert r.status_code == 200 and [m["id"] for m in r.json()] == [s]
    assert internal(c, f"?ids={ids}").json() == []


def test_ids_token_count_capped(c):
    s = new(c, "a", "shared", "공동")
    # 100번째 토큰 뒤는 보지 않는다
    assert internal(c, "?ids=" + ",".join(["x"] * 100) + f",{s}").json() == []
    assert [m["id"] for m in internal(c, "?ids=" + ",".join(["x"] * 99) + f",{s}").json()] == [s]


def test_api_link_uses_3s_timeout(c, monkeypatch):
    got = {}
    real = httpx.Client

    def make(**kw):
        got.update(kw)
        return real(transport=httpx.MockTransport(lambda req: httpx.Response(200, json=[])), **kw)
    monkeypatch.setattr(httpx, "Client", make)
    c.get("/api/link/events", headers=as_("a"))
    assert got["timeout"] == 3
    assert got["trust_env"] is False  # 시스템 프록시가 loopback 호출과 X-Link-Key를 가로채지 않게


def test_config_endpoint(client, monkeypatch):
    for k in ("LINK_API_KEY", "CALENDAR_URL", "SHARED_CALENDAR_URL"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("PUBLIC_URL", "https://memo.example.com/")
    assert client.get("/api/config").json() == {"app": "memo", "memo_url": "https://memo.example.com",
                                                "calendar_url": None, "link": False}  # 로그인 없이 조회
    monkeypatch.setenv("SHARED_CALENDAR_URL", "https://shared.example.com")
    assert client.get("/api/config").json()["calendar_url"] == "https://shared.example.com"
    monkeypatch.setenv("CALENDAR_URL", "https://cal.example.com/")  # CALENDAR_URL이 우선
    monkeypatch.setenv("LINK_API_KEY", KEY)
    r = client.get("/api/config")
    assert r.json() == {"app": "memo", "memo_url": "https://memo.example.com",
                        "calendar_url": "https://cal.example.com", "link": True}
    assert KEY not in r.text


@pytest.fixture
def discord(client, monkeypatch):
    monkeypatch.setenv("DISCORD_CLIENT_ID", "cid")
    monkeypatch.setenv("DISCORD_CLIENT_SECRET", "sec")
    monkeypatch.setenv("PUBLIC_URL", "https://memo.example.com")
    monkeypatch.delenv("DISCORD_GUILD_ID", raising=False)
    monkeypatch.setattr(auth, "fetch_discord_profile", lambda code, uri, gid: dict(id=code, name="이름" + code, in_guild=True))
    client.follow_redirects = False
    return client


def login_then_callback(c, nxt=None):
    """next를 실어 로그인 시작 -> 같은 세션으로 콜백. 콜백이 보낸 응답을 돌려준다."""
    r = c.get("/auth/login" + ("" if nxt is None else "?next=" + quote(nxt, safe="")))
    st = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
    return c.get(f"/auth/callback?code=boss&state={st}")


def test_login_callback_redirects_to_next(discord):
    r = login_then_callback(discord, "/?memo=5")
    assert r.status_code in (302, 307) and r.headers["location"] == "/?memo=5"
    assert discord.get("/api/me").json()["id"] == "boss"
    discord.post("/auth/logout")
    assert login_then_callback(discord).headers["location"] == "/"  # next 없으면 /
    # 이전 로그인 시도의 next가 다음 로그인에 남지 않는다
    discord.post("/auth/logout")
    discord.get("/auth/login?next=" + quote("/?memo=7", safe=""))
    assert login_then_callback(discord).headers["location"] == "/"
    # 로그인이 끝난 뒤 next는 세션에 남지 않는다
    discord.post("/auth/logout")
    login_then_callback(discord, "/?memo=9")
    discord.post("/auth/logout")
    assert login_then_callback(discord).headers["location"] == "/"


@pytest.mark.parametrize("nxt,want", [
    ("/?memo=5", "/?memo=5"), ("/", "/"), ("/?event=3", "/?event=3"), ("/#12", "/#12"),
    ("//evil.com", "/"), ("https://evil.com", "/"), ("/\\x", "/"), ("/\\/evil.com", "/"),
    ("evil.com", "/"), ("", "/"), ("/?u=http://evil.com", "/"), ("/\r\nSet-Cookie: x", "/"),
    ("/a\nb", "/"), ("/a\x00b", "/"), ("/a\x7fb", "/"), ("/a//b", "/"),
])
def test_login_next_sanitized(discord, nxt, want):
    assert login_then_callback(discord, nxt).headers["location"] == want


def test_login_next_length_limit(discord):
    ok = "/?memo=" + "1" * (200 - 7)
    assert len(ok) == 200 and login_then_callback(discord, ok).headers["location"] == ok
    discord.post("/auth/logout")
    assert login_then_callback(discord, ok + "1").headers["location"] == "/"  # 201자는 거절
    discord.post("/auth/logout")
    # 아주 긴 next가 쿠키를 키워 로그인을 깨뜨리지 않는다
    r = login_then_callback(discord, "/" + "a" * 6000)
    assert r.status_code in (302, 307) and r.headers["location"] == "/"
    assert discord.get("/api/me").json()["id"] == "boss"


def test_login_next_stored_in_session(discord):
    # 로그인 시작 시 next가 세션에 보관된다(쿠키 서명이라 값을 직접 볼 수는 없으니 콜백 결과로 확인)
    r = discord.get("/auth/login?next=" + quote("/?memo=5", safe=""))
    assert r.status_code in (302, 307) and "evil" not in r.headers["location"]
    st = parse_qs(urlparse(r.headers["location"]).query)["state"][0]
    assert discord.get(f"/auth/callback?code=boss&state={st}").headers["location"] == "/?memo=5"
