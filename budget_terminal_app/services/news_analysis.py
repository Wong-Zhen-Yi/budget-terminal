from __future__ import annotations

import re
from typing import Any


def normalize_news_symbol(value: Any) -> str:
    return str(value or "").upper().strip().replace(".", "-")


def article_dedupe_key(article: dict[str, Any]) -> str:
    url = str(article.get("url") or "").strip().lower()
    if url:
        return f"url:{url}"
    title = str(article.get("title") or "").strip().lower()
    return f"title:{title}" if title else ""


def dedupe_articles(articles: list[dict[str, Any]], existing: list[dict[str, Any]]) -> list[dict[str, Any]]:
    seen = {key for key in (article_dedupe_key(article) for article in existing) if key}
    unique = []
    for article in articles:
        key = article_dedupe_key(article)
        if key and key in seen:
            continue
        if key:
            seen.add(key)
        unique.append(article)
    return unique


def article_ticker_set(article: dict[str, Any]) -> set[str]:
    return {
        part.strip()
        for part in str(article.get("ticker") or "").upper().split(",")
        if part.strip() and part.strip() != "OTHER"
    }


def mentions_blocked_ticker(article: dict[str, Any], blocked_tickers: set[str]) -> bool:
    if article_ticker_set(article) & blocked_tickers:
        return True
    title = str(article.get("title") or "").upper()
    return any(
        re.search(rf"(?<![A-Z0-9]){re.escape(ticker)}(?![A-Z0-9])", title)
        for ticker in blocked_tickers
        if len(ticker) >= 2 and not any(char in ticker for char in ("^", "=", "-", "."))
    )
