"""Tests for trading strategies."""

from src.config import load_config
from src.models import Asset, AssetType, ScannerResult, TechnicalIndicators
from src.strategy.base import StrategyRegistry
from src.strategy import strategies as _  # noqa: F401 — registers strategies


def make_candidate(
    symbol: str = "TEST",
    price: float = 100.0,
    rsi: float = 50.0,
    relative_volume: float = 1.0,
    macd_histogram: float = 0.0,
    sma_20: float = 95.0,
    squeeze_on: bool = False,
    short_interest: float | None = None,
    days_to_earnings: int | None = None,
    atr_pct: float = 3.0,
    bollinger_lower: float = 90.0,
    bollinger_middle: float = 100.0,
    bollinger_upper: float = 110.0,
    ema_9: float = 98.0,
) -> ScannerResult:
    asset = Asset(
        product_id="123",
        symbol=symbol,
        name=symbol,
        exchange_id=906,
        asset_type=AssetType.STOCK,
        currency="USD",
    )
    indicators = TechnicalIndicators(
        rsi_14=rsi,
        macd_histogram=macd_histogram,
        sma_20=sma_20,
        relative_volume=relative_volume,
        squeeze_on=squeeze_on,
        atr_pct=atr_pct,
        atr_14=price * atr_pct / 100,
        bollinger_lower=bollinger_lower,
        bollinger_middle=bollinger_middle,
        bollinger_upper=bollinger_upper,
        ema_9=ema_9,
        keltner_upper=bollinger_upper + 5 if not squeeze_on else bollinger_upper - 1,
        keltner_lower=bollinger_lower - 5 if not squeeze_on else bollinger_lower + 1,
    )
    return ScannerResult(
        asset=asset,
        current_price=price,
        indicators=indicators,
        avg_daily_volume=1_000_000,
        short_interest_pct=short_interest,
        days_to_earnings=days_to_earnings,
    )


def test_all_strategies_registered():
    names = StrategyRegistry.all_names()
    assert "momentum_breakout" in names
    assert "mean_reversion_oversold" in names
    assert "squeeze_setup" in names
    assert "earnings_gap" in names
    assert "high_short_interest" in names
    assert "volume_spike" in names


def test_momentum_breakout_triggers():
    config = load_config()
    strategy = StrategyRegistry.get("momentum_breakout")(config)

    candidate = make_candidate(
        price=105,
        sma_20=100,
        relative_volume=2.5,
        macd_histogram=0.5,
        rsi=60,
    )
    signal = strategy.evaluate(candidate)
    assert signal is not None
    assert signal.direction.value == "BUY"
    assert signal.confidence > 0.5


def test_momentum_breakout_no_trigger():
    config = load_config()
    strategy = StrategyRegistry.get("momentum_breakout")(config)

    candidate = make_candidate(
        price=90,  # Below SMA
        sma_20=100,
        relative_volume=0.5,  # Low volume
        macd_histogram=-0.5,  # Bearish
        rsi=30,
    )
    signal = strategy.evaluate(candidate)
    assert signal is None


def test_mean_reversion_oversold():
    config = load_config()
    strategy = StrategyRegistry.get("mean_reversion_oversold")(config)

    candidate = make_candidate(
        price=85,
        rsi=18,
        bollinger_lower=90,
        atr_pct=4.0,
    )
    signal = strategy.evaluate(candidate)
    assert signal is not None
    assert signal.confidence > 0.5


def test_squeeze_setup():
    config = load_config()
    strategy = StrategyRegistry.get("squeeze_setup")(config)

    candidate = make_candidate(
        squeeze_on=True,
        macd_histogram=0.3,
        relative_volume=1.2,
    )
    signal = strategy.evaluate(candidate)
    assert signal is not None


def test_high_short_interest():
    config = load_config()
    strategy = StrategyRegistry.get("high_short_interest")(config)

    candidate = make_candidate(
        short_interest=25.0,
        relative_volume=2.5,
        macd_histogram=0.2,
        rsi=55,
    )
    signal = strategy.evaluate(candidate)
    assert signal is not None
    assert signal.confidence > 0.4


def test_volume_spike():
    config = load_config()
    strategy = StrategyRegistry.get("volume_spike")(config)

    candidate = make_candidate(
        relative_volume=3.0,
        ema_9=98,
        price=100,  # Above EMA9
    )
    signal = strategy.evaluate(candidate)
    assert signal is not None


def test_position_sizer_conviction_weighted():
    from src.risk.position_sizer import PositionSizer
    from src.models import Signal, SignalDirection, StrategyType

    config = load_config()
    sizer = PositionSizer(config)

    signals = [
        Signal(
            asset=make_candidate().asset,
            direction=SignalDirection.BUY,
            confidence=0.8,
            strategy=StrategyType.MOMENTUM_BREAKOUT,
            rationale="test",
            entry_price=100,
            target_price=110,
            expected_return_pct=10,
        ),
        Signal(
            asset=make_candidate(symbol="TEST2").asset,
            direction=SignalDirection.BUY,
            confidence=0.5,
            strategy=StrategyType.VOLUME_SPIKE,
            rationale="test2",
            entry_price=50,
            target_price=55,
            expected_return_pct=10,
        ),
    ]

    recs = sizer.size_positions(signals, 10_000)
    assert len(recs) == 2
    # Higher confidence signal should get larger allocation
    assert recs[0].allocation_pct > recs[1].allocation_pct
