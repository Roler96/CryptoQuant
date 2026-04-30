"""Statistical Arbitrage (StatArb) strategy module.

Provides pair trading strategy implementation based on cointegration analysis
and z-score mean reversion signals.
"""

from strategy.stat_arb.pair_trading import (
    StatArbConfig,
    StatArbStrategy,
    calculate_cointegration,
    calculate_hedge_ratio,
    calculate_zscore,
)

__all__ = [
    "StatArbConfig",
    "StatArbStrategy",
    "calculate_cointegration",
    "calculate_hedge_ratio",
    "calculate_zscore",
]
