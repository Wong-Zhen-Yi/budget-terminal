import sqlite3
import pandas as pd

db_path = "stock_cache.db"
try:
    with sqlite3.connect(db_path) as conn:
        print("NVDA 2026-03-09 chain summary:")
        df = pd.read_sql("SELECT * FROM opt_NVDA_2026_03_09", conn)
        print(df.columns.tolist())
        print(df.head(5))
except Exception as e:
    print(f"Error: {e}")
