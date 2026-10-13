"""화면 파일이 사이트 루트에서 나오는지(캘린더처럼 / 에 정적 파일). 화면 동작 자체는 브라우저로 수동 확인한다."""
import shutil
import subprocess
from pathlib import Path

import pytest


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


def test_index_has_folder_ui(client):
    t = client.get("/").text
    for i in ("folders", "subfolders", "folder-tools", "f-rename", "f-delete", "e-folder"):
        assert f'id="{i}"' in t, i
    assert t.index('id="folders"') < t.index('id="memos"')  # 폴더 줄은 목록 위


def test_index_has_link_ui(client):
    t = client.get("/").text
    assert '<nav class="apps" aria-label="앱 전환">' in t and 'id="to-cal"' in t and 'aria-current="page"' in t
    assert 'id="e-links"' in t and t.index('id="e-links"') < t.index('id="e-body"')  # 연결 칩 줄은 본문 위
    assert t.index('src="memolink.js"') < t.index('src="app.js"')
    assert client.get("/memolink.js").status_code == 200


def test_link_hints_above_cursor_and_text_only(client):
    bundle = client.get("/vendor/editor.bundle.js").text
    fail = "".join(f"\\u{ord(c):04X}" if ord(c) > 127 else c for c in "연결할 수 없습니다")
    assert "aboveCursor:!0" in bundle and fail in bundle  # 힌트는 커서 위쪽, 실패는 한 줄 안내(esbuild가 한글을 \uXXXX로 쓴다)
    assert "failed:!0" in bundle  # 실패 안내 행은 표시만: Enter는 본문으로 넘긴다(failGuard, 동작은 브라우저 수동 확인)
    app_js = client.get("/app.js").text
    # 화면에서 HTML로 넣는 곳은 무해화한 미리보기 하나뿐(제목·칩·힌트는 textContent)
    assert app_js.count("innerHTML") == 1 and "EvasMarkdown.render" in app_js
    assert "/auth/login?next=" in client.get("/common.js").text  # 로그인 뒤 딥링크로 돌아온다


@pytest.mark.skipif(not shutil.which("node"), reason="node가 없으면 파서 단위 테스트는 건너뛴다")
def test_memolink_node_unit_tests():
    r = subprocess.run(["node", "--test", str(Path(__file__).parent / "memolink.test.js")],
                       capture_output=True, text=True, encoding="utf-8", timeout=60)
    assert r.returncode == 0, r.stdout + r.stderr


def test_admin_space_not_in_static_page(client):
    # 전율 탭·옮기기 버튼·안내는 관리자에게만 app.js가 만든다: 정적 HTML에는 흔적이 없어야 한다
    t = client.get("/").text
    assert "전율" not in t and "data-tab=" not in t
    assert 'id="tabs"' in t and 'id="e-moves"' in t and 'id="help-basic"' in t


def test_admin_space_ui_rules(client):
    a = client.get("/app.js").text
    assert 'admin: {' in a and 'scope: "admin"' in a and "visible: isAdmin" in a
    for s in ("관리자만 볼 수 있게 됩니다(공동 메모였다면 다른 사람에게는 사라집니다)", "모든 사람에게 보입니다",
              "나만 볼 수 있게 됩니다(다른 관리자에게도 사라집니다)", "관리자 권한이 없어 닫혔습니다"):
        assert s in a, s
    assert "/move`" in a and "code === 4403" in a


def test_index_has_share_ui(client):
    html = client.get("/").text
    for el in ('id="share-dlg"', 'id="e-share"', 'id="f-share"', 'id="sh-save"', 'name="sh-mode"'):
        assert el in html, el
    js = client.get("/app.js").text
    assert "/share-with" in js and "/api/members/pick" in js and "user:" in js or "kind === \"user\"" in js
