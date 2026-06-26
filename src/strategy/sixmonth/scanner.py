"""6-month scanner — finds the best buy-and-hold candidates.

Uses intermediate-term momentum (strongest academic factor for 6-12 month returns),
trend structure, and volume confirmation.

Cannot sell during the 6-month period. Can add (pyramid into winners).
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import numpy as np
import yfinance as yf

from src.strategy.sixmonth.models import (
    MomentumScore,
    SixMonthPick,
    SixMonthStrategyType,
)

logger = logging.getLogger(__name__)

SIXMONTH_UNIVERSE = [
    # AI Infrastructure
    "NVDA", "AMD", "AVGO", "MRVL", "ARM", "SMCI", "TSM",
    # AI Software / Cloud
    "PLTR", "SNOW", "CRM", "MSFT", "GOOGL", "META", "AMZN",
    # Crypto / Digital Assets
    "MSTR", "MARA", "RIOT", "CLSK", "COIN",
    # Biotech (catalyst-rich)
    "MRNA", "BNTX", "CRSP", "NTLA", "EDIT", "BEAM",
    "REGN", "VRTX", "ALNY", "IONS",
    # GLP-1 / Obesity
    "NOVO-B.CO", "LLY",
    # EV / Clean Energy
    "TSLA", "RIVN", "LCID", "NIO",
    # Leveraged ETFs
    "TQQQ", "SOXL", "TNA",
    # EU High Growth
    "ASML.AS", "ADYEN.AS", "ASM.AS", "BESI.AS",
    "SAP.DE", "IFX.DE", "EVO.ST",
    # Meme / Short Squeeze
    "GME", "AMC",
    # Small-cap US growth
    "SOFI", "HOOD", "RBLX", "DKNG",
    # Commodity plays
    "OXY", "FANG", "3OIL.L", "NGAS.L",
    # Defense
    "RHM.DE",
]


class SixMonthScanner:
    """Scans for the best 6-month buy-and-hold candidates.

    Composite momentum score (0-100):
      6-month return:  40% weight (strongest factor)
      3-month return:  25% weight (trend acceleration)
      1-month return:  10% weight (recent confirmation)
      Trend structure: 15% weight (above 50/200 SMA, new highs)
      Volume trend:    10% weight (institutional buying)
    """

    def scan(self, symbols: list[str] | None = None) -> list[MomentumScore]:
        """Compute momentum scores for all symbols."""
        universe = symbols or SIXMONTH_UNIVERSE
        scores: list[MomentumScore] = []

        logger.info(f"6-month scanner: analyzing {len(universe)} symbols...")

        for symbol in universe:
            try:
                score = self._compute_momentum(symbol)
                if score:
                    scores.append(score)
            except Exception as e:
                logger.debug(f"Error scoring {symbol}: {e}")

        scores.sort(key=lambda s: s.composite_score, reverse=True)
        if scores:
            logger.info(f"Scored {len(scores)} symbols, top: {scores[0].symbol} ({scores[0].composite_score:.1f})")
        return scores

    def generate_picks(
        self,
        capital: float = 5000,
        max_picks: int = 3,
        scores: list[MomentumScore] | None = None,
    ) -> list[SixMonthPick]:
        """Generate top picks with pyramiding plan."""
        if scores is None:
            scores = self.scan()

        if not scores:
            return []

        top = scores[:max_picks]
        picks = []
        per_pick = 100.0 / max_picks

        for i, score in enumerate(top):
            initial_alloc = per_pick * 0.5  # Deploy 50% now, 50% for pyramiding

            if score.composite_score > 80:
                target_mult = 1.50
            elif score.composite_score > 60:
                target_mult = 1.35
            else:
                target_mult = 1.25

            target_price = score.price_now * target_mult
            expected_return = (target_mult - 1) * 100

            catalysts = []
            risks = []

            if score.return_6m > 50:
                catalysts.append(f"Strong 6m momentum: {score.return_6m:+.0f}%")
            if score.return_3m > 30:
                catalysts.append(f"Accelerating 3m: {score.return_3m:+.0f}%")
            if score.making_new_highs:
                catalysts.append("Making new 52-week highs")
            if score.volume_trend > 1.3:
                catalysts.append(f"Volume up {score.volume_trend:.1f}x (institutional buying)")
            if score.above_200_sma and score.above_50_sma:
                catalysts.append("Above 50 and 200 SMA (strong uptrend)")

            if score.return_6m > 100:
                risks.append(f"Already up {score.return_6m:.0f}% in 6m — could be overextended")
            if not score.above_200_sma:
                risks.append("Below 200 SMA — long-term trend is down")
            if score.volume_trend < 0.7:
                risks.append("Declining volume — smart money may be exiting")

            strategy = SixMonthStrategyType.PRICE_MOMENTUM
            if score.composite_score < 50:
                strategy = SixMonthStrategyType.THEMATIC

            hold_until = (datetime.now() + timedelta(days=182)).strftime("%Y-%m-%d")

            rationale = (
                f"6-month momentum rank #{i+1}: "
                f"6m {score.return_6m:+.1f}%, "
                f"3m {score.return_3m:+.1f}%, "
                f"1m {score.return_1m:+.1f}%. "
                f"Score {score.composite_score:.0f}/100."
            )
            if score.above_200_sma:
                rationale += " In long-term uptrend."
            if score.making_new_highs:
                rationale += " Making new highs."

            picks.append(SixMonthPick(
                symbol=score.symbol,
                strategy=strategy,
                entry_price=score.price_now,
                target_price=round(target_price, 2),
                expected_return_pct=round(expected_return, 1),
                confidence=min(score.composite_score / 100, 0.95),
                rationale=rationale,
                catalysts=catalysts,
                risks=risks,
                momentum_score=score,
                initial_allocation_pct=initial_alloc,
                add_trigger_pct=10.0,
                max_allocation_pct=per_pick,
                hold_until=hold_until,
            ))

        return picks

    def _compute_momentum(self, symbol: str) -> MomentumScore | None:
        """Compute multi-timeframe momentum score."""
        try:
            ticker = yf.Ticker(symbol)
            end = datetime.now()
            start = end - timedelta(days=365)

            df = ticker.history(start=start, end=end)
            if df.empty or len(df) < 120:
                return None

            close = df["Close"]
            volume = df["Volume"].astype(float)
            current_price = close.iloc[-1]

            idx_6m = min(126, len(close) - 1)
            price_6m_ago = close.iloc[-idx_6m]
            return_6m = ((current_price - price_6m_ago) / price_6m_ago) * 100

            idx_3m = min(63, len(close) - 1)
            return_3m = ((current_price - close.iloc[-idx_3m]) / close.iloc[-idx_3m]) * 100

            idx_1m = min(21, len(close) - 1)
            return_1m = ((current_price - close.iloc[-idx_1m]) / close.iloc[-idx_1m]) * 100

            sma_50 = close.rolling(50).mean().iloc[-1]
            sma_200 = close.rolling(min(200, len(close))).mean().iloc[-1]

            above_50 = current_price > sma_50
            above_200 = current_price > sma_200

            high_52w = close.max()
            making_new_highs = current_price >= high_52w * 0.95

            vol_recent = volume.iloc[-21:].mean()
            vol_old_start = max(-idx_6m, -len(volume))
            vol_old_end = vol_old_start + 21
            vol_6m_ago = volume.iloc[vol_old_start:vol_old_end].mean() if vol_old_end <= 0 else volume.iloc[:21].mean()
            volume_trend = (vol_recent / vol_6m_ago) if vol_6m_ago > 0 else 1.0

            # Composite score
            score = 0.0
            score += min(max(return_6m, 0), 100) * 0.40
            score += min(max(return_3m, 0), 50) * 0.50
            score += min(max(return_1m, 0), 20) * 0.50
            if above_50:
                score += 5
            if above_200:
                score += 5
            if making_new_highs:
                score += 5
            if volume_trend > 1.0:
                score += min((volume_trend - 1.0) * 20, 10)

            return MomentumScore(
                symbol=symbol,
                price_6m_ago=round(price_6m_ago, 2),
                price_now=round(current_price, 2),
                return_6m=round(return_6m, 1),
                return_3m=round(return_3m, 1),
                return_1m=round(return_1m, 1),
                composite_score=round(min(score, 100), 1),
                volume_trend=round(volume_trend, 2),
                above_200_sma=above_200,
                above_50_sma=above_50,
                making_new_highs=making_new_highs,
            )

        except Exception as e:
            logger.debug(f"Momentum calc failed for {symbol}: {e}")
            return None
