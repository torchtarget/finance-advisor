"""Weekly scanner — finds the best speculative candidates for NEXT Monday.

Scans Friday's close data to recommend buys for Monday open.
Covers US + European instruments available on DeGiro across 10+ exchanges.
"""

from __future__ import annotations

import logging
from datetime import datetime

from src.config import AppConfig
from src.data.market_data import MarketDataProvider
from src.models import Asset, AssetType, ScannerResult, Signal
from src.strategy.base import StrategyRegistry

logger = logging.getLogger(__name__)

# Full universe of instruments available on DeGiro — high volatility focus
DEFAULT_UNIVERSE = [
    # =====================================================================
    # US — NYSE & NASDAQ
    # =====================================================================

    # Large-cap Tech (high beta)
    "NVDA", "AMD", "TSLA", "META", "AMZN", "GOOGL", "MSFT", "AAPL", "NFLX", "CRM",
    # Growth / Momentum
    "PLTR", "SNOW", "COIN", "SHOP", "ROKU", "DKNG", "RBLX", "HOOD", "SOFI", "SPOT",
    # Biotech (volatile)
    "MRNA", "BNTX", "CRSP", "EDIT", "NTLA", "BEAM",
    # Meme / High Short Interest
    "GME", "AMC", "RIVN", "LCID", "NIO",
    # Semis
    "MU", "MRVL", "AVGO", "QCOM", "ARM", "SMCI",
    # Energy (volatile)
    "OXY", "DVN", "FANG",
    # Leveraged ETFs (US-listed)
    "TQQQ", "SOXL", "SPXL", "UPRO", "TNA",
    # Crypto miners & proxies
    "MSTR", "MARA", "RIOT", "CLSK", "HUT",

    # =====================================================================
    # Europe — Euronext Amsterdam
    # =====================================================================
    "ASML.AS", "ADYEN.AS", "PHIA.AS", "INGA.AS",
    "ASM.AS", "BESI.AS", "AKZA.AS", "WKL.AS",
    "ALFEN.AS", "LIGHT.AS",

    # =====================================================================
    # Europe — XETRA / Frankfurt
    # =====================================================================
    "SAP.DE", "SIE.DE", "ALV.DE", "BAS.DE", "DTE.DE",
    "BMW.DE", "VOW3.DE", "IFX.DE", "MRK.DE", "RHM.DE",
    "TKA.DE",

    # =====================================================================
    # Europe — London (LSE)
    # =====================================================================
    "SHEL.L", "AZN.L", "HSBA.L", "GSK.L", "BP.L",
    "RIO.L", "LSEG.L", "DGE.L", "BARC.L", "LLOY.L",
    "DARK.L",   # Darktrace (cybersecurity) -- verify availability

    # Commodity ETCs (LSE) — highly volatile
    "PHAU.L",   # Physical Gold
    "PHAG.L",   # Physical Silver
    "CRUD.L",   # Brent Crude Oil
    "NGAS.L",   # Natural Gas
    "COPA.L",   # Copper

    # Leveraged ETFs (LSE) — 3x daily, extreme volatility
    "3OIS.L",   # 3x Long Crude Oil
    "3NGL.L",   # 3x Long Natural Gas
    "3LUS.L",   # 3x Long S&P 500
    "3USS.L",   # 3x Short S&P 500
    "3LNQ.L",   # 3x Long NASDAQ 100 (may be delisted, verify)
    "3DEL.L",   # 3x Long DAX

    # =====================================================================
    # Europe — Euronext Paris
    # =====================================================================
    "MC.PA", "OR.PA", "SAN.PA", "AI.PA", "BNP.PA",
    "TTE.PA", "SU.PA", "AIR.PA", "CS.PA", "DG.PA",

    # =====================================================================
    # Europe — Milan (Borsa Italiana)
    # =====================================================================
    "UCG.MI",    # UniCredit (volatile bank)
    "ISP.MI",    # Intesa Sanpaolo
    "STLAM.MI",  # Stellantis
    "BAMI.MI",   # Banco BPM
    "RACE.MI",   # Ferrari
    "TIT.MI",    # Telecom Italia (penny-range, volatile)

    # =====================================================================
    # Europe — Madrid (BME)
    # =====================================================================
    "SAN.MC",   # Banco Santander
    "BBVA.MC",  # BBVA
    "IAG.MC",   # IAG (British Airways parent)
    "ITX.MC",   # Inditex
    "CABK.MC",  # CaixaBank

    # =====================================================================
    # Nordic — Stockholm (Nasdaq Stockholm)
    # =====================================================================
    "ERIC-B.ST",  # Ericsson
    "EVO.ST",     # Evolution AB (gaming, very liquid)
    "SINCH.ST",   # Sinch (cloud comms)
    "SSAB-A.ST",  # SSAB (steel, cyclical)
    "NIBE-B.ST",  # NIBE Industrier (heat pumps)
    "KINV-B.ST",  # Kinnevik (growth investor)

    # Crypto ETP (Stockholm) -- verify ticker
    # "BITC.ST",  # CoinShares Physical Bitcoin (delisted or renamed)

    # =====================================================================
    # Nordic — Copenhagen (Nasdaq Copenhagen)
    # =====================================================================
    "NOVO-B.CO",  # Novo Nordisk
    "GMAB.CO",    # Genmab (biotech)
    "ORSTED.CO",  # Orsted (green energy, volatile)
    "DEMANT.CO",  # Demant (medtech)
    "AMBU-B.CO",  # Ambu (medtech, volatile)
    "GN.CO",      # GN Store Nord (audio)

    # =====================================================================
    # Switzerland — SIX Swiss Exchange
    # =====================================================================
    "NESN.SW",   # Nestle
    "NOVN.SW",   # Novartis
    "ROG.SW",    # Roche
]


