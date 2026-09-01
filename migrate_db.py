import sqlite3
from pathlib import Path

db_path = Path("ipsi.db")
if db_path.exists():
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute("PRAGMA table_info(universities)")
    cols = [r[1] for r in cur.fetchall()]
    print("Existing columns:", cols)
    if "is_free_apply" not in cols:
        cur.execute("ALTER TABLE universities ADD COLUMN is_free_apply VARCHAR DEFAULT ''")
        conn.commit()
        print("Successfully added 'is_free_apply' column!")

    # Check and update universities that have 'M' suffix
    cur.execute("SELECT id, name, is_free_apply FROM universities")
    all_univs = cur.fetchall()
    updated = 0
    for uid, name, free in all_univs:
        if name and (name.endswith("M") or name.endswith("(M)") or name.endswith("[M]")):
            # set is_free_apply = 'M'
            cur.execute("UPDATE universities SET is_free_apply = 'M' WHERE id = ?", (uid,))
            updated += 1
            print(f"Updated university {uid}: {name} -> is_free_apply = 'M'")
    conn.commit()
    print(f"Total updated: {updated}")
    conn.close()
