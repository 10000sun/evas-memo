r"""사용자를 관리자로 만든다(관리자가 실수로 편집자가 됐거나 아무도 없을 때). 서버 PC의 레포 폴더에서:
  python scripts\make_admin.py            접속한 사용자 목록(디스코드 ID, 이름, 권한)
  python scripts\make_admin.py 디스코드ID   그 사람을 관리자로
앱이 켜져 있어도 된다(바로 반영). DB 위치는 .env의 EVAS_DB(없으면 data/evas.db)."""
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # 콘솔 코드 페이지와 상관없이 한글이 깨지지 않게
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dotenv import load_dotenv

load_dotenv()
from app import auth, db  # noqa: E402

db.init()
if len(sys.argv) < 2:
    with db.connect() as con:
        for r in con.execute("SELECT m.id, m.name, u.role FROM members m LEFT JOIN users u ON u.id=m.id ORDER BY m.name"):
            print(f"{r['id']}\t{r['name']}\t{r['role'] or auth.default_role()}")
    sys.exit(0)
uid = sys.argv[1].strip()
with db.connect() as con:
    row = con.execute("SELECT name FROM members WHERE id=?", (uid,)).fetchone()
    con.execute("INSERT INTO users(id,name,role) VALUES(?,?, 'admin') ON CONFLICT(id) DO UPDATE SET role='admin'",
                (uid, row["name"] if row else uid))
print("관리자로 지정:", uid)
