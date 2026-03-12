import yfinance as yf
import pandas as pd

tickers = ["AAPL"]
for t in tickers:
    print(f"Testing {t} options...")
    try:
        ticker = yf.Ticker(t)
        exps = ticker.options
        if exps:
            expiry = exps[0]
            print(f"Fetching chain for {expiry}...")
            chain = ticker.option_chain(expiry)
            print(f"Type: {type(chain)}")
            print(f"Attributes: {dir(chain)}")
    except Exception as e:
        print(f"Error fetching options for {t}: {e}")
