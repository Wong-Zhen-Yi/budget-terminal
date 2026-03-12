import yfinance as yf
import datetime

def parse_news(news_items, ticker):
    news_list = []
    for n in news_items:
        try:
            content = n.get('content', {})
            title = content.get('title', 'N/A')
            source = content.get('provider', {}).get('displayName', 'N/A')
            
            # pubDate is usually "2024-03-08T01:23:45Z" or similar
            pub_date_str = content.get('pubDate')
            time_str = "--:--"
            if pub_date_str:
                try:
                    # Try to parse ISO format
                    dt = datetime.datetime.fromisoformat(pub_date_str.replace('Z', '+00:00'))
                    time_str = dt.strftime('%H:%M')
                except:
                    time_str = pub_date_str[:10]
            
            news_list.append({
                "ticker": ticker,
                "title": title,
                "source": source,
                "time": time_str
            })
        except Exception as e:
            print(f"Error parsing single news item: {e}")
    return news_list

ticker_sym = "AAPL"
ticker_obj = yf.Ticker(ticker_sym)
news = ticker_obj.news
parsed = parse_news(news[:2], ticker_sym)
print(f"Parsed news: {parsed}")
