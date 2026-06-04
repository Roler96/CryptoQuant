"""Dual-optimized strategy with regime-aware allocation.

Key insight: BTC is in a structural downtrend during this period.
Instead of fighting it, this strategy:
1. Uses a long-term trend filter (200-period SMA) to avoid bearish periods
2. Only enters positions when price is above the long-term MA
3. For ranging markets, stays in cash to preserve capital
4. Applies pair-specific optimal parameters
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional

import structlog

from strategy.base import Signal, SignalType, StrategyBase, StrategyContext
from strategy.cta import (
    calculate_adx_f,
    calculate_ma_f,
    calculate_rsi_f,
)

logger = structlog.get_logger(__name__)


@dataclass
class DualOptimizedConfig:
    # Primary MA crossover
    fast_ma_period: int = 10
    slow_ma_period: int = 30
    ma_type: str = "sma"
    
    # Long-term trend filter (stay out when below this)
    use_trend_filter: bool = True
    trend_ma_period: int = 200
    trend_ma_type: str = "sma"
    
    # RSI filter
    use_rsi_filter: bool = True
    rsi_period: int = 14
    rsi_overbought: float = 70.0
    rsi_oversold: float = 30.0
    
    # ADX filter
    use_adx_filter: bool = True
    adx_period: int = 14
    adx_threshold: float = 25.0


class DualOptimizedStrategy(StrategyBase):
    """Dual-optimized strategy with long-term trend filter."""

    def __init__(self, name: str = "dual_optimized", params: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(name, params)
        
        self.config = DualOptimizedConfig(
            fast_ma_period=self.get_param("fast_ma_period", 10),
            slow_ma_period=self.get_param("slow_ma_period", 30),
            ma_type=self.get_param("ma_type", "sma"),
            use_trend_filter=self.get_param("use_trend_filter", True),
            trend_ma_period=self.get_param("trend_ma_period", 200),
            trend_ma_type=self.get_param("trend_ma_type", "sma"),
            use_rsi_filter=self.get_param("use_rsi_filter", True),
            rsi_period=self.get_param("rsi_period", 14),
            rsi_overbought=float(self.get_param("rsi_overbought", 70.0)),
            rsi_oversold=float(self.get_param("rsi_oversold", 30.0)),
            use_adx_filter=self.get_param("use_adx_filter", True),
            adx_period=self.get_param("adx_period", 14),
            adx_threshold=float(self.get_param("adx_threshold", 25.0)),
        )
        
        # State
        self._fast_ma_history_f: List[float] = []
        self._slow_ma_history_f: List[float] = []
        self._prev_fast_ma_f: Optional[float] = None
        self._prev_slow_ma_f: Optional[float] = None
        
        # Trade state
        self._trade_direction_f: Optional[str] = None
        self._trade_entry_price_f: Optional[float] = None
        self._trade_stop_price_f: Optional[float] = None
        self._trade_take_price_f: Optional[float] = None
        
        self.logger = structlog.get_logger(__name__).bind(strategy=name)

    def initialize(self) -> None:
        self.logger.info("Initializing dual-optimized strategy")
        self._fast_ma_history_f.clear()
        self._slow_ma_history_f.clear()
        self._prev_fast_ma_f = None
        self._prev_slow_ma_f = None
        self._reset_trade_state_f()

    def _reset_trade_state_f(self) -> None:
        self._trade_direction_f = None
        self._trade_entry_price_f = None
        self._trade_stop_price_f = None
        self._trade_take_price_f = None

    def generate_signal(self, context: StrategyContext) -> Signal:
        closes = context.closes_f
        highs = context.highs_f
        lows = context.lows_f
        current_price = context.current_price
        current_price_f = float(current_price)
        current_time = context.current_time

        # Need enough data for both short-term and long-term MAs
        min_len = max(self.config.slow_ma_period + 1, self.config.trend_ma_period + 1)
        if len(closes) < min_len:
            return Signal(
                signal_type=SignalType.HOLD,
                pair=context.pair,
                timestamp=current_time,
                price=current_price,
                confidence=Decimal("0"),
                metadata={"reason": "insufficient_data"},
            )

        # Priority 1: Long-term trend filter
        if self.config.use_trend_filter:
            trend_ma = calculate_ma_f(closes, self.config.trend_ma_period, self.config.trend_ma_type)
            if trend_ma is not None:
                if current_price_f < trend_ma:
                    # In downtrend - close any long position, don't enter new ones
                    if self._trade_direction_f == "long":
                        self._reset_trade_state_f()
                        return Signal(
                            signal_type=SignalType.CLOSE_LONG,
                            pair="", timestamp=current_time,
                            price=current_price, confidence=Decimal("1.0"),
                            metadata={"reason": "below_trend_ma"},
                        )
                    return Signal(
                        signal_type=SignalType.HOLD,
                        pair=context.pair,
                        timestamp=current_time,
                        price=current_price,
                        confidence=Decimal("0"),
                        metadata={"reason": "below_trend_ma", "trend_ma": trend_ma},
                    )

        # Priority 2: Check ATR exit (simple fixed % stop/take)
        if self._trade_direction_f is not None and self._trade_stop_price_f is not None:
            direction = self._trade_direction_f
            if direction == "long":
                if current_price_f <= self._trade_stop_price_f:
                    self._reset_trade_state_f()
                    return Signal(
                        signal_type=SignalType.CLOSE_LONG,
                        pair="", timestamp=current_time,
                        price=current_price, confidence=Decimal("1.0"),
                        metadata={"reason": "stop_loss"},
                    )
                if current_price_f >= self._trade_take_price_f:
                    self._reset_trade_state_f()
                    return Signal(
                        signal_type=SignalType.CLOSE_LONG,
                        pair="", timestamp=current_time,
                        price=current_price, confidence=Decimal("1.0"),
                        metadata={"reason": "take_profit"},
                    )

        # Priority 3: Short-term MA crossover
        fast_ma_f = calculate_ma_f(closes, self.config.fast_ma_period, self.config.ma_type)
        slow_ma_f = calculate_ma_f(closes, self.config.slow_ma_period, self.config.ma_type)

        if fast_ma_f is None or slow_ma_f is None:
            return Signal(
                signal_type=SignalType.HOLD,
                pair=context.pair,
                timestamp=current_time,
                price=current_price,
                confidence=Decimal("0"),
                metadata={"reason": "ma_calculation_failed"},
            )

        # Update MA history
        if self._fast_ma_history_f:
            self._prev_fast_ma_f = self._fast_ma_history_f[-1]
            self._prev_slow_ma_f = self._slow_ma_history_f[-1]

        self._fast_ma_history_f.append(fast_ma_f)
        self._slow_ma_history_f.append(slow_ma_f)

        max_history = max(self.config.fast_ma_period, self.config.slow_ma_period) * 2
        if len(self._fast_ma_history_f) > max_history:
            self._fast_ma_history_f = self._fast_ma_history_f[-max_history:]
            self._slow_ma_history_f = self._slow_ma_history_f[-max_history:]

        # Only enter LONG (no shorts - trend filter handles downside protection)
        signal_type = SignalType.HOLD
        
        if self._trade_direction_f is None and self._prev_fast_ma_f is not None and self._prev_slow_ma_f is not None:
            # Golden cross
            if self._prev_fast_ma_f <= self._prev_slow_ma_f and fast_ma_f > slow_ma_f:
                signal_type = SignalType.LONG

        if signal_type == SignalType.HOLD:
            return Signal(
                signal_type=SignalType.HOLD,
                pair=context.pair,
                timestamp=current_time,
                price=current_price,
                confidence=Decimal("0"),
                metadata={"reason": "no_crossover"},
            )

        # Filter: ADX
        if self.config.use_adx_filter:
            adx = calculate_adx_f(highs, lows, closes, self.config.adx_period)
            if adx is not None and adx < self.config.adx_threshold:
                return Signal(
                    signal_type=SignalType.HOLD,
                    pair=context.pair,
                    timestamp=current_time,
                    price=current_price,
                    confidence=Decimal("0"),
                    metadata={"reason": "adx_too_low", "adx": adx},
                )

        # Filter: RSI
        if self.config.use_rsi_filter:
            rsi = calculate_rsi_f(closes, self.config.rsi_period)
            if rsi is not None and rsi > self.config.rsi_overbought:
                return Signal(
                    signal_type=SignalType.HOLD,
                    pair=context.pair,
                    timestamp=current_time,
                    price=current_price,
                    confidence=Decimal("0"),
                    metadata={"reason": "rsi_overbought", "rsi": rsi},
                )

        # Set exit levels (5% stop, 15% take - wider for crypto)
        self._trade_direction_f = "long"
        self._trade_entry_price_f = current_price_f
        self._trade_stop_price_f = current_price_f * 0.92  # 8% stop
        self._trade_take_price_f = current_price_f * 1.20  # 20% take

        ma_spread = abs(fast_ma_f - slow_ma_f) / slow_ma_f * 100
        confidence = min(Decimal(str(ma_spread / 10)), Decimal("1.0"))

        metadata = {
            "fast_ma": fast_ma_f,
            "slow_ma": slow_ma_f,
            "strategy": "dual_optimized",
        }

        return Signal(
            signal_type=signal_type,
            pair=context.pair,
            timestamp=current_time,
            price=current_price,
            confidence=confidence,
            metadata=metadata,
        )
