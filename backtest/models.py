"""Backtest data models.

Contains configuration and result dataclasses for backtest execution.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class BacktestConfig:
    """Configuration for backtest execution."""

    initial_cash: float = 10000.0
    commission: float = 0.001
    slippage: float = 0.0005
    plot_results: bool = True
    log_path: str = "logs"


@dataclass
class BacktestResult:
    """Result of a backtest execution."""

    strategy_name: str
    pair: str
    timeframe: str
    initial_value: float
    final_value: float
    total_return: float
    trades: List[Dict[str, Any]] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)
    equity_timestamps: List[int] = field(default_factory=list)
    sharpe_ratio: Optional[float] = None
    max_drawdown: Optional[float] = None
    config: Optional[BacktestConfig] = None
    plot_path: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary."""
        return {
            "strategy_name": self.strategy_name,
            "pair": self.pair,
            "timeframe": self.timeframe,
            "initial_value": self.initial_value,
            "final_value": self.final_value,
            "total_return": self.total_return,
            "total_trades": len(self.trades),
            "sharpe_ratio": self.sharpe_ratio,
            "max_drawdown": self.max_drawdown,
            "plot_path": self.plot_path,
            "error": self.error,
        }