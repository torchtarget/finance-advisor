"""News data source — headlines and basic sentiment for trading catalysts."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import httpx

logger = logging.getLogger(__name__)

# Free RSS/API news sources that don't require keys
FINVIZ_NEWS_URL = "https://finviz.com/quote.ashx"
YAHOO_NEWS_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"


class NewsClient:
    """Aggregates news from multiple free sources."""

    def __init__(self, newsapi_key: str = ""):
        self._newsapi_key = newsapi_key
        self._http = httpx.Client(
            timeout=10.0,
            headers={"User-Agent": "FinanceAdvisor/0.1"},
        )

    def get_yahoo_news(self, symbol: str) -> list[dict]:
        """Fetch recent news headlines from Yahoo Finance."""
        try:
            import yfinance as yf

            ticker = yf.Ticker(symbol)
            news = ticker.news or []
            return [
                {
                    "title": item.get("title", ""),
                    "publisher": item.get("publisher", ""),
                    "link": item.get("link", ""),
                    "published": datetime.fromtimestamp(
                        item.get("providerPublishTime", 0)
                    ).isoformat(),
                    "source": "yahoo",
                }
                for item in news[:10]
            ]
        except Exception as e:
            logger.debug(f"Yahoo news error for {symbol}: {e}")
            return []

    def get_newsapi_headlines(self, query: str) -> list[dict]:
        """Fetch headlines from NewsAPI (requires API key)."""
        if not self._newsapi_key:
            return []
        try:
            from newsapi import NewsApiClient

            api = NewsApiClient(api_key=self._newsapi_key)
            week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
            result = api.get_everything(
                q=query,
                from_param=week_ago,
                language="en",
                sort_by="relevancy",
                page_size=10,
            )
            articles = result.get("articles", [])
            return [
                {
                    "title": a.get("title", ""),
                    "publisher": a.get("source", {}).get("name", ""),
                    "link": a.get("url", ""),
                    "published": a.get("publishedAt", ""),
                    "description": a.get("description", ""),
                    "source": "newsapi",
                }
                for a in articles
            ]
        except Exception as e:
            logger.debug(f"NewsAPI error for {query}: {e}")
            return []

    def get_all_news(self, symbol: str) -> list[dict]:
        """Aggregate news from all available sources."""
        all_news = []
        all_news.extend(self.get_yahoo_news(symbol))
        all_news.extend(self.get_newsapi_headlines(symbol))
        # Sort by published date descending
        all_news.sort(key=lambda x: x.get("published", ""), reverse=True)
        return all_news

    def has_catalyst(self, symbol: str) -> tuple[bool, str]:
        """Check if there's a recent news catalyst for this symbol."""
        news = self.get_all_news(symbol)
        if not news:
            return False, ""

        # Simple heuristic: if there are 3+ articles in last 24h, it's a catalyst
        recent_count = 0
        for article in news:
            try:
                pub = datetime.fromisoformat(article["published"].replace("Z", "+00:00"))
                if (datetime.now(pub.tzinfo) - pub).days < 1:
                    recent_count += 1
            except (ValueError, TypeError):
                continue

        if recent_count >= 3:
            return True, f"{recent_count} articles in last 24h: {news[0]['title']}"

        return False, ""
