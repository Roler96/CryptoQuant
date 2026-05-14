"""Multi-asset vectorized backtest engine.

Provides fast backtesting for cross-sectional strategies using pandas/numpy
vectorization, avoiding the overhead of event-driven backtest frameworks.

Features:
- Market-neutral portfolio backtesting
- Cross-sectional factor ranking
- Position rebalancing simulation
- Performance metrics calculation
"""

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import structlog

from backtest.multi_asset.data_loader import MultiAssetDataLoader
from backtest.metrics import (
    calculate_sharpe_ratio,
    calculate_max_drawdown,
    calculate_win_rate,
    calculate_profit_factor,
    calculate_annualized_return,
    calculate_calmar_ratio,
)

logger = structlog.get_logger(__name__)


@dataclass
class MultiAssetBacktestConfig:
    """Configuration for multi-asset backtest."""

    initial_cash: float = 100000.0
    commission: float = 0.0005  # 0.05% per trade (OKX futures rate)
    slippage: float = 0.0002  # 0.02% execution slippage
    gross_exposure: float = 2.0  # Target gross exposure (e.g., 2.0 = 100% long + 100% short)
    rebalance_frequency: str = "1d"  # Rebalance daily by default
    position_concentration_limit: float = 0.15  # Max 15% per position
    min_position_size: float = 0.01  # Min 1% position


