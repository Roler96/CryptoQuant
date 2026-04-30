"""Strategy module for CryptoQuant platform.

Provides base classes and implementations for trading strategies.
"""

from strategy.base import (
    Position,
    Signal,
    SignalType,
    StrategyBase,
    StrategyContext,
)
from strategy.cta import (
    calculate_atr,
    calculate_bollinger_bands,
    calculate_ma,
    calculate_macd,
    calculate_rsi,
    detect_breakout,
)
from strategy.cta.trend_following import (
    TrendFollowingConfig,
    TrendFollowingStrategy,
)
from strategy.stat_arb import (
    StatArbConfig,
    calculate_cointegration,
    calculate_hedge_ratio,
    calculate_zscore,
)
from strategy.stat_arb.pair_trading import StatArbStrategy

__all__ = [
    "Position",
    "Signal",
    "SignalType",
    "StrategyBase",
    "StrategyContext",
    "calculate_ma",
    "calculate_rsi",
    "calculate_atr",
    "calculate_bollinger_bands",
    "calculate_macd",
    "detect_breakout",
    "TrendFollowingConfig",
    "TrendFollowingStrategy",
    "StatArbConfig",
    "StatArbStrategy",
    "calculate_cointegration",
    "calculate_hedge_ratio",
    "calculate_zscore",
]
