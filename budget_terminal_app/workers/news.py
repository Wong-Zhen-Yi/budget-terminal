from __future__ import annotations

import re
from collections import Counter
from typing import Any

from budget_terminal_app.constants import (
    BEARISH_WORDS,
    BULLISH_WORDS,
    SECTOR_DATA,
    _BEARISH_PHRASES,
    _BULLISH_PHRASES,
    _SECTOR_KEYWORDS,
    _STOPWORDS,
)
from budget_terminal_app.dependencies import *

LATEST_HEADLINE_COUNT = 5
NOTABLE_HEADLINE_COUNT = 5
TOP_THEME_COUNT = 4
TOP_TICKER_COUNT = 6
TOP_SOURCE_COUNT = 5
KEY_TERMS_PER_HEADLINE = 5

_THEME_BY_TICKER = {
    str(ticker).upper(): sector
    for sector, tickers in SECTOR_DATA.items()
    for ticker in tickers
}


def _extract_words(text: Any) -> Any:
    """Lowercase words stripped of punctuation, excluding stopwords."""
    words = re.findall(r"[a-zA-Z']+", str(text or '').lower())
    return [w.strip("'") for w in words if w.strip("'") and w.strip("'") not in _STOPWORDS and len(w.strip("'")) > 2]


def _sentiment_score(headline: Any) -> Any:
    """Return a simple (bull_count, bear_count) score for one headline."""
    headline = str(headline or '')
    words = set(_extract_words(headline))
    bull = len(words & BULLISH_WORDS)
    bear = len(words & BEARISH_WORDS)
    lower = headline.lower()
    for phrase in _BULLISH_PHRASES:
        if phrase in lower:
            bull += 2
    for phrase in _BEARISH_PHRASES:
        if phrase in lower:
            bear += 2
    return (bull, bear)


def _sentiment_label(bull: Any, bear: Any) -> Any:
    """Return the simple headline sentiment label."""
    if bull > bear:
        return 'Bullish'
    if bear > bull:
        return 'Bearish'
    return 'Neutral'


def _theme_for_headline(ticker: Any, headline: Any) -> str:
    """Infer the headline theme from ticker membership and keyword hits."""
    ticker_key = str(ticker or '').upper().strip()
    if ticker_key in _THEME_BY_TICKER:
        return _THEME_BY_TICKER[ticker_key]
    words = set(re.findall(r'[A-Z0-9]+', f'{ticker_key} {str(headline or "").upper()}'))
    theme_hits = []
    for theme, keywords in _SECTOR_KEYWORDS.items():
        hits = len({str(word).upper() for word in keywords} & words)
        if hits > 0:
            theme_hits.append((hits, theme))
    if theme_hits:
        theme_hits.sort(key=lambda item: (item[0], item[1]), reverse=True)
        return theme_hits[0][1]
    return 'Other'


def _headline_key_terms(headline: Any, limit: int = KEY_TERMS_PER_HEADLINE) -> list[str]:
    """Return the most repeated signal-bearing terms in one headline."""
    counts = Counter(_extract_words(headline))
    return [term for term, _count in counts.most_common(limit)]


def _category_label(category: Any) -> str:
    """Return a readable category label."""
    text = str(category or '').strip().lower()
    if text == 'portfolio':
        return 'Portfolio'
    if text == 'macro':
        return 'Macro'
    return 'News'


def _compact_counter_lines(counter: Counter, limit: int, empty_text: str) -> list[str]:
    """Render the top items in a counter as simple bullet lines."""
    if not counter:
        return [f'- {empty_text}']
    return [f'- {name} ({count})' for name, count in counter.most_common(limit)]


