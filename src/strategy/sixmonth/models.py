"""6-month buy-and-hold strategy models.

Rules:
- Buy and hold for exactly 6 months
- CANNOT sell during the period
- CAN add to positions (pyramid into winners)
- Super high risk, accept total loss
- Concentrated: 1-3 positions max
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


class SixMonthStrategyType(str, Enum):
    PRICE_MOMENTUM = "price_momentum_6m"
    EARNINGS_REVISION = "earnings_revision"
    CATALYST_STACK = "catalyst_stack"
    THEMATIC = "thematic_concentration"
    LEVERAGED_MOMENTUM = "leveraged_momentum"


class MomentumScore(BaseModel):
    """Momentum ranking for a stock over 6-12 month horizon."""

    symbol: str
    price_6m_ago: float
    price_now: float
    return_6m: float
    return_3m: float
    return_1m: float
    composite_score: float = 0.0
    volume_trend: float = 0.0
    above_200_sma: bool = False
    above_50_sma: bool = False
    making_new_highs: bool = False


class SixMonthPick(BaseModel):
    """A 6-month buy-and-hold recommendation."""

    symbol: str
    strategy: SixMonthStrategyType
    entry_price: float
    target_price: float
    expected_return_pct: float
    confidence: float = Field(ge=0.0, le=1.0)
    rationale: str
    catalysts: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    momentum_score: MomentumScore | None = None

    # Pyramiding plan
    initial_allocation_pct: float = 50.0
    add_trigger_pct: float = 10.0  # Add more if price rises 10%+
    max_allocation_pct: float = 100.0

    generated_at: datetime = Field(default_factory=datetime.utcnow)
    hold_until: str = ""
