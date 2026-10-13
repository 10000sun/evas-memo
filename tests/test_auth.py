from urllib.parse import parse_qs, urlparse

import pytest

from app import auth


@pytest.fixture
def discord(client, monkeypatch):
    monkeypatch.setenv("DISCORD_CLIENT_ID", "cid")
    monkeypatch.setenv("DISCORD_CLIENT_SECRET", "sec")
    monkeypatch.setenv("PUBLIC_URL", "https://memo.example.com")
    monkeypatch.delenv("DISCORD_GUILD_ID", raising=False)
    # 디스코드 서버는 부르지 않는다: 인가 코드에 따라 가짜 프로필을 돌려준다
    monkeypatch.setattr(auth, "fetch_discord_profile", lambda code, uri, gid: dict(
        id=code, name="이름" + code, in_guild=gid in ("", "G1")))
    client.follow_redirects = False
    return client


def start(c):
    r = c.get("/auth/login")
    assert r.status_code in (302, 307)
    return r.headers["location"], parse_qs(urlparse(r.headers["location"]).query)["state"][0]


def test_로그인하면_세션으로_본인_확인됨_로그아웃하면_다시_거부(discord):
    _, st = start(discord)
    assert discord.get(f"/auth/callback?code=boss&state={st}").status_code in (302, 307)
    me = discord.get("/api/me").json()
    assert me == {"id": "boss", "name": "이름boss", "role": "admin"}  # EVAS_ADMIN_IDS=boss
    assert discord.post("/auth/logout").status_code == 204
    assert discord.get("/api/me").status_code == 401


def test_처음_로그인한_사람은_바로_편집자_관리자는_아님(discord):
    _, st = start(discord)
    discord.get(f"/auth/callback?code=newbie&state={st}")
    assert discord.get("/api/me").json()["role"] == "editor"
    assert discord.post("/api/categories", json=dict(name="x", color="#000000")).status_code == 403  # 분류 관리는 관리자만


def test_state가_다르면_로그인_거절(discord):
    start(discord)
    assert discord.get("/auth/callback?code=boss&state=forged").status_code == 400
    assert discord.get("/api/me").status_code == 401
    assert discord.get("/auth/callback?code=boss&state=").status_code == 400  # state 없이도 거절


def test_로그인_링크_없이_바로_콜백_거절(discord):
    assert discord.get("/auth/callback?code=boss&state=x").status_code == 400


def test_인가_링크는_설정값과_필요한_권한만_요청(discord, monkeypatch):
    url, _ = start(discord)
    q = parse_qs(urlparse(url).query)
    assert q["client_id"] == ["cid"] and q["scope"] == ["identify"]
    assert q["redirect_uri"] == ["https://memo.example.com/auth/callback"]
    monkeypatch.setenv("DISCORD_GUILD_ID", "G1")
    assert parse_qs(urlparse(start(discord)[0]).query)["scope"] == ["identify guilds.members.read"]


def test_서버_구성원_제한(discord, monkeypatch):
    monkeypatch.setenv("DISCORD_GUILD_ID", "G1")
    _, st = start(discord)
    assert discord.get(f"/auth/callback?code=boss&state={st}").status_code in (302, 307)  # G1 소속
    monkeypatch.setenv("DISCORD_GUILD_ID", "OTHER")
    discord.post("/auth/logout")
    _, st = start(discord)
    assert discord.get(f"/auth/callback?code=boss&state={st}").status_code == 403
    assert discord.get("/api/me").status_code == 401


def test_디스코드_통신_실패하면_로그인_안됨(discord, monkeypatch):
    def boom(*a):
        raise RuntimeError("down")
    monkeypatch.setattr(auth, "fetch_discord_profile", boom)
    _, st = start(discord)
    assert discord.get(f"/auth/callback?code=boss&state={st}").status_code == 502
    assert discord.get("/api/me").status_code == 401


def test_설정이_없으면_로그인_주소는_503(client, monkeypatch):
    monkeypatch.delenv("DISCORD_CLIENT_ID", raising=False)
    assert client.get("/auth/login", follow_redirects=False).status_code == 503


def test_표시이름은_서버닉네임_우선(client):
    u = dict(username="acct", global_name="글로벌")
    assert auth.display_name(u, {"nick": "닉"}) == "닉"
    assert auth.display_name(u, {"nick": None}) == "글로벌"      # 서버 닉네임을 안 정한 사람
    assert auth.display_name(dict(username="acct", global_name=None), None) == "acct"


def test_서버가_지정된_경우_디스코드_멤버_조회가_404면_구성원_아님(client, monkeypatch):
    # fetch_discord_profile 실제 코드를 가짜 디스코드(MockTransport)로 돌린다
    import httpx
    monkeypatch.setenv("DISCORD_CLIENT_ID", "c"); monkeypatch.setenv("DISCORD_CLIENT_SECRET", "s")

    def handler(req):
        p = req.url.path
        if p.endswith("/oauth2/token"): return httpx.Response(200, json={"access_token": "t"})
        if p.endswith("/users/@me"): return httpx.Response(200, json={"id": "9", "username": "acct", "global_name": "글로벌"})
        if p.endswith("/guilds/G1/member"): return httpx.Response(200, json={"nick": "서버닉"})
        return httpx.Response(404, json={"message": "Unknown Guild"})
    real = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    assert auth.fetch_discord_profile("c", "u", "G1") == {"id": "9", "name": "서버닉", "in_guild": True}
    assert auth.fetch_discord_profile("c", "u", "OTHER")["in_guild"] is False
    assert auth.fetch_discord_profile("c", "u", "")["name"] == "글로벌"


def test_개발용_로그인은_EVAS_DEV_AUTH일_때만(client, monkeypatch):
    # 브라우저 WebSocket은 X-User-Id 헤더를 못 붙여서 개발 중엔 세션으로 로그인한다
    client.follow_redirects = False
    assert client.get("/auth/dev?uid=a&name=에이").status_code in (302, 307)
    assert client.get("/api/me").json()["name"] == "에이"
    client.cookies.clear()
    monkeypatch.delenv("EVAS_DEV_AUTH")
    assert client.get("/auth/dev?uid=a").status_code == 404
    assert client.get("/api/me").status_code == 401
