from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from html import unescape
from typing import Any
from xml.etree import ElementTree

from ..dependencies import logger, requests


@dataclass(frozen=True)
class NewsFeed:
    source: str
    url: str
    score_bonus: int = 0


KEYLESS_TRADER_NEWS_FEEDS = (
    NewsFeed('Seeking Alpha', 'https://seekingalpha.com/market_currents.xml', 2),
    NewsFeed('MarketWatch MarketPulse', 'https://feeds.content.dowjones.io/public/rss/mw_marketpulse', 2),
    NewsFeed('MarketWatch', 'https://feeds.content.dowjones.io/public/rss/mw_topstories', 1),
    NewsFeed('CNBC Market Insider', 'https://www.cnbc.com/id/20409666/device/rss/rss.html', 1),
    NewsFeed('Nasdaq Markets', 'https://www.nasdaq.com/feed/rssoutbound?category=Markets', 1),
    NewsFeed('Investing.com', 'https://www.investing.com/rss/news_25.rss', 1),
)

KEYLESS_CRYPTO_NEWS_FEEDS = (
    NewsFeed('CoinDesk', 'https://www.coindesk.com/arc/outboundfeeds/rss/', 3),
    NewsFeed('Cointelegraph', 'https://cointelegraph.com/rss', 3),
    NewsFeed('Decrypt', 'https://decrypt.co/feed', 2),
    NewsFeed('Bitcoin Magazine', 'https://bitcoinmagazine.com/.rss/full/', 2),
)

KEYLESS_CRYPTO_NEWS_SOURCES = frozenset(feed.source for feed in KEYLESS_CRYPTO_NEWS_FEEDS)

HTTP_HEADERS = {
    'User-Agent': 'BudgetTerminal/1.0 (+https://local.app) keyless-market-news',
    'Accept': 'application/rss+xml, application/xml;q=0.9, text/xml;q=0.8, */*;q=0.5',
}

SIGNAL_PHRASES = (
    ('earnings', 6, ('earnings', 'results', 'revenue', 'profit', 'eps', 'sales', 'quarterly')),
    ('guidance', 6, ('guidance', 'outlook', 'forecast', 'raises forecast', 'cuts forecast')),
    ('beat/miss', 5, ('beats estimates', 'beat estimates', 'misses estimates', 'missed estimates', 'better than expected', 'worse than expected')),
    ('analyst', 5, ('upgrade', 'upgraded', 'downgrade', 'downgraded', 'price target', 'overweight', 'underweight', 'buy rating', 'sell rating', 'initiates')),
    ('m&a', 5, ('merger', 'acquisition', 'acquire', 'takeover', 'buyout', 'deal talks')),
    ('capital returns', 4, ('buyback', 'repurchase', 'dividend', 'stock split', 'special dividend')),
    ('capital raise', 4, ('offering', 'secondary', 'share sale', 'convertible notes', 'debt offering')),
    ('regulatory', 4, ('sec', 'doj', 'ftc', 'fda', 'antitrust', 'lawsuit', 'probe', 'investigation', 'subpoena', 'approval')),
    ('macro', 4, ('fed', 'fomc', 'inflation', 'cpi', 'pce', 'jobs report', 'payrolls', 'unemployment', 'gdp', 'treasury yields', 'interest rates', 'tariff')),
    ('market move', 4, ('jumps', 'jump', 'surges', 'soars', 'rallies', 'rises', 'gains', 'plunges', 'slides', 'slumps', 'sinks', 'falls', 'tumbles', 'record high', 'record low')),
    ('sector', 3, ('sector rotation', 'semiconductor', 'chip', 'ai', 'oil', 'crude', 'banks', 'crypto', 'bitcoin', 'retail sales')),
)

CASHTAG_PATTERN = re.compile(r'(?<![A-Z0-9])\$([A-Z][A-Z0-9.]{0,5})(?![A-Z0-9])')
EXCHANGE_TICKER_PATTERN = re.compile(r'\b(?:NASDAQ|NYSE|AMEX|OTC|CBOE|TSX|LON):\s*([A-Z][A-Z0-9.]{0,5})\b')
PAREN_TICKER_PATTERN = re.compile(r'\(([A-Z][A-Z0-9.]{1,5})\)')
HTML_TAG_PATTERN = re.compile(r'<[^>]+>')
WHITESPACE_PATTERN = re.compile(r'\s+')
AMBIGUOUS_TICKER_CONTEXT = {
    'AI': ('c3.ai', 'c3 ai'),
    'COST': ('costco', 'costco wholesale'),
    'NOW': ('servicenow', 'service now'),
    'T': ('at&t', 'at & t', 'at and t'),
}
DESCRIPTIVE_TICKER_CONTEXT = {
    'BNB': ('bnb', 'binance coin', 'binancecoin'),
    'BTC': ('bitcoin',),
    'COIN': ('coinbase',),
    'ETH': ('ethereum', 'ether'),
    'ETHA': ('etha', 'ishares ethereum trust'),
    'IBIT': ('ibit', 'ishares bitcoin trust'),
    'MSTR': ('microstrategy', 'strategy inc', 'strategy shares'),
    'SOL': ('solana',),
    'XRP': ('xrp', 'ripple'),
}


