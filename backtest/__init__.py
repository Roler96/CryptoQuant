"""Backtest module for CryptoQuant platform.

Provides backtesting capabilities through Backtrader integration:
- BacktestEngine: Main engine for running strategy backtests
- BacktestConfig: Configuration dataclass for backtest parameters
- BacktestResult: Result container for backtest outputs
- PandasDataFeed: Custom data feed for DataFrames from SQLite repository
- BacktraderStrategyAdapter: Bridge between StrategyBase and Backtrader
- Performance metrics for result analysis
"""

from backtest.adapter import BacktraderStrategyAdapter
from backtest.data_feed import PandasDataFeed
from backtest.engine import BacktestEngine
from backtest.models import BacktestConfig, BacktestResult
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