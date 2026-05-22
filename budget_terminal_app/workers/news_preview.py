from __future__ import annotations

import re
from html import unescape
from typing import Any

from bs4 import BeautifulSoup

from ..dependencies import logger, requests


HTTP_HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) BudgetTerminal/1.0',
    'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
    'Accept-Language': 'en-US,en;q=0.9',
}
MAX_PREVIEW_CHARS = 6000
MIN_PARAGRAPH_CHARS = 40
WHITESPACE_PATTERN = re.compile(r'\s+')


def build_news_preview_text(article: dict[str, Any]) -> dict[str, str]:
    """Fetch and extract a readable text preview for a news article."""
    url = str(article.get('url') or '').strip()
    fallback = _fallback_text(article)
    if not url:
        return {
            'text': fallback,
            'source': 'fallback',
            'error': 'No article URL is available for this headline.',
        }
    try:
        response = requests.get(url, headers=HTTP_HEADERS, timeout=8)
        response.raise_for_status()
        text = _extract_readable_text(response.text)
        if text:
            return {'text': _cap_text(text), 'source': 'article', 'error': ''}
        return {
            'text': fallback,
            'source': 'fallback',
            'error': 'Preview unavailable. The publisher may block readable extraction.',
        }
    except Exception as exc:
        logger.info('News preview fetch failed for %s: %s', url, exc)
        return {
            'text': fallback,
            'source': 'fallback',
            'error': f'Preview unavailable. Open externally for the full article. ({exc})',
        }


def _extract_readable_text(html: str) -> str:
    soup = BeautifulSoup(html or '', 'html.parser')
    for selector in ('script', 'style', 'noscript', 'svg', 'nav', 'footer', 'header', 'aside', 'form', 'iframe'):
        for node in soup.select(selector):
            node.decompose()

    candidates = []
    for selector in (
        'article',
        '[role="article"]',
        'main',
        '[class*="article"]',
        '[class*="story"]',
        '[class*="content"]',
    ):
        candidates.extend(soup.select(selector))
    candidates.append(soup.body or soup)

    best_text = ''
    best_score = 0
    for candidate in candidates:
        paragraphs = [_clean_text(node.get_text(' ', strip=True)) for node in candidate.find_all(('p', 'li'))]
        paragraphs = [text for text in paragraphs if len(text) >= MIN_PARAGRAPH_CHARS]
        text = '\n\n'.join(_dedupe_lines(paragraphs))
        score = len(text)
        if score > best_score:
            best_text = text
            best_score = score
    return best_text


def _fallback_text(article: dict[str, Any]) -> str:
    title = _clean_text(str(article.get('title') or 'N/A'))
    url = _clean_text(str(article.get('url') or ''))
    summary = _clean_text(
        str(
            article.get('description')
            or article.get('summary')
            or article.get('content')
            or article.get('snippet')
            or ''
        )
    )
    if summary:
        return _cap_text(summary)
    if url:
        return f'Preview unavailable.\n\n{title}\n\nURL: {url}'
    return f'Preview unavailable.\n\n{title}'


def _clean_text(text: str) -> str:
    return WHITESPACE_PATTERN.sub(' ', unescape(str(text or ''))).strip()


def _dedupe_lines(lines: list[str]) -> list[str]:
    seen: set[str] = set()
    output = []
    for line in lines:
        key = line.casefold()
        if key in seen:
            continue
        seen.add(key)
        output.append(line)
    return output


def _cap_text(text: str) -> str:
    clean = str(text or '').strip()
    if len(clean) <= MAX_PREVIEW_CHARS:
        return clean
    return f'{clean[:MAX_PREVIEW_CHARS].rstrip()}...'
