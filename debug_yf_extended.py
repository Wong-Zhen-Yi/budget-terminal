import yfinance as yf
import pandas as pd
import time

t = "AAPL"
print(f"Testing {t} info...")
start = time.time()
ticker = yf.Ticker(t)
try:
    info = ticker.info
    print(f"Info keys (first 5): {list(info.keys())[:5]}")
    print(f"Target: {info.get('targetMeanPrice', 'N/A')}")
except Exception as e:
    print(f"Info Error: {e}")
print(f"Time taken: {time.time() - start:.2f}s")

print(f"\nTesting news...")
try:
    news = ticker.news
    print(f"News count: {len(news)}")
    if news:
        print(f"First news: {news[0]['title']}")
except Exception as e:
    print(f"News Error: {e}")

print(f"\nTesting batch download with group_by='ticker'...")
symbols = ["AAPL", "MSFT", "SPY"]
data = yf.download(symbols, period="2d", group_by='ticker', progress=False)
print(f"Columns: {data.columns}")
for s in symbols:
    if s in data:
        print(f"{s} found. Close: {data[s]['Close'].iloc[-1 if len(data[s]) > 0 else 0]}")
    else:
        print(f"{s} NOT found")
