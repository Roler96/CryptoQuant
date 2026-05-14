"""Funding rate arbitrage strategy.

Implements cash-and-carry arbitrage: spot long + perpetual short to
collect funding rate payments with minimal directional risk.

For backtesting, funding rates are simulated from price dynamics.
In production, actual funding rate history would be fetched from OKX.
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import structlog

logger = structlog.get_logger(__name__)


@dataclass
class FundingRateConfig:
    """Configuration for funding rate arbitrage."""

    min_funding_rate: float = 0.0001  # 0.01% per 8h = minimum to open position
    position_size_pct: float = 0.95  # Use 95% of cash per position
    close_threshold: float = 0.00005  # Close when funding drops below 0.005%
    max_hold_periods: int = 168  # Max hold 168 periods (7 days for 1h)
    rebalance_threshold: float = 0.02  # Rebalance when drift exceeds 2%


class FundingRateSimulator:
    """Simulates historical funding rates for backtesting.

    In production, actual funding rate history can be fetched from OKX.
    This simulator creates synthetic funding rates based on price dynamics
    to enable backtesting without historical funding rate data.

    Simulation logic:
    - Funding rate correlates with market sentiment (price momentum)
    - When prices rise, funding tends positive (longs pay shorts)
    - When prices fall, funding tends negative (shorts pay longs)
    - Add random noise for realism
    """

    def __init__(self, volatility_scale: float = 0.0002):
        """Initialize simulator.

        Args:
            volatility_scale: Base funding rate volatility
        """
        self.volatility_scale = volatility_scale

    def simulate_funding_rates(
        self,
        returns: pd.Series,
        timestamp: int,
    ) -> pd.Series:
        """Simulate funding rates from returns.

        Args:
            returns: Historical returns series
            timestamp: Current timestamp

        Returns:
            Simulated funding rate for each asset
        """
        if returns.empty:
            return pd.Series(0.0, index=returns.index)

        # Use recent momentum as proxy for market sentiment
        recent_returns = returns.iloc[-24:] if len(returns) >= 24 else returns
        mean_return = recent_returns.mean()

        # Funding rate ~ momentum * scale + noise
        # Positive momentum -> positive funding (longs pay shorts)
        base_funding = mean_return * self.volatility_scale * 100

        # Add random noise
        noise = np.random.normal(0, self.volatility_scale, len(returns))
        funding_rates = base_funding + noise

        return pd.Series(funding_rates, index=returns.index)

    def simulate_funding_history(
        self,
        returns: pd.DataFrame,
    ) -> pd.DataFrame:
        """Simulate funding rate history for entire backtest period.

        Args:
            returns: Historical returns (timestamp by pair)

        Returns:
            DataFrame of simulated funding rates (timestamp by pair)
        """
        funding_history = pd.DataFrame(index=returns.index, columns=returns.columns)

        for ts in returns.index:
            funding_history.loc[ts] = self.simulate_funding_rates(
                returns.loc[ts],
                int(ts),
            )

        return funding_history.fillna(0)


class FundingRateArbitragePosition:
    """Tracks a funding rate arbitrage position.

    For each pair:
    - Spot position (long)
    - Perpetual position (short)
    - Funding collected
    - P&L tracking
    """

    def __init__(self, pair: str, entry_spot_price: float, entry_perp_price: float, size: float, entry_time: int):
        """Initialize position tracker.

        Args:
            pair: Trading pair
            entry_spot_price: Spot price at entry
            entry_perp_price: Perpetual price at entry
            size: Position size (in base currency)
            entry_time: Entry timestamp
        """
        self.pair = pair
        self.entry_spot_price = entry_spot_price
        self.entry_perp_price = entry_perp_price
        self.size = size
        self.entry_time = entry_time

        self.funding_collected = 0.0
        self.hold_periods = 0

    def update(
        self,
        current_spot_price: float,
        current_perp_price: float,
        funding_rate: float,
    ) -> Tuple[float, float]:
        """Update position with current prices and funding.

        Args:
            current_spot_price: Current spot price
            current_perp_price: Current perpetual price
            funding_rate: Current funding rate (per period)

        Returns:
            Tuple of (unrealized_pnl, funding_collected_this_period)
        """
        # Spot P&L = size * (current_spot - entry_spot)
        spot_pnl = self.size * (current_spot_price - self.entry_spot_price)

        # Perp P&L = size * (entry_perp - current_perp) (short position)
        perp_pnl = self.size * (self.entry_perp_price - current_perp_price)

        # Total price P&L
        price_pnl = spot_pnl + perp_pnl

        # Funding collected (short receives when funding positive)
        funding_this_period = self.size * current_perp_price * funding_rate
        self.funding_collected += funding_this_period

        self.hold_periods += 1

        # Total unrealized P&L
        unrealized_pnl = price_pnl + self.funding_collected

        return unrealized_pnl, funding_this_period

    def close(
        self,
        close_spot_price: float,
        close_perp_price: float,
        close_time: int,
    ) -> Dict[str, Any]:
        """Close position and calculate final P&L.

        Args:
            close_spot_price: Spot price at close
            close_perp_price: Perpetual price at close
            close_time: Close timestamp

        Returns:
            Dict with final P&L breakdown
        """
        # Final price P&L
        spot_pnl = self.size * (close_spot_price - self.entry_spot_price)
        perp_pnl = self.size * (self.entry_perp_price - close_perp_price)

        # Basis change (entry basis - close basis)
        entry_basis = self.entry_perp_price - self.entry_spot_price
        close_basis = close_perp_price - close_spot_price
        basis_pnl = self.size * (entry_basis - close_basis)

        return {
            "pair": self.pair,
            "entry_time": self.entry_time,
            "close_time": close_time,
            "hold_periods": self.hold_periods,
            "spot_pnl": spot_pnl,
            "perp_pnl": perp_pnl,
            "basis_pnl": basis_pnl,
            "funding_collected": self.funding_collected,
            "total_pnl": spot_pnl + perp_pnl + self.funding_collected,
            "entry_spot": self.entry_spot_price,
            "close_spot": close_spot_price,
            "entry_perp": self.entry_perp_price,
            "close_perp": close_perp_price,
        }


class FundingRateArbitrageStrategy:
    """Funding rate arbitrage strategy.

    For backtesting without real funding rate data, we simulate funding rates.
    The strategy logic:
    1. Identify pairs with high funding rates
    2. Open cash-and-carry position (spot long + perp short)
    3. Collect funding payments
    4. Close when funding rate drops or max hold reached

    Note: This is a single-asset strategy for simplicity.
    Multi-asset version would rank by funding rate and allocate capital.
    """

    def __init__(
        self,
        name: str = "funding_rate_arb",
        params: Optional[Dict[str, Any]] = None,
    ):
        """Initialize strategy.

        Args:
            name: Strategy name
            params: Strategy parameters
        """
        self.name = name
        self.params = params or {}

        self.config = FundingRateConfig(
            min_funding_rate=self.get_param("min_funding_rate", 0.0001),
            position_size_pct=self.get_param("position_size_pct", 0.95),
            close_threshold=self.get_param("close_threshold", 0.00005),
            max_hold_periods=self.get_param("max_hold_periods", 168),
        )

        self.funding_simulator = FundingRateSimulator()
        self.logger = structlog.get_logger(__name__).bind(strategy=name)

    def get_param(self, key: str, default: Any = None) -> Any:
        """Get parameter value."""
        return self.params.get(key, default)

    def backtest_single_pair(
        self,
        pair: str,
        spot_prices: pd.Series,
        timeframe: str = "1h",
        start_cash: float = 100000.0,
    ) -> Dict[str, Any]:
        """Backtest funding rate arbitrage on a single pair.

        Args:
            pair: Trading pair
            spot_prices: Historical spot prices
            timeframe: Candle timeframe
            start_cash: Initial capital

        Returns:
            Backtest result dict
        """
        if spot_prices.empty:
            return {"error": "No price data", "pair": pair}

        # Simulate perpetual prices (spot + basis)
        # Basis is typically small positive (contango) in bull markets
        basis_pct = 0.001  # 0.1% basis
        perp_prices = spot_prices * (1 + basis_pct + np.random.normal(0, 0.0005, len(spot_prices)))

        # Simulate funding rates
        returns = spot_prices.pct_change()
        funding_rates = self.funding_simulator.simulate_funding_history(
            pd.DataFrame({pair: returns})
        )[pair]

        # Initialize state
        cash = start_cash
        position: Optional[FundingRateArbitragePosition] = None
        equity_curve: List[float] = []
        trades: List[Dict[str, Any]] = []

        for i, ts in enumerate(spot_prices.index):
            spot_price = spot_prices.loc[ts]
            perp_price = perp_prices.iloc[i] if i < len(perp_prices) else spot_price * 1.001
            funding_rate = funding_rates.iloc[i] if i < len(funding_rates) else 0

            # Check if we should open position
            if position is None:
                if abs(funding_rate) >= self.config.min_funding_rate:
                    # Open cash-and-carry
                    # If funding positive: short perp (receive funding)
                    # If funding negative: long perp (receive funding)

                    size = (cash * self.config.position_size_pct) / spot_price
                    position = FundingRateArbitragePosition(
                        pair=pair,
                        entry_spot_price=float(spot_price),
                        entry_perp_price=float(perp_price),
                        size=size,
                        entry_time=int(ts),
                    )
                    cash -= size * spot_price  # Deduct spot purchase cost

                    self.logger.debug(
                        "position_opened",
                        pair=pair,
                        spot_price=float(spot_price),
                        perp_price=float(perp_price),
                        funding_rate=funding_rate,
                    )

            else:
                # Update existing position
                unrealized_pnl, funding_this_period = position.update(
                    float(spot_price),
                    float(perp_price),
                    funding_rate,
                )

                # Check close conditions
                should_close = False
                close_reason = ""

                # 1. Funding rate dropped
                if abs(funding_rate) < self.config.close_threshold:
                    should_close = True
                    close_reason = "funding_dropped"

                # 2. Max hold reached
                if position.hold_periods >= self.config.max_hold_periods:
                    should_close = True
                    close_reason = "max_hold"

                # 3. Negative total P&L
                if unrealized_pnl < -cash * 0.05:  # 5% loss threshold
                    should_close = True
                    close_reason = "stop_loss"

                if should_close:
                    trade_result = position.close(
                        float(spot_price),
                        float(perp_price),
                        int(ts),
                    )
                    trade_result["close_reason"] = close_reason
                    trades.append(trade_result)

                    # Return capital + P&L
                    cash += position.size * spot_price + trade_result["total_pnl"]
                    position = None

            # Record equity
            if position:
                unrealized, _ = position.update(float(spot_price), float(perp_price), funding_rate)
                equity = cash + position.size * spot_price + unrealized
            else:
                equity = cash
            equity_curve.append(equity)

        # Final result
        final_equity = equity_curve[-1] if equity_curve else start_cash
        total_return = (final_equity - start_cash) / start_cash

        # Calculate metrics
        equity_decimals = [Decimal(str(v)) for v in equity_curve]
        from backtest.metrics import calculate_sharpe_ratio, calculate_max_drawdown

        sharpe = calculate_sharpe_ratio(equity_decimals)
        max_dd = calculate_max_drawdown(equity_decimals)

        return {
            "pair": pair,
            "timeframe": timeframe,
            "initial_value": start_cash,
            "final_value": final_equity,
            "total_return": total_return,
            "sharpe_ratio": float(sharpe) if sharpe else None,
            "max_drawdown": float(max_dd) if max_dd else None,
            "total_trades": len(trades),
            "total_funding_collected": sum(t.get("funding_collected", 0) for t in trades),
            "equity_curve": equity_curve,
            "trades": trades,
        }

    def backtest_multi_pair(
        self,
        pairs: List[str],
        prices_df: pd.DataFrame,
        timeframe: str = "1h",
        start_cash: float = 100000.0,
        allocation_per_pair: float = 0.1,  # 10% per pair
    ) -> Dict[str, Any]:
        """Backtest funding rate arbitrage across multiple pairs.

        Allocates equal capital to each pair, runs individual backtests,
        then aggregates results.

        Args:
            pairs: List of pairs
            prices_df: Price DataFrame (timestamp by pair)
            timeframe: Candle timeframe
            start_cash: Total capital
            allocation_per_pair: Capital allocation per pair

        Returns:
            Aggregated backtest results
        """
        per_pair_cash = start_cash * allocation_per_pair
        all_results: List[Dict[str, Any]] = []

        for pair in pairs:
            if pair not in prices_df.columns:
                continue

            spot_prices = prices_df[pair]
            result = self.backtest_single_pair(
                pair=pair,
                spot_prices=spot_prices,
                timeframe=timeframe,
                start_cash=per_pair_cash,
            )
            all_results.append(result)

        # Aggregate equity curve
        if not all_results:
            return {"error": "No valid pairs", "pairs": pairs}

        # Combine equity curves by timestamp
        # Simple approach: sum individual equities
        total_equity = sum(r.get("final_value", per_pair_cash) for r in all_results)
        total_return = (total_equity - start_cash) / start_cash

        return {
            "pairs": pairs,
            "strategy": self.name,
            "initial_value": start_cash,
            "final_value": total_equity,
            "total_return": total_return,
            "individual_results": all_results,
            "total_funding_collected": sum(r.get("total_funding_collected", 0) for r in all_results),
            "successful_pairs": len([r for r in all_results if "error" not in r]),
        }