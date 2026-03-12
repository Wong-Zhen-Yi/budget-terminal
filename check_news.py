import yfinance as yf
ticker = yf.Ticker("AAPL")
news = ticker.news
if news:
    print(f"Keys: {news[0].keys()}")
    print(f"Content: {news[0]}")
else:
    print("No news found")
