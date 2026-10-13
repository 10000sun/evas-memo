"""실시간 편집 연결: 접근 제어, DB 저장·복원, 100,000자 제한, 보기 전용, 동시 입력 병합."""
import queue
import threading
import time

import pytest
from pycrdt import Doc, Text, YMessageType, create_sync_message, create_update_message, handle_sync_message
from starlette.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from app import auth, db, ws
from tests.conftest import as_
from tests.test_memos import new


class Peer:
    """TestClient 웹소켓 + pycrdt Doc. 읽기는 스레드로 받아 큐에 쌓는다(TestClient는 수신 타임아웃이 없다)."""

    def __init__(self, ws_):
        self.ws, self.doc, self.q = ws_, Doc(), queue.Queue()
        self.text = self.doc.get("text", type=Text)
        self.updates, self.closed = [], None
        self.doc.observe(lambda ev: self.updates.append(ev.update))
        threading.Thread(target=self._read, daemon=True).start()
        self.ws.send_bytes(create_sync_message(self.doc))
        self.pump()

    def _read(self):
        try:
            while True:
                self.q.put(self.ws.receive_bytes())
        except Exception as e:  # 서버가 닫으면 닫기 코드를 남긴다
            self.closed = e

    def pump(self, quiet=0.5):
        """조용해질 때까지 서버 메시지를 doc에 반영한다."""
        while True:
            try:
                msg = self.q.get(timeout=quiet)
            except queue.Empty:
                return
            if msg[0] == YMessageType.SYNC:
                reply = handle_sync_message(msg[1:], self.doc)
                if reply is not None:
                    self.ws.send_bytes(reply)

    def push(self):
        for upd in self.updates:
            self.ws.send_bytes(create_update_message(upd))
        self.updates.clear()


@pytest.fixture
def c(client, monkeypatch):
    monkeypatch.delenv("EVAS_OPEN_EDIT", raising=False)
    for uid in ("a", "b"):
        client.put(f"/api/users/{uid}", json=dict(name=uid, role="editor"), headers=as_("boss"))
    return client


def connect(c, mid, uid=None):
    return c.websocket_connect(f"/ws/memos/{mid}", headers=as_(uid) if uid else {})


def rejected(c, mid, uid=None):
    with pytest.raises(WebSocketDisconnect) as e:
        with connect(c, mid, uid) as w:
            w.receive_bytes()
    return e.value.code


def body_in_db(mid):
    with db.connect() as con:
        return con.execute("SELECT body_text FROM memos WHERE id=?", (mid,)).fetchone()["body_text"]


def wait_body(mid, want, timeout=1.0):
    end = time.time() + timeout
    while body_in_db(mid) != want and time.time() < end:
        time.sleep(0.05)
    return body_in_db(mid)


def test_ws_rejects_other_users_personal_memo(c):
    m = new(c, "a", "personal")["id"]
    with c:
        for uid in ("b", "boss", "v"):  # 관리자도 남의 개인 메모에 못 붙는다
            assert rejected(c, m, uid) == 1008
        with connect(c, m, "a") as w:
            assert w.receive_bytes()[0] == YMessageType.SYNC


def test_ws_rejects_anonymous_and_unknown_id(c):
    m = new(c, "a", "shared")["id"]
    with c:
        assert rejected(c, m) == 1008
        assert rejected(c, 9999, "a") == 1008


def test_ws_accepts_session_login(c, monkeypatch):
    monkeypatch.setenv("DISCORD_CLIENT_ID", "cid")
    monkeypatch.setenv("DISCORD_CLIENT_SECRET", "sec")
    monkeypatch.setenv("PUBLIC_URL", "https://memo.example.com")
    monkeypatch.delenv("DISCORD_GUILD_ID", raising=False)
    monkeypatch.setattr(auth, "fetch_discord_profile", lambda code, uri, gid: dict(id=code, name=code, in_guild=True))
    m = new(c, "a", "personal")["id"]
    c.follow_redirects = False
    state = c.get("/auth/login").headers["location"].split("state=")[1].split("&")[0]
    c.get(f"/auth/callback?code=a&state={state}")
    with c:
        with connect(c, m) as w:  # 헤더 없이 세션 쿠키만으로
            assert w.receive_bytes()[0] == YMessageType.SYNC


