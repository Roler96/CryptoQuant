"""Trend-filtered strategy - uses long-term MA to determine trade direction.

Logic:
- When price > trend_MA: only LONG (buy dips, sell on MA cross down)
- When price < trend_MA: only SHORT (sell rallies, cover on MA cross up)
- This prevents whipsaw by aligning all trades with the long-term trend
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
class TrendFilteredConfig:
    # Short-term MA for entry signals
    fast_ma_period: int = 10
    slow_ma_period: int = 30
    ma_type: str = "sma"
    
    # Long-term trend filter
    trend_ma_period: int = 200
    trend_ma_type: str = "sma"
    
    # Stop loss / take profit
    use_stop_loss: bool = True
    stop_loss_pct: float = 0.08
    take_profit_pct: float = 0.20
    trailing_stop_pct: float = 0.04


class TrendFilteredStrategy(StrategyBase):
    """Strategy that aligns trades with the long-term trend."""

    def __init__(self, name: str = "trend_filtered", params: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(name, params)
        
        self.config = TrendFilteredConfig(
            fast_ma_period=self.get_param("fast_ma_period", 10),
            slow_ma_period=self.get_param("slow_ma_period", 30),
            ma_type=self.get_param("ma_type", "sma"),
            trend_ma_period=self.get_param("trend_ma_period", 200),
            trend_ma_type=self.get_param("trend_ma_type", "sma"),
            use_stop_loss=self.get_param("use_stop_loss", True),
            stop_loss_pct=float(self.get_param("stop_loss_pct", 0.08)),
            take_profit_pct=float(self.get_param("take_profit_pct", 0.20)),
            trailing_stop_pct=float(self.get_param("trailing_stop_pct", 0.04)),
        )
        
        # State
        self._current_position: Optional[str] = None
        self._entry_price_f: Optional[float] = None
        self._stop_price_f: Optional[float] = None
        self._take_price_f: Optional[float] = None
        self._high_watermark_f: Optional[float] = None
        
        self.logger = structlog.get_logger(__name__).bind(strategy=name)

    def initialize(self) -> None:
        self.logger.info("Initializing trend-filtered strategy")
        self._reset_state()

    def _reset_state(self) -> None:
        self._current_position = None
        self._entry_price_f = None
        self._stop_price_f = None
        self._take_price_f = None
        self._high_watermark_f = None

    def _set_stop_take(self, entry_price_f: float, direction: str) -> None:
        if direction == "long":
            self._stop_price_f = entry_price_f * (1 - self.config.stop_loss_pct)
            self._take_price_f = entry_price_f * (1 + self.config.take_profit_pct)
        else:
            self._stop_price_f = entry_price_f * (1 + self.config.stop_loss_pct)
            self._take_price_f = entry_price_f * (1 - self.config.take_profit_pct)
        self._high_watermark_f = entry_price_f

    def _check_stop_take(self, current_price_f: float, current_time) -> Optional[Signal]:
        if self._current_position is None or not self.config.use_stop_loss:
            return None
        
        # Trailing stop
        if self._high_watermark_f is not None:
            if self._current_position == "long" and current_price_f > self._high_watermark_f:
                self._high_watermark_f = current_price_f
                new_stop = current_price_f * (1 - self.config.trailing_stop_pct)
                if new_stop > self._stop_price_f:
                    self._stop_price_f = new_stop
            elif self._current_position == "short" and current_price_f < self._high_watermark_f:
                self._high_watermark_f = current_price_f
                new_stop = current_price_f * (1 + self.config.trailing_stop_pct)
                if new_stop < self._stop_price_f:
                    self._stop_price_f = new_stop
        
        if self._current_position == "long" and current_price_f <= self._stop_price_f:
            self._reset_state()
            return Signal(signal_type=SignalType.CLOSE_LONG, pair="", timestamp=current_time,
                price=Decimal(str(current_price_f)), confidence=Decimal("1.0"), metadata={"reason": "stop_loss"})
        
        if self._current_position == "short" and current_price_f >= self._stop_price_f:
            self._reset_state()
            return Signal(signal_type=SignalType.CLOSE_SHORT, pair="", timestamp=current_time,
                price=Decimal(str(current_price_f)), confidence=Decimal("1.0"), metadata={"reason": "stop_loss"})
        
        if self._current_position == "long" and current_price_f >= self._take_price_f:
            self._reset_state()
            return Signal(signal_type=SignalType.CLOSE_LONG, pair="", timestamp=current_time,
                price=Decimal(str(current_price_f)), confidence=Decimal("1.0"), metadata={"reason": "take_profit"})
        
        if self._current_position == "short" and current_price_f <= self._take_price_f:
            self._reset_state()
            return Signal(signal_type=SignalType.CLOSE_SHORT, pair="", timestamp=current_time,
                price=Decimal(str(current_price_f)), confidence=Decimal("1.0"), metadata={"reason": "take_profit"})
        
        return None

    def generate_signal(self, context: StrategyContext) -> Signal:
        closes = context.closes_f
        highs = context.highs_f
        lows = context.lows_f
        current_price = context.current_price
        current_price_f = float(current_price)
        current_time = context.current_time

        min_len = max(self.config.slow_ma_period, self.config.trend_ma_period) + 1
        if len(closes) < min_len:
            return Signal(signal_type=SignalType.HOLD, pair=context.pair, timestamp=current_time,
                price=current_price, confidence=Decimal("0"), metadata={"reason": "insufficient_data"})

        # Priority 1: Check stops
        st_exit = self._check_stop_take(current_price_f, current_time)
        if st_exit is not None:
            return st_exit

        # Priority 2: Calculate MAs
        fast_ma = calculate_ma_f(closes, self.config.fast_ma_period, self.config.ma_type)
        slow_ma = calculate_ma_f(closes, self.config.slow_ma_period, self.config.ma_type)
        trend_ma = calculate_ma_f(closes, self.config.trend_ma_period, self.config.trend_ma_type)

        if fast_ma is None or slow_ma is None or trend_ma is None:
            return Signal(signal_type=SignalType.HOLD, pair=context.pair, timestamp=current_time,
                price=current_price, confidence=Decimal("0"), metadata={"reason": "ma_calculation_failed"})

        # Priority 3: Determine trend direction
        is_uptrend = current_price_f > trend_ma
        
        # Priority 4: Determine target position based on MA state AND trend
        if is_uptrend:
            # Uptrend: only LONG when fast > slow
            if fast_ma > slow_ma:
                target_position = "long"
            else:
                target_position = None  # Stay in cash during pullbacks
        else:
            # Downtrend: only SHORT when fast < slow
            if fast_ma < slow_ma:
                target_position = "short"
            else:
                target_position = None  # Stay in cash during bounces

        # Priority 5: Execute
        signal_type = SignalType.HOLD
        
        if target_position == "long":
            if self._current_position is None:
                signal_type = SignalType.LONG
                self._current_position = "long"
                self._entry_price_f = current_price_f
                self._set_stop_take(current_price_f, "long")
            elif self._current_position == "short":
                signal_type = SignalType.CLOSE_SHORT
                self._reset_state()
        
        elif target_position == "short":
            if self._current_position is None:
                signal_type = SignalType.SHORT
                self._current_position = "short"
                self._entry_price_f = current_price_f
                self._set_stop_take(current_price_f, "short")
            elif self._current_position == "long":
                signal_type = SignalType.CLOSE_LONG
                self._reset_state()
        
        elif target_position is None and self._current_position is not None:
            # Trend changed, close position
            if self._current_position == "long":
                signal_type = SignalType.CLOSE_LONG
            else:
                signal_type = SignalType.CLOSE_SHORT
            self._reset_state()

        metadata = {
            "fast_ma": fast_ma, "slow_ma": slow_ma, "trend_ma": trend_ma,
            "position": self._current_position, "target": target_position,
            "trend": "up" if is_uptrend else "down",
            "strategy": "trend_filtered",
        }

        return Signal(signal_type=signal_type, pair=context.pair, timestamp=current_time,
            price=current_price, confidence=Decimal("0.8") if signal_type != SignalType.HOLD else Decimal("0"),
            metadata=metadata)
