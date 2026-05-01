import sqlite3
import pandas as pd
import json

db_path = "stock_cache.db"
try:
    with sqlite3.connect(db_path) as conn:
        print("Meta table summary:")
        try:
            df_meta = pd.read_sql("SELECT * FROM meta", conn)
            print(df_meta.tail(10))
        except: print("Meta table empty or missing.")
        
        print("\nMeta_options table summary:")
        try:
            df_meta_opts = pd.read_sql("SELECT * FROM meta_options", conn)
            print(df_meta_opts.tail(10))
        except: print("Meta_options table empty or missing.")
except Exception as e:
    print(f"Error: {e}")
