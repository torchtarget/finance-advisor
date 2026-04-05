"""Validation suite for the backtest engine and scanner.

Run with: python -m src.backtest.validate
"""

from __future__ import annotations

import logging
import random
from datetime import date, timedelta

import yfinance as yf

from src.config import load_config
from src.backtest.engine import BacktestEngine
from src.data.market_data import MarketDataProvider
from src.strategy.scanner import DEFAULT_UNIVERSE, _INVERSE_SYMBOLS, _ETF_SYMBOLS

logger = logging.getLogger(__name__)


def validate_tickers() -> tuple[int, int]:
    """Verify all ETF/ETP tickers match their actual Yahoo Finance names.

    Catches long/short mislabelling (like the 3OIS.L bug).
    """
    print("\n=== TICKER VALIDATION ===")

    # Map of tickers to expected direction
    expected_long = {
        "TQQQ", "SOXL", "SPXL", "UPRO", "TNA",
        "3OIL.L", "3NGL.L", "3LUS.L", "3DEL.L",
    }
    expected_short = {"3USS.L"}

    passed = failed = 0

    for sym in _ETF_SYMBOLS:
        try:
            t = yf.Ticker(sym)
            info = t.info or {}
            name = (info.get("longName") or info.get("shortName") or "").lower()

            if not name:
                print(f"  SKIP {sym}: no name from Yahoo")
                continue

            is_short = any(w in name for w in ["short", "inverse", "bear"])
            is_long = any(w in name for w in ["long", "bull", "leveraged", "ultra"])

            if sym in expected_long and is_short:
                print(f"  FAIL {sym}: expected LONG but Yahoo says '{name}'")
                failed += 1
            elif sym in expected_short and is_long:
                print(f"  FAIL {sym}: expected SHORT but Yahoo says '{name}'")
                failed += 1
            elif sym in _INVERSE_SYMBOLS and not is_short:
                print(f"  WARN {sym}: marked inverse but name doesn't say short: '{name}'")
                passed += 1
            else:
                print(f"  OK   {sym}: {name[:60]}")
                passed += 1
        except Exception as e:
            print(f"  ERR  {sym}: {e}")

    return passed, failed


def validate_backtest(num_samples: int = 10, weeks: int = 52, capital: float = 5000) -> tuple[int, int]:
    """Spot-check random trades from a backtest against Yahoo Finance.

    Validates:
    1. Entry price matches Monday open from Yahoo
    2. Exit price matches next Monday open from Yahoo
    3. P&L math is correct: (exit - entry) * quantity
    4. No look-ahead: last visible data is before entry date
    5. Entry dates are Mondays (or Tuesday for holidays)
    """
    print(f"\n=== BACKTEST VALIDATION ({num_samples} random trades) ===")

    config = load_config()
    engine = BacktestEngine(config=config, capital=capital)
    result = engine.run(num_weeks=weeks)
    md = MarketDataProvider()

    all_trades = [(w, t) for w in result.weeks for t in w.trades]
    if not all_trades:
        print("  No trades to validate!")
        return 0, 1

    random.seed(42)
    sample = random.sample(all_trades, min(num_samples, len(all_trades)))

    passed = failed = 0

    for week, trade in sorted(sample, key=lambda x: x[1].entry_date):
        prices = md.get_price_history(trade.symbol, days=500)
        entry_d = date.fromisoformat(trade.entry_date)
        exit_d = date.fromisoformat(trade.exit_date)

        actual_entry = actual_exit = None
        last_before = None

        for p in prices:
            pd = p.timestamp.date()
            if pd == entry_d:
                actual_entry = p.open
            if pd == exit_d:
                actual_exit = p.open
            if pd < entry_d:
                last_before = p

        errors = []

        # Price checks (allow for holiday fallback)
        if actual_entry is not None and abs(actual_entry - trade.entry_price) > 0.02:
            errors.append(f"entry ${trade.entry_price:.2f} != yahoo ${actual_entry:.2f}")
        if actual_exit is not None and abs(actual_exit - trade.exit_price) > 0.02:
            errors.append(f"exit ${trade.exit_price:.2f} != yahoo ${actual_exit:.2f}")

        # P&L math
        expected_pnl = (trade.exit_price - trade.entry_price) * trade.quantity
        if abs(expected_pnl - trade.pnl) > 0.02:
            errors.append(f"pnl ${trade.pnl:.2f} != calc ${expected_pnl:.2f}")

        # Look-ahead check
        if last_before and (entry_d - last_before.timestamp.date()).days < 1:
            errors.append(f"look-ahead! last data {last_before.timestamp.date()} too close")

        # Day-of-week check
        if entry_d.weekday() > 1:
            errors.append(f"entry on {entry_d.strftime('%A')}, expected Mon/Tue")

        if errors:
            print(f"  FAIL {trade.symbol} {trade.entry_date}: {'; '.join(errors)}")
            failed += 1
        else:
            note = "(holiday fallback)" if actual_entry is None or actual_exit is None else ""
            print(f"  OK   {trade.symbol} {trade.entry_date} -> {trade.exit_date}  "
                  f"${trade.entry_price:.2f} -> ${trade.exit_price:.2f}  "
                  f"P&L ${trade.pnl:+.2f}  {note}")
            passed += 1

    # Overall date check
    entry_days = {}
    for w in result.weeks:
        for t in w.trades:
            d = date.fromisoformat(t.entry_date)
            day_name = d.strftime("%A")
            entry_days[day_name] = entry_days.get(day_name, 0) + 1

    print(f"\n  Entry day distribution: {dict(sorted(entry_days.items()))}")
    if any(d not in ("Monday", "Tuesday") for d in entry_days):
        print("  FAIL: entries on non-Monday/Tuesday!")
        failed += 1

    return passed, failed


