
"""Mean Reversion Strategy using Bollinger Bands + RSI.

For ranging/choppy markets where trend-following struggles.
- Enters LONG when price touches lower band AND RSI < 30 (oversold)
- Enters SHORT when price touches upper band AND RSI > 70 (overbought)
- Exits on return to middle band or opposite signal
"""
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional

import structlog

from strategy.base import Signal, SignalType, StrategyBase, StrategyContext
from strategy.cta import calculate_rsi_f, calculate_ma_f

logger = structlog.get_logger(__name__)


@dataclass
class MeanReversionConfig:
    bb_period: int = 20
    bb_std: float = 2.0
    rsi_period: int = 14
    rsi_oversold: float = 30.0
    rsi_overbought: float = 70.0
    use_stop_loss: bool = True
    stop_loss_pct: float = 0.03
    take_profit_pct: float = 0.06


class MeanReversionStrategy(StrategyBase):
    """Mean reversion: buy oversold bounces, sell overbought pullbacks."""

    def __init__(self, name: str = "mean_reversion", params: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(name, params)
        self.config = MeanReversionConfig(
            bb_period=self.get_param("bb_period", 20),
            bb_std=float(self.get_param("bb_std", 2.0)),
            rsi_period=self.get_param("rsi_period", 14),
            rsi_oversold=float(self.get_param("rsi_oversold", 30.0)),
            rsi_overbought=float(self.get_param("rsi_overbought", 70.0)),
            use_stop_loss=self.get_param("use_stop_loss", True),
            stop_loss_pct=float(self.get_param("stop_loss_pct", 0.03)),
            take_profit_pct=float(self.get_param("take_profit_pct", 0.06)),
        )
        self._position: Optional[str] = None
        self._entry_price: Optional[float] = None
        self._stop_price: Optional[float] = None
        self._take_price: Optional[float] = None

    def initialize(self) -> None:
        self._position = None
        self._entry_price = None

    def _calc_bb(self, closes: List[float]):
        """Calculate Bollinger Bands from close prices."""
        n = self.config.bb_period
        if len(closes) < n:
            return None, None, None
        recent = closes[-n:]
        sma = sum(recent) / n
        variance = sum((c - sma) ** 2 for c in recent) / n
        std = variance ** 0.5
        upper = sma + std * self.config.bb_std
        lower = sma - std * self.config.bb_std
        return sma, upper, lower

    def generate_signal(self, context: StrategyContext) -> Signal:
        closes = context.closes_f
        current_price = context.current_price
        current_price_f = float(current_price)
        current_time = context.current_time

        n = max(self.config.bb_period, self.config.rsi_period) + 1
        if len(closes) < n:
            return Signal(SignalType.HOLD, context.pair, current_time, current_price,
                         Decimal("0"), {"reason": "insufficient_data"})

        # Check stop loss / take profit
        if self._position and self.config.use_stop_loss:
            if self._position == "long":
                if current_price_f <= self._stop_price:
                    self._position = None
                    return Signal(SignalType.CLOSE_LONG, "", current_time, current_price,
                                 Decimal("1.0"), {"reason": "stop_loss"})
                if current_price_f >= self._take_price:
                    self._position = None
                    return Signal(SignalType.CLOSE_LONG, "", current_time, current_price,
                                 Decimal("1.0"), {"reason": "take_profit"})
            else:
                if current_price_f >= self._stop_price:
                    self._position = None
                    return Signal(SignalType.CLOSE_SHORT, "", current_time, current_price,
                                 Decimal("1.0"), {"reason": "stop_loss"})
                if current_price_f <= self._take_price:
                    self._position = None
                    return Signal(SignalType.CLOSE_SHORT, "", current_time, current_price,
                                 Decimal("1.0"), {"reason": "take_profit"})

        # Calculate indicators
        middle, upper, lower = self._calc_bb(closes)
        rsi = calculate_rsi_f(closes, self.config.rsi_period)

        if middle is None or rsi is None:
            return Signal(SignalType.HOLD, context.pair, current_time, current_price,
                         Decimal("0"), {"reason": "indicator_failed"})

        # Mean reversion logic
        signal_type = SignalType.HOLD
        target_pos = None

        if current_price_f <= lower and rsi <= self.config.rsi_oversold:
            target_pos = "long"  # Oversold bounce
        elif current_price_f >= upper and rsi >= self.config.rsi_overbought:
            target_pos = "short"  # Overbought pullback

        # Exit on return to middle
        if self._position == "long" and current_price_f >= middle:
            self._position = None
            return Signal(SignalType.CLOSE_LONG, "", current_time, current_price,
                         Decimal("0.8"), {"reason": "mean_reversion_exit"})
        if self._position == "short" and current_price_f <= middle:
            self._position = None
            return Signal(SignalType.CLOSE_SHORT, "", current_time, current_price,
                         Decimal("0.8"), {"reason": "mean_reversion_exit"})

        # Enter
        if target_pos == "long" and self._position != "long":
            if self._position == "short":
                self._position = None
                signal_type = SignalType.CLOSE_SHORT
            else:
                signal_type = SignalType.LONG
                self._position = "long"
                self._entry_price = current_price_f
                if self.config.use_stop_loss:
                    self._stop_price = current_price_f * (1 - self.config.stop_loss_pct)
                    self._take_price = current_price_f * (1 + self.config.take_profit_pct)
        elif target_pos == "short" and self._position != "short":
            if self._position == "long":
                self._position = None
                signal_type = SignalType.CLOSE_LONG
            else:
                signal_type = SignalType.SHORT
                self._position = "short"
                self._entry_price = current_price_f
                if self.config.use_stop_loss:
                    self._stop_price = current_price_f * (1 + self.config.stop_loss_pct)
                    self._take_price = current_price_f * (1 - self.config.take_profit_pct)

        return Signal(
            signal_type=signal_type,
            pair=context.pair,
            timestamp=current_time,
            price=current_price,
            confidence=Decimal("0.7") if signal_type != SignalType.HOLD else Decimal("0"),
            metadata={"rsi": rsi, "bb_middle": middle, "bb_lower": lower, "bb_upper": upper},
        )
