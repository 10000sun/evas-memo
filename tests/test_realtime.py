"""실시간 공동 편집: 두 클라이언트가 같은 메모에 동시에 입력해도 같은 결과로 합쳐진다."""
import queue
import threading

from pycrdt import Doc, Text, YMessageType, create_sync_message, create_update_message, handle_sync_message
from starlette.testclient import TestClient

from app.main import app


class Peer:
    """TestClient 웹소켓 + pycrdt Doc. 읽기는 스레드로 받아 큐에 쌓는다(TestClient는 수신 타임아웃이 없다)."""

    def __init__(self, ws):
        self.ws, self.doc, self.q = ws, Doc(), queue.Queue()
        self.text = self.doc.get("text", type=Text)
        self.updates = []
        self.doc.observe(lambda ev: self.updates.append(ev.update))
        threading.Thread(target=self._read, daemon=True).start()

    def _read(self):
        try:
            while True:
                self.q.put(self.ws.receive_bytes())
        except Exception:
            pass

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


def test_two_clients_merge_concurrent_inserts():
    with TestClient(app) as client:
        with client.websocket_connect("/ws/memos/1") as a, client.websocket_connect("/ws/memos/1") as b:
            p1, p2 = Peer(a), Peer(b)
            for p in (p1, p2):
                p.ws.send_bytes(create_sync_message(p.doc))
            for p in (p1, p2):
                p.pump()
            # 같은 위치(0)에 서로 모르는 채로 동시에 입력한다
            p1.text.insert(0, "A")
            p2.text.insert(0, "B")
            for p in (p1, p2):
                for upd in p.updates:
                    p.ws.send_bytes(create_update_message(upd))
            for _ in range(2):
                for p in (p1, p2):
                    p.pump()
    assert str(p1.text) == str(p2.text)
    assert "A" in str(p1.text) and "B" in str(p1.text)