@dataclass
class MultiAssetBacktestResult:
    """Result of a multi-asset backtest."""

    strategy_name: str
    pairs: List[str]
    timeframe: str
    start_date: str
    end_date: str
    initial_value: float
    final_value: float
    total_return: float
    annualized_return: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    max_drawdown: Optional[float] = None
    calmar_ratio: Optional[float] = None
    equity_curve: List[float] = field(default_factory=list)
    equity_timestamps: List[int] = field(default_factory=list)
    positions_history: List[Dict[str, Any]] = field(default_factory=list)
    trades: List[Dict[str, Any]] = field(default_factory=list)
    daily_returns: List[float] = field(default_factory=list)
    turnover: float = 0.0  # Total turnover (sum of position changes / avg equity)
    long_exposure_avg: float = 0.0
    short_exposure_avg: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary."""
        return {
            "strategy_name": self.strategy_name,
            "pairs": self.pairs,
            "timeframe": self.timeframe,
            "start_date": self.start_date,
            "end_date": self.end_date,
            "initial_value": self.initial_value,
            "final_value": self.final_value,
            "total_return": self.total_return,
            "annualized_return": self.annualized_return,
            "sharpe_ratio": self.sharpe_ratio,
            "max_drawdown": self.max_drawdown,
            "calmar_ratio": self.calmar_ratio,
            "total_trades": len(self.trades),
            "turnover": self.turnover,
            "long_exposure_avg": self.long_exposure_avg,
            "short_exposure_avg": self.short_exposure_avg,
        }


class MultiAssetBacktestEngine:
    """Vectorized multi-asset backtest engine.

    Implements fast backtesting for market-neutral cross-sectional strategies:
    1. Load price data for all pairs
    2. Compute factor scores at each rebalance point
    3. Rank assets and allocate positions
    4. Simulate P&L and track equity curve
    """

    def __init__(self, config: Optional[MultiAssetBacktestConfig] = None):
        """Initialize engine.

        Args:
            config: Backtest configuration (uses defaults if None)
        """
        self.config = config or MultiAssetBacktestConfig()
        self.data_loader = MultiAssetDataLoader()
        self.logger = structlog.get_logger(__name__)

    def run_backtest(
        self,
        strategy: "CrossSectionalStrategy",
        pairs: List[str],
        timeframe: str,
        start_date: str,
        end_date: str,
    ) -> MultiAssetBacktestResult:
        """Run cross-sectional strategy backtest.

        Args:
            strategy: Cross-sectional strategy instance
            pairs: List of trading pairs
            timeframe: Candle timeframe
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)

        Returns:
            MultiAssetBacktestResult with all metrics
        """
        self.logger.info(
            "starting_multi_asset_backtest",
            strategy=strategy.name,
            pairs=len(pairs),
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date,
        )

        # Load price data
        close_prices = self.data_loader.get_close_prices(
            pairs, timeframe, start_date, end_date
        )

        if close_prices.empty:
            return MultiAssetBacktestResult(
                strategy_name=strategy.name,
                pairs=pairs,
                timeframe=timeframe,
                start_date=start_date,
                end_date=end_date,
                initial_value=self.config.initial_cash,
                final_value=self.config.initial_cash,
                total_return=0.0,
                error="No price data available",
            )

        # Calculate returns
        returns = close_prices.pct_change()

        # Get rebalance timestamps
        rebalance_ts = self._get_rebalance_timestamps(
            close_prices.index, self.config.rebalance_frequency
        )

        # Initialize state
        cash = self.config.initial_cash
        positions: Dict[str, float] = {}  # pair -> weight (positive for long, negative for short)
        equity_curve: List[float] = []
        equity_timestamps: List[int] = []
        trades: List[Dict[str, Any]] = []
        positions_history: List[Dict[str, Any]] = []
        daily_portfolio_returns: List[float] = []

        # Track for exposure stats
        long_exposures: List[float] = []
        short_exposures: List[float] = []

        prev_ts = None

        # Iterate through each timestamp
        for ts in close_prices.index:
            ts_int = int(ts)

            # Get returns for this period
            if prev_ts is not None:
                period_returns = returns.loc[ts] if ts in returns.index else pd.Series(0, index=close_prices.columns)

                # Calculate portfolio P&L from positions
                portfolio_return = 0.0
                for pair, weight in positions.items():
                    if pair in period_returns.index and not pd.isna(period_returns[pair]):
                        # Return contribution = weight * period_return
                        portfolio_return += weight * period_returns[pair]

                # Update cash
                cash *= (1 + portfolio_return)
                daily_portfolio_returns.append(portfolio_return)

            # Check if we need to rebalance
            if ts_int in rebalance_ts:
                # Get factor scores from strategy
                factor_scores = strategy.compute_scores(
                    close_prices.loc[:ts],
                    returns.loc[:ts],
                    timestamp=ts_int,
                )

                # Compute target positions
                target_positions = self._allocate_positions(
                    factor_scores,
                    positions,
                    cash,
                )

                # Execute trades and update positions
                trades_executed = self._execute_rebalance(
                    positions,
                    target_positions,
                    cash,
                    close_prices.loc[ts],
                    ts_int,
                )
                trades.extend(trades_executed)

                # Record positions snapshot
                positions_history.append({
                    "timestamp": ts_int,
                    "positions": dict(positions),
                    "cash": cash,
                })

                # Track exposures
                long_exp = sum(w for w in positions.values() if w > 0)
                short_exp = abs(sum(w for w in positions.values() if w < 0))
                long_exposures.append(long_exp)
                short_exposures.append(short_exp)

            # Record equity
            equity = cash + self._calculate_position_value(positions, close_prices.loc[ts])
            equity_curve.append(equity)
            equity_timestamps.append(ts_int)

            prev_ts = ts

        # Calculate metrics
        final_equity = equity_curve[-1] if equity_curve else self.config.initial_cash
        total_return = (final_equity - self.config.initial_cash) / self.config.initial_cash

        equity_decimals = [Decimal(str(v)) for v in equity_curve]
        sharpe = calculate_sharpe_ratio(equity_decimals)
        max_dd = calculate_max_drawdown(equity_decimals)
        ann_return = calculate_annualized_return(equity_decimals)
        calmar = calculate_calmar_ratio(equity_decimals, max_dd)

        # Calculate turnover
        avg_equity = np.mean(equity_curve)
        total_position_changes = sum(
            abs(t.get("position_change", 0)) for t in trades
        )
        turnover = total_position_changes / avg_equity if avg_equity > 0 else 0

        result = MultiAssetBacktestResult(
            strategy_name=strategy.name,
            pairs=pairs,
            timeframe=timeframe,
            start_date=start_date,
            end_date=end_date,
            initial_value=self.config.initial_cash,
            final_value=final_equity,
            total_return=total_return,
            annualized_return=float(ann_return) if ann_return else None,
            sharpe_ratio=float(sharpe) if sharpe else None,
            max_drawdown=float(max_dd) if max_dd else None,
            calmar_ratio=float(calmar) if calmar else None,
            equity_curve=equity_curve,
            equity_timestamps=equity_timestamps,
            positions_history=positions_history,
            trades=trades,
            daily_returns=daily_portfolio_returns,
            turnover=turnover,
            long_exposure_avg=np.mean(long_exposures) if long_exposures else 0,
            short_exposure_avg=np.mean(short_exposures) if short_exposures else 0,
        )

        self.logger.info(
            "multi_asset_backtest_completed",
            strategy=strategy.name,
            total_return=total_return,
            sharpe=float(sharpe) if sharpe else None,
            max_drawdown=float(max_dd) if max_dd else None,
            trades=len(trades),
        )

        return result

    def _get_rebalance_timestamps(
        self,
        timestamps: pd.Index,
        frequency: str,
    ) -> set:
        """Get timestamps where rebalancing should occur.

        Args:
            timestamps: All timestamps in the data
            frequency: Rebalance frequency ("1d", "1w", "1h")

        Returns:
            Set of timestamps where rebalancing should happen
        """
        ts_series = pd.Series(timestamps)
        ts_series.index = timestamps

        if frequency == "1d":
            # Rebalance at the start of each day
            dates = ts_series.apply(lambda x: datetime.fromtimestamp(x / 1000).date())
            first_ts_per_day = ts_series.groupby(dates).first()
            return set(first_ts_per_day.values)
        elif frequency == "1w":
            # Rebalance at the start of each week
            weeks = ts_series.apply(lambda x: datetime.fromtimestamp(x / 1000).isocalendar()[1])
            first_ts_per_week = ts_series.groupby(weeks).first()
            return set(first_ts_per_week.values)
        else:
            # Default: every timestamp
            return set(timestamps)

    def _allocate_positions(
        self,
        factor_scores: pd.Series,
        current_positions: Dict[str, float],
        cash: float,
    ) -> Dict[str, float]:
        """Allocate positions based on factor scores.

        Args:
            factor_scores: Series of factor scores per pair
            current_positions: Current position weights
            cash: Current cash value

        Returns:
            Target position weights (positive for long, negative for short)
        """
        if factor_scores.empty:
            return {}

        # Sort by factor score
        sorted_scores = factor_scores.sort_values(ascending=False)

        # Determine number of positions
        n_assets = len(sorted_scores)
        n_positions = max(1, int(n_assets * 0.4))  # Top/bottom 40%

        # Long top N, short bottom N
        longs = sorted_scores.head(n_positions).index.tolist()
        shorts = sorted_scores.tail(n_positions).index.tolist()

        # Equal-weight allocation
        long_weight = self.config.gross_exposure / 2 / len(longs)
        short_weight = -self.config.gross_exposure / 2 / len(shorts)

        # Apply concentration limits
        long_weight = min(long_weight, self.config.position_concentration_limit)
        short_weight = max(short_weight, -self.config.position_concentration_limit)

        # Build target positions
        target_positions: Dict[str, float] = {}
        for pair in longs:
            target_positions[pair] = long_weight
        for pair in shorts:
            target_positions[pair] = short_weight

        return target_positions

    def _execute_rebalance(
        self,
        current_positions: Dict[str, float],
        target_positions: Dict[str, float],
        cash: float,
        prices: pd.Series,
        timestamp: int,
    ) -> List[Dict[str, Any]]:
        """Execute rebalancing trades.

        Args:
            current_positions: Current position weights
            target_positions: Target position weights
            cash: Current cash
            prices: Current prices for all pairs
            timestamp: Current timestamp

        Returns:
            List of executed trades
        """
        trades: List[Dict[str, Any]] = []

        # Calculate position changes
        all_pairs = set(current_positions.keys()) | set(target_positions.keys())

        for pair in all_pairs:
            current_weight = current_positions.get(pair, 0.0)
            target_weight = target_positions.get(pair, 0.0)

            if abs(target_weight - current_weight) < self.config.min_position_size:
                continue  # Skip small position changes

            # Simulate trade execution with slippage
            if pair not in prices.index or pd.isna(prices[pair]):
                continue

            price = prices[pair]
            slippage_adj = price * self.config.slippage

            if target_weight > current_weight:
                # Increase position (buy)
                exec_price = price + slippage_adj
                trade_type = "buy"
            else:
                # Decrease position (sell)
                exec_price = price - slippage_adj
                trade_type = "sell"

            position_change = target_weight - current_weight
            commission_cost = abs(position_change) * cash * self.config.commission

            trade = {
                "timestamp": timestamp,
                "pair": pair,
                "type": trade_type,
                "position_change": position_change,
                "price": float(exec_price),
                "commission": commission_cost,
            }
            trades.append(trade)

            # Update current positions
            current_positions[pair] = target_weight

        return trades

    def _calculate_position_value(
        self,
        positions: Dict[str, float],
        prices: pd.Series,
    ) -> float:
        """Calculate total value of positions.

        For market-neutral strategies, position value is approximated by
        cash exposure rather than actual asset holdings.

        Args:
            positions: Position weights
            prices: Current prices

        Returns:
            Approximate position value (cash exposure)
        """
        # For market-neutral, positions are weights on cash
        # Value = cash * sum of position weights (zero for market-neutral)
        return 0  # Market-neutral portfolio value tracked in cash only


class CrossSectionalStrategy:
    """Base class for cross-sectional strategies.

    Cross-sectional strategies rank assets by factor scores and
    allocate long/short positions based on relative rankings.
    """

    def __init__(self, name: str, params: Optional[Dict[str, Any]] = None):
        """Initialize strategy.

        Args:
            name: Strategy name
            params: Strategy parameters
        """
        self.name = name
        self.params = params or {}
        self.logger = structlog.get_logger(__name__).bind(strategy=name)

    def compute_scores(
        self,
        prices: pd.DataFrame,
        returns: pd.DataFrame,
        timestamp: int,
    ) -> pd.Series:
        """Compute factor scores for each asset.

        Higher scores = better (will be longed).
        Lower scores = worse (will be shorted).

        Args:
            prices: Historical close prices (timestamp by pair)
            returns: Historical returns (timestamp by pair)
            timestamp: Current timestamp

        Returns:
            Series of factor scores indexed by pair
        """
        raise NotImplementedError("Subclasses must implement compute_scores()")

    def get_param(self, key: str, default: Any = None) -> Any:
        """Get parameter value."""
        return self.params.get(key, default)