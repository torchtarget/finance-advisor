"""Market data fetching and technical indicator computation.

Uses only pandas/numpy for indicators — no external TA library needed.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta

import numpy as np
import pandas as pd
import yfinance as yf

from src.models import PriceData, TechnicalIndicators

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
        """Compute all technical indicators from price data using pandas/numpy."""
        if len(prices) < 20:
            return TechnicalIndicators()

        df = pd.DataFrame([p.model_dump() for p in prices])
        df = df.sort_values("timestamp").reset_index(drop=True)

        close = df["close"]
        high = df["high"]
        low = df["low"]
        volume = df["volume"].astype(float)
        current_price = close.iloc[-1]

        # --- RSI (14) ---
        delta = close.diff()
        gain = delta.where(delta > 0, 0.0)
        loss = (-delta).where(delta < 0, 0.0)
        avg_gain = gain.ewm(alpha=1 / 14, min_periods=14).mean()
        avg_loss = loss.ewm(alpha=1 / 14, min_periods=14).mean()
        rs = avg_gain / avg_loss.replace(0, np.nan)
        rsi_series = 100 - (100 / (1 + rs))
        rsi_val = rsi_series.iloc[-1]

        # --- MACD (12, 26, 9) ---
        ema_12 = close.ewm(span=12).mean()
        ema_26 = close.ewm(span=26).mean()
        macd_line = ema_12 - ema_26
        macd_signal = macd_line.ewm(span=9).mean()
        macd_hist = macd_line - macd_signal

        # --- Bollinger Bands (20, 2) ---
        sma_20 = close.rolling(20).mean()
        std_20 = close.rolling(20).std()
        bb_upper = sma_20 + 2 * std_20
        bb_lower = sma_20 - 2 * std_20
        bb_middle_val = sma_20.iloc[-1]
        bb_upper_val = bb_upper.iloc[-1]
        bb_lower_val = bb_lower.iloc[-1]
        bb_width = (bb_upper_val - bb_lower_val) / bb_middle_val if bb_middle_val > 0 else 0

        # --- ATR (14) ---
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low - close.shift(1)).abs(),
        ], axis=1).max(axis=1)
        atr_val = tr.rolling(14).mean().iloc[-1]
        atr_pct = (atr_val / current_price * 100) if current_price > 0 else 0

        # --- Moving averages ---
        sma_20_val = sma_20.iloc[-1]
        ema_9 = close.ewm(span=9).mean().iloc[-1]
        ema_21 = close.ewm(span=21).mean().iloc[-1]

        # --- Volume ---
        vol_sma_20 = volume.rolling(20).mean().iloc[-1]
        rel_volume = (volume.iloc[-1] / vol_sma_20) if vol_sma_20 > 0 else 1.0

        # --- Keltner Channels (for squeeze detection) ---
        kc_middle = close.ewm(span=20).mean()
        kc_range = atr_val * 1.5
        kc_upper = kc_middle.iloc[-1] + kc_range
        kc_lower = kc_middle.iloc[-1] - kc_range

        # Squeeze: BB inside KC
        squeeze_on = bb_upper_val < kc_upper and bb_lower_val > kc_lower

        return TechnicalIndicators(
            rsi_14=_safe_float(rsi_val),
            macd=_safe_float(macd_line.iloc[-1]),
            macd_signal=_safe_float(macd_signal.iloc[-1]),
            macd_histogram=_safe_float(macd_hist.iloc[-1]),
            bollinger_upper=_safe_float(bb_upper_val),
            bollinger_middle=_safe_float(bb_middle_val),
            bollinger_lower=_safe_float(bb_lower_val),
            bollinger_width=_safe_float(bb_width),
            atr_14=_safe_float(atr_val),
            atr_pct=_safe_float(atr_pct),
            sma_20=_safe_float(sma_20_val),
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


def _safe_float(val: float) -> float | None:
    """Convert to float, returning None if NaN or infinite."""
    if val is None or (isinstance(val, float) and (np.isnan(val) or np.isinf(val))):
        return None
    return float(val)