def test_body_persists_across_server_restart(c):
    m = new(c, "a", "shared")["id"]
    with c:
        with connect(c, m, "a") as w:
            p = Peer(w)
            p.text += "안녕하세요"
            p.push()
            p.pump()
        # 마지막 접속자가 나가면 바로 저장(2초 디바운스를 기다리지 않는다)
        assert wait_body(m, "안녕하세요") == "안녕하세요"
    got = c.get(f"/api/memos/{m}", headers=as_("b")).json()
    assert got["updated_name"] == "a"
    ws.rooms = ws.Rooms()  # 메모리에 남은 방을 버린다(서버 재시작)
    with TestClient(c.app) as c2:
        with connect(c2, m, "b") as w:
            assert str(Peer(w).text) == "안녕하세요"
    assert c.get(f"/api/memos/{m}", headers=as_("b")).json() == got  # 열어 보기만 하면 수정으로 치지 않는다


def test_debounced_save_while_editing(c):
    m = new(c, "a", "shared")["id"]
    with c:
        with connect(c, m, "a") as w:
            p = Peer(w)
            p.text += "저장"
            p.push()
            assert wait_body(m, "저장", timeout=4) == "저장"  # 연결이 열린 채로도 저장된다


def test_body_over_100000_chars_rejected(c):
    m = new(c, "a", "shared")["id"]
    with c:
        with connect(c, m, "a") as w:
            p = Peer(w)
            p.text += "x" * 100_000  # 딱 100,000자는 된다
            p.push()
            p.pump()
            assert p.closed is None
            p.text += "!"
            p.push()
            p.pump()
            assert isinstance(p.closed, WebSocketDisconnect) and p.closed.code == 1009
        with connect(c, m, "b") as w:
            assert str(Peer(w).text) == "x" * 100_000  # 문서는 바뀌지 않았다
    assert body_in_db(m) == "x" * 100_000


def test_two_users_edit_shared_memo_merge(c):
    m = new(c, "a", "shared")["id"]
    with c:
        with connect(c, m, "a") as wa, connect(c, m, "b") as wb:
            p1, p2 = Peer(wa), Peer(wb)
            # 같은 위치(0)에 서로 모르는 채로 동시에 입력한다
            p1.text.insert(0, "A")
            p2.text.insert(0, "B")
            p1.push()
            p2.push()
            for _ in range(2):
                for p in (p1, p2):
                    p.pump()
            assert str(p1.text) == str(p2.text)
            assert sorted(str(p1.text)) == ["A", "B"]
        assert wait_body(m, str(p1.text)) == str(p1.text)


def test_viewer_cannot_edit_shared_memo(c):
    m = new(c, "a", "shared")["id"]
    with c:
        with connect(c, m, "a") as wa:
            pa = Peer(wa)
            pa.text += "원본"
            pa.push()
            pa.pump()
            with connect(c, m, "v") as wv:
                pv = Peer(wv)
                assert str(pv.text) == "원본"  # 읽기는 된다
                pv.text += "낙서"
                pv.push()
                pv.pump()
                pa.pump()
                assert str(pa.text) == "원본" and pv.closed is None
    assert body_in_db(m) == "원본"


def test_text_frame_closes_connection_cleanly(c):
    m = new(c, "a", "shared")["id"]
    with c:
        with connect(c, m, "a") as w:
            w.receive_bytes()
            w.send_text("hello")
            with pytest.raises(WebSocketDisconnect) as e:
                while True:
                    w.receive_bytes()
            assert e.value.code == 1003
        with connect(c, m, "a") as w:  # 서버는 멀쩡하다
            assert str(Peer(w).text) == ""
