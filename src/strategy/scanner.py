"""Weekly scanner — finds the best speculative candidates."""

from __future__ import annotations

import logging
from datetime import datetime

from src.config import AppConfig
from src.data.market_data import MarketDataProvider
from src.models import Asset, AssetType, ScannerResult, Signal
from src.strategy.base import StrategyRegistry

logger = logging.getLogger(__name__)

# Popular high-liquidity tickers to scan — extendable
DEFAULT_UNIVERSE = [
    # US Large-cap Tech (high beta)
    "NVDA", "AMD", "TSLA", "META", "AMZN", "GOOGL", "MSFT", "AAPL", "NFLX", "CRM",
    # US Growth / Momentum
    "PLTR", "SNOW", "COIN", "SHOP", "ROKU", "DKNG", "RBLX", "HOOD", "SOFI",
    # Biotech (volatile)
    "MRNA", "BNTX", "CRSP", "EDIT", "NTLA", "BEAM",
    # Meme / High Short Interest
    "GME", "AMC", "RIVN", "LCID", "NIO",
    # Semis
    "MU", "MRVL", "AVGO", "QCOM", "ARM", "SMCI",
    # Energy (volatile)
    "OXY", "DVN", "FANG",
    # Leveraged ETFs (for aggressive plays)
    "TQQQ", "SOXL", "SPXL", "UPRO", "TNA",
]


class WeeklyScanner:
    """Scans the market universe and generates ranked trade recommendations."""

    def __init__(self, config: AppConfig, market_data: MarketDataProvider | None = None):
        self.config = config
        self.market_data = market_data or MarketDataProvider()

    def scan(self, symbols: list[str] | None = None) -> list[ScannerResult]:
        """Scan the universe and return candidates meeting criteria."""
        universe = symbols or DEFAULT_UNIVERSE
        scanner_cfg = self.config.scanner
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
                if price < md_cfg.min_price or price > md_cfg.max_price:
                    continue

                avg_vol = sum(p.volume for p in prices[-20:]) / 20
                if avg_vol < md_cfg.min_avg_volume:
                    continue

                indicators = self.market_data.compute_indicators(prices)

                # Weekly change
                if len(prices) >= 5:
                    week_ago_price = prices[-5].close
                    weekly_change = ((price - week_ago_price) / week_ago_price) * 100
                else:
                    weekly_change = 0.0

                # Extra data
                short_interest = self.market_data.get_short_interest(symbol)
                days_to_earnings = self.market_data.get_upcoming_earnings(symbol)

                # Gap detection (today's open vs yesterday's close)
                gap_pct = None
                if len(prices) >= 2:
                    gap_pct = (latest.open - prices[-2].close) / prices[-2].close

                asset = Asset(
                    product_id="",
                    symbol=symbol,
                    name=symbol,
                    exchange_id=0,
                    asset_type=AssetType.STOCK,
                    currency="USD",
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
        """Run all enabled strategies against candidates and return ranked signals."""
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
