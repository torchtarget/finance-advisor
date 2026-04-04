"""FastAPI backend serving data to the React frontend."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src.config import load_config
from src.data.market_data import MarketDataProvider
from src.data.finnhub_client import FinnhubClient
from src.data.news_client import NewsClient
from src.execution.paper_trader import PaperTrader
from src.models import Recommendation
from src.risk.position_sizer import PositionSizer
from src.strategy.scanner import WeeklyScanner, DEFAULT_UNIVERSE
from src.strategy import strategies as _  # noqa: F401
from src.backtest.engine import BacktestEngine

logger = logging.getLogger(__name__)

app = FastAPI(title="Finance Advisor API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global state
config = load_config()
market_data = MarketDataProvider()
finnhub = FinnhubClient(api_key=config.market_data.finnhub_api_key)
news_client = NewsClient(newsapi_key=config.market_data.newsapi_key)
paper_trader = PaperTrader(starting_capital=1_000.0)


# --- Request/Response models ---

class ScanRequest(BaseModel):
    capital: float = 1_000.0
    symbols: list[str] | None = None


# --- API Routes ---

@app.get("/api/health")
def health():
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


@app.get("/api/config")
def get_config():
    """Return current configuration (excluding secrets)."""
    return {
        "strategy": config.strategy.model_dump(),
        "risk": config.risk.model_dump(),
        "scanner": config.scanner.model_dump(),
        "market_data": {
            "exchanges": config.market_data.exchanges,
            "asset_types": config.market_data.asset_types,
        },
    }


@app.get("/api/data-sources")
def get_data_sources():
    """List all data sources and their status."""
    return {
        "sources": [
            {
                "name": "Yahoo Finance",
                "type": "Market Data",
                "status": "active",
                "provides": [
                    "OHLCV prices", "Fundamentals", "Earnings dates",
                    "Short interest", "News headlines",
                ],
                "cost": "Free",
            },
            {
                "name": "Finnhub",
                "type": "Market Data + Sentiment",
                "status": "active" if finnhub.available else "no_api_key",
                "provides": [
                    "Real-time quotes", "News sentiment", "Insider transactions",
                    "Social sentiment", "Analyst ratings",
                ],
                "cost": "Free tier: 60 calls/min",
                "key_env": "FINNHUB_API_KEY",
            },
            {
                "name": "NewsAPI",
                "type": "News",
                "status": "active" if news_client._newsapi_key else "no_api_key",
                "provides": [
                    "News headlines", "Article search", "Catalyst detection",
                ],
                "cost": "Free tier: 100 req/day",
                "key_env": "NEWSAPI_KEY",
            },
        ]
    }


@app.post("/api/scan")
def run_scan(request: ScanRequest):
    """Scan the market and return ranked buy/sell recommendations."""
    scanner = WeeklyScanner(config, market_data)

    candidates = scanner.scan(request.symbols or None)
    signals = scanner.generate_signals(candidates)

    if not signals:
        return {"recommendations": [], "message": "No signals found this scan"}

    sizer = PositionSizer(config)
    recommendations = sizer.size_positions(signals, request.capital)

    return {
        "recommendations": [_format_recommendation(r) for r in recommendations],
        "scanned_at": datetime.utcnow().isoformat(),
        "total_candidates": len(candidates),
        "total_signals": len(signals),
        "capital": request.capital,
    }


@app.get("/api/quote/{symbol}")
def get_quote(symbol: str):
    """Get current quote and indicators for a symbol."""
    prices = market_data.get_price_history(symbol, days=60)
    if not prices:
        raise HTTPException(404, f"No data found for {symbol}")

    indicators = market_data.compute_indicators(prices)
    current = prices[-1]

    week_change = 0.0
    if len(prices) >= 5:
        week_change = ((current.close - prices[-5].close) / prices[-5].close) * 100

    return {
        "symbol": symbol,
        "price": current.close,
        "open": current.open,
        "high": current.high,
        "low": current.low,
        "volume": current.volume,
        "week_change_pct": round(week_change, 2),
        "indicators": {k: v for k, v in indicators.model_dump().items() if v is not None},
        "price_history": [
            {
                "date": p.timestamp.isoformat(),
                "open": p.open,
                "high": p.high,
                "low": p.low,
                "close": p.close,
                "volume": p.volume,
            }
            for p in prices[-30:]
        ],
    }


@app.get("/api/news/{symbol}")
def get_news(symbol: str):
    """Get recent news for a symbol."""
    articles = news_client.get_all_news(symbol)
    has_catalyst, catalyst_desc = news_client.has_catalyst(symbol)

    return {
        "symbol": symbol,
        "articles": articles,
        "has_catalyst": has_catalyst,
        "catalyst": catalyst_desc,
    }


@app.get("/api/sentiment/{symbol}")
def get_sentiment(symbol: str):
    """Get sentiment data from Finnhub."""
    if not finnhub.available:
        return {"symbol": symbol, "available": False, "message": "Finnhub API key not configured"}

    news_sent = finnhub.get_news_sentiment(symbol)
    social = finnhub.get_social_sentiment(symbol)
    recs = finnhub.get_recommendation_trends(symbol)
    insiders = finnhub.get_insider_transactions(symbol)

    return {
        "symbol": symbol,
        "available": True,
        "news": news_sent,
        "social": social,
        "analyst_recommendations": recs[:3] if recs else [],
        "insider_transactions": insiders[:10],
    }


@app.get("/api/portfolio")
def get_portfolio():
    """Get current paper tracking portfolio (for tracking what-if performance)."""
    positions = []
    for pos in paper_trader.positions:
        current = market_data.get_current_price(pos.asset.symbol) or pos.current_price
        pos.current_price = current
        positions.append({
            "symbol": pos.asset.symbol,
            "quantity": pos.quantity,
            "entry_price": pos.avg_entry_price,
            "current_price": current,
            "pnl": pos.unrealized_pnl,
            "pnl_pct": round(pos.pnl_pct * 100, 2),
            "allocation_pct": pos.allocation_pct,
            "strategy": pos.strategy.value if pos.strategy else None,
            "opened_at": pos.opened_at.isoformat(),
        })

    total_value = paper_trader.get_total_value(market_data.get_current_price)

    return {
        "cash": round(paper_trader.cash, 2),
        "positions": positions,
        "total_value": round(total_value, 2),
        "starting_capital": paper_trader.starting_capital,
        "total_return_pct": round(
            ((total_value - paper_trader.starting_capital) / paper_trader.starting_capital) * 100, 2
        ),
    }


@app.post("/api/paper/buy")
def paper_buy(request: ScanRequest):
    """Track paper trades for the top recommendations (what-if tracking)."""
    scanner = WeeklyScanner(config, market_data)
    signals = scanner.generate_signals()

    if not signals:
        return {"trades": [], "message": "No signals to track"}

    sizer = PositionSizer(config)
    recommendations = sizer.size_positions(signals, request.capital)

    orders = []
    for rec in recommendations:
        order = paper_trader.execute_recommendation(rec)
        orders.append({
            "symbol": order.asset.symbol,
            "direction": order.direction.value,
            "quantity": order.quantity,
            "price": order.filled_price,
            "status": order.status.value,
        })

    return {"trades": orders, "portfolio": get_portfolio()}


@app.post("/api/paper/close-all")
def paper_close_all():
    """Close all paper positions."""
    orders = paper_trader.close_all_positions(market_data.get_current_price)
    return {
        "closed": [
            {
                "symbol": o.asset.symbol,
                "quantity": o.quantity,
                "price": o.filled_price,
            }
            for o in orders
        ],
        "portfolio": get_portfolio(),
    }


@app.get("/api/backtest")
def run_backtest(weeks: int = 12, capital: float = 1_000.0):
    """Run a historical backtest and return results as JSON."""
    engine = BacktestEngine(config=config, capital=capital)
    result = engine.run(num_weeks=weeks)
    return result.to_dict()


@app.get("/api/universe")
def get_universe():
    """Return the scan universe — all instruments available on DeGiro."""
    return {
        "symbols": DEFAULT_UNIVERSE,
        "total": len(DEFAULT_UNIVERSE),
    }


@app.get("/api/strategies")
def get_strategies():
    """List all available strategies."""
    from src.strategy.base import StrategyRegistry

    strategies = StrategyRegistry.get_enabled(config)
    return {
        "strategies": [
            {"name": s.name, "description": s.describe()}
            for s in strategies
        ],
        "enabled": config.strategy.enabled_strategies,
    }


def _format_recommendation(rec: Recommendation) -> dict:
    sig = rec.signal
    return {
        "rank": rec.rank,
        "symbol": sig.asset.symbol,
        "direction": sig.direction.value,
        "strategy": sig.strategy.value,
        "confidence": round(sig.confidence, 3),
        "entry_price": round(sig.entry_price, 2),
        "target_price": round(sig.target_price, 2) if sig.target_price else None,
        "expected_return_pct": round(sig.expected_return_pct, 1) if sig.expected_return_pct else None,
        "allocation_pct": round(rec.allocation_pct, 1),
        "quantity": rec.suggested_quantity,
        "cost": round(sig.entry_price * rec.suggested_quantity, 2),
        "max_loss_pct": round(rec.max_loss_pct, 1) if rec.max_loss_pct else None,
        "rationale": sig.rationale,
        "generated_at": sig.generated_at.isoformat(),
    }


# Serve React build if it exists
frontend_build = Path(__file__).parent.parent.parent / "frontend" / "dist"
if frontend_build.exists():
    app.mount("/", StaticFiles(directory=str(frontend_build), html=True), name="frontend")
