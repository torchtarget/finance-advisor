"""Position sizing for aggressive weekly trading.

MAX RISK mode: deploy ALL capital every week. No idle cash.
Supports fractional-share-aware redistribution for whole-share brokers like DeGiro.
"""

from __future__ import annotations

import logging
from src.config import AppConfig
from src.models import OrderType, Recommendation, Signal

logger = logging.getLogger(__name__)


class PositionSizer:
    """Determines how much capital to allocate to each trade.

    Key principle: DEPLOY EVERYTHING. Any cash left idle is wasted opportunity
    in a high-risk weekly strategy. Leftover from rounding to whole shares
    gets redistributed to the next position.
    """

    def __init__(self, config: AppConfig):
        self.config = config

    def size_positions(
        self,
        signals: list[Signal],
        available_capital: float,
    ) -> list[Recommendation]:
        """Generate recommendations deploying ALL available capital.

        No idle cash. Leftover from whole-share rounding goes to next position.
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

        # Normalize so total = 1.0 (deploy 100% of capital)
        total = sum(allocations)
        if total > 0:
            allocations = [a / total for a in allocations]

        # Build recommendations with whole-share redistribution
        recommendations = []
        remaining_capital = available_capital

        for i, (signal, alloc_pct) in enumerate(zip(signals, allocations)):
            if alloc_pct <= 0 or remaining_capital <= 0:
                continue

            price = signal.entry_price
            if price <= 0:
                continue

            # For the LAST position, give it ALL remaining capital
            if i == len(signals) - 1 or i == len(allocations) - 1:
                capital_for_position = remaining_capital
            else:
                capital_for_position = available_capital * alloc_pct

            quantity = int(capital_for_position / price)
            if quantity <= 0:
                # Can't afford even 1 share — give capital to next position
                continue

            actual_cost = quantity * price
            remaining_capital -= actual_cost

            actual_alloc_pct = (actual_cost / available_capital) * 100

            recommendations.append(
                Recommendation(
                    signal=signal,
                    suggested_quantity=quantity,
                    allocation_pct=actual_alloc_pct,
                    suggested_order_type=OrderType.MARKET,
                    suggested_limit_price=None,
                    expected_return_pct=signal.expected_return_pct,
                    max_loss_pct=actual_alloc_pct,
                    rationale_summary=signal.rationale,
                    rank=i + 1,
                )
            )

        # Redistribute ALL remaining capital across existing positions
        # Keep cycling through positions until we can't buy any more shares
        if remaining_capital > 0 and recommendations:
            changed = True
            while changed and remaining_capital > 0:
                changed = False
                for rec in recommendations:
                    price = rec.signal.entry_price
                    if price <= 0 or price > remaining_capital:
                        continue
                    extra = int(remaining_capital / price)
                    if extra > 0:
                        rec.suggested_quantity += extra
                        cost = extra * price
                        remaining_capital -= cost
                        changed = True

            # Recalculate allocation percentages
            for rec in recommendations:
                actual_cost = rec.suggested_quantity * rec.signal.entry_price
                rec.allocation_pct = (actual_cost / available_capital) * 100
                rec.max_loss_pct = rec.allocation_pct

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
            allocations[0] = 1.0
        return allocations

    def _kelly(self, signals: list[Signal]) -> list[float]:
        """Simplified Kelly criterion: f* = (bp - q) / b"""
        allocations = []
        for signal in signals:
            p = signal.confidence
            q = 1 - p
            expected_ret = (signal.expected_return_pct or 5) / 100
            risk = 1.0

            b = expected_ret / risk if risk > 0 else 0
            kelly_fraction = (b * p - q) / b if b > 0 else 0
            kelly_fraction = max(kelly_fraction, 0)

            # Full Kelly — no half-Kelly, max risk mode
            allocations.append(kelly_fraction)

        return allocations
