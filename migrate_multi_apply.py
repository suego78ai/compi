import sqlite3
from pathlib import Path

db_path = Path("ipsi.db")
if db_path.exists():
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    try:
        cur.execute("ALTER TABLE universities ADD COLUMN is_multi_apply VARCHAR DEFAULT ''")
        print("Added column is_multi_apply")
    except Exception as e:
        print("Column already exists or note:", e)

    cur.execute("SELECT id, name FROM universities")
    rows = cur.fetchall()
    updated = 0
    for uid, name in rows:
        if name and (name.endswith("M") or name.endswith("(M)") or name.endswith("[M]")):
            cur.execute("UPDATE universities SET is_multi_apply = 'M' WHERE id = ?", (uid,))
            updated += 1
    conn.commit()
    print(f"Updated {updated} universities with is_multi_apply = 'M'")
    conn.close()
