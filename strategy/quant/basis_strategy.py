"""Basis momentum and mean reversion strategy.

Implements two approaches:
1. Basis mean reversion: Trade when basis deviates from normal range
2. Basis momentum: Follow basis expansion/contraction trends

Basis = Perpetual price - Spot price (or Perp - Index price)
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class BasisStrategyConfig:
    """Configuration for basis trading strategy."""

    lookback_period: int = 20  # For Bollinger bands / mean calculation
    entry_threshold: float = 2.0  # Z-score threshold for entry
    exit_threshold: float = 0.5  # Z-score threshold for exit
    max_hold_periods: int = 72  # Max hold 72 hours
    position_size_pct: float = 0.95
    mode: str = "mean_reversion"  # "mean_reversion" or "momentum"


class BasisStrategy:
    """Basis trading strategy.

    Two modes:
    - Mean reversion: When basis is extreme, expect it to revert
    - Momentum: When basis expands, expect it to continue

    For backtesting without real perpetual data, we simulate basis
    as a function of price volatility and market regime.
    """

    def __init__(
        self,
        name: str = "basis_strategy",
        params: Optional[Dict[str, Any]] = None,
    ):
        """Initialize strategy.

        Args:
            name: Strategy name
            params: Strategy parameters
        """
        self.name = name
        self.params = params or {}

        self.config = BasisStrategyConfig(
            lookback_period=self.get_param("lookback_period", 20),
            entry_threshold=self.get_param("entry_threshold", 2.0),
            exit_threshold=self.get_param("exit_threshold", 0.5),
            max_hold_periods=self.get_param("max_hold_periods", 72),
            position_size_pct=self.get_param("position_size_pct", 0.95),
            mode=self.get_param("mode", "mean_reversion"),
        )

        self.logger = structlog.get_logger(__name__).bind(strategy=name)

    def get_param(self, key: str, default: Any = None) -> Any:
        """Get parameter value."""
        return self.params.get(key, default)

    def simulate_basis(
        self,
        prices: pd.Series,
        regime_indicator: Optional[pd.Series] = None,
    ) -> pd.Series:
        """Simulate basis (perp - spot) for backtesting.

        In production, this would use actual perpetual vs spot prices.
        Simulation creates realistic basis dynamics:
        - Basis tends to be positive in bull markets (contango)
        - Basis tends to be negative in bear markets (backwardation)
        - Basis fluctuates around zero with volatility

        Args:
            prices: Spot prices
            regime_indicator: Optional regime signal (positive = bull, negative = bear)

        Returns:
            Series of simulated basis values (percentage)
        """
        # Calculate price momentum as regime proxy
        returns = prices.pct_change()
        momentum = returns.rolling(24).mean()  # 24-period momentum

        # Basis ~ momentum * scale + noise
        base_basis = momentum * 0.01  # Scale momentum to basis

        # Add mean-reverting noise
        noise = np.random.normal(0, 0.002, len(prices))
        basis = base_basis + noise

        # Clamp to realistic range (-2% to +2%)
        basis = np.clip(basis, -0.02, 0.02)

        return pd.Series(basis, index=prices.index)

    def calculate_basis_zscore(
        self,
        basis: pd.Series,
        lookback: int,
    ) -> pd.Series:
        """Calculate z-score of basis.

        Args:
            basis: Historical basis values
            lookback: Lookback period for mean/std calculation

        Returns:
            Series of z-scores
        """
        rolling_mean = basis.rolling(lookback).mean()
        rolling_std = basis.rolling(lookback).std()

        zscore = (basis - rolling_mean) / rolling_std
        return zscore.fillna(0)

    def backtest_single_pair(
        self,
        pair: str,
        spot_prices: pd.Series,
        timeframe: str = "1h",
        start_cash: float = 100000.0,
    ) -> Dict[str, Any]:
        """Backtest basis strategy on a single pair.

        Args:
            pair: Trading pair
            spot_prices: Historical spot prices
            timeframe: Candle timeframe
            start_cash: Initial capital

        Returns:
            Backtest result dict
        """
        if spot_prices.empty or len(spot_prices) < self.config.lookback_period:
            return {"error": "Insufficient data", "pair": pair}

        # Simulate basis
        basis = self.simulate_basis(spot_prices)
        basis_zscore = self.calculate_basis_zscore(basis, self.config.lookback_period)

        # Initialize state
        cash = start_cash
        position: Optional[Dict[str, Any]] = None
        equity_curve: List[float] = []
        trades: List[Dict[str, Any]] = []

        # Simulate perpetual prices
        perp_prices = spot_prices * (1 + basis)

        for i, ts in enumerate(spot_prices.index):
            spot_price = float(spot_prices.loc[ts])
            perp_price = float(perp_prices.iloc[i])
            current_basis = float(basis.iloc[i])
            current_zscore = float(basis_zscore.iloc[i])

            # Determine signal
            signal = self._get_signal(current_zscore, position)

            # Execute signal
            if signal == "open_long_basis":
                # Basis is negative extreme -> expect revert to zero
                # Open: Long perp, Short spot (or just Long perp for simplicity)
                size = (cash * self.config.position_size_pct) / perp_price
                position = {
                    "type": "long_basis",
                    "entry_spot": spot_price,
                    "entry_perp": perp_price,
                    "entry_basis": current_basis,
                    "size": size,
                    "entry_time": int(ts),
                    "hold_periods": 0,
                }
                cash -= size * perp_price

            elif signal == "open_short_basis":
                # Basis is positive extreme -> expect revert to zero
                # Open: Short perp, Long spot
                size = (cash * self.config.position_size_pct) / perp_price
                position = {
                    "type": "short_basis",
                    "entry_spot": spot_price,
                    "entry_perp": perp_price,
                    "entry_basis": current_basis,
                    "size": size,
                    "entry_time": int(ts),
                    "hold_periods": 0,
                }
                cash -= size * spot_price  # Cash used as collateral

            elif signal == "close" and position:
                # Close position
                if position["type"] == "long_basis":
                    pnl = position["size"] * (perp_price - position["entry_perp"])
                    cash += position["size"] * position["entry_perp"] + pnl
                else:  # short_basis
                    pnl = position["size"] * (position["entry_perp"] - perp_price)
                    cash += position["size"] * position["entry_spot"] + pnl

                trades.append({
                    "pair": pair,
                    "type": position["type"],
                    "entry_time": position["entry_time"],
                    "close_time": int(ts),
                    "entry_basis": position["entry_basis"],
                    "close_basis": current_basis,
                    "entry_zscore": float(basis_zscore.iloc[
                        spot_prices.index.get_loc(ts) - position["hold_periods"]
                        if position["hold_periods"] > 0 else i
                    ]),
                    "close_zscore": current_zscore,
                    "pnl": pnl,
                    "hold_periods": position["hold_periods"],
                })
                position = None

            # Update hold periods
            if position:
                position["hold_periods"] += 1

            # Calculate equity
            if position:
                if position["type"] == "long_basis":
                    unrealized = position["size"] * (perp_price - position["entry_perp"])
                else:
                    unrealized = position["size"] * (position["entry_perp"] - perp_price)
                equity = cash + unrealized
            else:
                equity = cash

            equity_curve.append(equity)

        # Close any remaining position
        if position:
            final_spot = float(spot_prices.iloc[-1])
            final_perp = float(perp_prices.iloc[-1])
            if position["type"] == "long_basis":
                pnl = position["size"] * (final_perp - position["entry_perp"])
            else:
                pnl = position["size"] * (position["entry_perp"] - final_perp)
            cash += pnl
            trades.append({
                "pair": pair,
                "type": position["type"],
                "entry_time": position["entry_time"],
                "close_time": int(spot_prices.index[-1]),
                "pnl": pnl,
                "close_reason": "end_of_backtest",
            })

        # Calculate metrics
        final_equity = equity_curve[-1] if equity_curve else start_cash
        total_return = (final_equity - start_cash) / start_cash

        equity_decimals = [Decimal(str(v)) for v in equity_curve]
        from backtest.metrics import calculate_sharpe_ratio, calculate_max_drawdown

        sharpe = calculate_sharpe_ratio(equity_decimals)
        max_dd = calculate_max_drawdown(equity_decimals)

        return {
            "pair": pair,
            "mode": self.config.mode,
            "timeframe": timeframe,
            "initial_value": start_cash,
            "final_value": final_equity,
            "total_return": total_return,
            "sharpe_ratio": float(sharpe) if sharpe else None,
            "max_drawdown": float(max_dd) if max_dd else None,
            "total_trades": len(trades),
            "winning_trades": len([t for t in trades if t.get("pnl", 0) > 0]),
            "equity_curve": equity_curve,
            "trades": trades,
            "basis_stats": {
                "mean": float(basis.mean()),
                "std": float(basis.std()),
                "max": float(basis.max()),
                "min": float(basis.min()),
            },
        }

    def _get_signal(
        self,
        zscore: float,
        position: Optional[Dict[str, Any]],
    ) -> str:
        """Determine trading signal based on z-score.

        Args:
            zscore: Current basis z-score
            position: Current position (if any)

        Returns:
            Signal string: "open_long_basis", "open_short_basis", "close", or "hold"
        """
        if self.config.mode == "mean_reversion":
            # Mean reversion: trade against extremes

            if position is None:
                # Entry signals
                if zscore < -self.config.entry_threshold:
                    return "open_long_basis"  # Basis too negative, expect revert
                elif zscore > self.config.entry_threshold:
                    return "open_short_basis"  # Basis too positive, expect revert

            else:
                # Exit signals
                if abs(zscore) < self.config.exit_threshold:
                    return "close"  # Basis reverted to normal

                if position["hold_periods"] >= self.config.max_hold_periods:
                    return "close"  # Max hold reached

        else:  # momentum mode
            # Momentum: follow basis direction

            if position is None:
                # Entry: follow expanding basis
                if zscore > self.config.entry_threshold:
                    return "open_long_basis"  # Basis expanding upward, continue
                elif zscore < -self.config.entry_threshold:
                    return "open_short_basis"  # Basis expanding downward, continue

            else:
                # Exit: when momentum reverses
                if position["type"] == "long_basis" and zscore < 0:
                    return "close"
                elif position["type"] == "short_basis" and zscore > 0:
                    return "close"

                if position["hold_periods"] >= self.config.max_hold_periods:
                    return "close"

        return "hold"


class BasisMomentumStrategy(BasisStrategy):
    """Basis momentum strategy - follow basis expansion."""

    def __init__(self, params: Optional[Dict[str, Any]] = None):
        super().__init__("basis_momentum", params)
        self.config.mode = "momentum"


class BasisMeanReversionStrategy(BasisStrategy):
    """Basis mean reversion strategy - trade against extremes."""

    def __init__(self, params: Optional[Dict[str, Any]] = None):
        super().__init__("basis_mean_reversion", params)
        self.config.mode = "mean_reversion"