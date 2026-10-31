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
