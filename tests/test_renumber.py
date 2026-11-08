"""번호 목록 자동 정렬(tools/renumber.js). node와 tools/node_modules가 있을 때만 돈다(없으면 건너뜀)."""
import shutil
import subprocess
from pathlib import Path

import pytest

TOOLS = Path(__file__).parent.parent / "tools"


@pytest.mark.skipif(not shutil.which("node") or not (TOOLS / "node_modules").exists(), reason="node 또는 tools/node_modules 없음")
def test_renumber():
    r = subprocess.run(["node", "test-renumber.mjs"], cwd=TOOLS, capture_output=True, text=True)
    assert r.returncode == 0 and "renumber: ok" in r.stdout, r.stdout + r.stderr
