"""메모별 실시간 공동 편집 방(Yjs 중계). pycrdt-websocket의 WebsocketServer/YRoom을 FastAPI WebSocket에 붙인다.

방은 DB의 memos.ydoc에서 복원하고, 바뀌면 SAVE_DELAY초 안에, 마지막 접속자가 나갈 때, 서버가 꺼질 때 저장한다.
"""
import asyncio
from contextlib import asynccontextmanager

from fastapi import APIRouter, WebSocket
from pycrdt import Doc, Text, YMessageType, YSyncMessageType, create_update_message, read_message
from pycrdt.websocket import WebsocketServer, YRoom

from . import auth, db

MAX_CHARS = 100_000
MAX_BYTES = 5_000_000  # 들어오는 업데이트와 문서 전체(Yjs 상태) 바이트 상한. text 밖 루트 타입으로 키우는 것도 막는다
SAVE_DELAY = 2  # 초. 편집이 계속돼도 첫 변경 뒤 이만큼 지나면 저장한다(재시작 손실을 줄이려고 미루기만 하지 않는다)
_EDITS = (YSyncMessageType.SYNC_STEP2, YSyncMessageType.SYNC_UPDATE)  # 문서를 바꾸는 동기화 메시지


def body(doc: Doc) -> str:
    return str(doc.get("text", type=Text))  # 에디터(EvasEditor)가 쓰는 공유 텍스트 이름


def can_access(memo, user) -> bool:
    """공동은 로그인한 누구나, 개인은 소유자만(관리자도 예외 없음)."""
    return memo["kind"] == "shared" or memo["owner_id"] == user["id"]


def can_edit(memo, user) -> bool:
    """공동은 편집자·관리자만(보기 전용은 읽기만), 개인은 소유자."""
    return can_access(memo, user) and (memo["kind"] == "personal" or user["role"] in ("admin", "editor"))


def _integrate(doc: Doc, update: bytes) -> bytes | None:
    """update를 문서 사본에 적용해 보고, 제한 안이면 실제로 합쳐진 부분(diff)을, 넘으면 None을 돌려준다.

    방에는 원본 update 대신 diff만 넣는다. 선행 업데이트가 빠져 보류(pending)된 조각은 get_update에 안 나오므로
    버려진다 -> 방 문서에 보이지 않는 보류분이 쌓였다가 나중에 한꺼번에 합쳐지며 제한을 넘는 일이 없다.
    """
    if len(update) > MAX_BYTES:
        return None
    trial = Doc()
    trial.apply_update(doc.get_update())
    trial.apply_update(update)
    if len(body(trial)) > MAX_CHARS or len(trial.get_update()) > MAX_BYTES:
        return None
    return trial.get_update(doc.get_state())


class _Room(YRoom):
    """DB 메모 한 개의 방. 바뀌면 SAVE_DELAY초 뒤에 ydoc/body_text/updated_*를 저장한다."""

    def __init__(self, memo_id: int):
        doc = Doc()
        with db.connect() as con:
            row = con.execute("SELECT ydoc FROM memos WHERE id=?", (memo_id,)).fetchone()
        if row and row["ydoc"]:
            doc.apply_update(row["ydoc"])
        super().__init__(ydoc=doc)
        # editor: 지금 편집 메시지를 보낸 사람, changed_by: 실제로 문서를 바꾼 마지막 사람(저장에 쓴다)
        self.memo_id, self.editor, self.changed_by, self._timer = memo_id, None, None, None
        self._sub = doc.observe(self._changed)

    def _changed(self, _event):
        self.changed_by = self.editor
        if self._timer is None:
            self._timer = asyncio.get_running_loop().call_later(SAVE_DELAY, self.save)

    def save(self):
        """바뀐 게 있으면 지금 저장한다. 동기 함수라 저장 도중에 다른 접속이 끼어들지 않는다."""
        if self._timer is None:
            return
        self._timer.cancel()
        self._timer = None
        u = self.changed_by or {}
        with db.connect() as con:
            con.execute("UPDATE memos SET ydoc=?, body_text=?, updated_by=COALESCE(?, updated_by), "
                        "updated_name=COALESCE(?, updated_name), updated_at=? WHERE id=?",
                        (self.ydoc.get_update(), body(self.ydoc), u.get("id"), u.get("name"), db.now(),
                         self.memo_id))

    def discard(self):
        """저장하지 않는다(메모가 지워짐)."""
        if self._timer:
            self._timer.cancel()
        self._timer = None

    async def stop(self):
        self.ydoc.unobserve(self._sub)
        await super().stop()
        # 구독 객체는 만든 스레드에서 버려야 한다(아니면 종료 때 "Subscription is unsendable" 경고)
        self._sub = self._subscription = None


