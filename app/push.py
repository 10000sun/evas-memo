"""공동 메모가 추가·삭제되면 구독한 폰·브라우저로 웹 푸시를 보낸다. VAPID 키가 .env에 없으면 아무것도 하지 않는다."""
import json
import os
from urllib.parse import urlparse

from . import db

KIND = {"add": "추가", "delete": "삭제"}
# 구독 주소로 서버가 직접 요청을 보내므로, 알려진 푸시 서비스 주소만 받는다(서버가 임의 주소로 요청하는 것을 막는다)
PUSH_HOSTS = ("push.apple.com", "fcm.googleapis.com", "push.services.mozilla.com", "notify.windows.com")


def allowed(endpoint: str) -> bool:
    u = urlparse(endpoint)
    host = u.hostname or ""
    return u.scheme == "https" and any(host == h or host.endswith("." + h) for h in PUSH_HOSTS)


def text(kind, name, title):
    return f"{name}님이 공동 메모를 {KIND[kind]}했습니다: {title or '(제목 없음)'}"


def notify(kind, title, user):
    """바꾼 사람 자신을 뺀 모든 구독자에게 보낸다. 한 곳이 실패해도 나머지는 계속 보낸다."""
    key = os.environ.get("VAPID_PRIVATE_KEY")
    if not key:
        return
    try:
        from pywebpush import WebPushException, webpush  # 패키지가 없어도 앱이 뜨도록 쓸 때 불러온다
    except ImportError:
        return
    data = json.dumps({"title": "에바스 메모", "body": text(kind, user["name"], title)}, ensure_ascii=False)
    with db.connect() as con:
        for s in con.execute("SELECT * FROM push_subs WHERE user_id != ?", (user["id"],)).fetchall():
            try:
                webpush({"endpoint": s["endpoint"], "keys": {"p256dh": s["p256dh"], "auth": s["auth"]}}, data=data,
                        vapid_private_key=key, ttl=86400, timeout=10,
                        vapid_claims={"sub": os.environ.get("VAPID_SUBJECT", "mailto:admin@example.com")})
            except WebPushException as e:
                if e.response is not None and e.response.status_code in (404, 410):  # 앱을 지웠거나 알림을 끈 기기
                    con.execute("DELETE FROM push_subs WHERE endpoint=?", (s["endpoint"],))
            except Exception:
                pass
