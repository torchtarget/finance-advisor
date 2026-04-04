"""Finnhub data source — real-time quotes, news sentiment, insider trades."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import finnhub

logger = logging.getLogger(__name__)


class FinnhubClient:
    """Wraps Finnhub API for supplementary market data."""

    def __init__(self, api_key: str):
        self._client = finnhub.Client(api_key=api_key) if api_key else None

    @property
    def available(self) -> bool:
        return self._client is not None

    def get_quote(self, symbol: str) -> dict | None:
        """Real-time quote: current, high, low, open, prev close, timestamp."""
        if not self.available:
            return None
        try:
            return self._client.quote(symbol)
        except Exception as e:
            logger.debug(f"Finnhub quote error for {symbol}: {e}")
            return None

    def get_news_sentiment(self, symbol: str) -> dict | None:
        """Get news sentiment score for a symbol."""
        if not self.available:
            return None
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            week_ago = (datetime.now() - timedelta(days=7)).strftime("%Y-%m-%d")
            news = self._client.company_news(symbol, _from=week_ago, to=today)
            if not news:
                return {"score": 0, "articles": 0}

            # Finnhub doesn't directly give sentiment — count positive/negative headlines
            # as a basic proxy. Can be enhanced with NLP.
            return {
                "articles": len(news),
                "latest_headlines": [n.get("headline", "") for n in news[:5]],
                "sources": list({n.get("source", "") for n in news[:10]}),
            }
        except Exception as e:
            logger.debug(f"Finnhub news error for {symbol}: {e}")
            return None

    def get_insider_transactions(self, symbol: str) -> list[dict]:
        """Recent insider buy/sell transactions."""
        if not self.available:
            return []
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            three_months_ago = (datetime.now() - timedelta(days=90)).strftime("%Y-%m-%d")
            result = self._client.stock_insider_transactions(symbol, three_months_ago, today)
            txns = result.get("data", []) if result else []

            return [
                {
                    "name": t.get("name", ""),
                    "share": t.get("share", 0),
                    "change": t.get("change", 0),
                    "transaction_type": "BUY" if t.get("change", 0) > 0 else "SELL",
                    "date": t.get("transactionDate", ""),
                }
                for t in txns[:20]
            ]
        except Exception as e:
            logger.debug(f"Finnhub insider error for {symbol}: {e}")
            return []

    def get_recommendation_trends(self, symbol: str) -> list[dict]:
        """Analyst recommendation trends."""
        if not self.available:
            return []
        try:
            return self._client.recommendation_trends(symbol) or []
        except Exception as e:
            logger.debug(f"Finnhub recommendation error for {symbol}: {e}")
            return []

    def get_earnings_calendar(self, days_ahead: int = 7) -> list[dict]:
        """Upcoming earnings for the next N days."""
        if not self.available:
            return []
        try:
            today = datetime.now().strftime("%Y-%m-%d")
            end = (datetime.now() + timedelta(days=days_ahead)).strftime("%Y-%m-%d")
            result = self._client.earnings_calendar(_from=today, to=end, symbol="")
            return result.get("earningsCalendar", []) if result else []
        except Exception as e:
            logger.debug(f"Finnhub earnings calendar error: {e}")
            return []

    def get_social_sentiment(self, symbol: str) -> dict | None:
        """Social media sentiment (Reddit, Twitter)."""
        if not self.available:
            return None
        try:
            reddit = self._client.stock_social_sentiment(symbol)
            return reddit if reddit else None
        except Exception as e:
            logger.debug(f"Finnhub social sentiment error for {symbol}: {e}")
            return None