class _Server(WebsocketServer):
    async def get_room(self, name: str) -> YRoom:
        if name not in self.rooms:
            self.rooms[name] = _Room(int(name))
        return await super().get_room(name)

    async def delete_room(self, *, name=None, room=None):
        room = room or self.rooms[name]
        if room not in self.rooms.values():
            return  # 메모 삭제로 이미 내린 방(Rooms.drop)
        # 마지막 접속자가 나감: 방을 내리기 전에 저장해야 곧바로 들어온 사람이 옛 DB를 읽지 않는다
        room.save()
        await super().delete_room(room=room)


class Rooms:
    """메모 id별 방 관리자. 서버 객체는 이벤트 루프에 묶이므로 앱이 시작할 때마다 새로 만든다(lifespan)."""

    def __init__(self):
        self.server = _Server(auto_clean_rooms=True)

    def get(self, memo_id):
        """열려 있는 방(없으면 None)."""
        return self.server.rooms.get(str(memo_id))

    async def drop(self, memo_id, code=4404, reason="메모가 삭제되었습니다"):
        """메모 삭제: 저장하지 않고 방을 내리고 접속자를 끊는다.

        DB 삭제 직후 await 없이 방을 빼야 한다: 그 사이 같은 id(AUTOINCREMENT 없는 옛 DB)의 새 메모가 옛 방에 붙지 않게.
        """
        room = self.server.rooms.pop(str(memo_id), None)
        if room is None:
            return
        room.discard()
        for ch in list(room.clients):
            await ch.close(code, reason)
        await room.stop()


rooms = Rooms()
router = APIRouter()


async def get_doc(memo_id) -> Doc:
    """DB의 ydoc로 복원한 방의 문서(이미 열려 있으면 그 방)."""
    return (await rooms.server.get_room(str(memo_id))).ydoc


@asynccontextmanager
async def lifespan(_app):
    global rooms
    rooms = Rooms()
    async with rooms.server:
        try:
            yield
        finally:
            for name in list(rooms.server.rooms):  # 꺼지기 전에 모두 저장하고 내린다
                await rooms.server.delete_room(name=name)


class _Channel:
    """FastAPI WebSocket을 pycrdt의 Channel 규약(path/send/recv/async 반복)에 맞춘 어댑터.

    받은 메시지를 방에 넘기기 전에 거른다: 보기 전용의 편집은 버리고, 100,000자를 넘기는 편집은 연결을 1009로 닫는다.
    """

    def __init__(self, ws: WebSocket, path: str, user: dict, can_edit: bool, room: _Room):
        self._ws, self._path, self.user, self.can_edit, self.room = ws, path, user, can_edit, room
        self.closed = False

    @property
    def path(self) -> str:
        return self._path

    def __aiter__(self):
        return self

    async def __anext__(self) -> bytes:
        return await self.recv()

    async def send(self, message: bytes) -> None:
        try:
            await self._ws.send_bytes(message)
        except Exception:  # 막 끊긴 연결: 방 전체(다른 접속자)를 죽이지 않는다. 끊김은 recv가 처리한다
            pass

    async def close(self, code: int, reason: str = "") -> None:
        self.closed = True
        try:
            await self._ws.close(code, reason)
        except Exception:  # 이미 끊김
            pass

    async def recv(self) -> bytes:
        while True:
            msg = await self._ws.receive()
            if msg["type"] == "websocket.disconnect" or self.closed:
                raise StopAsyncIteration
            data = msg.get("bytes")
            if not data:  # 텍스트 프레임 등 Yjs가 아닌 메시지
                await self.close(1003)
                raise StopAsyncIteration
            if data[0] == YMessageType.SYNC and len(data) > 1 and data[1] in _EDITS:
                if not self.can_edit:
                    continue  # 보기 전용: 받기만 하고 적용하지 않는다
                diff = _integrate(self.room.ydoc, read_message(data[2:]))
                if diff is None:
                    await self.close(1009, "본문은 100,000자까지입니다")  # 메시지가 너무 큼
                    raise StopAsyncIteration
                self.room.editor = self.user
                return create_update_message(diff)
            return data


@router.websocket("/ws/memos/{memo_id}")
async def memo_ws(websocket: WebSocket, memo_id: int):
    # 수락 전에 확인한다. 로그인 안 함·없는 메모·남의 개인 메모를 구별하지 않고 1008(정책 위반)로 닫는다
    user = auth.user_of(websocket.session, websocket.headers.get("x-user-id"))
    with db.connect() as con:
        memo = con.execute("SELECT kind, owner_id FROM memos WHERE id=?", (memo_id,)).fetchone()
    if not user or not memo or not can_access(memo, user):
        await websocket.close(1008)
        return
    await websocket.accept()
    room = await rooms.server.get_room(str(memo_id))
    await rooms.server.serve(_Channel(websocket, str(memo_id), user, can_edit(memo, user), room))
