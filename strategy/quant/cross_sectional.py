"""Cross-sectional multi-factor strategy.

Implements a market-neutral portfolio that ranks assets by multiple factors:
- Momentum (past N days return)
- Carry (funding rate, simulated for backtest)
- Size (inverse market cap, small-cap premium)
- Volatility (inverse, low-vol anomaly)

Based on Unravel Finance research: 2+ Sharpe ratio without overfitting.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional

import numpy as np
import pandas as pd
import structlog

from backtest.multi_asset.engine import CrossSectionalStrategy

logger = structlog.get_logger(__name__)


@dataclass
class FactorWeights:
    """Weights for each factor in composite score."""

    momentum: float = 0.35
    carry: float = 0.25
    size: float = 0.20
    low_vol: float = 0.20


class CrossSectionalMultiFactorStrategy(CrossSectionalStrategy):
    """Cross-sectional multi-factor strategy.

    Generates factor scores for each asset based on:
    1. Momentum: N-day cumulative return
    2. Carry: Funding rate (simulated from returns for backtest)
    3. Size: Inverse of price (proxy for market cap rank)
    4. Low Volatility: Inverse of realized volatility

    Assets are ranked by composite factor score:
    - Top N = Long
    - Bottom N = Short
    """

    def __init__(
        self,
        name: str = "cross_sectional_multifactor",
        params: Optional[Dict[str, Any]] = None,
    ):
        """Initialize strategy.

        Args:
            name: Strategy name
            params: Strategy parameters
                - momentum_period: Lookback period for momentum (default 30)
                - vol_period: Lookback for volatility (default 30)
                - factor_weights: FactorWeights or dict of weights
        """
        super().__init__(name, params)

        self.momentum_period = self.get_param("momentum_period", 30)
        self.vol_period = self.get_param("vol_period", 30)
        self.size_proxy_decay = self.get_param("size_proxy_decay", 0.01)

        # Factor weights
        weights_dict = self.get_param("factor_weights", {})
        if isinstance(weights_dict, FactorWeights):
            self.weights = weights_dict
        else:
            self.weights = FactorWeights(
                momentum=weights_dict.get("momentum", 0.35),
                carry=weights_dict.get("carry", 0.25),
                size=weights_dict.get("size", 0.20),
                low_vol=weights_dict.get("low_vol", 0.20),
            )

        self.logger.info(
            "strategy_initialized",
            momentum_period=self.momentum_period,
            vol_period=self.vol_period,
            weights={
                "momentum": self.weights.momentum,
                "carry": self.weights.carry,
                "size": self.weights.size,
                "low_vol": self.weights.low_vol,
            },
        )

    def compute_scores(
        self,
        prices: pd.DataFrame,
        returns: pd.DataFrame,
        timestamp: int,
    ) -> pd.Series:
        """Compute composite factor scores for each asset.

        Args:
            prices: Historical close prices (timestamp by pair)
            returns: Historical returns (timestamp by pair)
            timestamp: Current timestamp

        Returns:
            Series of composite factor scores indexed by pair
        """
        if prices.empty or len(prices) < max(self.momentum_period, self.vol_period):
            return pd.Series(dtype=float)

        # Get last N days of data
        recent_prices = prices.iloc[-max(self.momentum_period, self.vol_period) * 24 :]  # Assuming hourly
        recent_returns = returns.iloc[-max(self.momentum_period, self.vol_period) * 24 :]

        # Compute individual factor scores
        momentum_scores = self._compute_momentum(recent_prices)
        carry_scores = self._compute_carry(recent_returns)  # Simulated carry
        size_scores = self._compute_size(recent_prices)
        vol_scores = self._compute_volatility(recent_returns)

        # Normalize scores to z-scores (cross-sectional ranking)
        def zscore(s: pd.Series) -> pd.Series:
            if s.std() == 0 or s.empty:
                return pd.Series(0, index=s.index)
            return (s - s.mean()) / s.std()

        momentum_z = zscore(momentum_scores)
        carry_z = zscore(carry_scores)
        size_z = zscore(size_scores)
        vol_z = zscore(vol_scores)

        # Composite score = weighted sum
        composite = (
            self.weights.momentum * momentum_z
            + self.weights.carry * carry_z
            + self.weights.size * size_z
            + self.weights.low_vol * vol_z
        )

        # Remove NaN values
        composite = composite.dropna()

        self.logger.debug(
            "scores_computed",
            timestamp=timestamp,
            n_assets=len(composite),
            momentum_top=momentum_scores.idxmax() if not momentum_scores.empty else None,
            composite_top=composite.idxmax() if not composite.empty else None,
        )

        return composite

    def _compute_momentum(self, prices: pd.DataFrame) -> pd.Series:
        """Compute momentum scores (cumulative return over period).

        Args:
            prices: Historical prices

        Returns:
            Series of momentum scores (higher = stronger momentum)
        """
        if len(prices) < self.momentum_period:
            return pd.Series(dtype=float)

        # Cumulative return over momentum period
        # Use last price / price N periods ago
        recent = prices.iloc[-self.momentum_period :]
        start_prices = recent.iloc[0]
        end_prices = recent.iloc[-1]

        momentum = (end_prices / start_prices - 1) * 100  # Percentage return

        return momentum

    def _compute_carry(self, returns: pd.DataFrame) -> pd.Series:
        """Compute carry scores (simulated from returns for backtest).

        In production, this would use actual funding rates.
        For backtest simulation, we approximate carry as:
        - Negative mean return (assets that tend to drop have positive carry when short)
        - This is a simplified proxy

        Args:
            returns: Historical returns

        Returns:
            Series of carry scores (higher = better carry when long)
        """
        if len(returns) < 10:
            return pd.Series(dtype=float)

        # Use negative mean return as proxy for carry
        # Assets that trend downward (negative mean return) have positive carry when shorted
        # We flip this: positive carry_score = good to long
        mean_return = returns.iloc[-30:].mean()

        # In reality, carry = funding rate = payment from longs to shorts
        # When funding rate positive, shorts receive payment
        # So carry_score should be inverse of funding rate for long position

        # Simulate: if mean return positive, assume funding rate negative (shorts receive)
        # carry_score = -mean_return (so positive mean return -> negative carry for longs)
        carry = -mean_return * 100

        return carry

    def _compute_size(self, prices: pd.DataFrame) -> pd.Series:
        """Compute size scores (inverse price as market cap proxy).

        Lower price ≈ lower market cap ≈ small-cap premium.

        Args:
            prices: Historical prices

        Returns:
            Series of size scores (higher = smaller asset)
        """
        if prices.empty:
            return pd.Series(dtype=float)

        last_prices = prices.iloc[-1]

        # Inverse price as size proxy (normalized)
        # Higher score = smaller asset
        size_score = -np.log(last_prices + 1)  # Negative log-price

        return size_score

    def _compute_volatility(self, returns: pd.DataFrame) -> pd.Series:
        """Compute volatility scores (inverse, low-vol anomaly).

        Low volatility assets tend to outperform (low-vol anomaly).
        Higher score = lower volatility.

        Args:
            returns: Historical returns

        Returns:
            Series of volatility scores (higher = lower volatility)
        """
        if len(returns) < self.vol_period:
            return pd.Series(dtype=float)

        # Realized volatility (std of returns)
        vol = returns.iloc[-self.vol_period:].std()

        # Inverse: higher score = lower volatility
        vol_score = -vol * 100

        return vol_score


class MomentumOnlyStrategy(CrossSectionalStrategy):
    """Simple cross-sectional momentum strategy.

    Single-factor version: rank by past N-day returns,
    long top decile, short bottom decile.
    """

    def __init__(
        self,
        name: str = "momentum_only",
        params: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(name, params)
        self.lookback = self.get_param("lookback", 30)

    def compute_scores(
        self,
        prices: pd.DataFrame,
        returns: pd.DataFrame,
        timestamp: int,
    ) -> pd.Series:
        if len(prices) < self.lookback:
            return pd.Series(dtype=float)

        recent = prices.iloc[-self.lookback:]
        momentum = (recent.iloc[-1] / recent.iloc[0] - 1) * 100

        return momentum.dropna()


class CarryOnlyStrategy(CrossSectionalStrategy):
    """Simple carry strategy.

    Rank by funding rate (simulated), long assets with negative funding
    (receiving payment), short assets with positive funding (paying).
    """

    def __init__(
        self,
        name: str = "carry_only",
        params: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(name, params)
        self.lookback = self.get_param("lookback", 30)

    def compute_scores(
        self,
        prices: pd.DataFrame,
        returns: pd.DataFrame,
        timestamp: int,
    ) -> pd.Series:
        if len(returns) < self.lookback:
            return pd.Series(dtype=float)

        # Simulated carry = negative mean return
        carry = -returns.iloc[-self.lookback:].mean() * 100

        return carry.dropna()