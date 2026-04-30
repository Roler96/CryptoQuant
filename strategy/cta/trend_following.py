"""Trend Following Strategy implementation.

A CTA-style trend following strategy using moving average crossovers,
RSI filters, and optional breakout detection for signal confirmation.
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional

import structlog

from data.models import OHLCVCandle
from strategy.base import Signal, SignalType, StrategyBase, StrategyContext
from strategy.cta import calculate_ma, calculate_rsi, detect_breakout

logger = structlog.get_logger(__name__)


@dataclass
class TrendFollowingConfig:
    """Configuration for trend following strategy.

    Attributes:
        fast_ma_period: Fast moving average period
        slow_ma_period: Slow moving average period
        ma_type: Moving average type ("sma" or "ema")
        use_rsi_filter: Whether to filter signals with RSI
        rsi_period: RSI calculation period
        rsi_overbought: RSI overbought threshold
        rsi_oversold: RSI oversold threshold
        use_breakout: Whether to require breakout confirmation
        breakout_lookback: Periods to look back for breakout levels
        breakout_mode: Breakout detection mode
    """
    fast_ma_period: int = 10
    slow_ma_period: int = 30
    ma_type: str = "sma"
    use_rsi_filter: bool = True
    rsi_period: int = 14
    rsi_overbought: Decimal = Decimal("70")
    rsi_oversold: Decimal = Decimal("30")
    use_breakout: bool = False
    breakout_lookback: int = 20
    breakout_mode: str = "both"


class TrendFollowingStrategy(StrategyBase):
    """Trend following strategy with MA crossover and RSI filter.

    Generates LONG signals when fast MA crosses above slow MA (and RSI confirms).
    Generates SHORT signals when fast MA crosses below slow MA (and RSI confirms).
    Includes optional breakout confirmation mode.

    Attributes:
        config: Strategy configuration object
        _fast_ma_history: Historical fast MA values
        _slow_ma_history: Historical slow MA values
        _prev_fast_ma: Previous fast MA for crossover detection
        _prev_slow_ma: Previous slow MA for crossover detection
    """

    def __init__(self, name: str = "trend_following", params: Optional[Dict[str, Any]] = None) -> None:
        """Initialize trend following strategy.

        Args:
            name: Strategy name identifier
            params: Strategy parameters (merged with defaults)
        """
        super().__init__(name, params)

        self.config = TrendFollowingConfig(
            fast_ma_period=self.get_param("fast_ma_period", 10),
            slow_ma_period=self.get_param("slow_ma_period", 30),
            ma_type=self.get_param("ma_type", "sma"),
            use_rsi_filter=self.get_param("use_rsi_filter", True),
            rsi_period=self.get_param("rsi_period", 14),
            rsi_overbought=Decimal(str(self.get_param("rsi_overbought", 70))),
            rsi_oversold=Decimal(str(self.get_param("rsi_oversold", 30))),
            use_breakout=self.get_param("use_breakout", False),
            breakout_lookback=self.get_param("breakout_lookback", 20),
            breakout_mode=self.get_param("breakout_mode", "both"),
        )

        self._fast_ma_history: List[Decimal] = []
        self._slow_ma_history: List[Decimal] = []
        self._prev_fast_ma: Optional[Decimal] = None
        self._prev_slow_ma: Optional[Decimal] = None

        self.logger = structlog.get_logger(__name__).bind(
            strategy=name,
            fast_period=self.config.fast_ma_period,
            slow_period=self.config.slow_ma_period,
        )

    def initialize(self) -> None:
        """Initialize strategy state and warm up indicators."""
        self.logger.info("Initializing trend following strategy")

        errors = self.validate_params()
        if errors:
            raise ValueError(f"Invalid parameters: {', '.join(errors)}")

        self._fast_ma_history.clear()
        self._slow_ma_history.clear()
        self._prev_fast_ma = None
        self._prev_slow_ma = None

    def generate_signal(self, context: StrategyContext) -> Signal:
        """Generate trading signal based on MA crossover and filters.

        Args:
            context: Current market and account context

        Returns:
            Signal object with signal type and metadata
        """
        candles = context.candles
        current_price = context.current_price

        if len(candles) < self.config.slow_ma_period + 1:
            return Signal(
                signal_type=SignalType.HOLD,
                pair=context.pair,
                timestamp=context.current_time,
                price=current_price,
                confidence=Decimal("0"),
                metadata={"reason": "insufficient_data"},
            )

        fast_ma = calculate_ma(
            candles,
            self.config.fast_ma_period,
            self.config.ma_type,
        )
        slow_ma = calculate_ma(
            candles,
            self.config.slow_ma_period,
            self.config.ma_type,
        )

        if fast_ma is None or slow_ma is None:
            return Signal(
                signal_type=SignalType.HOLD,
                pair=context.pair,
                timestamp=context.current_time,
                price=current_price,
                confidence=Decimal("0"),
                metadata={"reason": "ma_calculation_failed"},
            )

        self._update_ma_history(fast_ma, slow_ma)

        signal_type = self._determine_signal(
            fast_ma,
            slow_ma,
            candles,
            context,
        )

        confidence = self._calculate_confidence(
            fast_ma,
            slow_ma,
            candles,
            signal_type,
        )

        metadata: Dict[str, Any] = {
            "fast_ma": float(fast_ma),
            "slow_ma": float(slow_ma),
            "ma_spread": float((fast_ma - slow_ma) / slow_ma * 100),
            "strategy": "trend_following",
        }

        if self.config.use_rsi_filter:
            rsi = calculate_rsi(candles, self.config.rsi_period)
            if rsi is not None:
                metadata["rsi"] = float(rsi)

        if self.config.use_breakout and signal_type in (SignalType.LONG, SignalType.SHORT):
            is_breakout, level, strength = detect_breakout(
                candles,
                self.config.breakout_lookback,
                self.config.breakout_mode,
            )
            metadata["breakout_confirmed"] = is_breakout
            if level is not None:
                metadata["breakout_level"] = float(level)
            if strength is not None:
                metadata["breakout_strength"] = float(strength)

        self.logger.debug(
            "Signal generated",
            signal=signal_type.name,
            pair=context.pair,
            fast_ma=float(fast_ma),
            slow_ma=float(slow_ma),
            confidence=float(confidence),
        )

        return Signal(
            signal_type=signal_type,
            pair=context.pair,
            timestamp=context.current_time,
            price=current_price,
            confidence=confidence,
            metadata=metadata,
        )

    def _update_ma_history(self, fast_ma: Decimal, slow_ma: Decimal) -> None:
        """Update MA history for crossover detection.

        Args:
            fast_ma: Current fast moving average value
            slow_ma: Current slow moving average value
        """
        if self._fast_ma_history:
            self._prev_fast_ma = self._fast_ma_history[-1]
            self._prev_slow_ma = self._slow_ma_history[-1]

        self._fast_ma_history.append(fast_ma)
        self._slow_ma_history.append(slow_ma)

        max_history = max(self.config.fast_ma_period, self.config.slow_ma_period) * 2
        if len(self._fast_ma_history) > max_history:
            self._fast_ma_history = self._fast_ma_history[-max_history:]
            self._slow_ma_history = self._slow_ma_history[-max_history:]

    def _determine_signal(
        self,
        fast_ma: Decimal,
        slow_ma: Decimal,
        candles: List[OHLCVCandle],
        context: StrategyContext,
    ) -> SignalType:
        """Determine signal type based on crossover and filters.

        Args:
            fast_ma: Current fast moving average
            slow_ma: Current slow moving average
            candles: Recent candle data
            context: Strategy context

        Returns:
            Signal type (LONG, SHORT, or HOLD)
        """
        position = context.get_position()
        current_side = None
        if position and not position.is_flat:
            current_side = "long" if position.is_long else "short"

        if self._prev_fast_ma is None or self._prev_slow_ma is None:
            return SignalType.HOLD

        bullish_cross = self._prev_fast_ma <= self._prev_slow_ma and fast_ma > slow_ma
        bearish_cross = self._prev_fast_ma >= self._prev_slow_ma and fast_ma < slow_ma

        if not bullish_cross and not bearish_cross:
            return SignalType.HOLD

        rsi = None
        if self.config.use_rsi_filter:
            rsi = calculate_rsi(candles, self.config.rsi_period)

        if bullish_cross:
            if self.config.use_rsi_filter and rsi is not None:
                if rsi > self.config.rsi_overbought:
                    return SignalType.HOLD

            if self.config.use_breakout:
                is_breakout, _, _ = detect_breakout(
                    candles,
                    self.config.breakout_lookback,
                    "resistance",
                )
                if not is_breakout:
                    return SignalType.HOLD

            if current_side == "long":
                return SignalType.HOLD
            elif current_side == "short":
                return SignalType.CLOSE_SHORT
            else:
                return SignalType.LONG

        if bearish_cross:
            if self.config.use_rsi_filter and rsi is not None:
                if rsi < self.config.rsi_oversold:
                    return SignalType.HOLD

            if self.config.use_breakout:
                is_breakout, _, _ = detect_breakout(
                    candles,
                    self.config.breakout_lookback,
                    "support",
                )
                if not is_breakout:
                    return SignalType.HOLD

            if current_side == "short":
                return SignalType.HOLD
            elif current_side == "long":
                return SignalType.CLOSE_LONG
            else:
                return SignalType.SHORT

        return SignalType.HOLD

    def _calculate_confidence(
        self,
        fast_ma: Decimal,
        slow_ma: Decimal,
        candles: List[OHLCVCandle],
        signal_type: SignalType,
    ) -> Decimal:
        """Calculate signal confidence based on trend strength.

        Args:
            fast_ma: Current fast moving average
            slow_ma: Current slow moving average
            candles: Recent candle data
            signal_type: Generated signal type

        Returns:
            Confidence score (0.0 to 1.0)
        """
        if signal_type == SignalType.HOLD:
            return Decimal("0.5")

        ma_spread = abs(fast_ma - slow_ma) / slow_ma
        base_confidence = min(ma_spread * Decimal("10"), Decimal("0.6"))

        if self.config.use_rsi_filter:
            rsi = calculate_rsi(candles, self.config.rsi_period)
            if rsi is not None:
                if signal_type in (SignalType.LONG, SignalType.CLOSE_SHORT):
                    rsi_boost = (Decimal("50") - rsi) / Decimal("100")
                    base_confidence += max(rsi_boost, Decimal("0"))
                elif signal_type in (SignalType.SHORT, SignalType.CLOSE_LONG):
                    rsi_boost = (rsi - Decimal("50")) / Decimal("100")
                    base_confidence += max(rsi_boost, Decimal("0"))

        if self.config.use_breakout:
            is_breakout, _, strength = detect_breakout(
                candles,
                self.config.breakout_lookback,
                self.config.breakout_mode,
            )
            if is_breakout and strength is not None:
                base_confidence += min(strength * Decimal("10"), Decimal("0.2"))

        return min(base_confidence, Decimal("1.0"))

    def validate_params(self) -> List[str]:
        """Validate strategy parameters.

        Returns:
            List of validation error messages
        """
        errors: List[str] = []

        if self.config.fast_ma_period >= self.config.slow_ma_period:
            errors.append("fast_ma_period must be less than slow_ma_period")

        if self.config.fast_ma_period < 2:
            errors.append("fast_ma_period must be at least 2")

        if self.config.slow_ma_period < 5:
            errors.append("slow_ma_period must be at least 5")

        if self.config.ma_type not in ("sma", "ema"):
            errors.append("ma_type must be 'sma' or 'ema'")

        if not (0 < self.config.rsi_overbought < 100):
            errors.append("rsi_overbought must be between 0 and 100")

        if not (0 < self.config.rsi_oversold < 100):
            errors.append("rsi_oversold must be between 0 and 100")

        if self.config.rsi_oversold >= self.config.rsi_overbought:
            errors.append("rsi_oversold must be less than rsi_overbought")

        if self.config.breakout_mode not in ("resistance", "support", "both"):
            errors.append("breakout_mode must be 'resistance', 'support', or 'both'")

        return errors

    def reset(self) -> None:
        """Reset strategy state."""
        super().reset()
        self._fast_ma_history.clear()
        self._slow_ma_history.clear()
        self._prev_fast_ma = None
        self._prev_slow_ma = None
