"""배포 안내(changes.json): 형식이 맞아야 팝업이 뜬다."""
import json
from pathlib import Path


def test_changes_json_is_valid_and_served(client):
    data = json.loads((Path(__file__).parent.parent / "static" / "changes.json").read_text(encoding="utf-8"))
    ids = [r["id"] for r in data]
    assert ids == sorted(ids, reverse=True) and len(set(ids)) == len(ids)  # 최신이 맨 앞, 중복 없음
    for r in data:
        assert r["title"] and r["items"] and all(i["text"] for i in r["items"])
    assert client.get("/changes.json").status_code == 200
    assert 'src="whatsnew.js"' in client.get("/").text


def test_static_files_are_revalidated_on_every_open(client):
    # 홈 화면에 추가한 앱도 새 배포를 바로 받게: 캐시 지시가 없으면 브라우저가 옛 파일을 며칠 쓴다
    for path in ("/", "/app.js", "/changes.json"):
        assert client.get(path).headers["cache-control"] == "no-cache"
