"""Backtest module for CryptoQuant platform.

Provides backtesting capabilities through Backtrader integration:
- BacktestEngine: Main engine for running strategy backtests
- BacktestConfig: Configuration dataclass for backtest parameters
- BacktestResult: Result container for backtest outputs
- PandasDataFeed: Custom data feed for Parquet DataFrames
- Performance metrics for result analysis
"""

from backtest.engine import (
    BacktestConfig,
    BacktestEngine,
    BacktestResult,
    BacktraderStrategyAdapter,
    PandasDataFeed,
)
from backtest.metrics import (
    SHARPE_THRESHOLD,
    MAX_DRAWDOWN_THRESHOLD,
    WIN_RATE_THRESHOLD,
    calculate_sharpe_ratio,
    calculate_max_drawdown,
    calculate_win_rate,
    calculate_profit_factor,
    calculate_annualized_return,
    calculate_volatility,
    calculate_average_trade,
    calculate_calmar_ratio,
    generate_performance_report,
    get_threshold_status,
)

__all__ = [
    "BacktestEngine",
    "BacktestConfig",
    "BacktestResult",
    "BacktraderStrategyAdapter",
    "PandasDataFeed",
    "calculate_sharpe_ratio",
    "calculate_max_drawdown",
    "calculate_win_rate",
    "calculate_profit_factor",
    "calculate_annualized_return",
    "calculate_volatility",
    "calculate_average_trade",
    "calculate_calmar_ratio",
    "generate_performance_report",
    "get_threshold_status",
    "SHARPE_THRESHOLD",
    "MAX_DRAWDOWN_THRESHOLD",
    "WIN_RATE_THRESHOLD",
]
