import importlib
import os
import tempfile

import pytest
from fastapi.testclient import TestClient


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
