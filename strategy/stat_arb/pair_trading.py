"""Pair Trading Strategy implementation.

A statistical arbitrage strategy that trades pairs of cointegrated assets.
Long the underperformer, short the outperformer when the spread diverges.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import structlog

from data.models import OHLCVCandle
from strategy.base import Signal, SignalType, StrategyBase, StrategyContext

logger = structlog.get_logger(__name__)


@dataclass
class StatArbConfig:
    """Configuration for statistical arbitrage pair trading strategy.

    Attributes:
        pair1: First trading pair symbol (e.g., "BTC/USDT")
        pair2: Second trading pair symbol (e.g., "ETH/USDT")
        lookback_period: Period for calculating mean and std of price ratio
        entry_threshold: Z-score threshold for entry (default 2.0)
        exit_threshold: Z-score threshold for exit (default 0.5)
    """
    pair1: str = "BTC/USDT"
    pair2: str = "ETH/USDT"
    lookback_period: int = 20
    entry_threshold: Decimal = Decimal("2.0")
    exit_threshold: Decimal = Decimal("0.5")


def calculate_cointegration(
    prices1: np.ndarray,
    prices2: np.ndarray,
) -> Tuple[bool, float]:
    """Test for cointegration between two price series.

    Uses Engle-Granger two-step method to test if the spread is stationary.

    Args:
        prices1: Price series for first asset
        prices2: Price series for second asset

    Returns:
        Tuple of (is_cointegrated, test_statistic)
    """
    if len(prices1) < 30 or len(prices2) < 30:
        return False, 0.0

    x = np.column_stack([np.ones(len(prices2)), prices2])
    y = prices1

    try:
        beta = np.linalg.lstsq(x, y, rcond=None)[0]
        residuals = y - x @ beta

        spread_diff = np.diff(residuals)
        spread_lag = residuals[:-1]

        if np.std(spread_lag) == 0:
            return False, 0.0

        x_adf = np.column_stack([np.ones(len(spread_lag)), spread_lag])
        y_adf = spread_diff

        beta_adf = np.linalg.lstsq(x_adf, y_adf, rcond=None)[0]
        test_stat = beta_adf[1]

        critical_value = -0.05
        is_cointegrated = test_stat < critical_value

        return is_cointegrated, float(test_stat)

    except Exception:
        return False, 0.0


def calculate_hedge_ratio(
    prices1: np.ndarray,
    prices2: np.ndarray,
) -> float:
    """Calculate hedge ratio using OLS regression.

    Args:
        prices1: Price series for first asset (dependent variable)
        prices2: Price series for second asset (independent variable)

    Returns:
        Hedge ratio (beta) for position sizing
    """
    if len(prices1) < 2 or len(prices2) < 2:
        return 1.0

    x = np.column_stack([np.ones(len(prices2)), prices2])
    y = prices1

    try:
        beta = np.linalg.lstsq(x, y, rcond=None)[0]
        return float(beta[1])
    except Exception:
        return 1.0


def calculate_zscore(
    price_ratio: np.ndarray,
    lookback: int = 20,
) -> Optional[float]:
    """Calculate z-score for the price ratio.

    z = (price_ratio - mean) / std

    Args:
        price_ratio: Array of price ratios
        lookback: Lookback period for calculating mean and std

    Returns:
        Current z-score or None if insufficient data
    """
    if len(price_ratio) < lookback:
        return None

    recent = price_ratio[-lookback:]
    mean = np.mean(recent)
    std = np.std(recent)

    if std == 0:
        return 0.0

    current = price_ratio[-1]
    zscore = (current - mean) / std

    return float(zscore)


class StatArbStrategy(StrategyBase):
    """Statistical arbitrage pair trading strategy.

    Generates signals based on z-score of price ratio between two
    cointegrated assets. Long underperformer, short outperformer
    when spread diverges, exit when spread reverts.

    Attributes:
        config: Strategy configuration
        _ratio_history: Historical price ratios
        _hedge_ratio: Current hedge ratio between pairs
        _position_pair1: Current position in pair1 (None, "long", "short")
        _position_pair2: Current position in pair2 (None, "long", "short")
    """

    def __init__(self, name: str = "stat_arb", params: Optional[Dict[str, Any]] = None) -> None:
        """Initialize statistical arbitrage strategy.

        Args:
            name: Strategy name identifier
            params: Strategy parameters (merged with defaults)
        """
        super().__init__(name, params)

        self.config = StatArbConfig(
            pair1=self.get_param("pair1", "BTC/USDT"),
            pair2=self.get_param("pair2", "ETH/USDT"),
            lookback_period=self.get_param("lookback_period", 20),
            entry_threshold=Decimal(str(self.get_param("entry_threshold", 2.0))),
            exit_threshold=Decimal(str(self.get_param("exit_threshold", 0.5))),
        )

        self._ratio_history: List[Decimal] = []
        self._hedge_ratio: float = 1.0
        self._position_pair1: Optional[str] = None
        self._position_pair2: Optional[str] = None

        self.logger = structlog.get_logger(__name__).bind(
            strategy=name,
            pair1=self.config.pair1,
            pair2=self.config.pair2,
        )

    def initialize(self) -> None:
        """Initialize strategy state and warm up indicators."""
        self.logger.info("Initializing statistical arbitrage strategy")

        errors = self.validate_params()
        if errors:
            raise ValueError(f"Invalid parameters: {', '.join(errors)}")

        self._ratio_history.clear()
        self._hedge_ratio = 1.0
        self._position_pair1 = None
        self._position_pair2 = None

    def generate_signal(self, context: StrategyContext) -> Signal:
        """Generate trading signal based on z-score analysis.

        Args:
            context: Current market and account context

        Returns:
            Signal object with signal type and metadata
        """
        pair1_data = self._get_pair_data(context, self.config.pair1)
        pair2_data = self._get_pair_data(context, self.config.pair2)

        if pair1_data is None or pair2_data is None:
            return Signal(
                signal_type=SignalType.HOLD,
                pair=context.pair,
                timestamp=context.current_time,
                price=context.current_price,
                confidence=Decimal("0"),
                metadata={"reason": "insufficient_pair_data"},
            )

        current_price1 = pair1_data.close_price
        current_price2 = pair2_data.close_price

        if current_price1 <= 0 or current_price2 <= 0:
            return Signal(
                signal_type=SignalType.HOLD,
                pair=context.pair,
                timestamp=context.current_time,
                price=context.current_price,
                confidence=Decimal("0"),
                metadata={"reason": "invalid_prices"},
            )

        price_ratio = current_price1 / current_price2
        self._ratio_history.append(price_ratio)

        max_history = self.config.lookback_period * 3
        if len(self._ratio_history) > max_history:
            self._ratio_history = self._ratio_history[-max_history:]

        if len(self._ratio_history) < self.config.lookback_period:
            return Signal(
                signal_type=SignalType.HOLD,
                pair=context.pair,
                timestamp=context.current_time,
                price=context.current_price,
                confidence=Decimal("0"),
                metadata={"reason": "insufficient_history"},
            )

        ratio_array = np.array([float(r) for r in self._ratio_history])
        zscore = calculate_zscore(ratio_array, self.config.lookback_period)

        if zscore is None:
            return Signal(
                signal_type=SignalType.HOLD,
                pair=context.pair,
                timestamp=context.current_time,
                price=context.current_price,
                confidence=Decimal("0"),
                metadata={"reason": "zscore_calculation_failed"},
            )

        signal_type = self._determine_signal(zscore)

        abs_zscore = abs(zscore)
        confidence = Decimal(str(min(abs_zscore / 3.0, 1.0)))

        metadata: Dict[str, Any] = {
            "pair1": self.config.pair1,
            "pair2": self.config.pair2,
            "price_ratio": float(price_ratio),
            "zscore": zscore,
            "hedge_ratio": self._hedge_ratio,
            "strategy": "stat_arb",
        }

        if self._position_pair1:
            metadata["position_pair1"] = self._position_pair1
        if self._position_pair2:
            metadata["position_pair2"] = self._position_pair2

        self.logger.debug(
            "Signal generated",
            signal=signal_type.name,
            zscore=zscore,
            confidence=float(confidence),
        )

        return Signal(
            signal_type=signal_type,
            pair=context.pair,
            timestamp=context.current_time,
            price=context.current_price,
            confidence=confidence,
            metadata=metadata,
        )

    def _get_pair_data(
        self,
        context: StrategyContext,
        pair: str,
    ) -> Optional[OHLCVCandle]:
        """Get candle data for a specific trading pair.

        Args:
            context: Strategy context
            pair: Trading pair symbol

        Returns:
            Latest OHLCV candle for the pair or None
        """
        if context.pair == pair and context.candles:
            return context.candles[-1]

        return None

    def _determine_signal(self, zscore: float) -> SignalType:
        """Determine signal type based on z-score thresholds.

        Entry: |z| > entry_threshold (long underperformer, short outperformer)
        Exit: |z| < exit_threshold

        Args:
            zscore: Current z-score of price ratio

        Returns:
            Signal type (LONG, SHORT, CLOSE_LONG, CLOSE_SHORT, or HOLD)
        """
        abs_z = abs(zscore)
        entry_threshold = float(self.config.entry_threshold)
        exit_threshold = float(self.config.exit_threshold)

        if self._position_pair1 is None and self._position_pair2 is None:
            if abs_z > entry_threshold:
                if zscore > 0:
                    self._position_pair1 = "short"
                    self._position_pair2 = "long"
                    return SignalType.SHORT
                else:
                    self._position_pair1 = "long"
                    self._position_pair2 = "short"
                    return SignalType.LONG

        else:
            if abs_z < exit_threshold:
                if self._position_pair1 == "long":
                    self._position_pair1 = None
                    self._position_pair2 = None
                    return SignalType.CLOSE_LONG
                elif self._position_pair1 == "short":
                    self._position_pair1 = None
                    self._position_pair2 = None
                    return SignalType.CLOSE_SHORT

        return SignalType.HOLD

    def validate_params(self) -> List[str]:
        """Validate strategy parameters.

        Returns:
            List of validation error messages
        """
        errors: List[str] = []

        if self.config.lookback_period < 5:
            errors.append("lookback_period must be at least 5")

        if self.config.lookback_period > 100:
            errors.append("lookback_period must be at most 100")

        if self.config.entry_threshold <= self.config.exit_threshold:
            errors.append("entry_threshold must be greater than exit_threshold")

        if self.config.entry_threshold <= 0:
            errors.append("entry_threshold must be positive")

        if self.config.exit_threshold < 0:
            errors.append("exit_threshold must be non-negative")

        if "/" not in self.config.pair1:
            errors.append("pair1 must be a valid trading pair (e.g., 'BTC/USDT')")

        if "/" not in self.config.pair2:
            errors.append("pair2 must be a valid trading pair (e.g., 'ETH/USDT')")

        return errors

    def reset(self) -> None:
        """Reset strategy state."""
        super().reset()
        self._ratio_history.clear()
        self._hedge_ratio = 1.0
        self._position_pair1 = None
        self._position_pair2 = None