class NewsSummarizerWorker(QObject):
    """Deterministic headline summarizer used by the News Hub."""

    finished = pyqtSignal(str)
    error = pyqtSignal(str)
    status = pyqtSignal(str)

    def __init__(self, articles: Any) -> None:
        super().__init__()
        self.articles = articles

    def run(self) -> None:
        """Generate a rule-based briefing from the loaded headline metadata."""
        try:
            self.status.emit('Analyzing headlines...')
            cleaned = self._normalize_articles(self.articles)
            if not cleaned:
                self.finished.emit('No news loaded yet.')
                return
            analyses = [self._analyze_article(article) for article in cleaned]
            if len(analyses) == 1:
                text = self._single_article(analyses[0])
            else:
                text = self._multi_article(analyses)
            self.finished.emit(text)
        except Exception as ex:
            self.error.emit(str(ex))

    def _normalize_articles(self, articles: Any) -> list[dict[str, Any]]:
        """Normalize article dicts and remove obvious duplicates."""
        seen = set()
        cleaned = []
        for article in articles or []:
            if not isinstance(article, dict):
                continue
            title = str(article.get('title', '') or '').strip()
            if not title:
                continue
            ticker = str(article.get('ticker', '') or '').strip() or 'News'
            source = str(article.get('source', '') or '').strip() or 'Unknown source'
            category = str(article.get('category', '') or '').strip() or 'news'
            time_str = str(article.get('time', '') or '').strip() or '--:--'
            ts = article.get('_ts', 0) or 0
            key = (' '.join(title.lower().split()), ticker, source)
            if key in seen:
                continue
            seen.add(key)
            cleaned.append(
                {
                    'title': title,
                    'ticker': ticker,
                    'source': source,
                    'category': category,
                    'time': time_str,
                    '_ts': ts,
                }
            )
        cleaned.sort(key=lambda article: article.get('_ts', 0), reverse=True)
        return cleaned

    def _matched_signal_terms(self, headline: Any, label: str) -> list[str]:
        """Return the matched signal words and phrases for one headline."""
        title = str(headline or '')
        lower = title.lower()
        words = set(_extract_words(title))
        terms = []
        if label == 'Bullish':
            for phrase in _BULLISH_PHRASES:
                if phrase in lower:
                    terms.append(phrase)
            terms.extend(sorted(words & BULLISH_WORDS))
        elif label == 'Bearish':
            for phrase in _BEARISH_PHRASES:
                if phrase in lower:
                    terms.append(phrase)
            terms.extend(sorted(words & BEARISH_WORDS))
        else:
            for phrase in _BULLISH_PHRASES + _BEARISH_PHRASES:
                if phrase in lower:
                    terms.append(phrase)
        deduped = []
        seen = set()
        for term in terms:
            if term in seen:
                continue
            seen.add(term)
            deduped.append(term)
        return deduped[:4]

    def _analyze_article(self, article: dict[str, Any]) -> dict[str, Any]:
        """Attach heuristic sentiment and theme metadata to one article."""
        bull, bear = _sentiment_score(article.get('title', ''))
        label = _sentiment_label(bull, bear)
        key_terms = _headline_key_terms(article.get('title', ''))
        theme = _theme_for_headline(article.get('ticker', ''), article.get('title', ''))
        return {
            **article,
            'bull': bull,
            'bear': bear,
            'label': label,
            'theme': theme,
            'key_terms': key_terms,
            'signal_terms': self._matched_signal_terms(article.get('title', ''), label),
            'score': bull - bear,
            'intensity': bull + bear,
        }

    def _single_article_reason(self, article: dict[str, Any]) -> str:
        """Return one short explanation line for a single headline summary."""
        label = article.get('label', 'Neutral')
        signals = article.get('signal_terms', [])
        key_terms = article.get('key_terms', [])
        theme = article.get('theme', 'Other')
        if label == 'Bullish':
            if signals:
                return f"Headline wording leans bullish because it includes positive cues like {', '.join(signals[:3])}."
            if key_terms:
                return f"Headline wording leans bullish based on terms such as {', '.join(key_terms[:3])}."
            return 'Headline wording leans bullish, but the signal is light and headline-only.'
        if label == 'Bearish':
            if signals:
                return f"Headline wording leans bearish because it includes negative cues like {', '.join(signals[:3])}."
            if key_terms:
                return f"Headline wording leans bearish based on terms such as {', '.join(key_terms[:3])}."
            return 'Headline wording leans bearish, but the signal is light and headline-only.'
        if theme != 'Other' and key_terms:
            return f"Headline reads mostly informational and centers on {theme.lower()} terms like {', '.join(key_terms[:3])}."
        if signals:
            return f"Headline is mixed or informational despite using terms like {', '.join(signals[:3])}."
        return 'Headline reads mostly informational and does not contain strong bullish or bearish signal words.'

    def _single_article(self, article: dict[str, Any]) -> str:
        """Return the deterministic single-headline summary."""
        key_terms = article.get('key_terms', [])
        lines = [
            f"{article.get('ticker', 'News')} | {article.get('source', 'Unknown source')} | {article.get('time', '--:--')}",
            f"Headline: {article.get('title', '')}",
            f"Signal: {article.get('label', 'Neutral')}",
            f"Theme: {article.get('theme', 'Other')}",
            f"Key terms: {', '.join(key_terms) if key_terms else 'None'}",
            f"Why: {self._single_article_reason(article)}",
        ]
        return '\n'.join(lines)

    def _coverage_line(self, analyses: list[dict[str, Any]]) -> str:
        """Return a compact description of the current briefing coverage."""
        portfolio_count = sum((1 for article in analyses if str(article.get('category', '')).lower() == 'portfolio'))
        macro_count = sum((1 for article in analyses if str(article.get('category', '')).lower() == 'macro'))
        return f'Summarized {len(analyses)} loaded headlines ({portfolio_count} portfolio, {macro_count} macro).'

    def _overall_tone(self, counts: Counter) -> str:
        """Return a readable top-line tone label for the full briefing."""
        bullish = counts.get('Bullish', 0)
        bearish = counts.get('Bearish', 0)
        neutral = counts.get('Neutral', 0)
        if bullish == bearish == 0:
            return 'Mostly neutral / informational'
        if bullish >= bearish + 3:
            return 'Bullish tilt'
        if bearish >= bullish + 3:
            return 'Bearish tilt'
        if bullish > bearish:
            return 'Slightly bullish'
        if bearish > bullish:
            return 'Slightly bearish'
        if neutral > 0:
            return 'Mixed / neutral'
        return 'Mixed'

    def _latest_headline_lines(self, analyses: list[dict[str, Any]]) -> list[str]:
        """Return display lines for the newest headlines."""
        lines = []
        for article in analyses[:LATEST_HEADLINE_COUNT]:
            lines.append(
                f"- [{_category_label(article.get('category'))}] "
                f"{article.get('ticker', 'News')} | {article.get('source', 'Unknown source')} | "
                f"{article.get('time', '--:--')} | {article.get('title', '')}"
            )
        return lines or ['- None']

    def _notable_headline_lines(self, analyses: list[dict[str, Any]]) -> list[str]:
        """Return display lines for the strongest and newest headlines."""
        ranked = sorted(
            analyses,
            key=lambda article: (article.get('intensity', 0), abs(article.get('score', 0)), article.get('_ts', 0)),
            reverse=True,
        )
        selected = ranked[:NOTABLE_HEADLINE_COUNT]
        lines = []
        for article in selected:
            lines.append(
                f"- {article.get('label', 'Neutral')} | {article.get('theme', 'Other')} | "
                f"{article.get('ticker', 'News')} | {article.get('title', '')}"
            )
        return lines or ['- None']

    def _multi_article(self, analyses: list[dict[str, Any]]) -> str:
        """Return the deterministic multi-headline briefing."""
        sentiment_counts = Counter(article.get('label', 'Neutral') for article in analyses)
        theme_counts = Counter(article.get('theme', 'Other') for article in analyses if article.get('theme') != 'Other')
        portfolio_counts = Counter(
            article.get('ticker', 'News')
            for article in analyses
            if str(article.get('category', '')).lower() == 'portfolio'
        )
        macro_counts = Counter(
            article.get('ticker', 'News')
            for article in analyses
            if str(article.get('category', '')).lower() == 'macro'
        )
        source_counts = Counter(article.get('source', 'Unknown source') for article in analyses)

        lines = [
            self._coverage_line(analyses),
            '',
            'News Briefing',
            f"Overall tone: {self._overall_tone(sentiment_counts)}",
            (
                'Counts: '
                f"{sentiment_counts.get('Bullish', 0)} bullish, "
                f"{sentiment_counts.get('Bearish', 0)} bearish, "
                f"{sentiment_counts.get('Neutral', 0)} neutral"
            ),
            '',
            'Key themes:',
            *_compact_counter_lines(theme_counts, TOP_THEME_COUNT, 'No dominant themes'),
            '',
            'Portfolio names:',
            *_compact_counter_lines(portfolio_counts, TOP_TICKER_COUNT, 'No portfolio-specific headlines'),
            '',
            'Macro drivers:',
            *_compact_counter_lines(macro_counts, TOP_TICKER_COUNT, 'No macro headlines'),
            '',
            'Most active sources:',
            *_compact_counter_lines(source_counts, TOP_SOURCE_COUNT, 'No source data'),
            '',
            'Latest headlines:',
            *self._latest_headline_lines(analyses),
            '',
            'Notable headlines:',
            *self._notable_headline_lines(analyses),
            '',
            'Cautions:',
            '- This briefing is headline-only and does not inspect article bodies.',
            '- Neutral headlines may still matter; they simply lack strong bullish or bearish signal words.',
        ]
        return '\n'.join(lines)
