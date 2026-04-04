"""DeGiro API client wrapper."""

from __future__ import annotations

import logging
from typing import Any

from degiro_connector.trading.api import API as TradingAPI
from degiro_connector.trading.models.credentials import Credentials
from degiro_connector.quotecast.api import API as QuotecastAPI

from src.config import DegiroConfig
from src.models import Asset, AssetType, Order, OrderType, Position, SignalDirection

logger = logging.getLogger(__name__)


class DegiroClient:
    """Wrapper around degiro-connector for trading and data operations."""

    def __init__(self, config: DegiroConfig):
        self._config = config
        self._trading_api: TradingAPI | None = None
        self._connected = False

    def connect(self) -> None:
        """Authenticate and connect to DeGiro."""
        credentials = Credentials(
            int_account=None,
            username=self._config.username,
            password=self._config.password,
            totp_secret_key=self._config.totp_secret or None,
        )
        self._trading_api = TradingAPI(credentials=credentials)
        self._trading_api.connect()
        self._connected = True
        logger.info("Connected to DeGiro")

    @property
    def api(self) -> TradingAPI:
        if not self._trading_api or not self._connected:
            raise RuntimeError("Not connected to DeGiro. Call connect() first.")
        return self._trading_api

    def get_account_info(self) -> dict[str, Any]:
        """Get account overview including cash balance."""
        return self.api.get_account_info()

    def get_cash_available(self) -> float:
        """Get available cash for trading."""
        account_info = self.get_account_info()
        # Navigate the account info structure for free space
        try:
            for item in account_info.get("cashFunds", {}).get("value", []):
                if item.get("currencyCode") == "USD":
                    return float(item.get("value", 0))
            # Fallback: try total portfolio value
            return float(account_info.get("marginFreeSpace", 0))
        except (KeyError, TypeError, ValueError):
            logger.warning("Could not parse cash available from account info")
            return 0.0

    def get_portfolio(self) -> list[Position]:
        """Get current portfolio positions."""
        portfolio_raw = self.api.get_portfolio()
        positions = []

        if not portfolio_raw:
            return positions

        for item in portfolio_raw.get("portfolio", {}).get("value", []):
            try:
                pos_data = {v["name"]: v.get("value") for v in item.get("value", [])}
                if pos_data.get("positionType") != "PRODUCT":
                    continue

                asset = Asset(
                    product_id=str(pos_data.get("id", "")),
                    symbol=pos_data.get("symbol", ""),
                    name=pos_data.get("product", ""),
                    exchange_id=int(pos_data.get("exchangeId", 0)),
                    currency=pos_data.get("currency", "USD"),
                )

                positions.append(
                    Position(
                        asset=asset,
                        quantity=float(pos_data.get("size", 0)),
                        avg_entry_price=float(pos_data.get("breakEvenPrice", 0)),
                        current_price=float(pos_data.get("price", 0)),
                    )
                )
            except (KeyError, TypeError, ValueError) as e:
                logger.warning(f"Skipping portfolio item: {e}")
                continue

        return positions

    def search_products(
        self,
        query: str = "",
        exchange_id: int | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """Search for products on DeGiro."""
        search_params = {
            "searchText": query,
            "limit": limit,
            "offset": 0,
        }
        if exchange_id:
            search_params["exchangeId"] = exchange_id

        result = self.api.product_search(**search_params)
        return result.get("products", []) if result else []

    def get_product_info(self, product_ids: list[str]) -> dict[str, Any]:
        """Get detailed product info for a list of product IDs."""
        return self.api.get_products_info(
            product_list=product_ids,
        )

    def place_order(self, order: Order) -> str | None:
        """Place an order on DeGiro. Returns order ID if successful."""
        from degiro_connector.trading.models.order import Order as DegiroOrder

        action_map = {
            SignalDirection.BUY: DegiroOrder.Action.BUY,
            SignalDirection.SELL: DegiroOrder.Action.SELL,
            SignalDirection.SHORT: DegiroOrder.Action.SELL,
        }

        order_type_map = {
            OrderType.MARKET: DegiroOrder.OrderType.MARKET,
            OrderType.LIMIT: DegiroOrder.OrderType.LIMIT,
            OrderType.STOP_LIMIT: DegiroOrder.OrderType.STOP_LIMIT,
        }

        degiro_order = DegiroOrder(
            action=action_map[order.direction],
            order_type=order_type_map[order.order_type],
            price=order.limit_price,
            product_id=int(order.asset.product_id),
            size=order.quantity,
            time_type=DegiroOrder.TimeType.GOOD_TILL_DAY,
        )

        # Check order first
        check_result = self.api.check_order(order=degiro_order)
        if not check_result:
            logger.error(f"Order check failed for {order.asset.symbol}")
            return None

        confirmation_id = check_result.get("confirmationId")
        if not confirmation_id:
            logger.error(f"No confirmation ID for {order.asset.symbol}")
            return None

        # Confirm the order
        result = self.api.confirm_order(
            confirmation_id=confirmation_id,
            order=degiro_order,
        )

        order_id = result.get("orderId") if result else None
        if order_id:
            logger.info(f"Order placed: {order.direction} {order.quantity}x {order.asset.symbol} -> {order_id}")
        else:
            logger.error(f"Order confirmation failed for {order.asset.symbol}")

        return order_id

    def get_orders(self) -> list[dict[str, Any]]:
        """Get current open orders."""
        return self.api.get_orders() or []

    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order."""
        result = self.api.delete_order(order_id=order_id)
        return result is not None

    def disconnect(self) -> None:
        """Logout from DeGiro."""
        if self._trading_api and self._connected:
            self._trading_api.logout()
            self._connected = False
            logger.info("Disconnected from DeGiro")
