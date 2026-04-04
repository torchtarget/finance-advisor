"""Aggressive short-term trading strategies for weekly returns."""

from __future__ import annotations

from src.config import AppConfig
from src.models import ScannerResult, Signal, SignalDirection, StrategyType
from src.strategy.base import BaseStrategy, StrategyRegistry


@StrategyRegistry.register
class MomentumBreakout(BaseStrategy):
    """Buy stocks breaking out of consolidation with volume confirmation.

    Looks for:
    - Price breaking above 20-day SMA
    - Volume spike (2x+ average)
    - MACD crossing above signal line
    - RSI between 50-75 (strong but not overbought)
    """

    name = "momentum_breakout"

    def evaluate(self, candidate: ScannerResult) -> Signal | None:
        ind = candidate.indicators
        price = candidate.current_price

        if ind.sma_20 is None or ind.relative_volume is None:
            return None

        conditions = [
            price > ind.sma_20,  # Above 20 SMA
            ind.relative_volume and ind.relative_volume >= 1.5,  # Volume confirmation
            ind.macd_histogram and ind.macd_histogram > 0,  # MACD bullish
            ind.rsi_14 and 45 < ind.rsi_14 < 80,  # Momentum but not exhausted
        ]

        met = sum(1 for c in conditions if c)
        if met < 3:
            return None

        confidence = min(met / len(conditions) + 0.1, 1.0)

        # Target: ATR-based (2x ATR upside)
        atr = ind.atr_14 or (price * 0.03)
        target = price + (atr * 2.5)

        return Signal(
            asset=candidate.asset,
            direction=SignalDirection.BUY,
            confidence=confidence,
            strategy=StrategyType.MOMENTUM_BREAKOUT,
            rationale=f"Breakout above SMA20 with {ind.relative_volume:.1f}x volume. "
                      f"MACD bullish, RSI {ind.rsi_14:.0f}.",
            entry_price=price,
            target_price=target,
            expected_return_pct=((target - price) / price) * 100,
        )

    def describe(self) -> str:
        return "Momentum breakout: catches stocks breaking out of ranges with volume"


@StrategyRegistry.register
class MeanReversionOversold(BaseStrategy):
    """Buy deeply oversold stocks expecting a snapback.

    Looks for:
    - RSI < 25 (deeply oversold)
    - Price below lower Bollinger Band
    - High ATR (volatile = bigger snapback potential)
    - Not in a death cross (EMA9 still somewhat close to EMA21)
    """

    name = "mean_reversion_oversold"

    def evaluate(self, candidate: ScannerResult) -> Signal | None:
        ind = candidate.indicators
        price = candidate.current_price
        scanner_cfg = self.config.scanner

        if ind.rsi_14 is None or ind.bollinger_lower is None:
            return None

        conditions = [
            ind.rsi_14 < scanner_cfg.rsi_oversold,
            price < ind.bollinger_lower,
            ind.atr_pct and ind.atr_pct >= scanner_cfg.min_atr_pct,
        ]

        met = sum(1 for c in conditions if c)
        if met < 2:
            return None

        # Deeper oversold = higher confidence for snapback
        confidence = min(0.5 + (scanner_cfg.rsi_oversold - ind.rsi_14) / 50, 0.95)

        # Target: middle Bollinger Band (mean reversion target)
        target = ind.bollinger_middle or price * 1.05

        return Signal(
            asset=candidate.asset,
            direction=SignalDirection.BUY,
            confidence=confidence,
            strategy=StrategyType.MEAN_REVERSION_OVERSOLD,
            rationale=f"Deeply oversold: RSI {ind.rsi_14:.0f}, below lower BB. "
                      f"ATR {ind.atr_pct:.1f}% suggests high volatility for snapback.",
            entry_price=price,
            target_price=target,
            expected_return_pct=((target - price) / price) * 100,
        )

    def describe(self) -> str:
        return "Mean reversion: buys deeply oversold stocks expecting a bounce"


@StrategyRegistry.register
class SqueezeSetup(BaseStrategy):
    """Buy stocks in a volatility squeeze about to explode.

    The squeeze (Bollinger Bands inside Keltner Channels) indicates
    compressed volatility. When it fires, the move can be explosive.

    Looks for:
    - Squeeze is ON (BB inside KC)
    - MACD histogram positive (directional bias = up)
    - Volume building (relative volume > 1.0)
    """

    name = "squeeze_setup"

    def evaluate(self, candidate: ScannerResult) -> Signal | None:
        ind = candidate.indicators
        price = candidate.current_price

        if not ind.squeeze_on:
            return None

        # Determine direction from MACD histogram
        if not ind.macd_histogram or ind.macd_histogram <= 0:
            return None  # Only take bullish squeezes for simplicity

        conditions = [
            ind.squeeze_on,
            ind.macd_histogram > 0,
            ind.relative_volume and ind.relative_volume >= 1.0,
        ]

        met = sum(1 for c in conditions if c)
        if met < 2:
            return None

        confidence = 0.7 if met == 3 else 0.55

        # Target: BB width expansion — expect 1.5x current range
        bb_range = (ind.bollinger_upper or price * 1.02) - (ind.bollinger_lower or price * 0.98)
        target = price + bb_range * 1.5

        return Signal(
            asset=candidate.asset,
            direction=SignalDirection.BUY,
            confidence=confidence,
            strategy=StrategyType.SQUEEZE_SETUP,
            rationale=f"Volatility squeeze detected (BB inside KC). "
                      f"MACD histogram positive, expecting breakout.",
            entry_price=price,
            target_price=target,
            expected_return_pct=((target - price) / price) * 100,
        )

    def describe(self) -> str:
        return "Squeeze: catches compressed volatility before explosive moves"


