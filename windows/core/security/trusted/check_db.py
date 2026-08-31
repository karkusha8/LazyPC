import sqlite3
import os

db = os.path.expandvars(
    r"%LOCALAPPDATA%\LazyPC\lazypc.db"
)

print("Database:", db)
print()

with sqlite3.connect(db) as conn:
    conn.row_factory = sqlite3.Row

    rows = conn.execute(
        "SELECT * FROM trusted_devices"
    ).fetchall()

    if not rows:
        print("trusted_devices is EMPTY")
    else:
        print(f"Found {len(rows)} trusted device(s):")
        print()

        for row in rows:
            for key in row.keys():
                print(f"{key}: {row[key]}")
            print("-" * 60)