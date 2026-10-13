import json
import struct
from pathlib import Path

STATIC = Path(__file__).parent.parent / "static"


def png_size(path):
    d = path.read_bytes()
    assert d[:8] == b"\x89PNG\r\n\x1a\n", f"PNG가 아님: {path}"
    return struct.unpack(">II", d[16:24])  # IHDR의 가로·세로


def test_매니페스트의_아이콘이_실제로_있고_선언한_크기와_같다(client):
    m = client.get("/manifest.json")  # 로그인 없이도 받아야 설치 화면이 뜬다
    assert m.status_code == 200
    data = m.json()
    assert data["display"] == "standalone" and data["start_url"] == "/"
    assert data["icons"], "아이콘이 없으면 설치 가능으로 인정되지 않는다"
    for ic in data["icons"]:
        w, h = map(int, ic["sizes"].split("x"))
        assert png_size(STATIC / ic["src"]) == (w, h), ic["src"]
        assert client.get("/" + ic["src"]).status_code == 200


def test_두_페이지_모두_매니페스트와_아이폰_아이콘을_연결(client):
    for page in ("index.html", "admin.html"):
        html = (STATIC / page).read_text(encoding="utf-8")
        assert 'rel="manifest" href="manifest.json"' in html, page
        assert 'rel="icon" href="icons/icon.svg"' in html, page  # 브라우저 탭 아이콘
        assert 'rel="apple-touch-icon" href="icons/apple-touch-icon.png"' in html, page
    assert png_size(STATIC / "icons/apple-touch-icon.png") == (180, 180)  # iOS가 요구하는 크기


def test_로그인_없이_정적_파일은_열리고_API는_여전히_막힘(client):
    assert client.get("/icons/icon-192.png").status_code == 200
    assert client.get("/api/me").status_code == 401


def test_매니페스트_이름과_서비스워커(client):
    assert client.get("/manifest.json").json()["name"] == "에바스 메모"
    r = client.get("/sw.js")
    assert r.status_code == 200
    # 푸시 전용: fetch를 가로채면 /api·/auth·/ws(웹소켓)가 깨지거나 캐시될 수 있다
    assert '"fetch"' not in r.text and "'fetch'" not in r.text and "caches" not in r.text
    assert "에바스 메모" in r.text
