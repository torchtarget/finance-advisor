"""Weekly scanner — finds the best speculative candidates for NEXT Monday.

Scans Friday's close data to recommend buys for Monday open.
Covers US + European instruments available on DeGiro.
"""

from __future__ import annotations

import logging
from datetime import datetime

from src.config import AppConfig
from src.data.market_data import MarketDataProvider
from src.models import Asset, AssetType, ScannerResult, Signal
from src.strategy.base import StrategyRegistry

logger = logging.getLogger(__name__)

# Instruments available on DeGiro — US + European exchanges
DEFAULT_UNIVERSE = [
    # === US — NYSE & NASDAQ (available on DeGiro) ===

    # US Large-cap Tech (high beta)
    "NVDA", "AMD", "TSLA", "META", "AMZN", "GOOGL", "MSFT", "AAPL", "NFLX", "CRM",
    # US Growth / Momentum
    "PLTR", "SNOW", "COIN", "SHOP", "ROKU", "DKNG", "RBLX", "HOOD", "SOFI",
    # US Biotech (volatile)
    "MRNA", "BNTX", "CRSP", "EDIT", "NTLA", "BEAM",
    # US Meme / High Short Interest
    "GME", "AMC", "RIVN", "LCID", "NIO",
    # US Semis
    "MU", "MRVL", "AVGO", "QCOM", "ARM", "SMCI",
    # US Energy (volatile)
    "OXY", "DVN", "FANG",
    # US Leveraged ETFs
    "TQQQ", "SOXL", "SPXL", "UPRO", "TNA",

    # === Europe — Amsterdam (Euronext AMS, DeGiro home exchange) ===
    "ASML.AS", "ADYEN.AS", "PHIA.AS", "INGA.AS",
    "ASM.AS", "BESI.AS", "AKZA.AS", "WKL.AS",

    # === Europe — XETRA / Frankfurt (German stocks on DeGiro) ===
    "SAP.DE", "SIE.DE", "ALV.DE", "BAS.DE", "DTE.DE",
    "BMW.DE", "VOW3.DE", "IFX.DE", "MRK.DE", "RHM.DE",

    # === Europe — London (LSE, available on DeGiro) ===
    "SHEL.L", "AZN.L", "HSBA.L", "GSK.L", "BP.L",
    "RIO.L", "LSEG.L", "DGE.L", "BARC.L", "LLOY.L",

    # === Europe — Paris (Euronext Paris) ===
    "MC.PA", "OR.PA", "SAN.PA", "AI.PA", "BNP.PA",
    "TTE.PA", "SU.PA", "AIR.PA", "CS.PA", "DG.PA",

    # === Europe — Other (available on DeGiro) ===
    "NESN.SW",   # Nestle (Swiss)
    "NOVN.SW",   # Novartis (Swiss)
    "ROG.SW",    # Roche (Swiss)
    "NOVO-B.CO", # Novo Nordisk (Copenhagen)
    "ERIC-B.ST", # Ericsson (Stockholm)
    "SPOT",      # Spotify (US-listed)
]


def _infer_currency(symbol: str) -> str:
    """Infer currency from Yahoo Finance ticker suffix."""
    if symbol.endswith(".AS") or symbol.endswith(".PA"):
        return "EUR"
    elif symbol.endswith(".DE"):
        return "EUR"
    elif symbol.endswith(".L"):
        return "GBP"
    elif symbol.endswith(".SW"):
        return "CHF"
    elif symbol.endswith(".CO"):
        return "DKK"
    elif symbol.endswith(".ST"):
        return "SEK"
    return "USD"


def _infer_exchange(symbol: str) -> str:
    """Infer exchange name from ticker suffix."""
    suffixes = {
        ".AS": "Euronext Amsterdam",
        ".DE": "XETRA",
        ".L": "LSE",
        ".PA": "Euronext Paris",
        ".SW": "SIX Swiss",
        ".CO": "Copenhagen",
        ".ST": "Stockholm",
    }
    for suffix, exchange in suffixes.items():
        if symbol.endswith(suffix):
            return exchange
    return "US"


