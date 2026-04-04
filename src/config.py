"""Configuration management with environment variable overrides."""

from __future__ import annotations

import os
from pathlib import Path

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore[no-redef]

from pydantic import BaseModel, Field

CONFIG_PATH = Path(__file__).parent.parent / "config" / "settings.toml"


class StrategyConfig(BaseModel):
    lookback_days: int = 30
    holding_period_days: int = 7
    min_confidence: float = 0.5
    max_positions: int = 1
    ranking: str = "expected_return"  # "confidence" or "expected_return"
    enabled_strategies: list[str] = Field(
        default_factory=lambda: [
            "momentum_breakout",
            "mean_reversion_oversold",
            "squeeze_setup",
            "earnings_gap",
            "high_short_interest",
            "volume_spike",
        ]
    )


class RiskConfig(BaseModel):
    max_position_size: float = 1.0
    weekly_loss_limit: float = 1.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    use_trailing_stop: bool = False
    sizing_method: str = "all_in"


class MarketDataConfig(BaseModel):
    finnhub_api_key: str = ""
    newsapi_key: str = ""
    exchanges: list[int] = Field(default_factory=lambda: [906, 908])
    asset_types: list[str] = Field(default_factory=lambda: ["stock"])
    min_avg_volume: int = 500_000
    min_price: float = 1.0
    max_price: float = 500.0
    min_volatility_percentile: int = 75


class ScannerConfig(BaseModel):
    gap_threshold: float = 0.03
    volume_spike_multiplier: float = 2.0
    rsi_oversold: int = 25
    rsi_overbought: int = 75
    short_interest_min: float = 10.0
    min_atr_pct: float = 3.0
    earnings_window_days: int = 7


class ScheduleConfig(BaseModel):
    scan_day: str = "monday"
    scan_time: str = "09:35"
    exit_day: str = "friday"
    exit_time: str = "15:30"
    midweek_check: bool = True
    midweek_day: str = "wednesday"
    midweek_time: str = "12:00"


class AlertsConfig(BaseModel):
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""


class AppConfig(BaseModel):
    strategy: StrategyConfig = Field(default_factory=StrategyConfig)
    risk: RiskConfig = Field(default_factory=RiskConfig)
    market_data: MarketDataConfig = Field(default_factory=MarketDataConfig)
    scanner: ScannerConfig = Field(default_factory=ScannerConfig)
    schedule: ScheduleConfig = Field(default_factory=ScheduleConfig)
    alerts: AlertsConfig = Field(default_factory=AlertsConfig)


def load_config(path: Path | None = None) -> AppConfig:
    """Load config from TOML file with environment variable overrides."""
    config_path = path or CONFIG_PATH
    data: dict = {}

    if config_path.exists():
        with open(config_path, "rb") as f:
            data = tomllib.load(f)

    # Environment variable overrides for API keys
    env_overrides = {
        ("market_data", "finnhub_api_key"): "FINNHUB_API_KEY",
        ("market_data", "newsapi_key"): "NEWSAPI_KEY",
        ("alerts", "telegram_bot_token"): "TELEGRAM_BOT_TOKEN",
        ("alerts", "telegram_chat_id"): "TELEGRAM_CHAT_ID",
    }

    for (section, key), env_var in env_overrides.items():
        value = os.environ.get(env_var)
        if value:
            data.setdefault(section, {})[key] = value

    return AppConfig(**data)
