from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from budget_terminal_app.paths import user_data_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect Budget Terminal's SQLite cache schema and metadata.")
    parser.add_argument("--db", type=Path, default=Path(user_data_path("budget_cache.db")))
    parser.add_argument("--limit", type=int, default=20)
    args = parser.parse_args()
    if not args.db.exists():
        parser.error(f"cache does not exist: {args.db}")

    with sqlite3.connect(args.db) as connection:
        tables = [row[0] for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")]
        print(f"Cache: {args.db}")
        print(f"Tables ({len(tables)}):")
        for name in tables:
            count = connection.execute(f'SELECT COUNT(*) FROM "{name.replace(chr(34), chr(34) * 2)}"').fetchone()[0]
            print(f"- {name}: {count} row(s)")
        for name in ("meta", "meta_options"):
            if name not in tables:
                continue
            print(f"\n{name} latest rows:")
            for row in connection.execute(f"SELECT * FROM {name} ORDER BY last_updated DESC LIMIT ?", (args.limit,)):
                print(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
