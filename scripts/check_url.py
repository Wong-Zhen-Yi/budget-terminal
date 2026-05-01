import yfinance as yf
ticker = yf.Ticker("AAPL")
news = ticker.news
if news:
    item = news[0]
    content = item.get('content', {})
    print("Top level keys:", item.keys())
    print("Content keys:", content.keys())
    print("Canonical URL:", content.get('canonicalUrl'))
    print("Short URL:", content.get('url'))
    print("Click-through URL:", content.get('clickThroughUrl'))
else:
    print("No news found")
