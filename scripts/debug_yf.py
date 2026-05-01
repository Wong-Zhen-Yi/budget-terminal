import yfinance as yf
import pandas as pd

tickers = ["AAPL", "MSFT"]
all_symbols = list(set(tickers + ["SPY", "QQQ", "^VIX", "GLD", "CL=F"]))
print(f"Downloading for: {all_symbols}")

try:
    batch_data = yf.download(all_symbols, period="2d", interval="1d", group_by='ticker', progress=False)
    print("\nColumns structure:")
    print(batch_data.columns)
    
    # Test access
    for t in tickers:
        if t in batch_data:
            print(f"\nAccessing {t}:")
            df_t = batch_data[t]
            print(f"Type: {type(df_t)}")
            print(f"Index: {df_t.index}")
            close = df_t['Close'].dropna()
            if len(close) >= 2:
                curr = close.iloc[-1]
                prev = close.iloc[-2]
                print(f"Curr: {curr}, Prev: {prev}")
            elif len(close) == 1:
                print(f"Curr: {close.iloc[-1]}, (Only 1 point)")
            else:
                print("No data points after dropna()")
        else:
            print(f"{t} not in batch_data")

except Exception as e:
    print(f"Error: {e}")
    import traceback
    traceback.print_exc()
