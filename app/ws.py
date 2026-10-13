"""메모별 실시간 공동 편집 방(Yjs 중계). pycrdt-websocket의 WebsocketServer/YRoom을 FastAPI WebSocket에 붙인다."""
from contextlib import asynccontextmanager

from fastapi import APIRouter, WebSocket, WebSocketDisconnect
from pycrdt import Doc
from pycrdt.websocket import WebsocketServer


class _Channel:
    """FastAPI WebSocket을 pycrdt의 Channel 규약(path/send/recv/async 반복)에 맞춘 어댑터."""

    def __init__(self, ws: WebSocket, path: str):
        self._ws, self._path = ws, path

    @property
    def path(self) -> str:
        return self._path

    def __aiter__(self):
        return self

    async def __anext__(self) -> bytes:
        return await self.recv()

    async def send(self, message: bytes) -> None:
        await self._ws.send_bytes(message)

    async def recv(self) -> bytes:
        try:
            return await self._ws.receive_bytes()
        except WebSocketDisconnect:
            raise StopAsyncIteration


class Rooms:
    """메모 id별 방 관리자. shortcut: 문서는 메모리에만 있다(방이 비면 사라짐) -> Task 3에서 DB 로드/저장으로 교체."""

    def __init__(self):
        self.server = WebsocketServer(auto_clean_rooms=True)

    async def get_doc(self, memo_id) -> Doc:
        return (await self.server.get_room(str(memo_id))).ydoc


rooms = Rooms()
router = APIRouter()


@asynccontextmanager
async def lifespan(_app):
    async with rooms.server:
        yield


@router.websocket("/ws/memos/{memo_id}")
async def memo_ws(websocket: WebSocket, memo_id: int):
    await websocket.accept()
    await rooms.server.serve(_Channel(websocket, str(memo_id)))
