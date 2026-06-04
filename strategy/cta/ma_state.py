"""MA State strategy - enters based on MA relationship, not crossover.

Unlike crossover strategies that only trade at the moment of crossing,
this strategy enters when the MA relationship changes state and stays
in position until the state changes again.

For bear markets: enters SHORT when fast < slow, exits when fast > slow.
For bull markets: enters LONG when fast > slow, exits when fast < slow.
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
class MAStateConfig:
    fast_ma_period: int = 20
    slow_ma_period: int = 50
    ma_type: str = "sma"
    
    # RSI filter
    use_rsi_filter: bool = False
    rsi_period: int = 14
    rsi_overbought: float = 70.0
    rsi_oversold: float = 30.0
    
    # ADX filter
    use_adx_filter: bool = False
    adx_period: int = 14
    adx_threshold: float = 25.0
    
    # Stop loss / take profit
    use_stop_loss: bool = True
    stop_loss_pct: float = 0.05      # 5% stop loss
    take_profit_pct: float = 0.15    # 15% take profit
    trailing_stop_pct: float = 0.03  # 3% trailing stop


class MAStateStrategy(StrategyBase):
    """Strategy based on MA relationship state, not crossover events."""

    def __init__(self, name: str = "ma_state", params: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(name, params)
        
        self.config = MAStateConfig(
            fast_ma_period=self.get_param("fast_ma_period", 20),
            slow_ma_period=self.get_param("slow_ma_period", 50),
            ma_type=self.get_param("ma_type", "sma"),
            use_rsi_filter=self.get_param("use_rsi_filter", False),
            rsi_period=self.get_param("rsi_period", 14),
            rsi_overbought=float(self.get_param("rsi_overbought", 70.0)),
            rsi_oversold=float(self.get_param("rsi_oversold", 30.0)),
            use_adx_filter=self.get_param("use_adx_filter", False),
            adx_period=self.get_param("adx_period", 14),
            adx_threshold=float(self.get_param("adx_threshold", 25.0)),
            use_stop_loss=self.get_param("use_stop_loss", True),
            stop_loss_pct=float(self.get_param("stop_loss_pct", 0.05)),
            take_profit_pct=float(self.get_param("take_profit_pct", 0.15)),
            trailing_stop_pct=float(self.get_param("trailing_stop_pct", 0.03)),
        )
        
        # State tracking
        self._current_position: Optional[str] = None  # "long", "short", or None
        self._entry_price_f: Optional[float] = None
        self._stop_price_f: Optional[float] = None
        self._take_price_f: Optional[float] = None
        self._high_watermark_f: Optional[float] = None
        
        self.logger = structlog.get_logger(__name__).bind(strategy=name)

    def initialize(self) -> None:
        self.logger.info("Initializing MA state strategy")
        self._reset_state()

    def _reset_state(self) -> None:
        self._current_position = None
        self._entry_price_f = None
        self._stop_price_f = None
        self._take_price_f = None
        self._high_watermark_f = None

    def _set_stop_take(self, entry_price_f: float, direction: str) -> None:
        """Set stop loss and take profit levels."""
        if not self.config.use_stop_loss:
            return
        
        if direction == "long":
            self._stop_price_f = entry_price_f * (1 - self.config.stop_loss_pct)
            self._take_price_f = entry_price_f * (1 + self.config.take_profit_pct)
        else:  # short
            self._stop_price_f = entry_price_f * (1 + self.config.stop_loss_pct)
            self._take_price_f = entry_price_f * (1 - self.config.take_profit_pct)
        
        self._high_watermark_f = entry_price_f

    def _check_stop_take(self, current_price_f: float, current_time) -> Optional[Signal]:
        """Check if stop loss or take profit is hit."""
        if self._current_position is None or not self.config.use_stop_loss:
            return None
        
        # Update trailing stop
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
        
        # Check stop loss
        if self._current_position == "long" and current_price_f <= self._stop_price_f:
            self._reset_state()
            return Signal(
                signal_type=SignalType.CLOSE_LONG,
                pair="", timestamp=current_time,
                price=Decimal(str(current_price_f)), confidence=Decimal("1.0"),
                metadata={"reason": "stop_loss"},
            )
        
        if self._current_position == "short" and current_price_f >= self._stop_price_f:
            self._reset_state()
            return Signal(
                signal_type=SignalType.CLOSE_SHORT,
                pair="", timestamp=current_time,
                price=Decimal(str(current_price_f)), confidence=Decimal("1.0"),
                metadata={"reason": "stop_loss"},
            )
        
        # Check take profit
        if self._current_position == "long" and current_price_f >= self._take_price_f:
            self._reset_state()
            return Signal(
                signal_type=SignalType.CLOSE_LONG,
                pair="", timestamp=current_time,
                price=Decimal(str(current_price_f)), confidence=Decimal("1.0"),
                metadata={"reason": "take_profit"},
            )
        
        if self._current_position == "short" and current_price_f <= self._take_price_f:
            self._reset_state()
            return Signal(
                signal_type=SignalType.CLOSE_SHORT,
                pair="", timestamp=current_time,
                price=Decimal(str(current_price_f)), confidence=Decimal("1.0"),
                metadata={"reason": "take_profit"},
            )
        
        return None

    def generate_signal(self, context: StrategyContext) -> Signal:
        closes = context.closes_f
        highs = context.highs_f
        lows = context.lows_f
        current_price = context.current_price
        current_price_f = float(current_price)
        current_time = context.current_time

        min_len = self.config.slow_ma_period + 1
        if len(closes) < min_len:
            return Signal(
                signal_type=SignalType.HOLD,
                pair=context.pair,
                timestamp=current_time,
                price=current_price,
                confidence=Decimal("0"),
                metadata={"reason": "insufficient_data"},
            )

        # Priority 1: Check stop loss / take profit
        st_exit = self._check_stop_take(current_price_f, current_time)
        if st_exit is not None:
            return st_exit

        # Priority 2: Calculate MAs
        fast_ma = calculate_ma_f(closes, self.config.fast_ma_period, self.config.ma_type)
        slow_ma = calculate_ma_f(closes, self.config.slow_ma_period, self.config.ma_type)

        if fast_ma is None or slow_ma is None:
            return Signal(
                signal_type=SignalType.HOLD,
                pair=context.pair,
                timestamp=current_time,
                price=current_price,
                confidence=Decimal("0"),
                metadata={"reason": "ma_calculation_failed"},
            )

        # Priority 3: Determine target position based on MA state
        if fast_ma > slow_ma:
            target_position = "long"
        else:
            target_position = "short"

        # Filter: RSI
        if self.config.use_rsi_filter:
            rsi = calculate_rsi_f(closes, self.config.rsi_period)
            if rsi is not None:
                if target_position == "long" and rsi > self.config.rsi_overbought:
                    target_position = None  # Don't enter
                if target_position == "short" and rsi < self.config.rsi_oversold:
                    target_position = None  # Don't enter

        # Filter: ADX
        if self.config.use_adx_filter and target_position is not None:
            adx = calculate_adx_f(highs, lows, closes, self.config.adx_period)
            if adx is not None and adx < self.config.adx_threshold:
                target_position = None  # No trend, don't enter

        # Priority 4: Execute position changes
        signal_type = SignalType.HOLD
        
        if target_position == "long":
            if self._current_position is None:
                # Enter long
                signal_type = SignalType.LONG
                self._current_position = "long"
                self._entry_price_f = current_price_f
                self._set_stop_take(current_price_f, "long")
            elif self._current_position == "short":
                # Reverse: close short, then enter long
                signal_type = SignalType.CLOSE_SHORT  # Close short first
                # The next bar will enter long
                self._reset_state()
        
        elif target_position == "short":
            if self._current_position is None:
                # Enter short
                signal_type = SignalType.SHORT
                self._current_position = "short"
                self._entry_price_f = current_price_f
                self._set_stop_take(current_price_f, "short")
            elif self._current_position == "long":
                # Reverse: close long, then enter short
                signal_type = SignalType.CLOSE_LONG  # Close long first
                # The next bar will enter short
                self._reset_state()
        
        elif target_position is None and self._current_position is not None:
            # Filter says exit, but no target - close position
            if self._current_position == "long":
                signal_type = SignalType.CLOSE_LONG
            else:
                signal_type = SignalType.CLOSE_SHORT
            self._reset_state()

        metadata = {
            "fast_ma": fast_ma,
            "slow_ma": slow_ma,
            "position": self._current_position,
            "target": target_position,
            "strategy": "ma_state",
        }

        return Signal(
            signal_type=signal_type,
            pair=context.pair,
            timestamp=current_time,
            price=current_price,
            confidence=Decimal("0.8") if signal_type != SignalType.HOLD else Decimal("0"),
            metadata=metadata,
        )
