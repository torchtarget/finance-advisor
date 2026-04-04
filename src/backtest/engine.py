"""Backtesting engine — replays past weeks to evaluate scanner performance.

Strategy: buy Monday open, sell NEXT Monday open, 1-week holding period.
No look-ahead bias: indicators are computed only on data available before each Monday.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timedelta

import numpy as np
import yfinance as yf

from src.config import AppConfig, load_config
from src.data.market_data import MarketDataProvider
from src.models import PriceData
from src.risk.position_sizer import PositionSizer
from src.strategy.scanner import WeeklyScanner, DEFAULT_UNIVERSE
from src.strategy import strategies as _  # noqa: F401 — registers strategies

logger = logging.getLogger(__name__)


@dataclass
class TradeSummary:
    """Result of a single simulated trade within a backtest week."""

    symbol: str
    strategy: str
    confidence: float
    entry_date: str
    exit_date: str
    entry_price: float
    exit_price: float
    quantity: int
    allocation_pct: float
    pnl: float
    return_pct: float


@dataclass
class WeekResult:
    """Aggregate result for one simulated week."""

    week_start: str  # Entry Monday ISO date
    week_end: str  # Exit Monday ISO date
    trades: list[TradeSummary] = field(default_factory=list)
    weekly_pnl: float = 0.0
    weekly_return_pct: float = 0.0
    capital_start: float = 0.0
    capital_end: float = 0.0


@dataclass
class BacktestResult:
    """Full backtest output."""

    weeks: list[WeekResult] = field(default_factory=list)
    total_return_pct: float = 0.0
    total_pnl: float = 0.0
    win_rate: float = 0.0
    avg_weekly_return_pct: float = 0.0
    best_week_return_pct: float = 0.0
    worst_week_return_pct: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    total_trades: int = 0
    winning_trades: int = 0
    losing_trades: int = 0
    starting_capital: float = 0.0
    ending_capital: float = 0.0

    def to_dict(self) -> dict:
        """Serialize for JSON API response."""
        return {
            "summary": {
                "starting_capital": round(self.starting_capital, 2),
                "ending_capital": round(self.ending_capital, 2),
                "total_pnl": round(self.total_pnl, 2),
                "total_return_pct": round(self.total_return_pct, 2),
                "win_rate": round(self.win_rate, 2),
                "avg_weekly_return_pct": round(self.avg_weekly_return_pct, 2),
                "best_week_return_pct": round(self.best_week_return_pct, 2),
                "worst_week_return_pct": round(self.worst_week_return_pct, 2),
                "max_drawdown_pct": round(self.max_drawdown_pct, 2),
                "sharpe_ratio": round(self.sharpe_ratio, 2),
                "total_trades": self.total_trades,
                "winning_trades": self.winning_trades,
                "losing_trades": self.losing_trades,
            },
            "weeks": [
                {
                    "week_start": w.week_start,
                    "week_end": w.week_end,
                    "capital_start": round(w.capital_start, 2),
                    "capital_end": round(w.capital_end, 2),
                    "weekly_pnl": round(w.weekly_pnl, 2),
                    "weekly_return_pct": round(w.weekly_return_pct, 2),
                    "trades": [
                        {
                            "symbol": t.symbol,
                            "strategy": t.strategy,
                            "confidence": round(t.confidence, 3),
                            "entry_date": t.entry_date,
                            "exit_date": t.exit_date,
                            "entry_price": round(t.entry_price, 2),
                            "exit_price": round(t.exit_price, 2),
                            "quantity": t.quantity,
                            "allocation_pct": round(t.allocation_pct, 1),
                            "pnl": round(t.pnl, 2),
                            "return_pct": round(t.return_pct, 2),
                        }
                        for t in w.trades
                    ],
                }
                for w in self.weeks
            ],
        }


class _HistoricalMarketDataProvider(MarketDataProvider):
    """MarketDataProvider that returns data only up to a cutoff date.

    Prevents look-ahead bias: when simulating a Monday scan,
    only price data available before that Monday is used.
    """

    def __init__(self, cutoff: datetime, cache: dict[str, list[PriceData]] | None = None):
        super().__init__()
        self.cutoff = cutoff
        self._cache = cache if cache is not None else {}

    def get_price_history(
        self,
        symbol: str,
        days: int = 60,
        interval: str = "1d",
    ) -> list[PriceData]:
        """Return price history up to (but not including) the cutoff date."""
        if symbol not in self._cache:
            return []
        all_prices = self._cache[symbol]
        return [p for p in all_prices if p.timestamp < self.cutoff]

    def get_current_price(self, symbol: str) -> float | None:
        prices = self.get_price_history(symbol)
        return prices[-1].close if prices else None

    def get_upcoming_earnings(self, symbol: str) -> int | None:
        return None  # Skip API calls in backtest

    def get_short_interest(self, symbol: str) -> float | None:
        return None  # Skip API calls in backtest


class BacktestEngine:
    """Replays past weeks: buy Monday open, sell next Monday open."""

    def __init__(
        self,
        config: AppConfig | None = None,
        capital: float = 1_000.0,
        symbols: list[str] | None = None,
    ):
        self.config = config or load_config()
        self.capital = capital
        self.symbols = symbols or DEFAULT_UNIVERSE

    def run(self, num_weeks: int = 52) -> BacktestResult:
        """Run the backtest over the last `num_weeks` weeks.

        For each week:
        1. On entry Monday: run scanner using only pre-Monday data
        2. Buy at Monday's open price
        3. Sell at NEXT Monday's open price (7 calendar days later)
        4. Compound capital week to week
        """
        logger.info(f"Starting backtest: {num_weeks} weeks, ${self.capital:,.0f} capital")

        # Need enough data: num_weeks + lookback for indicators + buffer
        total_days = num_weeks * 7 + 120
        price_cache = self._prefetch_data(total_days)

        # Build list of (entry_monday, exit_monday) pairs
        monday_pairs = self._get_monday_pairs(num_weeks, price_cache)

        if not monday_pairs:
            logger.warning("No valid trading weeks found")
            return BacktestResult(starting_capital=self.capital, ending_capital=self.capital)

        logger.info(f"Found {len(monday_pairs)} trading weeks to simulate")

        running_capital = self.capital
        results: list[WeekResult] = []

        for entry_monday, exit_monday in monday_pairs:
            week_result = self._simulate_week(entry_monday, exit_monday, running_capital, price_cache)
            running_capital = week_result.capital_end
            results.append(week_result)

            # Safety: stop if capital goes to zero
            if running_capital <= 0:
                logger.warning(f"Capital depleted at week {entry_monday.date()}")
                break

        return self._compile_results(results)

    def _prefetch_data(self, total_days: int) -> dict[str, list[PriceData]]:
        """Download all price data up front."""
        logger.info(f"Prefetching {len(self.symbols)} symbols ({total_days} days)...")
        cache: dict[str, list[PriceData]] = {}
        market_data = MarketDataProvider()

        for symbol in self.symbols:
            try:
                prices = market_data.get_price_history(symbol, days=total_days)
                if prices:
                    cache[symbol] = prices
            except Exception as e:
                logger.debug(f"Failed to prefetch {symbol}: {e}")

        logger.info(f"Prefetched data for {len(cache)} symbols")
        return cache

    def _get_monday_pairs(
        self, num_weeks: int, price_cache: dict[str, list[PriceData]]
    ) -> list[tuple[datetime, datetime]]:
        """Find consecutive Monday pairs from actual trading data.

        Each pair is (entry_monday, exit_monday) = buy and sell dates.
        If Monday is a holiday, use Tuesday.
        """
        # Gather all unique trading dates
        all_dates: set[datetime] = set()
        for prices in price_cache.values():
            for p in prices:
                all_dates.add(p.timestamp.replace(hour=0, minute=0, second=0, microsecond=0))

        if not all_dates:
            return []

        sorted_dates = sorted(all_dates)

        # Find all Mondays (or Tuesday substitutes) in the data
        mondays: list[datetime] = []
        seen_weeks: set[tuple[int, int]] = set()  # (year, week_number)

        for d in sorted_dates:
            year_week = d.isocalendar()[:2]
            if year_week in seen_weeks:
                continue
            # Accept Monday (0) or Tuesday (1) as week start
            if d.weekday() <= 1:
                seen_weeks.add(year_week)
                mondays.append(d)

        if len(mondays) < 2:
            return []

        # Take the last num_weeks+1 mondays to form num_weeks pairs
        relevant = mondays[-(num_weeks + 1):]

        pairs = []
        for i in range(len(relevant) - 1):
            pairs.append((relevant[i], relevant[i + 1]))

        return pairs

    def _simulate_week(
        self,
        entry_monday: datetime,
        exit_monday: datetime,
        capital: float,
        price_cache: dict[str, list[PriceData]],
    ) -> WeekResult:
        """Simulate one week: scan on entry Monday, buy at open, sell next Monday open."""
        week = WeekResult(
            week_start=entry_monday.strftime("%Y-%m-%d"),
            week_end=exit_monday.strftime("%Y-%m-%d"),
            capital_start=capital,
            capital_end=capital,
        )

        if capital <= 0:
            return week

        # Scanner sees only data before entry Monday
        hist_md = _HistoricalMarketDataProvider(cutoff=entry_monday, cache=price_cache)

        scanner = WeeklyScanner(self.config, hist_md)
        try:
            candidates = scanner.scan(self.symbols)
            signals = scanner.generate_signals(candidates)
        except Exception as e:
            logger.debug(f"Scanner failed for week {entry_monday.date()}: {e}")
            return week

        if not signals:
            return week

        sizer = PositionSizer(self.config)
        recommendations = sizer.size_positions(signals, capital)

        if not recommendations:
            return week

        # Resolve actual Monday open prices and compute quantities
        # Deploy ALL capital — redistribute rounding leftovers
        trade_specs: list[dict] = []
        for rec in recommendations:
            symbol = rec.signal.asset.symbol
            if symbol not in price_cache:
                continue

            prices = price_cache[symbol]
            entry_price = self._get_price_on_date(prices, entry_monday, field="open")
            exit_price = self._get_price_on_date(prices, exit_monday, field="open")

            if entry_price is None or exit_price is None or entry_price <= 0:
                continue

            trade_specs.append({
                "rec": rec,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "quantity": 0,
            })

        if not trade_specs:
            return week

        # First pass: allocate based on sizer percentages
        remaining = capital
        for spec in trade_specs:
            alloc = capital * (spec["rec"].allocation_pct / 100.0)
            qty = int(alloc / spec["entry_price"])
            spec["quantity"] = qty
            remaining -= qty * spec["entry_price"]

        # Second pass: redistribute ALL remaining capital across positions
        # Keep buying shares of the cheapest affordable stock until nothing fits
        changed = True
        while changed and remaining > 0:
            changed = False
            for spec in trade_specs:
                price = spec["entry_price"]
                if price <= remaining:
                    extra = int(remaining / price)
                    if extra > 0:
                        spec["quantity"] += extra
                        remaining -= extra * price
                        changed = True

        # Build trade summaries
        total_pnl = 0.0
        for spec in trade_specs:
            quantity = spec["quantity"]
            if quantity <= 0:
                continue

            entry_price = spec["entry_price"]
            exit_price = spec["exit_price"]
            pnl = (exit_price - entry_price) * quantity
            return_pct = ((exit_price - entry_price) / entry_price) * 100
            actual_alloc = (entry_price * quantity / capital * 100) if capital > 0 else 0

            trade = TradeSummary(
                symbol=spec["rec"].signal.asset.symbol,
                strategy=spec["rec"].signal.strategy.value,
                confidence=spec["rec"].signal.confidence,
                entry_date=entry_monday.strftime("%Y-%m-%d"),
                exit_date=exit_monday.strftime("%Y-%m-%d"),
                entry_price=entry_price,
                exit_price=exit_price,
                quantity=quantity,
                allocation_pct=actual_alloc,
                pnl=pnl,
                return_pct=return_pct,
            )
            week.trades.append(trade)
            total_pnl += pnl

        week.weekly_pnl = total_pnl
        week.capital_end = capital + total_pnl
        week.weekly_return_pct = (total_pnl / capital * 100) if capital > 0 else 0.0

        return week

    def _get_price_on_date(
        self,
        prices: list[PriceData],
        target: datetime,
        field: str = "close",
    ) -> float | None:
        """Get a price field (open/close) for a specific date, or nearest trading day."""
        # Exact match first
        for p in prices:
            if p.timestamp.date() == target.date():
                return p.open if field == "open" else p.close

        # Try next day (if Monday was holiday, use Tuesday)
        next_day = target + timedelta(days=1)
        for p in prices:
            if p.timestamp.date() == next_day.date():
                return p.open if field == "open" else p.close

        return None

    def _compile_results(self, weeks: list[WeekResult]) -> BacktestResult:
        """Aggregate per-week results into final stats."""
        result = BacktestResult(
            weeks=weeks,
            starting_capital=self.capital,
        )

        if not weeks:
            result.ending_capital = self.capital
            return result

        result.ending_capital = weeks[-1].capital_end
        result.total_pnl = result.ending_capital - self.capital
        result.total_return_pct = (result.total_pnl / self.capital * 100) if self.capital > 0 else 0

        weekly_returns = [w.weekly_return_pct for w in weeks]
        result.avg_weekly_return_pct = np.mean(weekly_returns) if weekly_returns else 0
        result.best_week_return_pct = max(weekly_returns) if weekly_returns else 0
        result.worst_week_return_pct = min(weekly_returns) if weekly_returns else 0

        # Trade stats
        all_trades = [t for w in weeks for t in w.trades]
        result.total_trades = len(all_trades)
        result.winning_trades = sum(1 for t in all_trades if t.pnl > 0)
        result.losing_trades = sum(1 for t in all_trades if t.pnl <= 0)
        result.win_rate = (result.winning_trades / result.total_trades * 100) if result.total_trades > 0 else 0

        # Max drawdown
        max_dd = 0.0
        running_peak = self.capital
        for w in weeks:
            if w.capital_end > running_peak:
                running_peak = w.capital_end
            dd = ((running_peak - w.capital_end) / running_peak * 100) if running_peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
        result.max_drawdown_pct = max_dd

        # Annualized Sharpe ratio (weekly returns, 52 periods/year)
        if len(weekly_returns) > 1:
            avg_ret = np.mean(weekly_returns)
            std_ret = np.std(weekly_returns, ddof=1)
            if std_ret > 0:
                result.sharpe_ratio = float((avg_ret / std_ret) * np.sqrt(52))
            else:
                result.sharpe_ratio = 0.0

        return result