def fetch_keyless_trader_news(
    focus_tickers: list[str],
    *,
    limit: int,
    candidate_limit: int,
    cancel_check: Any = None,
) -> list[dict[str, Any]]:
    """Fetch keyless market news feeds and return trader-ranked article rows."""
    return _fetch_ranked_news(
        KEYLESS_TRADER_NEWS_FEEDS,
        focus_tickers,
        limit=limit,
        candidate_limit=candidate_limit,
        cancel_check=cancel_check,
        log_label='Keyless trader news feed',
    )


def fetch_keyless_crypto_news(
    focus_tickers: list[str],
    *,
    limit: int,
    candidate_limit: int,
    cancel_check: Any = None,
) -> list[dict[str, Any]]:
    """Fetch crypto-native keyless RSS feeds and return ranked article rows."""
    return _fetch_ranked_news(
        KEYLESS_CRYPTO_NEWS_FEEDS,
        focus_tickers,
        limit=limit,
        candidate_limit=candidate_limit,
        cancel_check=cancel_check,
        log_label='Keyless crypto news feed',
    )


def _fetch_ranked_news(
    feeds: tuple[NewsFeed, ...],
    focus_tickers: list[str],
    *,
    limit: int,
    candidate_limit: int,
    cancel_check: Any = None,
    log_label: str,
) -> list[dict[str, Any]]:
    ticker_universe = _normalize_ticker_universe(focus_tickers)
    articles: list[dict[str, Any]] = []
    for feed in feeds:
        if _is_cancelled(cancel_check):
            return []
        try:
            articles.extend(_fetch_feed_articles(feed, ticker_universe))
        except Exception as exc:
            logger.info('%s failed for %s: %s', log_label, feed.source, exc)
    unique = _dedupe_articles(articles)
    ranked = sorted(unique, key=lambda article: (article.get('_trader_score', 0), article.get('_ts', 0)), reverse=True)
    return ranked[:max(0, min(int(limit or 0), int(candidate_limit or limit or 0)))]


def _fetch_feed_articles(feed: NewsFeed, ticker_universe: set[str]) -> list[dict[str, Any]]:
    response = requests.get(feed.url, headers=HTTP_HEADERS, timeout=12)
    response.raise_for_status()
    root = ElementTree.fromstring(response.content)
    feed_title = _child_text(root.find('channel'), 'title') or feed.source
    articles = []
    for item in root.findall('.//item'):
        article = _parse_rss_item(item, feed, feed_title, ticker_universe)
        if article is not None:
            articles.append(article)
    return articles


def _parse_rss_item(item: ElementTree.Element, feed: NewsFeed, feed_title: str, ticker_universe: set[str]) -> dict[str, Any] | None:
    title = _clean_text(_child_text(item, 'title'))
    if not title:
        return None
    link = _clean_url(_child_text(item, 'link') or _child_text(item, 'guid'))
    description = _clean_text(_child_text(item, 'description') or _child_text(item, 'content:encoded'))
    categories = [_clean_text(node.text or '') for node in item.findall('category')]
    published = _first_text(
        _child_text(item, 'pubDate'),
        _child_text(item, 'published'),
        _child_text(item, 'updated'),
        _namespaced_child_text(item, 'date'),
    )
    timestamp = _parse_timestamp(published)
    ticker_values = _extract_tickers(title, description, categories, link, ticker_universe)
    score, tags = _score_article(title, description, feed.score_bonus, ticker_values)
    return {
        'ticker': ', '.join(ticker_values[:3]) if ticker_values else 'OTHER',
        'title': title,
        'source': feed.source or feed_title,
        'time': _format_time(timestamp),
        'url': link,
        'category': 'other',
        '_ts': timestamp,
        '_trader_score': score,
        '_signal_tags': tags,
    }


def _extract_tickers(
    title: str,
    description: str,
    categories: list[str],
    url: str,
    ticker_universe: set[str],
) -> list[str]:
    found: list[str] = []
    combined_text = f'{title} {description} {" ".join(categories)}'
    combined_upper = combined_text.upper()
    for pattern in (EXCHANGE_TICKER_PATTERN, CASHTAG_PATTERN):
        for match in pattern.findall(combined_upper):
            _add_ticker(found, match, ticker_universe, strong_evidence=True)
    for match in PAREN_TICKER_PATTERN.findall(combined_upper):
        _add_ticker(found, match, ticker_universe, evidence_text=combined_text)
    metadata_values = categories
    for value in metadata_values:
        for token in re.findall(r'\b[A-Z][A-Z0-9.]{1,5}\b', str(value or '').upper()):
            _add_ticker(found, token, ticker_universe, evidence_text=combined_text)
    for ticker in sorted(ticker_universe, key=lambda value: (-len(value), value)):
        if len(ticker) < 3:
            continue
        if re.search(rf'(?<![A-Z0-9]){re.escape(ticker)}(?![A-Z0-9])', combined_upper):
            _add_ticker(found, ticker, ticker_universe, evidence_text=combined_text)
    for ticker in sorted(AMBIGUOUS_TICKER_CONTEXT):
        if ticker in ticker_universe and _has_ambiguous_ticker_context(ticker, combined_text):
            _add_ticker(found, ticker, ticker_universe, strong_evidence=True)
    for ticker in sorted(DESCRIPTIVE_TICKER_CONTEXT):
        if ticker in ticker_universe and _has_descriptive_ticker_context(ticker, combined_text):
            _add_ticker(found, ticker, ticker_universe, strong_evidence=True)
    return found


