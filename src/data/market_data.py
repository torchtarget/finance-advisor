"""Market data fetching and technical indicator computation."""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import ta
import yfinance as yf

from src.models import Asset, PriceData, TechnicalIndicators

logger = logging.getLogger(__name__)


class MarketDataProvider:
    """Fetches price data and computes technical indicators."""

    def get_price_history(
        self,
        symbol: str,
        days: int = 60,
        interval: str = "1d",
    ) -> list[PriceData]:
        """Fetch OHLCV price history from Yahoo Finance."""
        try:
            ticker = yf.Ticker(symbol)
            end = datetime.now()
            start = end - timedelta(days=days)

            df = ticker.history(start=start, end=end, interval=interval)
            if df.empty:
                logger.warning(f"No price data for {symbol}")
                return []

            prices = []
            for idx, row in df.iterrows():
                prices.append(
                    PriceData(
                        timestamp=idx.to_pydatetime(),
                        open=float(row["Open"]),
                        high=float(row["High"]),
                        low=float(row["Low"]),
                        close=float(row["Close"]),
                        volume=int(row["Volume"]),
                    )
                )
            return prices

        except Exception as e:
            logger.error(f"Failed to fetch price data for {symbol}: {e}")
            return []

    def get_current_price(self, symbol: str) -> float | None:
        """Get the latest price for a symbol."""
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.fast_info
            return float(info.get("lastPrice", 0) or info.get("previousClose", 0))
        except Exception as e:
            logger.error(f"Failed to get current price for {symbol}: {e}")
            return None

    def compute_indicators(self, prices: list[PriceData]) -> TechnicalIndicators:
        """Compute all technical indicators from price data."""
        if len(prices) < 20:
            return TechnicalIndicators()

        df = pd.DataFrame([p.model_dump() for p in prices])
        df = df.sort_values("timestamp").reset_index(drop=True)

        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"].astype(float)
        current_price = close.iloc[-1]

        # RSI
        rsi = ta.momentum.RSIIndicator(close, window=14)
        rsi_val = rsi.rsi().iloc[-1]

        # MACD
        macd = ta.trend.MACD(close, window_slow=26, window_fast=12, window_sign=9)
        macd_val = macd.macd().iloc[-1]
        macd_signal = macd.macd_signal().iloc[-1]
        macd_hist = macd.macd_diff().iloc[-1]

        # Bollinger Bands
        bb = ta.volatility.BollingerBands(close, window=20, window_dev=2)
        bb_upper = bb.bollinger_hband().iloc[-1]
        bb_middle = bb.bollinger_mavg().iloc[-1]
        bb_lower = bb.bollinger_lband().iloc[-1]
        bb_width = (bb_upper - bb_lower) / bb_middle if bb_middle > 0 else 0

        # ATR
        atr_indicator = ta.volatility.AverageTrueRange(high, low, close, window=14)
        atr_val = atr_indicator.average_true_range().iloc[-1]
        atr_pct = (atr_val / current_price * 100) if current_price > 0 else 0

        # Moving averages
        sma_20 = close.rolling(20).mean().iloc[-1]
        ema_9 = close.ewm(span=9).mean().iloc[-1]
        ema_21 = close.ewm(span=21).mean().iloc[-1]

        # Volume
        vol_sma_20 = volume.rolling(20).mean().iloc[-1]
        rel_volume = (volume.iloc[-1] / vol_sma_20) if vol_sma_20 > 0 else 1.0

        # Keltner Channels (for squeeze detection)
        kc_middle = close.ewm(span=20).mean()
        kc_range = atr_val * 1.5
        kc_upper = kc_middle.iloc[-1] + kc_range
        kc_lower = kc_middle.iloc[-1] - kc_range

        # Squeeze: BB inside KC
        squeeze_on = bb_upper < kc_upper and bb_lower > kc_lower

        return TechnicalIndicators(
            rsi_14=_safe_float(rsi_val),
            macd=_safe_float(macd_val),
            macd_signal=_safe_float(macd_signal),
            macd_histogram=_safe_float(macd_hist),
            bollinger_upper=_safe_float(bb_upper),
            bollinger_middle=_safe_float(bb_middle),
            bollinger_lower=_safe_float(bb_lower),
            bollinger_width=_safe_float(bb_width),
            atr_14=_safe_float(atr_val),
            atr_pct=_safe_float(atr_pct),
            sma_20=_safe_float(sma_20),
            ema_9=_safe_float(ema_9),
            ema_21=_safe_float(ema_21),
            volume_sma_20=_safe_float(vol_sma_20),
            relative_volume=_safe_float(rel_volume),
            keltner_upper=_safe_float(kc_upper),
            keltner_lower=_safe_float(kc_lower),
            squeeze_on=squeeze_on,
        )

    def get_upcoming_earnings(self, symbol: str) -> int | None:
        """Return days until next earnings, or None if unknown."""
        try:
            ticker = yf.Ticker(symbol)
            cal = ticker.calendar
            if cal is not None and "Earnings Date" in cal:
                earnings_dates = cal["Earnings Date"]
                if earnings_dates:
                    next_earnings = min(earnings_dates)
                    delta = (next_earnings - datetime.now()).days
                    return max(delta, 0)
        except Exception:
            pass
        return None

    def get_short_interest(self, symbol: str) -> float | None:
        """Get short interest as % of float, if available."""
        try:
            ticker = yf.Ticker(symbol)
            info = ticker.info or {}
            short_pct = info.get("shortPercentOfFloat")
            if short_pct:
                return float(short_pct) * 100
        except Exception:
            pass
        return None

    def scan_universe(
        self,
        symbols: list[str],
        min_volume: int = 500_000,
        min_price: float = 1.0,
        max_price: float = 500.0,
    ) -> list[dict]:
        """Scan a list of symbols and return those meeting basic criteria."""
        results = []
        for symbol in symbols:
            try:
                prices = self.get_price_history(symbol, days=30)
                if len(prices) < 20:
                    continue

                latest = prices[-1]
                avg_vol = np.mean([p.volume for p in prices[-20:]])

                if avg_vol < min_volume:
                    continue
                if latest.close < min_price or latest.close > max_price:
                    continue

                indicators = self.compute_indicators(prices)
                results.append({
                    "symbol": symbol,
                    "price": latest.close,
                    "avg_volume": int(avg_vol),
                    "indicators": indicators,
                    "prices": prices,
                })
            except Exception as e:
                logger.debug(f"Skipping {symbol} in scan: {e}")
                continue

        return results


def _safe_float(val: float) -> float | None:
    """Convert to float, returning None if NaN or infinite."""
    if val is None or (isinstance(val, float) and (np.isnan(val) or np.isinf(val))):
        return None
    return float(val)
