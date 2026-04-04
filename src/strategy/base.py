"""Base strategy interface and strategy registry."""

from __future__ import annotations

from abc import ABC, abstractmethod

from src.config import AppConfig
from src.models import ScannerResult, Signal


class BaseStrategy(ABC):
    """Base class for all trading strategies."""

    name: str = "base"

    def __init__(self, config: AppConfig):
        self.config = config

    @abstractmethod
    def evaluate(self, candidate: ScannerResult) -> Signal | None:
        """Evaluate a scanner result and return a Signal if criteria met, else None."""
        ...

    @abstractmethod
    def describe(self) -> str:
        """Human-readable description of the strategy."""
        ...


class StrategyRegistry:
    """Registry of available strategies."""

    _strategies: dict[str, type[BaseStrategy]] = {}

    @classmethod
    def register(cls, strategy_cls: type[BaseStrategy]) -> type[BaseStrategy]:
        cls._strategies[strategy_cls.name] = strategy_cls
        return strategy_cls

    @classmethod
    def get(cls, name: str) -> type[BaseStrategy] | None:
        return cls._strategies.get(name)

    @classmethod
    def get_enabled(cls, config: AppConfig) -> list[BaseStrategy]:
        enabled = config.strategy.enabled_strategies
        strategies = []
        for name in enabled:
            strategy_cls = cls._strategies.get(name)
            if strategy_cls:
                strategies.append(strategy_cls(config))
            else:
                import logging
                logging.getLogger(__name__).warning(f"Unknown strategy: {name}")
        return strategies

    @classmethod
    def all_names(cls) -> list[str]:
        return list(cls._strategies.keys())