def _score_article(title: str, description: str, feed_bonus: int, tickers: list[str]) -> tuple[int, list[str]]:
    text = f'{title} {description}'.casefold()
    score = int(feed_bonus)
    tags: list[str] = []
    for tag, points, phrases in SIGNAL_PHRASES:
        if any(phrase in text for phrase in phrases):
            score += points
            tags.append(tag)
    if tickers:
        score += 2
        tags.append('ticker')
    if '?' in title:
        score -= 1
    return max(score, 0), sorted(set(tags))


def _normalize_ticker_universe(values: list[str]) -> set[str]:
    return {
        text
        for text in (str(value or '').upper().strip() for value in values or [])
        if text and not any(ch in text for ch in ('^', '='))
    }


def _has_ambiguous_ticker_context(ticker: str, evidence_text: str) -> bool:
    context_values = AMBIGUOUS_TICKER_CONTEXT.get(ticker, ())
    text = str(evidence_text or '').casefold()
    return bool(context_values and any(context in text for context in context_values))


def _has_descriptive_ticker_context(ticker: str, evidence_text: str) -> bool:
    context_values = DESCRIPTIVE_TICKER_CONTEXT.get(ticker, ())
    text = str(evidence_text or '').casefold()
    return bool(context_values and any(context in text for context in context_values))


def _add_ticker(
    found: list[str],
    value: str,
    ticker_universe: set[str],
    *,
    evidence_text: str='',
    strong_evidence: bool=False,
) -> None:
    ticker = str(value or '').upper().strip().strip('.')
    if ticker not in ticker_universe or ticker in found:
        return
    if ticker in AMBIGUOUS_TICKER_CONTEXT and not strong_evidence and not _has_ambiguous_ticker_context(ticker, evidence_text):
        return
    found.append(ticker)


def _dedupe_articles(articles: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = set()
    unique = []
    for article in articles:
        key = _article_key(article)
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        unique.append(article)
    return unique


def _article_key(article: dict[str, Any]) -> str:
    url = str(article.get('url') or '').strip().lower()
    if url:
        return f'url:{url}'
    title = str(article.get('title') or '').strip().casefold()
    return f'title:{title}' if title else ''


def _parse_timestamp(value: str) -> float:
    text = str(value or '').strip()
    if not text:
        return 0.0
    for parser in (_parse_rfc_datetime, _parse_iso_datetime, _parse_investing_datetime):
        parsed = parser(text)
        if parsed is not None:
            return parsed.timestamp()
    return 0.0


def _parse_rfc_datetime(value: str) -> dt.datetime | None:
    try:
        parsed = parsedate_to_datetime(value)
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def _parse_iso_datetime(value: str) -> dt.datetime | None:
    try:
        parsed = dt.datetime.fromisoformat(value.replace('Z', '+00:00'))
    except Exception:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=dt.timezone.utc)
    return parsed


def _parse_investing_datetime(value: str) -> dt.datetime | None:
    try:
        parsed = dt.datetime.strptime(value, '%Y-%m-%d %H:%M:%S')
    except Exception:
        return None
    return parsed.replace(tzinfo=dt.timezone.utc)


def _format_time(timestamp: float) -> str:
    if not timestamp:
        return '--:--'
    try:
        return dt.datetime.fromtimestamp(float(timestamp)).strftime('%H:%M')
    except Exception:
        return '--:--'


def _clean_text(value: str | None) -> str:
    text = unescape(str(value or ''))
    text = HTML_TAG_PATTERN.sub(' ', text)
    return WHITESPACE_PATTERN.sub(' ', text).strip()


def _clean_url(value: str | None) -> str:
    return unescape(str(value or '')).strip()


def _child_text(parent: ElementTree.Element | None, tag: str) -> str:
    if parent is None:
        return ''
    child = parent.find(tag)
    return child.text if child is not None and child.text is not None else ''


def _namespaced_child_text(parent: ElementTree.Element, local_name: str) -> str:
    suffix = f'}}{local_name}'
    for child in parent:
        if child.tag == local_name or str(child.tag).endswith(suffix):
            return child.text or ''
    return ''


def _first_text(*values: str) -> str:
    for value in values:
        if str(value or '').strip():
            return value
    return ''


def _is_cancelled(cancel_check: Any) -> bool:
    try:
        return bool(cancel_check and cancel_check())
    except Exception:
        return False