@StrategyRegistry.register
class EarningsGap(BaseStrategy):
    """Position before earnings for a potential gap move.

    HIGH RISK: Earnings are binary events. This strategy bets on
    the pre-earnings run-up and/or the post-earnings move.

    Looks for:
    - Earnings within the next 7 days
    - Stock showing relative strength (above SMA20)
    - Increasing volume into earnings
    """

    name = "earnings_gap"

    def evaluate(self, candidate: ScannerResult) -> Signal | None:
        ind = candidate.indicators
        price = candidate.current_price

        if candidate.days_to_earnings is None:
            return None
        if candidate.days_to_earnings > self.config.scanner.earnings_window_days:
            return None

        conditions = [
            candidate.days_to_earnings <= 7,
            ind.sma_20 and price > ind.sma_20,  # Relative strength
            ind.relative_volume and ind.relative_volume >= 1.2,  # Volume building
        ]

        met = sum(1 for c in conditions if c)
        if met < 2:
            return None

        # Earnings plays are inherently risky — cap confidence
        confidence = min(0.4 + met * 0.1, 0.65)

        # Target: typical earnings gap is 5-15%
        target = price * 1.08

        return Signal(
            asset=candidate.asset,
            direction=SignalDirection.BUY,
            confidence=confidence,
            strategy=StrategyType.EARNINGS_GAP,
            rationale=f"Earnings in {candidate.days_to_earnings} days. "
                      f"Stock showing relative strength with building volume.",
            entry_price=price,
            target_price=target,
            expected_return_pct=8.0,
        )

    def describe(self) -> str:
        return "Earnings gap: positions for binary earnings events"


@StrategyRegistry.register
class HighShortInterest(BaseStrategy):
    """Buy heavily shorted stocks for potential short squeeze.

    Looks for:
    - Short interest > 10% of float
    - Any bullish catalyst (volume spike, price uptick)
    - This is the highest risk / highest reward strategy
    """

    name = "high_short_interest"

    def evaluate(self, candidate: ScannerResult) -> Signal | None:
        ind = candidate.indicators
        price = candidate.current_price

        if candidate.short_interest_pct is None:
            return None
        if candidate.short_interest_pct < self.config.scanner.short_interest_min:
            return None

        # Need some bullish trigger
        bullish_triggers = [
            ind.relative_volume and ind.relative_volume >= 2.0,  # Volume spike
            ind.macd_histogram and ind.macd_histogram > 0,
            ind.rsi_14 and ind.rsi_14 > 50,  # Momentum turning
        ]

        triggers_met = sum(1 for t in bullish_triggers if t)
        if triggers_met < 1:
            return None

        # Higher short interest = more squeeze potential
        confidence = min(0.4 + (candidate.short_interest_pct - 10) / 40, 0.85)

        # Short squeezes can be violent — 20-50%+ moves
        target = price * 1.20

        return Signal(
            asset=candidate.asset,
            direction=SignalDirection.BUY,
            confidence=confidence,
            strategy=StrategyType.HIGH_SHORT_INTEREST,
            rationale=f"Short interest {candidate.short_interest_pct:.1f}% of float. "
                      f"{triggers_met} bullish trigger(s) active. Squeeze potential.",
            entry_price=price,
            target_price=target,
            expected_return_pct=20.0,
        )

    def describe(self) -> str:
        return "Short squeeze: targets heavily shorted stocks with bullish triggers"


@StrategyRegistry.register
class VolumeSpikeStrategy(BaseStrategy):
    """Buy on unusual volume spikes — someone knows something.

    Looks for:
    - Volume 2x+ the 20-day average
    - Price action confirming direction (up on volume)
    - Not at obvious resistance
    """

    name = "volume_spike"

    def evaluate(self, candidate: ScannerResult) -> Signal | None:
        ind = candidate.indicators
        price = candidate.current_price

        if not ind.relative_volume:
            return None

        multiplier = self.config.scanner.volume_spike_multiplier
        if ind.relative_volume < multiplier:
            return None

        # Price must be moving up with the volume
        if ind.ema_9 is None or price < ind.ema_9:
            return None

        # Higher volume = higher confidence
        confidence = min(0.45 + (ind.relative_volume - multiplier) * 0.1, 0.85)

        atr = ind.atr_14 or (price * 0.03)
        target = price + atr * 2

        return Signal(
            asset=candidate.asset,
            direction=SignalDirection.BUY,
            confidence=confidence,
            strategy=StrategyType.VOLUME_SPIKE,
            rationale=f"Volume spike: {ind.relative_volume:.1f}x average volume. "
                      f"Price above EMA9, bullish confirmation.",
            entry_price=price,
            target_price=target,
            expected_return_pct=((target - price) / price) * 100,
        )

    def describe(self) -> str:
        return "Volume spike: unusual volume with bullish price action"