def _infer_currency(symbol: str) -> str:
    """Infer currency from Yahoo Finance ticker suffix."""
    suffix_map = {
        ".AS": "EUR", ".PA": "EUR", ".DE": "EUR",
        ".MI": "EUR", ".MC": "EUR",
        ".L": "GBP",
        ".SW": "CHF",
        ".CO": "DKK",
        ".ST": "SEK",
    }
    for suffix, currency in suffix_map.items():
        if symbol.endswith(suffix):
            return currency
    return "USD"


def _infer_exchange(symbol: str) -> str:
    """Infer exchange name from ticker suffix."""
    suffix_map = {
        ".AS": "Euronext Amsterdam",
        ".DE": "XETRA",
        ".L": "LSE",
        ".PA": "Euronext Paris",
        ".MI": "Borsa Italiana",
        ".MC": "BME Madrid",
        ".SW": "SIX Swiss",
        ".CO": "Nasdaq Copenhagen",
        ".ST": "Nasdaq Stockholm",
    }
    for suffix, exchange in suffix_map.items():
        if symbol.endswith(suffix):
            return exchange
    return "US"


class WeeklyScanner:
    """Scans the market universe and generates ranked trade recommendations.

    Uses Friday's close data to produce Monday-open buy signals.
    Entry = next Monday open. Hold 1 week, sell next Monday open.
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

                # Basic filters — relaxed for non-USD
                currency = _infer_currency(symbol)
                max_price = md_cfg.max_price * 5 if currency != "USD" else md_cfg.max_price
                if price < md_cfg.min_price or price > max_price:
                    continue

                avg_vol = sum(p.volume for p in prices[-20:]) / 20
                min_vol = md_cfg.min_avg_volume
                if currency != "USD":
                    min_vol = min(min_vol, 50_000)  # Lower bar for EU/commodity ETCs
                if avg_vol < min_vol:
                    continue

                indicators = self.market_data.compute_indicators(prices)

                # Weekly change
                if len(prices) >= 5:
                    week_ago_price = prices[-5].close
                    weekly_change = ((price - week_ago_price) / week_ago_price) * 100
                else:
                    weekly_change = 0.0

                # Extra data (API calls — only for US stocks to avoid rate limits)
                short_interest = None
                days_to_earnings = None
                if currency == "USD" and not symbol.endswith(("TQQQ", "SOXL", "SPXL", "UPRO", "TNA")):
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
                    asset_type=AssetType.ETF if _is_etf(symbol) else AssetType.STOCK,
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

        Signals are for NEXT Monday open entry.
        Only extreme weekly moves (>20%) are penalized.
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
                        # Only penalize extreme moves that are likely exhausted
                        weekly_move = abs(candidate.weekly_change_pct)
                        if weekly_move > 25:
                            signal.confidence *= 0.5
                            signal.rationale += f" [CAUTION: already moved {candidate.weekly_change_pct:+.1f}% this week]"
                        elif weekly_move > 20:
                            signal.confidence *= 0.7
                            signal.rationale += f" [Note: moved {candidate.weekly_change_pct:+.1f}% this week]"

                        if signal.confidence >= self.config.strategy.min_confidence:
                            all_signals.append(signal)
                except Exception as e:
                    logger.debug(
                        f"Strategy {strategy.name} failed on {candidate.asset.symbol}: {e}"
                    )

        # Rank signals based on config
        if self.config.strategy.ranking == "expected_return":
            # MAX RISK: pick the biggest potential movers
            all_signals.sort(
                key=lambda s: (s.expected_return_pct or 0, s.confidence),
                reverse=True,
            )
        else:
            # Conservative: pick highest confidence
            all_signals.sort(
                key=lambda s: (s.confidence, s.expected_return_pct or 0),
                reverse=True,
            )

        # Deduplicate — best signal per symbol
        seen_symbols: set[str] = set()
        unique_signals: list[Signal] = []
        for signal in all_signals:
            if signal.asset.symbol not in seen_symbols:
                seen_symbols.add(signal.asset.symbol)
                unique_signals.append(signal)

        max_pos = self.config.strategy.max_positions
        top_signals = unique_signals[:max_pos]

        logger.info(
            f"Generated {len(all_signals)} total signals, "
            f"{len(unique_signals)} unique, returning top {len(top_signals)}"
        )

        return top_signals


# ETF/ETC/ETP identifiers
_ETF_SYMBOLS = {
    "TQQQ", "SOXL", "SPXL", "UPRO", "TNA", "ETHE",
    "PHAU.L", "PHAG.L", "CRUD.L", "NGAS.L", "COPA.L",
    "3OIS.L", "3NGL.L", "3LUS.L", "3USS.L", "3LNQ.L", "3DEL.L",
    "BITC.ST",
}


def _is_etf(symbol: str) -> bool:
    return symbol in _ETF_SYMBOLS
