"""Performance metrics calculator for backtest results.

Provides comprehensive performance analysis including:
- Sharpe ratio (annualized)
- Maximum drawdown
- Win rate
- Profit factor
- Annualized return
- Volatility (annualized standard deviation)
- Complete performance report generation

All metrics follow industry standard calculations with crypto-appropriate
defaults and thresholds.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import structlog

logger = structlog.get_logger(__name__)


# Performance thresholds
SHARPE_THRESHOLD = Decimal("1.0")
MAX_DRAWDOWN_THRESHOLD = Decimal("0.20")  # 20%
WIN_RATE_THRESHOLD = Decimal("0.40")  # 40%


def calculate_sharpe_ratio(
    equity_curve: List[Decimal],
    risk_free_rate: float = 0.02,
    trading_days_per_year: int = 365,
) -> Optional[Decimal]:
    """Calculate annualized Sharpe ratio.

    Sharpe ratio measures risk-adjusted return. Higher is better.
    Formula: (annualized_return - risk_free_rate) / annualized_volatility

    Args:
        equity_curve: List of portfolio values over time
        risk_free_rate: Annual risk-free rate (default: 0.02 = 2%)
        trading_days_per_year: Number of trading days per year (default: 365 for crypto)

    Returns:
        Annualized Sharpe ratio, or None if insufficient data
    """
    if len(equity_curve) < 2:
        logger.warning("insufficient_data_for_sharpe", length=len(equity_curve))
        return None

    try:
        # Convert to numpy array of floats
        values = np.array([float(v) for v in equity_curve])

        # Calculate returns (percentage change)
        returns = np.diff(values) / values[:-1]

        if len(returns) < 1 or np.std(returns) == 0:
            logger.warning("no_returns_for_sharpe")
            return None

        # Calculate mean return per period
        mean_return = np.mean(returns)

        # Calculate volatility (standard deviation)
        volatility = np.std(returns, ddof=1)

        if volatility == 0:
            logger.warning("zero_volatility_for_sharpe")
            return None

        # Annualize returns and volatility
        # Assuming daily data for crypto (365 days/year)
        periods_per_year = trading_days_per_year
        annualized_return = mean_return * periods_per_year
        annualized_volatility = volatility * np.sqrt(periods_per_year)

        # Calculate Sharpe ratio
        sharpe = (annualized_return - risk_free_rate) / annualized_volatility

        logger.debug(
            "sharpe_calculated",
            sharpe=float(sharpe),
            annualized_return=float(annualized_return),
            annualized_volatility=float(annualized_volatility),
        )

        return Decimal(str(sharpe))

    except Exception as e:
        logger.error("sharpe_calculation_failed", error=str(e))
        return None


def calculate_max_drawdown(equity_curve: List[Decimal]) -> Decimal:
    """Calculate maximum drawdown from peak to trough.

    Maximum drawdown is the largest percentage decline from a peak to a trough.
    Lower is better (less drawdown).

    Args:
        equity_curve: List of portfolio values over time

    Returns:
        Maximum drawdown as a percentage (0.0 to 1.0), or 0 if no drawdown
    """
    if len(equity_curve) < 2:
        logger.warning("insufficient_data_for_drawdown", length=len(equity_curve))
        return Decimal("0")

    try:
        # Convert to numpy array
        values = np.array([float(v) for v in equity_curve])

        # Calculate running maximum (peak)
        running_max = np.maximum.accumulate(values)

        # Calculate drawdown at each point
        drawdowns = (running_max - values) / running_max

        # Maximum drawdown
        max_dd = np.max(drawdowns)

        logger.debug("max_drawdown_calculated", max_drawdown=float(max_dd))

        return Decimal(str(max_dd))

    except Exception as e:
        logger.error("drawdown_calculation_failed", error=str(e))
        return Decimal("0")


def calculate_win_rate(trades: List[Dict[str, Any]]) -> Decimal:
    """Calculate win rate (percentage of winning trades).

    Args:
        trades: List of trade dictionaries with 'pnl' key (profit/loss)

    Returns:
        Win rate as a percentage (0.0 to 1.0), or 0 if no trades
    """
    if not trades:
        logger.warning("no_trades_for_win_rate")
        return Decimal("0")

    try:
        # Count winning trades (pnl > 0)
        winning_trades = sum(1 for trade in trades if trade.get("pnl", 0) > 0)
        total_trades = len(trades)

        win_rate = winning_trades / total_trades

        logger.debug(
            "win_rate_calculated",
            win_rate=float(win_rate),
            winning_trades=winning_trades,
            total_trades=total_trades,
        )

        return Decimal(str(win_rate))

    except Exception as e:
        logger.error("win_rate_calculation_failed", error=str(e))
        return Decimal("0")


def calculate_profit_factor(trades: List[Dict[str, Any]]) -> Optional[Decimal]:
    """Calculate profit factor (gross profit / gross loss).

    Profit factor > 1 indicates profitable strategy.
    Higher is better.

    Args:
        trades: List of trade dictionaries with 'pnl' key

    Returns:
        Profit factor, or None if no losing trades (infinite)
    """
    if not trades:
        logger.warning("no_trades_for_profit_factor")
        return None

    try:
        gross_profit = sum(trade.get("pnl", 0) for trade in trades if trade.get("pnl", 0) > 0)
        gross_loss = abs(sum(trade.get("pnl", 0) for trade in trades if trade.get("pnl", 0) < 0))

        if gross_loss == 0:
            if gross_profit > 0:
                logger.debug("infinite_profit_factor", gross_profit=gross_profit)
                return None  # Infinite profit factor
            else:
                return Decimal("0")

        profit_factor = gross_profit / gross_loss

        logger.debug(
            "profit_factor_calculated",
            profit_factor=float(profit_factor),
            gross_profit=float(gross_profit),
            gross_loss=float(gross_loss),
        )

        return Decimal(str(profit_factor))

    except Exception as e:
        logger.error("profit_factor_calculation_failed", error=str(e))
        return None


def calculate_annualized_return(
    equity_curve: List[Decimal],
    trading_days_per_year: int = 365,
) -> Optional[Decimal]:
    """Calculate annualized return.

    Args:
        equity_curve: List of portfolio values over time
        trading_days_per_year: Number of trading days per year (default: 365 for crypto)

    Returns:
        Annualized return as a percentage, or None if insufficient data
    """
    if len(equity_curve) < 2:
        logger.warning("insufficient_data_for_return", length=len(equity_curve))
        return None

    try:
        initial_value = float(equity_curve[0])
        final_value = float(equity_curve[-1])

        if initial_value <= 0:
            logger.warning("invalid_initial_value", initial_value=initial_value)
            return None

        # Total return
        total_return = (final_value - initial_value) / initial_value

        # Number of periods (days)
        num_periods = len(equity_curve) - 1

        # Annualize
        if num_periods < trading_days_per_year:
            # Scale up to annual
            annualized_return = total_return * (trading_days_per_year / num_periods)
        else:
            # Compound annual growth rate
            years = num_periods / trading_days_per_year
            annualized_return = (final_value / initial_value) ** (1 / years) - 1

        logger.debug(
            "annualized_return_calculated",
            annualized_return=float(annualized_return),
            total_return=float(total_return),
            num_periods=num_periods,
        )

        return Decimal(str(annualized_return))

    except Exception as e:
        logger.error("annualized_return_calculation_failed", error=str(e))
        return None


def calculate_volatility(
    equity_curve: List[Decimal],
    trading_days_per_year: int = 365,
) -> Optional[Decimal]:
    """Calculate annualized volatility (standard deviation of returns).

    Args:
        equity_curve: List of portfolio values over time
        trading_days_per_year: Number of trading days per year (default: 365 for crypto)

    Returns:
        Annualized volatility as a percentage, or None if insufficient data
    """
    if len(equity_curve) < 2:
        logger.warning("insufficient_data_for_volatility", length=len(equity_curve))
        return None

    try:
        # Convert to numpy array
        values = np.array([float(v) for v in equity_curve])

        # Calculate returns
        returns = np.diff(values) / values[:-1]

        if len(returns) < 1:
            logger.warning("no_returns_for_volatility")
            return None

        # Calculate standard deviation
        std_dev = np.std(returns, ddof=1)

        # Annualize
        annualized_volatility = std_dev * np.sqrt(trading_days_per_year)

        logger.debug(
            "volatility_calculated",
            volatility=float(annualized_volatility),
            daily_std=float(std_dev),
        )

        return Decimal(str(annualized_volatility))

    except Exception as e:
        logger.error("volatility_calculation_failed", error=str(e))
        return None


def calculate_average_trade(trades: List[Dict[str, Any]]) -> Decimal:
    """Calculate average profit/loss per trade.

    Args:
        trades: List of trade dictionaries with 'pnl' key

    Returns:
        Average P&L per trade, or 0 if no trades
    """
    if not trades:
        logger.warning("no_trades_for_average")
        return Decimal("0")

    try:
        total_pnl = sum(trade.get("pnl", 0) for trade in trades)
        avg_trade = total_pnl / len(trades)

        logger.debug(
            "average_trade_calculated",
            average=float(avg_trade),
            total_trades=len(trades),
        )

        return Decimal(str(avg_trade))

    except Exception as e:
        logger.error("average_trade_calculation_failed", error=str(e))
        return Decimal("0")


def calculate_calmar_ratio(
    equity_curve: List[Decimal],
    max_drawdown: Optional[Decimal] = None,
    trading_days_per_year: int = 365,
) -> Optional[Decimal]:
    """Calculate Calmar ratio (annualized return / max drawdown).

    Calmar ratio is similar to Sharpe but uses max drawdown instead of volatility.
    Higher is better.

    Args:
        equity_curve: List of portfolio values over time
        max_drawdown: Pre-calculated max drawdown (optional)
        trading_days_per_year: Number of trading days per year

    Returns:
        Calmar ratio, or None if calculation not possible
    """
    if max_drawdown is None:
        max_drawdown = calculate_max_drawdown(equity_curve)

    if max_drawdown is None or max_drawdown == 0:
        logger.warning("no_drawdown_for_calmar")
        return None

    annualized_return = calculate_annualized_return(equity_curve, trading_days_per_year)

    if annualized_return is None:
        logger.warning("no_return_for_calmar")
        return None

    try:
        calmar = float(annualized_return) / float(max_drawdown)
        logger.debug("calmar_calculated", calmar=float(calmar))
        return Decimal(str(calmar))
    except Exception as e:
        logger.error("calmar_calculation_failed", error=str(e))
        return None


def generate_performance_report(
    trades: List[Dict[str, Any]],
    equity_curve: List[Decimal],
    initial_value: Decimal,
) -> Dict[str, Any]:
    """Generate comprehensive performance report.

    Combines all metrics into a single report dictionary with performance
    thresholds evaluation.

    Args:
        trades: List of completed trades with 'pnl' key
        equity_curve: List of portfolio values over time
        initial_value: Initial portfolio value

    Returns:
        Dictionary containing all performance metrics and thresholds
    """
    logger.info("generating_performance_report", trades=len(trades), equity_points=len(equity_curve))

    # Calculate all metrics
    final_value = equity_curve[-1] if equity_curve else initial_value
    total_return = (final_value - initial_value) / initial_value if initial_value > 0 else Decimal("0")

    sharpe_ratio = calculate_sharpe_ratio(equity_curve)
    max_drawdown = calculate_max_drawdown(equity_curve)
    win_rate = calculate_win_rate(trades)
    profit_factor = calculate_profit_factor(trades)
    annualized_return = calculate_annualized_return(equity_curve)
    volatility = calculate_volatility(equity_curve)
    avg_trade = calculate_average_trade(trades)
    calmar_ratio = calculate_calmar_ratio(equity_curve, max_drawdown)

    # Determine thresholds status
    sharpe_pass = sharpe_ratio is not None and sharpe_ratio >= SHARPE_THRESHOLD
    max_dd_pass = max_drawdown is not None and max_drawdown <= MAX_DRAWDOWN_THRESHOLD
    win_rate_pass = win_rate is not None and win_rate >= WIN_RATE_THRESHOLD

    overall_pass = sharpe_pass and max_dd_pass and win_rate_pass

    report = {
        "summary": {
            "initial_value": float(initial_value),
            "final_value": float(final_value),
            "total_return": float(total_return),
            "total_trades": len(trades),
            "winning_trades": sum(1 for t in trades if t.get("pnl", 0) > 0),
            "losing_trades": sum(1 for t in trades if t.get("pnl", 0) < 0),
        },
        "returns": {
            "total_return_pct": float(total_return * 100),
            "annualized_return_pct": float(annualized_return * 100) if annualized_return else None,
            "volatility_pct": float(volatility * 100) if volatility else None,
        },
        "risk_metrics": {
            "sharpe_ratio": float(sharpe_ratio) if sharpe_ratio else None,
            "max_drawdown_pct": float(max_drawdown * 100) if max_drawdown else None,
            "calmar_ratio": float(calmar_ratio) if calmar_ratio else None,
        },
        "trade_metrics": {
            "win_rate_pct": float(win_rate * 100) if win_rate else None,
            "profit_factor": float(profit_factor) if profit_factor else None,
            "average_trade_pnl": float(avg_trade),
        },
        "thresholds": {
            "sharpe_ratio": {"value": float(sharpe_ratio) if sharpe_ratio else None, "threshold": float(SHARPE_THRESHOLD), "pass": sharpe_pass},
            "max_drawdown": {"value": float(max_drawdown) if max_drawdown else None, "threshold": float(MAX_DRAWDOWN_THRESHOLD), "pass": max_dd_pass},
            "win_rate": {"value": float(win_rate) if win_rate else None, "threshold": float(WIN_RATE_THRESHOLD), "pass": win_rate_pass},
            "overall_pass": overall_pass,
        },
        "metadata": {
            "data_points": len(equity_curve),
            "calculation_timestamp": pd.Timestamp.now().isoformat(),
        },
    }

    logger.info(
        "performance_report_generated",
        total_return=float(total_return),
        sharpe=float(sharpe_ratio) if sharpe_ratio else None,
        max_drawdown=float(max_drawdown) if max_drawdown else None,
        win_rate=float(win_rate) if win_rate else None,
        overall_pass=overall_pass,
    )

    return report


def get_threshold_status(metric_name: str, value: Optional[Decimal]) -> Dict[str, Any]:
    """Get threshold status for a specific metric.

    Args:
        metric_name: Name of the metric ('sharpe', 'max_drawdown', 'win_rate')
        value: The calculated metric value

    Returns:
        Dictionary with threshold info and pass/fail status
    """
    thresholds = {
        "sharpe": (SHARPE_THRESHOLD, "ge"),  # >= threshold
        "max_drawdown": (MAX_DRAWDOWN_THRESHOLD, "le"),  # <= threshold
        "win_rate": (WIN_RATE_THRESHOLD, "ge"),  # >= threshold
    }

    if metric_name not in thresholds or value is None:
        return {"value": None, "threshold": None, "pass": False}

    threshold, comparison = thresholds[metric_name]

    if comparison == "ge":
        passed = value >= threshold
    else:
        passed = value <= threshold

    return {
        "value": float(value),
        "threshold": float(threshold),
        "pass": passed,
    }
