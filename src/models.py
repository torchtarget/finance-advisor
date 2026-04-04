"""Core domain models for high-risk weekly speculative trading."""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class SignalDirection(str, Enum):
    BUY = "BUY"
    SELL = "SELL"
    SHORT = "SHORT"


class AssetType(str, Enum):
    STOCK = "stock"
    ETF = "etf"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"
    STOP_LIMIT = "stop_limit"


class OrderStatus(str, Enum):
    PENDING = "pending"
    FILLED = "filled"
    PARTIALLY_FILLED = "partially_filled"
    CANCELLED = "cancelled"
    REJECTED = "rejected"


class StrategyType(str, Enum):
    MOMENTUM_BREAKOUT = "momentum_breakout"
    MEAN_REVERSION_OVERSOLD = "mean_reversion_oversold"
    SQUEEZE_SETUP = "squeeze_setup"
    EARNINGS_GAP = "earnings_gap"
    HIGH_SHORT_INTEREST = "high_short_interest"
    VOLUME_SPIKE = "volume_spike"


class Asset(BaseModel):
    """A tradeable instrument available on DeGiro's platform."""

    product_id: str
    symbol: str
    name: str
    exchange_id: int
    asset_type: AssetType = AssetType.STOCK
    currency: str = "USD"
    isin: str = ""
    sector: str = ""


class PriceData(BaseModel):
    """OHLCV price bar."""

    timestamp: datetime
    open: float
    high: float
    low: float
    close: float
    volume: int = 0


class TechnicalIndicators(BaseModel):
    """Computed technical indicators for an asset."""

    # Momentum
    rsi_14: float | None = None
    macd: float | None = None
    macd_signal: float | None = None
    macd_histogram: float | None = None

    # Volatility
    bollinger_upper: float | None = None
    bollinger_middle: float | None = None
    bollinger_lower: float | None = None
    atr_14: float | None = None
    atr_pct: float | None = None  # ATR as % of price

    # Trend
    sma_20: float | None = None
    ema_9: float | None = None
    ema_21: float | None = None

    # Volume
    volume_sma_20: float | None = None
    relative_volume: float | None = None  # Current vol / 20d avg

    # Squeeze
    bollinger_width: float | None = None
    keltner_upper: float | None = None
    keltner_lower: float | None = None
    squeeze_on: bool = False  # BB inside KC = squeeze


class ScannerResult(BaseModel):
    """Result from the weekly scanner — a candidate for trading."""

    asset: Asset
    current_price: float
    indicators: TechnicalIndicators
    avg_daily_volume: int = 0
    weekly_change_pct: float = 0.0
    short_interest_pct: float | None = None
    days_to_earnings: int | None = None
    gap_pct: float | None = None  # Pre-market gap
    catalyst: str = ""  # Brief description of why this is interesting
    scanned_at: datetime = Field(default_factory=datetime.utcnow)


class Signal(BaseModel):
    """A trading signal — high conviction, speculative."""

    asset: Asset
    direction: SignalDirection
    confidence: float = Field(ge=0.0, le=1.0)
    strategy: StrategyType
    rationale: str
    entry_price: float
    target_price: float | None = None  # Expected exit price
    stop_loss: float | None = None  # Optional, given high-risk nature
    expected_return_pct: float | None = None
    risk_reward_ratio: float | None = None
    generated_at: datetime = Field(default_factory=datetime.utcnow)


class Position(BaseModel):
    """A current portfolio position."""

    asset: Asset
    quantity: float
    avg_entry_price: float
    current_price: float = 0.0
    allocation_pct: float = 0.0  # % of total capital
    opened_at: datetime = Field(default_factory=datetime.utcnow)
    strategy: StrategyType | None = None
    signal_confidence: float = 0.0

    @property
    def market_value(self) -> float:
        return self.quantity * self.current_price

    @property
    def unrealized_pnl(self) -> float:
        return (self.current_price - self.avg_entry_price) * self.quantity

    @property
    def pnl_pct(self) -> float:
        if self.avg_entry_price == 0:
            return 0.0
        return (self.current_price - self.avg_entry_price) / self.avg_entry_price


class Order(BaseModel):
    """An order for paper trading tracking."""

    asset: Asset
    direction: SignalDirection
    quantity: float
    order_type: OrderType = OrderType.MARKET
    limit_price: float | None = None
    stop_price: float | None = None
    status: OrderStatus = OrderStatus.PENDING
    order_id: str | None = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    filled_at: datetime | None = None
    filled_price: float | None = None


class Recommendation(BaseModel):
    """A recommendation presented to the user — go big or stay out."""

    signal: Signal
    suggested_quantity: int
    allocation_pct: float  # What % of capital to deploy
    suggested_order_type: OrderType
    suggested_limit_price: float | None = None
    expected_return_pct: float | None = None
    max_loss_pct: float | None = None  # Worst case
    rationale_summary: str
    rank: int = 0  # 1 = top pick


class WeeklyReport(BaseModel):
    """End-of-week performance report."""

    week_start: datetime
    week_end: datetime
    starting_capital: float
    ending_capital: float
    total_return_pct: float
    trades: list[Order] = Field(default_factory=list)
    best_trade_pct: float = 0.0
    worst_trade_pct: float = 0.0
    win_rate: float = 0.0
    total_trades: int = 0
