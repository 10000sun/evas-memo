"""이미지 첨부. 메모 본문에는 링크 [📎 이름](/files/<긴 무작위 이름>.png)만 들어가고, 파일은 data/uploads/에 따로 둔다
(DB·본문 100,000자 제한과 무관하고, DB 백업·복구에도 들어가지 않는다).

메모 권한은 따로 보지 않는다: 주소가 추측할 수 없는 무작위 값이고, 그 메모를 볼 수 있는 사람만 링크를 보기 때문이다.
대신 로그인한 사람만 열 수 있다. 종류는 내용의 첫 바이트로 확인하고(보낸 사람이 말한 형식은 믿지 않는다), SVG·HTML은 받지 않는다.
shortcut: 메모를 지워도 이미지 파일은 남는다(링크가 다른 메모로 복사됐을 수 있어서). 디스크가 문제가 되면 안 쓰는 파일 정리 작업을 따로.
"""
import os
import re
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse

from . import db
from .auth import current_user, editor

router = APIRouter()
MAX = 5 * 1024 * 1024
MIME = {"png": "image/png", "jpg": "image/jpeg", "gif": "image/gif", "webp": "image/webp"}
NAME = re.compile(r"^[0-9a-f]{32}\.(png|jpg|gif|webp)$")


def uploads_dir():
    return os.environ.get("EVAS_UPLOAD_DIR") or os.path.join(os.path.dirname(db.db_path()) or ".", "uploads")


def sniff(b):
    """내용으로 이미지 종류(확장자). 허용 목록 밖이면 None."""
    if b.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if b.startswith(b"\xff\xd8\xff"):
        return "jpg"
    if b[:6] in (b"GIF87a", b"GIF89a"):
        return "gif"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "webp"
    return None


def clean(name):
    """링크 글로 쓸 파일 이름: 링크 문법을 깨는 글자와 줄바꿈을 뺀다."""
    return re.sub(r"[\[\]()\\<>\r\n\t]", "", name).strip()[:60]


@router.post("/api/files", status_code=201)
async def upload(request: Request, name: str = "", user=Depends(editor)):
    if int(request.headers.get("content-length") or 0) > MAX:
        raise HTTPException(413, "이미지는 5MB까지 올릴 수 있습니다")
    data = b""
    async for chunk in request.stream():  # 길이를 속여도 넘치는 순간 멈춘다
        data += chunk
        if len(data) > MAX:
            raise HTTPException(413, "이미지는 5MB까지 올릴 수 있습니다")
    ext = sniff(data)
    if not ext:
        raise HTTPException(422, "PNG·JPG·GIF·WebP 이미지만 올릴 수 있습니다")
    d = uploads_dir()
    os.makedirs(d, exist_ok=True)
    fname = f"{secrets.token_hex(16)}.{ext}"
    tmp = os.path.join(d, fname + ".tmp")
    with open(tmp, "wb") as f:
        f.write(data)
    os.replace(tmp, os.path.join(d, fname))  # 쓰는 도중의 파일이 열리지 않게
    return {"url": f"/files/{fname}", "name": clean(name) or f"이미지.{ext}"}


@router.get("/files/{fname}")
def get_file(fname: str, _=Depends(current_user)):
    path = os.path.join(uploads_dir(), fname)
    if not NAME.match(fname) or not os.path.isfile(path):
        raise HTTPException(404)
    # 이름이 곧 내용의 해시 같은 값이라 바뀌지 않는다 -> 오래 캐시. nosniff·CSP: 혹시 이미지가 아닌 것이 들어와도 실행되지 않게
    return FileResponse(path, media_type=MIME[fname.rsplit(".", 1)[1]], headers={
        "Cache-Control": "private, max-age=31536000, immutable", "X-Content-Type-Options": "nosniff",
        "Content-Security-Policy": "default-src 'none'; img-src 'self'", "Content-Disposition": "inline"})
