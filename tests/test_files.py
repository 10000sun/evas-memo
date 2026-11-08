"""이미지 첨부: 종류는 내용으로 확인, 5MB 제한, 로그인한 사람만 열람, 이름으로 다른 경로를 못 연다."""
import os

from app import files
from tests.conftest import as_

PNG = b"\x89PNG\r\n\x1a\n" + b"x" * 20
JPG = b"\xff\xd8\xff\xe0" + b"x" * 20
GIF = b"GIF89a" + b"x" * 20
WEBP = b"RIFF\x00\x00\x00\x00WEBP" + b"x" * 20
ED = as_("boss")


def up(client, data, name="a.png", who=ED):
    return client.post(f"/api/files?name={name}", content=data, headers=who)


def test_upload_and_view_each_type(client):
    for data, ext in ((PNG, "png"), (JPG, "jpg"), (GIF, "gif"), (WEBP, "webp")):
        r = up(client, data, f"사진.{ext}")
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["url"].startswith("/files/") and body["url"].endswith("." + ext) and body["name"] == f"사진.{ext}"
        got = client.get(body["url"], headers=ED)
        assert got.status_code == 200 and got.content == data and got.headers["content-type"] == files.MIME[ext]
        assert got.headers["x-content-type-options"] == "nosniff" and "immutable" in got.headers["cache-control"]
        assert "default-src 'none'" in got.headers["content-security-policy"]


def test_only_real_images_are_accepted(client):
    assert up(client, b"<svg onload=alert(1)></svg>", "x.png").status_code == 422  # 이름이 png여도 내용으로 본다
    assert up(client, b"<html><script>alert(1)</script>", "x.png").status_code == 422
    assert up(client, b"", "x.png").status_code == 422
    assert up(client, b"GIF89", "x.gif").status_code == 422


def test_size_limit(client, monkeypatch):
    monkeypatch.setattr(files, "MAX", 100)
    assert up(client, PNG + b"x" * 200).status_code == 413
    assert up(client, PNG).status_code == 201


def test_login_required_and_bad_names(client):
    url = up(client, PNG).json()["url"]
    assert client.get(url).status_code == 401  # 로그인 필요
    assert client.get(url, headers=as_("anyone")).status_code == 200  # 로그인만 하면 메모 권한과 무관하게 열림(주소가 비밀)
    for bad in ("/files/..%2F..%2Fevas.db", "/files/" + "0" * 32 + ".png", "/files/abc.png", "/files/" + "0" * 32 + ".svg"):
        assert client.get(bad, headers=ED).status_code == 404
    assert client.post("/api/files", content=PNG).status_code == 401


def test_name_is_cleaned_for_the_link(client):
    assert up(client, PNG, "a[1](x)\\.png").json()["name"] == "a1x.png"
    assert up(client, PNG, "").json()["name"] == "이미지.png"
    assert len(up(client, PNG, "가" * 200 + ".png").json()["name"]) == 60


def test_files_live_outside_the_db_and_are_not_guessable(client):
    names = {up(client, PNG).json()["url"] for _ in range(5)}
    assert len(names) == 5
    assert all(os.path.exists(os.path.join(files.uploads_dir(), n.rsplit("/", 1)[1])) for n in names)
