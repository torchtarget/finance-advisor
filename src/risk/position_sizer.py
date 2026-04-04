"""Position sizing for aggressive weekly trading."""

from __future__ import annotations

import logging
from src.config import AppConfig
from src.models import OrderType, Recommendation, Signal

logger = logging.getLogger(__name__)


class PositionSizer:
    """Determines how much capital to allocate to each trade.

    Sizing methods:
    - equal: Split capital equally across all signals
    - conviction_weighted: Allocate proportional to signal confidence
    - all_in: Put everything into the #1 signal
    - kelly: Kelly criterion based on expected return and win probability
    """

    def __init__(self, config: AppConfig):
        self.config = config

    def size_positions(
        self,
        signals: list[Signal],
        available_capital: float,
    ) -> list[Recommendation]:
        """Generate recommendations with position sizes from signals.

        Core constraint: never risk more than available_capital.
        No margin, no leverage — can only lose what's in the account.
        """
        if not signals or available_capital <= 0:
            return []

        method = self.config.risk.sizing_method
        max_size = self.config.risk.max_position_size

        if method == "all_in":
            allocations = self._all_in(signals)
        elif method == "kelly":
            allocations = self._kelly(signals)
        elif method == "conviction_weighted":
            allocations = self._conviction_weighted(signals)
        else:
            allocations = self._equal(signals)

        # Cap each position at max_position_size
        allocations = [min(a, max_size) for a in allocations]

        # Normalize if total > 1.0
        total = sum(allocations)
        if total > 1.0:
            allocations = [a / total for a in allocations]

        recommendations = []
        for i, (signal, alloc_pct) in enumerate(zip(signals, allocations)):
            if alloc_pct <= 0:
                continue

            capital_for_position = available_capital * alloc_pct
            price = signal.entry_price

            if price <= 0:
                continue

            quantity = int(capital_for_position / price)
            if quantity <= 0:
                continue

            # Determine order type
            exec_cfg = self.config.execution
            order_type = OrderType(exec_cfg.default_order_type)
            limit_price = None
            if order_type == OrderType.LIMIT:
                limit_price = price * (1 + exec_cfg.limit_price_buffer)

            # Max loss: without stop-loss, you can lose the full position
            max_loss_pct = alloc_pct * 100  # Worst case = total loss of position

            recommendations.append(
                Recommendation(
                    signal=signal,
                    suggested_quantity=quantity,
                    allocation_pct=alloc_pct * 100,
                    suggested_order_type=order_type,
                    suggested_limit_price=limit_price,
                    expected_return_pct=signal.expected_return_pct,
                    max_loss_pct=max_loss_pct,
                    rationale_summary=signal.rationale,
                    rank=i + 1,
                )
            )

        return recommendations

    def _equal(self, signals: list[Signal]) -> list[float]:
        n = len(signals)
        return [1.0 / n] * n

    def _conviction_weighted(self, signals: list[Signal]) -> list[float]:
        total_confidence = sum(s.confidence for s in signals)
        if total_confidence == 0:
            return self._equal(signals)
        return [s.confidence / total_confidence for s in signals]

    def _all_in(self, signals: list[Signal]) -> list[float]:
        allocations = [0.0] * len(signals)
        if signals:
            allocations[0] = 1.0  # Signals are already ranked
        return allocations

    def _kelly(self, signals: list[Signal]) -> list[float]:
        """Simplified Kelly criterion: f* = (bp - q) / b

        Where:
        - b = odds (expected_return / risk)
        - p = probability of win (confidence)
        - q = probability of loss (1 - confidence)
        """
        allocations = []
        for signal in signals:
            p = signal.confidence
            q = 1 - p
            expected_ret = (signal.expected_return_pct or 5) / 100
            risk = 1.0  # Can lose entire position (high risk)

            b = expected_ret / risk if risk > 0 else 0
            kelly_fraction = (b * p - q) / b if b > 0 else 0
            kelly_fraction = max(kelly_fraction, 0)

            # Half-Kelly for some safety even in aggressive mode
            allocations.append(kelly_fraction * 0.5)

        return allocations
