"""Final optimized strategy tuned for TON/USDT 1h.

Key optimizations:
1. EMA(5)/EMA(21) crossover for faster signals
2. ADX > 25 filter to avoid choppy periods
3. RSI filter (25/75) for entry timing
4. ATR-based stop loss (2x) and take profit (3x)
5. Trailing stop to lock in profits
6. Cooldown after stop loss (3 bars)
"""

from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional

import structlog

from strategy.base import Signal, SignalType, StrategyBase, StrategyContext
from strategy.cta import (
    calculate_adx_f,
    calculate_atr_f,
    calculate_ma_f,
    calculate_rsi_f,
)
from strategy.regime import MarketRegime, RegimeDetector

logger = structlog.get_logger(__name__)


@dataclass
class FinalOptimizedConfig:
    fast_ma_period: int = 5
    slow_ma_period: int = 21
    ma_type: str = "ema"
    
    use_rsi_filter: bool = True
    rsi_period: int = 14
    rsi_overbought: float = 75.0
    rsi_oversold: float = 25.0
    
    use_adx_filter: bool = True
    adx_period: int = 14
    adx_threshold: float = 25.0
    
    use_atr_exit: bool = True
    atr_period: int = 14
    atr_stop_multiplier: float = 2.0
    atr_take_multiplier: float = 3.0
    atr_trail_multiplier: float = 2.5
    
    use_regime_filter: bool = True
    regime_adx_period: int = 14
    regime_chop_period: int = 14
    regime_atr_period: int = 14
    
    cooldown_after_stop: int = 3


