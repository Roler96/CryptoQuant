"""Backtesting data types."""

from dataclasses import dataclass

import pandas as pd


@dataclass
class Trade:
    """Single trade lifecycle record."""

    id: int
    symbol: str
    side: str  # "long" | "short"
    entry_time: int  # Unix ms
    entry_price: float
    entry_signal: int
    exit_time: int
    exit_price: float
    exit_reason: str  # "take_profit" | "stop_loss" | "time_exit" | "signal_reverse" | "end_of_data"
    pnl_pct: float
    pnl_abs: float
    hold_bars: int
    hold_hours: float
    mae_pct: float  # Maximum Adverse Excursion (%)
    mfe_pct: float  # Maximum Favorable Excursion (%)
    position_size: float = 0.0  # Quote-currency notional allocated at entry


@dataclass
class PerformanceMetrics:
    """Backtest performance metrics."""

    total_return_pct: float
    annualized_return_pct: float
    monthly_returns: pd.Series
    sharpe_ratio: float
    sortino_ratio: float
    max_drawdown_pct: float
    max_drawdown_days: int
    volatility_annual_pct: float
    var_95_pct: float
    cvar_95_pct: float
    total_trades: int
    win_rate_pct: float
    profit_factor: float
    avg_win_pct: float
    avg_loss_pct: float
    avg_hold_hours: float
    drawdown_periods: list[dict]


@dataclass
class BacktestResult:
    """Complete backtest result."""

    strategy_name: str
    strategy_version: str
    symbol: str
    timeframe: str
    start_time: int
    end_time: int
    initial_capital: float
    final_equity: float
    trades: list[Trade]
    metrics: PerformanceMetrics
    equity_curve: pd.Series
    drawdown_curve: pd.Series
    config: dict


@dataclass
class PaperTradingResult:
    """Complete paper trading simulation result."""

    strategy_name: str
    symbol: str
    timeframe: str
    initial_balance: float
    final_balance: float
    total_trades: int
    win_rate_pct: float
    total_slippage_bps: float
    total_latency_ms: int
    sim_start_time: int
    sim_end_time: int
    trade_log: list[Trade]
    balance_curve: pd.Series
