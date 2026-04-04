"""Backtesting engine — replays past weeks to evaluate scanner performance.

Strategy: buy Monday open, sell Friday close, 1-week holding period.
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

    week_start: str  # Monday date ISO
    week_end: str  # Friday date ISO
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

    This prevents look-ahead bias: when simulating a Monday scan,
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
        # Only return data strictly before the cutoff
        return [p for p in all_prices if p.timestamp < self.cutoff]

    def get_current_price(self, symbol: str) -> float | None:
        """Return the last available close price before cutoff."""
        prices = self.get_price_history(symbol)
        if prices:
            return prices[-1].close
        return None

    def get_upcoming_earnings(self, symbol: str) -> int | None:
        # In backtest mode, skip earnings lookups to avoid API calls
        return None

    def get_short_interest(self, symbol: str) -> float | None:
        # In backtest mode, skip short interest lookups
        return None


class BacktestEngine:
    """Replays past weeks to evaluate the scanner's historical performance."""

    def __init__(
        self,
        config: AppConfig | None = None,
        capital: float = 1_000.0,
        symbols: list[str] | None = None,
    ):
        self.config = config or load_config()
        self.capital = capital
        self.symbols = symbols or DEFAULT_UNIVERSE

    def run(self, num_weeks: int = 12) -> BacktestResult:
        """Run the backtest over the last `num_weeks` weeks.

        For each historical week:
        1. Fetch data available up to Monday morning
        2. Run the scanner to generate signals
        3. Size positions
        4. Look up actual Monday open and Friday close prices
        5. Compute P&L
        """
        logger.info(f"Starting backtest: {num_weeks} weeks, ${self.capital:,.0f} capital")

        # Pre-fetch all historical data in one batch to be efficient.
        # We need enough history: num_weeks of weeks + 60 days lookback for indicators.
        total_days = num_weeks * 7 + 90
        price_cache = self._prefetch_data(total_days)

        # Build the list of (monday, friday) date pairs going backwards
        week_pairs = self._get_week_pairs(num_weeks, price_cache)

        if not week_pairs:
            logger.warning("No valid trading weeks found in the date range")
            return BacktestResult(starting_capital=self.capital, ending_capital=self.capital)

        running_capital = self.capital
        results: list[WeekResult] = []
        peak_capital = running_capital

        for monday, friday in week_pairs:
            week_result = self._simulate_week(monday, friday, running_capital, price_cache)
            running_capital = week_result.capital_end
            results.append(week_result)

            if running_capital > peak_capital:
                peak_capital = running_capital

        return self._compile_results(results, peak_capital)

    def _prefetch_data(self, total_days: int) -> dict[str, list[PriceData]]:
        """Download all price data up front to avoid repeated API calls."""
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

    def _get_week_pairs(
        self, num_weeks: int, price_cache: dict[str, list[PriceData]]
    ) -> list[tuple[datetime, datetime]]:
        """Find actual (Monday, Friday) trading day pairs from the data.

        If Monday is missing (holiday), use Tuesday.
        If Friday is missing (holiday), use Thursday.
        """
        # Gather all unique trading dates across all symbols
        all_dates: set[datetime] = set()
        for prices in price_cache.values():
            for p in prices:
                # Normalize to date only (midnight)
                all_dates.add(p.timestamp.replace(hour=0, minute=0, second=0, microsecond=0))

        if not all_dates:
            return []

        sorted_dates = sorted(all_dates)
        latest_date = sorted_dates[-1]

        pairs: list[tuple[datetime, datetime]] = []

        # Walk backwards from the most recent completed week
        # Start from the Friday before or on latest_date
        current = latest_date
        # Find the most recent Friday
        while current.weekday() != 4:  # 4 = Friday
            current -= timedelta(days=1)

        for _ in range(num_weeks):
            friday_target = current
            monday_target = friday_target - timedelta(days=4)

            # Find actual entry day: Monday, or Tuesday if Monday missing
            entry_day = self._find_nearest_trading_day(
                monday_target, sorted_dates, direction="forward", max_offset=1
            )
            # Find actual exit day: Friday, or Thursday if Friday missing
            exit_day = self._find_nearest_trading_day(
                friday_target, sorted_dates, direction="backward", max_offset=1
            )

            if entry_day and exit_day and entry_day < exit_day:
                pairs.append((entry_day, exit_day))

            # Move to previous week's Friday
            current -= timedelta(days=7)

        pairs.reverse()  # Chronological order
        return pairs

    def _find_nearest_trading_day(
        self,
        target: datetime,
        sorted_dates: list[datetime],
        direction: str = "forward",
        max_offset: int = 1,
    ) -> datetime | None:
        """Find the closest trading day to `target` within max_offset days."""
        for offset in range(max_offset + 1):
            delta = timedelta(days=offset)
            candidate = target + delta if direction == "forward" else target - delta
            # Check if this date is in our trading dates
            for d in sorted_dates:
                if d.date() == candidate.date():
                    return d
        return None

    def _simulate_week(
        self,
        monday: datetime,
        friday: datetime,
        capital: float,
        price_cache: dict[str, list[PriceData]],
    ) -> WeekResult:
        """Simulate one week: scan on Monday, buy at open, sell Friday close."""
        week = WeekResult(
            week_start=monday.strftime("%Y-%m-%d"),
            week_end=friday.strftime("%Y-%m-%d"),
            capital_start=capital,
            capital_end=capital,
        )

        if capital <= 0:
            return week

        # Create a historical market data provider that only sees data before Monday
        hist_md = _HistoricalMarketDataProvider(cutoff=monday, cache=price_cache)

        # Run the scanner as if it were Monday morning
        scanner = WeeklyScanner(self.config, hist_md)
        try:
            candidates = scanner.scan(self.symbols)
            signals = scanner.generate_signals(candidates)
        except Exception as e:
            logger.debug(f"Scanner failed for week {monday.date()}: {e}")
            return week

        if not signals:
            return week

        # Size positions
        sizer = PositionSizer(self.config)
        recommendations = sizer.size_positions(signals, capital)

        if not recommendations:
            return week

        # Simulate trades using actual Monday open / Friday close prices
        total_pnl = 0.0
        for rec in recommendations:
            symbol = rec.signal.asset.symbol
            if symbol not in price_cache:
                continue

            prices = price_cache[symbol]
            entry_price = self._get_price_on_date(prices, monday, field="open")
            exit_price = self._get_price_on_date(prices, friday, field="close")

            if entry_price is None or exit_price is None or entry_price <= 0:
                continue

            # Recompute quantity based on actual entry price
            alloc_capital = capital * (rec.allocation_pct / 100.0)
            quantity = int(alloc_capital / entry_price)
            if quantity <= 0:
                continue

            pnl = (exit_price - entry_price) * quantity
            return_pct = ((exit_price - entry_price) / entry_price) * 100

            trade = TradeSummary(
                symbol=symbol,
                strategy=rec.signal.strategy.value,
                confidence=rec.signal.confidence,
                entry_date=monday.strftime("%Y-%m-%d"),
                exit_date=friday.strftime("%Y-%m-%d"),
                entry_price=entry_price,
                exit_price=exit_price,
                quantity=quantity,
                allocation_pct=rec.allocation_pct,
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
        """Get a price field (open/close) for a specific date."""
        for p in prices:
            if p.timestamp.date() == target.date():
                return p.open if field == "open" else p.close
        return None

    def _compile_results(
        self,
        weeks: list[WeekResult],
        peak_capital: float,
    ) -> BacktestResult:
        """Aggregate per-week results into final backtest stats."""
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

        # Per-week stats
        weekly_returns = [w.weekly_return_pct for w in weeks]
        result.avg_weekly_return_pct = sum(weekly_returns) / len(weekly_returns) if weekly_returns else 0
        result.best_week_return_pct = max(weekly_returns) if weekly_returns else 0
        result.worst_week_return_pct = min(weekly_returns) if weekly_returns else 0

        # Trade-level stats
        all_trades = [t for w in weeks for t in w.trades]
        result.total_trades = len(all_trades)
        result.winning_trades = sum(1 for t in all_trades if t.pnl > 0)
        result.losing_trades = sum(1 for t in all_trades if t.pnl <= 0)
        result.win_rate = (result.winning_trades / result.total_trades * 100) if result.total_trades > 0 else 0

        # Max drawdown (based on weekly capital values)
        max_dd = 0.0
        running_peak = self.capital
        for w in weeks:
            if w.capital_end > running_peak:
                running_peak = w.capital_end
            dd = ((running_peak - w.capital_end) / running_peak * 100) if running_peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
        result.max_drawdown_pct = max_dd

        # Sharpe-like ratio: avg weekly return / std of weekly returns (annualized)
        if len(weekly_returns) > 1:
            avg_ret = np.mean(weekly_returns)
            std_ret = np.std(weekly_returns, ddof=1)
            if std_ret > 0:
                # Annualize: multiply by sqrt(52) since weekly periods
                result.sharpe_ratio = float((avg_ret / std_ret) * np.sqrt(52))
            else:
                result.sharpe_ratio = 0.0
        else:
            result.sharpe_ratio = 0.0

        return result
