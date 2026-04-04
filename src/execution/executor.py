"""Trade executor — routes to paper or live execution."""

from __future__ import annotations

import logging

from src.config import AppConfig
from src.data.degiro_client import DegiroClient
from src.execution.paper_trader import PaperTrader
from src.models import Order, OrderStatus, Recommendation

logger = logging.getLogger(__name__)


class TradeExecutor:
    """Routes trade execution to paper or live mode."""

    def __init__(
        self,
        config: AppConfig,
        degiro_client: DegiroClient | None = None,
        paper_trader: PaperTrader | None = None,
    ):
        self.config = config
        self.mode = config.execution.mode
        self.degiro = degiro_client
        self.paper = paper_trader or PaperTrader()

    def execute(self, recommendation: Recommendation) -> Order:
        """Execute a recommendation in the configured mode."""
        if self.mode == "paper":
            return self._execute_paper(recommendation)
        elif self.mode == "live":
            return self._execute_live(recommendation)
        else:
            raise ValueError(f"Unknown execution mode: {self.mode}")

    def _execute_paper(self, rec: Recommendation) -> Order:
        return self.paper.execute_recommendation(rec)

    def _execute_live(self, rec: Recommendation) -> Order:
        if not self.degiro:
            raise RuntimeError("Live mode requires a connected DeGiro client")

        signal = rec.signal
        order = Order(
            asset=signal.asset,
            direction=signal.direction,
            quantity=rec.suggested_quantity,
            order_type=rec.suggested_order_type,
            limit_price=rec.suggested_limit_price,
        )

        logger.warning(
            f"LIVE ORDER: {order.direction} {order.quantity}x {order.asset.symbol} "
            f"@ {order.order_type.value}"
        )

        order_id = self.degiro.place_order(order)
        if order_id:
            order.degiro_order_id = order_id
            order.status = OrderStatus.PENDING
            logger.info(f"Live order placed: {order_id}")
        else:
            order.status = OrderStatus.REJECTED
            logger.error(f"Live order rejected for {order.asset.symbol}")

        return order

    def execute_all(self, recommendations: list[Recommendation]) -> list[Order]:
        """Execute all recommendations."""
        orders = []
        for rec in recommendations:
            order = self.execute(rec)
            orders.append(order)
        return orders
