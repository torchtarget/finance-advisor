"""Paper trading engine for testing strategies without real money."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path

from src.models import (
    Order,
    OrderStatus,
    OrderType,
    Position,
    Recommendation,
    SignalDirection,
    WeeklyReport,
)

logger = logging.getLogger(__name__)

TRADES_LOG = Path(__file__).parent.parent.parent / "data" / "paper_trades.json"


class PaperTrader:
    """Simulates order execution for paper trading mode."""

    def __init__(self, starting_capital: float = 1_000.0):
        self.starting_capital = starting_capital
        self.cash = starting_capital
        self.positions: list[Position] = []
        self.order_history: list[Order] = []
        self.weekly_start_capital = starting_capital

    def execute_recommendation(self, rec: Recommendation) -> Order:
        """Execute a paper trade from a recommendation."""
        signal = rec.signal
        price = signal.entry_price
        quantity = rec.suggested_quantity
        cost = price * quantity

        if cost > self.cash:
            # Adjust quantity to what we can afford
            quantity = int(self.cash / price)
            cost = price * quantity

        if quantity <= 0:
            order = Order(
                asset=signal.asset,
                direction=signal.direction,
                quantity=0,
                order_type=rec.suggested_order_type,
                status=OrderStatus.REJECTED,
            )
            logger.warning(f"Paper trade rejected: insufficient funds for {signal.asset.symbol}")
            return order

        # Execute at current price (paper = instant fill)
        order = Order(
            asset=signal.asset,
            direction=signal.direction,
            quantity=quantity,
            order_type=rec.suggested_order_type,
            limit_price=rec.suggested_limit_price,
            status=OrderStatus.FILLED,
            filled_at=datetime.utcnow(),
            filled_price=price,
        )

        self.cash -= cost

        # Add to positions
        self.positions.append(
            Position(
                asset=signal.asset,
                quantity=quantity,
                avg_entry_price=price,
                current_price=price,
                strategy=signal.strategy,
                signal_confidence=signal.confidence,
            )
        )

        self.order_history.append(order)
        logger.info(
            f"PAPER BUY: {quantity}x {signal.asset.symbol} @ ${price:.2f} "
            f"(${cost:.2f} total, ${self.cash:.2f} remaining)"
        )

        return order

    def close_position(self, position: Position, current_price: float) -> Order:
        """Close a position at the given price."""
        proceeds = current_price * position.quantity

        order = Order(
            asset=position.asset,
            direction=SignalDirection.SELL,
            quantity=position.quantity,
            order_type=OrderType.MARKET,
            status=OrderStatus.FILLED,
            filled_at=datetime.utcnow(),
            filled_price=current_price,
        )

        self.cash += proceeds
        self.positions.remove(position)
        self.order_history.append(order)

        pnl = (current_price - position.avg_entry_price) * position.quantity
        pnl_pct = ((current_price - position.avg_entry_price) / position.avg_entry_price) * 100

        logger.info(
            f"PAPER SELL: {position.quantity}x {position.asset.symbol} @ ${current_price:.2f} "
            f"(P&L: ${pnl:+.2f} / {pnl_pct:+.1f}%)"
        )

        return order

    def close_all_positions(self, price_getter) -> list[Order]:
        """Close all open positions. price_getter(symbol) -> float."""
        orders = []
        for pos in list(self.positions):
            price = price_getter(pos.asset.symbol)
            if price:
                orders.append(self.close_position(pos, price))
        return orders

    def get_total_value(self, price_getter=None) -> float:
        """Total portfolio value (cash + positions)."""
        position_value = 0.0
        for pos in self.positions:
            if price_getter:
                price = price_getter(pos.asset.symbol) or pos.current_price
            else:
                price = pos.current_price
            position_value += price * pos.quantity
        return self.cash + position_value

    def generate_weekly_report(self) -> WeeklyReport:
        """Generate end-of-week performance report."""
        total_value = self.get_total_value()
        total_return = ((total_value - self.weekly_start_capital) / self.weekly_start_capital) * 100

        # Compute trade stats from this week's orders
        fills = [o for o in self.order_history if o.status == OrderStatus.FILLED]
        buy_fills = {o.asset.symbol: o for o in fills if o.direction == SignalDirection.BUY}
        sell_fills = [o for o in fills if o.direction == SignalDirection.SELL]

        trade_returns = []
        for sell in sell_fills:
            buy = buy_fills.get(sell.asset.symbol)
            if buy and buy.filled_price and sell.filled_price:
                ret = ((sell.filled_price - buy.filled_price) / buy.filled_price) * 100
                trade_returns.append(ret)

        return WeeklyReport(
            week_start=datetime.utcnow(),
            week_end=datetime.utcnow(),
            starting_capital=self.weekly_start_capital,
            ending_capital=total_value,
            total_return_pct=total_return,
            trades=fills,
            best_trade_pct=max(trade_returns) if trade_returns else 0.0,
            worst_trade_pct=min(trade_returns) if trade_returns else 0.0,
            win_rate=(
                sum(1 for r in trade_returns if r > 0) / len(trade_returns) * 100
                if trade_returns
                else 0.0
            ),
            total_trades=len(fills),
        )

    def save_state(self, path: Path | None = None):
        """Persist paper trading state to disk."""
        save_path = path or TRADES_LOG
        save_path.parent.mkdir(parents=True, exist_ok=True)

        state = {
            "cash": self.cash,
            "starting_capital": self.starting_capital,
            "positions": [p.model_dump(mode="json") for p in self.positions],
            "order_history": [o.model_dump(mode="json") for o in self.order_history],
        }

        with open(save_path, "w") as f:
            json.dump(state, f, indent=2, default=str)
        logger.info(f"Paper trading state saved to {save_path}")
