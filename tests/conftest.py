import importlib
import os
import tempfile

import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def no_real_peer_calls(monkeypatch):
    """권한 동기화가 실제 캘린더 주소로 접속하지 않게 한다(LINK_API_KEY를 켠 테스트에서 연결 대기로 느려진다). 필요한 테스트가 직접 바꿔 끼운다"""
    from app import usersync
    monkeypatch.setattr(usersync, "push", lambda *a, **k: None)


@pytest.fixture
def client():
    # 운영 DB를 건드리지 않도록 import 전에 임시 DB로 돌린다
    os.environ["EVAS_DB"] = os.path.join(tempfile.mkdtemp(), "t.db")
    os.environ["EVAS_DEV_AUTH"] = "1"
    os.environ["EVAS_ADMIN_IDS"] = "boss"
    import app.main
    importlib.reload(app.main)
    return TestClient(app.main.app)


def as_(uid):
    return {"X-User-Id": uid}
