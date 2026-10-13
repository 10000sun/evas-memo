"""화면 파일이 사이트 루트에서 나오는지(캘린더처럼 / 에 정적 파일). 화면 동작 자체는 브라우저로 수동 확인한다."""


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200
    assert "<title>에바스 메모</title>" in r.text


def test_admin_page_served(client):
    r = client.get("/admin.html")
    assert r.status_code == 200
    assert "관리" in r.text


def test_editor_bundle_served(client):
    assert client.get("/vendor/editor.bundle.js").status_code == 200


def test_export_function_present(client):
    r = client.get("/common.js")
    assert r.status_code == 200
    assert "exportMemo" in r.text


def test_api_still_wins_over_static(client):
    # 루트 정적 마운트가 API를 가리면 안 된다
    assert client.get("/api/me").status_code == 401


def test_markdown_bundle_served(client):
    r = client.get("/vendor/markdown.bundle.js")
    assert r.status_code == 200
    assert "EvasMarkdown" in r.text


def test_index_has_preview_toggle(client):
    t = client.get("/").text
    assert 'data-mode="preview"' in t and 'id="e-preview"' in t
    assert "vendor/markdown.bundle.js" in t
