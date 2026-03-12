from __future__ import annotations
from typing import Any
from ..constants import BULLISH_WORDS, BEARISH_WORDS, _BULLISH_PHRASES, _BEARISH_PHRASES, _STOPWORDS, _SECTOR_KEYWORDS
from ..dependencies import *


def _extract_words(text: Any) -> Any:
    """Lowercase words stripped of punctuation, excluding stopwords."""
    import re
    words = re.findall("[a-zA-Z']+", str(text or '').lower())
    return [w.strip("'") for w in words if w.strip("'") and w.strip("'") not in _STOPWORDS and (len(w) > 2)]


def _sentiment_score(headline: Any) -> Any:
    """Return (bull_count, bear_count) for a headline."""
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
    """Handle sentiment label."""
    if bull > bear:
        return 'Bullish'
    if bear > bull:
        return 'Bearish'
    return 'Neutral'


class NewsSummarizerWorker(QObject):
    """Pure-Python news briefing generator with no external summarizer."""
    finished = pyqtSignal(str)
    error = pyqtSignal(str)

    def __init__(self, articles: Any) -> None:
        """Initialize the object."""
        super().__init__()
        self.articles = articles

    def run(self) -> None:
        """Handle run."""
        try:
            cleaned = self._normalize_articles(self.articles)
            if not cleaned:
                self.finished.emit('No news loaded yet.')
            elif len(cleaned) == 1:
                self.finished.emit(self._single_article(cleaned[0]))
            else:
                self.finished.emit(self._multi_article(cleaned))
        except Exception as ex:
            self.error.emit(str(ex))

    def _normalize_articles(self, articles: Any) -> Any:
        """Normalize article dicts and remove obvious duplicates."""
        seen = set()
        cleaned = []
        for article in articles or []:
            title = str(article.get('title', '') or '').strip()
            if not title:
                continue
            ticker = str(article.get('ticker', '') or '').strip()
            source = str(article.get('source', '') or '').strip()
            category = str(article.get('category', '') or '').strip()
            time_str = str(article.get('time', '') or '').strip()
            ts = article.get('_ts', 0) or 0
            key = (' '.join(title.lower().split()), ticker, source)
            if key in seen:
                continue
            seen.add(key)
            cleaned.append({'title': title, 'ticker': ticker, 'source': source, 'category': category, 'time': time_str, '_ts': ts, 'words': _extract_words(title)})
        cleaned.sort(key=lambda a: a.get('_ts', 0), reverse=True)
        return cleaned

    def _article_sentiment(self, article: Any) -> Any:
        """Return sentiment metadata for an article."""
        bull, bear = _sentiment_score(article.get('title', ''))
        label = _sentiment_label(bull, bear)
        strength = bull + bear
        if strength >= 4:
            confidence = 'high'
        elif strength >= 2:
            confidence = 'medium'
        else:
            confidence = 'low'
        return {'bull': bull, 'bear': bear, 'label': label, 'confidence': confidence}

    def _article_theme(self, article: Any) -> Any:
        """Infer a broad theme from the headline."""
        words = set(article.get('words', []))
        sector_hits = []
        for sector, keywords in _SECTOR_KEYWORDS.items():
            hit = len(words & keywords)
            if hit > 0:
                sector_hits.append((hit, sector))
        if sector_hits:
            sector_hits.sort(reverse=True)
            return sector_hits[0][1]
        return 'General'

    def _format_article_ref(self, article: Any) -> Any:
        """Render a compact article reference."""
        ticker = article.get('ticker', '') or article.get('source', '') or 'News'
        time_str = article.get('time', '')
        if time_str and time_str != '--:--':
            return f'{ticker} ({time_str})'
        return ticker

    def _single_article(self, article: Any) -> Any:
        """Handle single article."""
        sentiment = self._article_sentiment(article)
        theme = self._article_theme(article)
        key_terms = [w for w in article.get('words', []) if len(w) > 3][:6]
        terms_line = ', '.join(dict.fromkeys(key_terms)) if key_terms else 'headline-driven, no strong repeated terms'
        title = article.get('title', '')
        ticker = article.get('ticker', '') or 'No ticker'
        source = article.get('source', '') or 'Unknown source'
        time_str = article.get('time', '') or '--:--'
        lines = [
            f'{ticker} | {source} | {time_str}',
            '',
            title,
            '',
            f"Tone: {sentiment['label']} ({sentiment['confidence']} confidence)",
            f'Theme: {theme}',
            f'Key terms: {terms_line}',
        ]
        if sentiment['label'] == 'Bullish':
            lines.append('Read: the headline language leans supportive for the stock or theme.')
        elif sentiment['label'] == 'Bearish':
            lines.append('Read: the headline language leans negative or risk-focused.')
        else:
            lines.append('Read: the headline looks informational rather than clearly directional.')
        return '\n'.join(lines)

    def _multi_article(self, articles: Any) -> Any:
        """Handle multi article."""
        from collections import Counter, defaultdict
        total = len(articles)
        tone_counts = Counter()
        category_counts = Counter()
        ticker_counts = Counter()
        source_counts = Counter()
        theme_counts = Counter()
        article_sentiment = {}
        ticker_tone = defaultdict(Counter)
        word_counter = Counter()
        notable_pool = []
        for article in articles:
            sentiment = self._article_sentiment(article)
            label = sentiment['label']
            theme = self._article_theme(article)
            article_sentiment[id(article)] = sentiment
            tone_counts[label] += 1
            category_counts[article.get('category', '') or 'other'] += 1
            source = article.get('source', '')
            ticker = article.get('ticker', '')
            if source:
                source_counts[source] += 1
            if ticker:
                ticker_counts[ticker] += 1
                ticker_tone[ticker][label] += 1
            theme_counts[theme] += 1
            word_counter.update(article.get('words', []))
            score = sentiment['bull'] + sentiment['bear']
            recency = article.get('_ts', 0) or 0
            notable_pool.append((score, recency, article))
        bull_count = tone_counts['Bullish']
        bear_count = tone_counts['Bearish']
        neutral_count = tone_counts['Neutral']
        if bull_count > bear_count + 1:
            overall_tone = 'Mostly positive'
        elif bear_count > bull_count + 1:
            overall_tone = 'Mostly negative'
        elif bull_count > bear_count:
            overall_tone = 'Slightly positive'
        elif bear_count > bull_count:
            overall_tone = 'Slightly negative'
        else:
            overall_tone = 'Mixed'
        top_themes = [name for name, _ in theme_counts.most_common(4) if name != 'General']
        top_terms = []
        for word, _ in word_counter.most_common(8):
            if len(word) > 3:
                top_terms.append(word)
            if len(top_terms) == 5:
                break
        portfolio_bits = []
        for ticker, count in ticker_counts.most_common(5):
            if not any((a.get('category') == 'portfolio' and a.get('ticker') == ticker for a in articles)):
                continue
            tones = ticker_tone[ticker]
            if tones['Bullish'] > tones['Bearish']:
                leaning = 'positive'
            elif tones['Bearish'] > tones['Bullish']:
                leaning = 'negative'
            else:
                leaning = 'mixed'
            portfolio_bits.append(f'{ticker} ({count}, {leaning})')
        macro_bits = []
        for ticker, count in ticker_counts.most_common(6):
            if not any((a.get('category') == 'macro' and a.get('ticker') == ticker for a in articles)):
                continue
            macro_bits.append(f'{ticker} x{count}')
        notable_pool.sort(key=lambda item: (item[0], item[1]), reverse=True)
        notable = []
        seen_titles = set()
        for _, _, article in notable_pool:
            title_key = article.get('title', '').lower()
            if title_key in seen_titles:
                continue
            seen_titles.add(title_key)
            notable.append(article)
            if len(notable) == 4:
                break
        latest = articles[:3]
        lines = [
            f'News Briefing',
            f'{total} loaded headlines reviewed',
            '',
            f'Overall tone: {overall_tone}.',
            f'Breakdown: {bull_count} positive, {bear_count} negative, {neutral_count} neutral.',
        ]
        if top_themes:
            lines.append(f"The main themes are {', '.join(top_themes)}.")
        elif top_terms:
            lines.append(f"The repeated terms are {', '.join(top_terms)}.")
        if portfolio_bits:
            lines.extend(['', 'What is driving portfolio names:', ', '.join(portfolio_bits) + '.'])
        if macro_bits:
            lines.extend(['', 'What is driving macro and market news:', ', '.join(macro_bits) + '.'])
        if source_counts:
            lines.extend(['', f"Most active sources: {', '.join((f'{name} ({count})' for name, count in source_counts.most_common(3)))}."])
        if latest:
            latest_bits = [f"{self._format_article_ref(article)}: {article.get('title', '')}" for article in latest]
            lines.extend(['', 'Latest headlines in the feed:', *latest_bits])
        if notable:
            lines.append('')
            lines.append('Notable headlines:')
            for article in notable:
                tone = article_sentiment[id(article)]['label'].lower()
                lines.append(f"- {self._format_article_ref(article)} [{tone}] {article.get('title', '')}")
        return '\n'.join(lines)