class WeeklyScanner:
    """Scans the market universe and generates ranked trade recommendations.

    The scanner uses Friday's close data to produce Monday-open buy signals.
    Entry price = next Monday's expected open (estimated from Friday close).
    Hold for 1 week, sell next Monday open.
    """

    def __init__(self, config: AppConfig, market_data: MarketDataProvider | None = None):
        self.config = config
        self.market_data = market_data or MarketDataProvider()

    def scan(self, symbols: list[str] | None = None) -> list[ScannerResult]:
        """Scan the universe and return candidates meeting criteria."""
        universe = symbols or DEFAULT_UNIVERSE
        md_cfg = self.config.market_data

        logger.info(f"Scanning {len(universe)} symbols...")
        candidates = []

        for symbol in universe:
            try:
                prices = self.market_data.get_price_history(symbol, days=60)
                if len(prices) < 20:
                    continue

                latest = prices[-1]
                price = latest.close

                # Basic filters
                # For non-USD, convert min/max thresholds loosely
                # (EUR/GBP/CHF are roughly similar order of magnitude to USD)
                if price < md_cfg.min_price or price > md_cfg.max_price * 5:
                    continue

                avg_vol = sum(p.volume for p in prices[-20:]) / 20
                # European stocks often have lower volume — adjust threshold
                min_vol = md_cfg.min_avg_volume
                currency = _infer_currency(symbol)
                if currency != "USD":
                    min_vol = min(min_vol, 100_000)  # Lower bar for EU stocks
                if avg_vol < min_vol:
                    continue

                indicators = self.market_data.compute_indicators(prices)

                # Weekly change (last 5 trading days)
                if len(prices) >= 5:
                    week_ago_price = prices[-5].close
                    weekly_change = ((price - week_ago_price) / week_ago_price) * 100
                else:
                    weekly_change = 0.0

                # Extra data (API calls — only for US stocks to avoid rate limits)
                short_interest = None
                days_to_earnings = None
                if currency == "USD":
                    short_interest = self.market_data.get_short_interest(symbol)
                    days_to_earnings = self.market_data.get_upcoming_earnings(symbol)

                # Gap detection
                gap_pct = None
                if len(prices) >= 2:
                    gap_pct = (latest.open - prices[-2].close) / prices[-2].close

                asset = Asset(
                    product_id="",
                    symbol=symbol,
                    name=symbol,
                    exchange_id=0,
                    asset_type=AssetType.STOCK,
                    currency=currency,
                )

                result = ScannerResult(
                    asset=asset,
                    current_price=price,
                    indicators=indicators,
                    avg_daily_volume=int(avg_vol),
                    weekly_change_pct=weekly_change,
                    short_interest_pct=short_interest,
                    days_to_earnings=days_to_earnings,
                    gap_pct=gap_pct,
                )
                candidates.append(result)

            except Exception as e:
                logger.debug(f"Error scanning {symbol}: {e}")
                continue

        logger.info(f"Found {len(candidates)} candidates passing basic filters")
        return candidates

    def generate_signals(self, candidates: list[ScannerResult] | None = None) -> list[Signal]:
        """Run all enabled strategies against candidates and return ranked signals.

        Signals are for NEXT Monday open entry, NOT for immediate execution.
        Strategies that already ran this past week are penalized.
        """
        if candidates is None:
            candidates = self.scan()

        strategies = StrategyRegistry.get_enabled(self.config)
        if not strategies:
            logger.warning("No strategies enabled!")
            return []

        logger.info(f"Running {len(strategies)} strategies against {len(candidates)} candidates")

        all_signals: list[Signal] = []

        for candidate in candidates:
            for strategy in strategies:
                try:
                    signal = strategy.evaluate(candidate)
                    if signal and signal.confidence >= self.config.strategy.min_confidence:
                        # Only penalize extreme moves (>20%) that are likely exhausted
                        # Moderate momentum (5-20%) is actually the signal working correctly
                        weekly_move = abs(candidate.weekly_change_pct)
                        if weekly_move > 25:
                            signal.confidence *= 0.5
                            signal.rationale += f" [CAUTION: already moved {candidate.weekly_change_pct:+.1f}% this week]"
                        elif weekly_move > 20:
                            signal.confidence *= 0.7
                            signal.rationale += f" [Note: moved {candidate.weekly_change_pct:+.1f}% this week]"

                        # Re-check confidence after penalty
                        if signal.confidence >= self.config.strategy.min_confidence:
                            all_signals.append(signal)
                except Exception as e:
                    logger.debug(
                        f"Strategy {strategy.name} failed on {candidate.asset.symbol}: {e}"
                    )

        # Rank by confidence (highest first), then by expected return
        all_signals.sort(
            key=lambda s: (s.confidence, s.expected_return_pct or 0),
            reverse=True,
        )

        # Deduplicate — keep the highest confidence signal per symbol
        seen_symbols: set[str] = set()
        unique_signals: list[Signal] = []
        for signal in all_signals:
            if signal.asset.symbol not in seen_symbols:
                seen_symbols.add(signal.asset.symbol)
                unique_signals.append(signal)

        # Limit to max positions
        max_pos = self.config.strategy.max_positions
        top_signals = unique_signals[:max_pos]

        logger.info(
            f"Generated {len(all_signals)} total signals, "
            f"{len(unique_signals)} unique, returning top {len(top_signals)}"
        )

        return top_signals