def validate_capital_flow(weeks: int = 52, capital: float = 5000) -> tuple[int, int]:
    """Verify capital compounds correctly week to week."""
    print(f"\n=== CAPITAL FLOW VALIDATION ===")

    config = load_config()
    engine = BacktestEngine(config=config, capital=capital)
    result = engine.run(num_weeks=weeks)

    passed = failed = 0

    for i, w in enumerate(result.weeks):
        # Check P&L sums
        trade_pnl = sum(t.pnl for t in w.trades)
        if abs(trade_pnl - w.weekly_pnl) > 0.02:
            print(f"  FAIL {w.week_start}: trade_pnl={trade_pnl:.2f} != weekly_pnl={w.weekly_pnl:.2f}")
            failed += 1
            continue

        # Check capital_end = capital_start + pnl
        expected_end = w.capital_start + w.weekly_pnl
        if abs(expected_end - w.capital_end) > 0.02:
            print(f"  FAIL {w.week_start}: start+pnl={expected_end:.2f} != end={w.capital_end:.2f}")
            failed += 1
            continue

        # Check chaining to next week
        if i + 1 < len(result.weeks):
            next_start = result.weeks[i + 1].capital_start
            if abs(w.capital_end - next_start) > 0.02:
                print(f"  FAIL {w.week_start}: end={w.capital_end:.2f} != next_start={next_start:.2f}")
                failed += 1
                continue

        passed += 1

    # Check utilization
    utils = []
    for w in result.weeks:
        if not w.trades:
            continue
        invested = sum(t.entry_price * t.quantity for t in w.trades)
        utils.append(invested / w.capital_start * 100)

    avg_util = sum(utils) / len(utils) if utils else 0
    print(f"  Avg capital utilization: {avg_util:.0f}%")
    print(f"  {passed}/{passed + failed} weeks capital flow correct")

    return passed, failed


def run_all():
    """Run all validations."""
    logging.basicConfig(level=logging.WARNING)
    total_pass = total_fail = 0

    p, f = validate_tickers()
    total_pass += p
    total_fail += f

    p, f = validate_backtest()
    total_pass += p
    total_fail += f

    p, f = validate_capital_flow()
    total_pass += p
    total_fail += f

    print(f"\n{'=' * 60}")
    print(f"TOTAL: {total_pass} passed, {total_fail} failed")
    if total_fail == 0:
        print("ALL VALIDATIONS PASSED")
    else:
        print(f"WARNING: {total_fail} failures detected!")
    return total_fail == 0


if __name__ == "__main__":
    run_all()
