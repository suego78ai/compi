import sqlite3
from pathlib import Path

db_path = Path("ipsi.db")
if db_path.exists():
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("UPDATE universities SET is_free_apply = 'F' WHERE is_free_apply = 'M'")
    print(f"Updated {cur.rowcount} rows with is_free_apply = 'F'")
    
    # Also ensure any university ending with 'M' or '(M)' or '[M]' or 'F' has is_free_apply = 'F'
    cur.execute("SELECT id, name, is_free_apply FROM universities")
    all_univs = cur.fetchall()
    updated = 0
    for uid, name, free in all_univs:
        if name and (name.endswith("M") or name.endswith("(M)") or name.endswith("[M]") or name.endswith("F") or name.endswith("(F)")):
            cur.execute("UPDATE universities SET is_free_apply = 'F' WHERE id = ?", (uid,))
            updated += 1
    conn.commit()
    print(f"Total verified & updated: {updated}")
    conn.close()