class FinalOptimizedStrategy(StrategyBase):
    """Final optimized trend following strategy."""

    def __init__(self, name: str = "final_optimized", params: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(name, params)
        
        self.config = FinalOptimizedConfig(
            fast_ma_period=self.get_param("fast_ma_period", 5),
            slow_ma_period=self.get_param("slow_ma_period", 21),
            ma_type=self.get_param("ma_type", "ema"),
            use_rsi_filter=self.get_param("use_rsi_filter", True),
            rsi_period=self.get_param("rsi_period", 14),
            rsi_overbought=float(self.get_param("rsi_overbought", 75.0)),
            rsi_oversold=float(self.get_param("rsi_oversold", 25.0)),
            use_adx_filter=self.get_param("use_adx_filter", True),
            adx_period=self.get_param("adx_period", 14),
            adx_threshold=float(self.get_param("adx_threshold", 25.0)),
            use_atr_exit=self.get_param("use_atr_exit", True),
            atr_period=self.get_param("atr_period", 14),
            atr_stop_multiplier=float(self.get_param("atr_stop_multiplier", 2.0)),
            atr_take_multiplier=float(self.get_param("atr_take_multiplier", 3.0)),
            atr_trail_multiplier=float(self.get_param("atr_trail_multiplier", 2.5)),
            use_regime_filter=self.get_param("use_regime_filter", True),
            regime_adx_period=self.get_param("regime_adx_period", 14),
            regime_chop_period=self.get_param("regime_chop_period", 14),
            regime_atr_period=self.get_param("regime_atr_period", 14),
            cooldown_after_stop=self.get_param("cooldown_after_stop", 3),
        )
        
        # State
        self._fast_ma_history_f: List[float] = []
        self._slow_ma_history_f: List[float] = []
        self._prev_fast_ma_f: Optional[float] = None
        self._prev_slow_ma_f: Optional[float] = None
        
        self._trade_direction_f: Optional[str] = None
        self._trade_entry_price_f: Optional[float] = None
        self._trade_stop_price_f: Optional[float] = None
        self._trade_take_price_f: Optional[float] = None
        self._trade_high_watermark_f: Optional[float] = None
        
        self._cooldown_remaining: int = 0
        
        self._regime_detector = RegimeDetector(
            adx_period=self.config.regime_adx_period,
            chop_period=self.config.regime_chop_period,
            atr_period=self.config.regime_atr_period,
        )
        self._current_regime: MarketRegime = MarketRegime.UNKNOWN
        
        self.logger = structlog.get_logger(__name__).bind(strategy=name)

    def initialize(self) -> None:
        self.logger.info("Initializing final optimized strategy")
        self._fast_ma_history_f.clear()
        self._slow_ma_history_f.clear()
        self._prev_fast_ma_f = None
        self._prev_slow_ma_f = None
        self._reset_trade_state_f()
        self._cooldown_remaining = 0

    def _reset_trade_state_f(self) -> None:
        self._trade_direction_f = None
        self._trade_entry_price_f = None
        self._trade_stop_price_f = None
        self._trade_take_price_f = None
        self._trade_high_watermark_f = None

    def _set_atr_exit(self, highs, lows, closes, direction, entry_price_f) -> None:
        atr = calculate_atr_f(highs, lows, closes, self.config.atr_period)
        if atr is None:
            atr = entry_price_f * 0.02
        
        if direction == "long":
            self._trade_stop_price_f = entry_price_f - (atr * self.config.atr_stop_multiplier)
            self._trade_take_price_f = entry_price_f + (atr * self.config.atr_take_multiplier)
            self._trade_high_watermark_f = entry_price_f
        else:
            self._trade_stop_price_f = entry_price_f + (atr * self.config.atr_stop_multiplier)
            self._trade_take_price_f = entry_price_f - (atr * self.config.atr_take_multiplier)
            self._trade_high_watermark_f = entry_price_f
        
        self._trade_direction_f = direction
        self._trade_entry_price_f = entry_price_f

    def _update_trailing_stop(self, current_price_f) -> None:
        if self._trade_direction_f is None or self._trade_high_watermark_f is None:
            return
        
        if self._trade_direction_f == "long":
            if current_price_f > self._trade_high_watermark_f:
                self._trade_high_watermark_f = current_price_f
                atr_approx = (self._trade_take_price_f - self._trade_entry_price_f) / self.config.atr_take_multiplier
                new_stop = current_price_f - (atr_approx * self.config.atr_trail_multiplier)
                if new_stop > self._trade_stop_price_f:
                    self._trade_stop_price_f = new_stop
        elif self._trade_direction_f == "short":
            if current_price_f < self._trade_high_watermark_f:
                self._trade_high_watermark_f = current_price_f
                atr_approx = (self._trade_entry_price_f - self._trade_take_price_f) / self.config.atr_take_multiplier
                new_stop = current_price_f + (atr_approx * self.config.atr_trail_multiplier)
                if new_stop < self._trade_stop_price_f:
                    self._trade_stop_price_f = new_stop

    def _check_atr_exit(self, current_price_f, current_time) -> Optional[Signal]:
        if self._trade_direction_f is None or self._trade_stop_price_f is None:
            return None
        
        self._update_trailing_stop(current_price_f)
        
        direction = self._trade_direction_f
        if direction == "long":
            if current_price_f <= self._trade_stop_price_f:
                self._reset_trade_state_f()
                self._cooldown_remaining = self.config.cooldown_after_stop
                return Signal(
                    signal_type=SignalType.CLOSE_LONG,
                    pair="", timestamp=current_time,
                    price=Decimal(str(current_price_f)), confidence=Decimal("1.0"),
                    metadata={"reason": "stop_loss"},
                )
            if current_price_f >= self._trade_take_price_f:
                self._reset_trade_state_f()
                return Signal(
                    signal_type=SignalType.CLOSE_LONG,
                    pair="", timestamp=current_time,
                    price=Decimal(str(current_price_f)), confidence=Decimal("1.0"),
                    metadata={"reason": "take_profit"},
                )
        elif direction == "short":
            if current_price_f >= self._trade_stop_price_f:
                self._reset_trade_state_f()
                self._cooldown_remaining = self.config.cooldown_after_stop
                return Signal(
                    signal_type=SignalType.CLOSE_SHORT,
                    pair="", timestamp=current_time,
                    price=Decimal(str(current_price_f)), confidence=Decimal("1.0"),
                    metadata={"reason": "stop_loss"},
                )
            if current_price_f <= self._trade_take_price_f:
                self._reset_trade_state_f()
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

        if len(closes) < self.config.slow_ma_period + 1:
            return Signal(
                signal_type=SignalType.HOLD,
                pair=context.pair,
                timestamp=current_time,
                price=current_price,
                confidence=Decimal("0"),
                metadata={"reason": "insufficient_data"},
            )

        # Priority 1: Check exits
        atr_exit = self._check_atr_exit(current_price_f, current_time)
        if atr_exit is not None:
            return atr_exit
        
        # Priority 2: Cooldown
        if self._cooldown_remaining > 0:
            self._cooldown_remaining -= 1
            return Signal(
                signal_type=SignalType.HOLD,
                pair=context.pair,
                timestamp=current_time,
                price=current_price,
                confidence=Decimal("0"),
                metadata={"reason": "cooldown"},
            )

        # Priority 3: Regime detection
        if self.config.use_regime_filter:
            self._current_regime, _ = self._regime_detector.detect_with_scores_f(highs, lows, closes)
        else:
            self._current_regime = MarketRegime.STRONG_TREND

        # Skip high volatility
        if self._current_regime == MarketRegime.HIGH_VOLATILITY:
            return Signal(
                signal_type=SignalType.HOLD,
                pair=context.pair,
                timestamp=current_time,
                price=current_price,
                confidence=Decimal("0"),
                metadata={"reason": "high_volatility"},
            )

        # Priority 4: MA crossover
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

        # Check for crossover only if not in position
        signal_type = SignalType.HOLD
        
        if self._trade_direction_f is None and self._prev_fast_ma_f is not None and self._prev_slow_ma_f is not None:
            if self._prev_fast_ma_f <= self._prev_slow_ma_f and fast_ma_f > slow_ma_f:
                signal_type = SignalType.LONG
            elif self._prev_fast_ma_f >= self._prev_slow_ma_f and fast_ma_f < slow_ma_f:
                signal_type = SignalType.SHORT

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
            if rsi is not None:
                if signal_type == SignalType.LONG and rsi > self.config.rsi_overbought:
                    return Signal(
                        signal_type=SignalType.HOLD,
                        pair=context.pair,
                        timestamp=current_time,
                        price=current_price,
                        confidence=Decimal("0"),
                        metadata={"reason": "rsi_overbought", "rsi": rsi},
                    )
                if signal_type == SignalType.SHORT and rsi < self.config.rsi_oversold:
                    return Signal(
                        signal_type=SignalType.HOLD,
                        pair=context.pair,
                        timestamp=current_time,
                        price=current_price,
                        confidence=Decimal("0"),
                        metadata={"reason": "rsi_oversold", "rsi": rsi},
                    )

        # Set ATR exit on new entry
        if signal_type in (SignalType.LONG, SignalType.SHORT):
            direction = "long" if signal_type == SignalType.LONG else "short"
            self._set_atr_exit(highs, lows, closes, direction, current_price_f)

        ma_spread = abs(fast_ma_f - slow_ma_f) / slow_ma_f * 100
        confidence = min(Decimal(str(ma_spread / 10)), Decimal("1.0"))
        
        metadata = {
            "fast_ma": fast_ma_f,
            "slow_ma": slow_ma_f,
            "ma_spread_pct": ma_spread,
            "strategy": "final_optimized",
            "regime": self._current_regime.value,
        }
        
        if self.config.use_rsi_filter:
            rsi = calculate_rsi_f(closes, self.config.rsi_period)
            if rsi is not None:
                metadata["rsi"] = rsi

        return Signal(
            signal_type=signal_type,
            pair=context.pair,
            timestamp=current_time,
            price=current_price,
            confidence=confidence,
            metadata=metadata,
        )
