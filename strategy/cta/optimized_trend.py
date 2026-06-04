"""Optimized Trend Following Strategy.

Key optimizations over default CTA strategy:
1. EMA instead of SMA for faster signal response
2. Tighter MA periods (7/21) for better trend capture
3. Stricter ADX filter (threshold 30) to avoid ranging markets
4. Wider RSI bands (25/75) to reduce false signals
5. ATR-based exit with tighter stop (1.5x) and take profit (2.5x)
6. Volume confirmation on breakouts
7. Cooldown period after stop-loss to avoid revenge trading
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
    detect_breakout_f,
)
from strategy.regime import MarketRegime, RegimeDetector

logger = structlog.get_logger(__name__)


@dataclass
class OptimizedTrendConfig:
    """Optimized configuration for trend following."""
    # MA crossover - EMA for faster response
    fast_ma_period: int = 7
    slow_ma_period: int = 21
    ma_type: str = "ema"
    
    # RSI filter - wider bands
    use_rsi_filter: bool = True
    rsi_period: int = 14
    rsi_overbought: float = 75.0
    rsi_oversold: float = 25.0
    
    # ADX filter - stricter
    use_adx_filter: bool = True
    adx_period: int = 14
    adx_threshold: float = 30.0
    
    # ATR exit - tighter stop, reasonable take
    use_atr_exit: bool = True
    atr_period: int = 14
    atr_stop_multiplier: float = 1.5
    atr_take_multiplier: float = 2.5
    
    # Regime filter
    use_regime_filter: bool = True
    regime_adx_period: int = 14
    regime_chop_period: int = 14
    regime_atr_period: int = 14
    
    # Volume confirmation
    use_volume_filter: bool = True
    volume_lookback: int = 20
    volume_multiplier: float = 1.2
    
    # Cooldown after stop loss (bars)
    cooldown_after_stop: int = 5


class OptimizedTrendStrategy(StrategyBase):
    """Optimized trend following strategy with multiple filters."""

    def __init__(self, name: str = "optimized_trend", params: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(name, params)
        
        self.config = OptimizedTrendConfig(
            fast_ma_period=self.get_param("fast_ma_period", 7),
            slow_ma_period=self.get_param("slow_ma_period", 21),
            ma_type=self.get_param("ma_type", "ema"),
            use_rsi_filter=self.get_param("use_rsi_filter", True),
            rsi_period=self.get_param("rsi_period", 14),
            rsi_overbought=float(self.get_param("rsi_overbought", 75.0)),
            rsi_oversold=float(self.get_param("rsi_oversold", 25.0)),
            use_adx_filter=self.get_param("use_adx_filter", True),
            adx_period=self.get_param("adx_period", 14),
            adx_threshold=float(self.get_param("adx_threshold", 30.0)),
            use_atr_exit=self.get_param("use_atr_exit", True),
            atr_period=self.get_param("atr_period", 14),
            atr_stop_multiplier=float(self.get_param("atr_stop_multiplier", 1.5)),
            atr_take_multiplier=float(self.get_param("atr_take_multiplier", 2.5)),
            use_regime_filter=self.get_param("use_regime_filter", True),
            regime_adx_period=self.get_param("regime_adx_period", 14),
            regime_chop_period=self.get_param("regime_chop_period", 14),
            regime_atr_period=self.get_param("regime_atr_period", 14),
            use_volume_filter=self.get_param("use_volume_filter", True),
            volume_lookback=self.get_param("volume_lookback", 20),
            volume_multiplier=float(self.get_param("volume_multiplier", 1.2)),
            cooldown_after_stop=self.get_param("cooldown_after_stop", 5),
        )
        
        # Float state
        self._fast_ma_history_f: List[float] = []
        self._slow_ma_history_f: List[float] = []
        self._prev_fast_ma_f: Optional[float] = None
        self._prev_slow_ma_f: Optional[float] = None
        
        # Trade state
        self._trade_direction_f: Optional[str] = None
        self._trade_entry_price_f: Optional[float] = None
        self._trade_stop_price_f: Optional[float] = None
        self._trade_take_price_f: Optional[float] = None
        
        # Cooldown
        self._cooldown_remaining: int = 0
        
        # Regime detector
        self._regime_detector = RegimeDetector(
            adx_period=self.config.regime_adx_period,
            chop_period=self.config.regime_chop_period,
            atr_period=self.config.regime_atr_period,
        )
        self._current_regime: MarketRegime = MarketRegime.UNKNOWN
        
        self.logger = structlog.get_logger(__name__).bind(
            strategy=name,
            fast_period=self.config.fast_ma_period,
            slow_period=self.config.slow_ma_period,
        )

    def initialize(self) -> None:
        self.logger.info("Initializing optimized trend strategy")
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

    def _set_atr_exit_f(self, highs, lows, closes, direction, entry_price_f) -> None:
        atr = calculate_atr_f(highs, lows, closes, self.config.atr_period)
        if atr is None:
            atr = entry_price_f * 0.02  # 2% fallback
        
        if direction == "long":
            self._trade_stop_price_f = entry_price_f - (atr * self.config.atr_stop_multiplier)
            self._trade_take_price_f = entry_price_f + (atr * self.config.atr_take_multiplier)
        else:
            self._trade_stop_price_f = entry_price_f + (atr * self.config.atr_stop_multiplier)
            self._trade_take_price_f = entry_price_f - (atr * self.config.atr_take_multiplier)
        
        self._trade_direction_f = direction
        self._trade_entry_price_f = entry_price_f

    def _check_atr_exit(self, current_price_f, current_time) -> Optional[Signal]:
        if self._trade_direction_f is None or self._trade_stop_price_f is None:
            return None
        
        direction = self._trade_direction_f
        if direction == "long":
            if current_price_f <= self._trade_stop_price_f:
                self._reset_trade_state_f()
                self._cooldown_remaining = self.config.cooldown_after_stop
                return Signal(
                    signal_type=SignalType.CLOSE_LONG,
                    pair="", timestamp=current_time,
                    price=Decimal(str(current_price_f)), confidence=Decimal("1.0"),
                    metadata={"reason": "atr_stop_loss"},
                )
            if current_price_f >= self._trade_take_price_f:
                self._reset_trade_state_f()
                return Signal(
                    signal_type=SignalType.CLOSE_LONG,
                    pair="", timestamp=current_time,
                    price=Decimal(str(current_price_f)), confidence=Decimal("1.0"),
                    metadata={"reason": "atr_take_profit"},
                )
        elif direction == "short":
            if current_price_f >= self._trade_stop_price_f:
                self._reset_trade_state_f()
                self._cooldown_remaining = self.config.cooldown_after_stop
                return Signal(
                    signal_type=SignalType.CLOSE_SHORT,
                    pair="", timestamp=current_time,
                    price=Decimal(str(current_price_f)), confidence=Decimal("1.0"),
                    metadata={"reason": "atr_stop_loss"},
                )
            if current_price_f <= self._trade_take_price_f:
                self._reset_trade_state_f()
                return Signal(
                    signal_type=SignalType.CLOSE_SHORT,
                    pair="", timestamp=current_time,
                    price=Decimal(str(current_price_f)), confidence=Decimal("1.0"),
                    metadata={"reason": "atr_take_profit"},
                )
        return None

    def _check_volume_confirmation(self, volumes_f) -> bool:
        if not self.config.use_volume_filter or len(volumes_f) < self.config.volume_lookback + 1:
            return True  # No filter if insufficient data
        
        current_volume = volumes_f[-1]
        avg_volume = sum(volumes_f[-(self.config.volume_lookback + 1):-1]) / self.config.volume_lookback
        
        if avg_volume == 0:
            return True
        
        return current_volume >= (avg_volume * self.config.volume_multiplier)

    def generate_signal(self, context: StrategyContext) -> Signal:
        closes = context.closes_f
        highs = context.highs_f
        lows = context.lows_f
        volumes = context.volumes_f
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

        # Priority 1: Check ATR exit
        atr_exit = self._check_atr_exit(current_price_f, current_time)
        if atr_exit is not None:
            return atr_exit
        
        # Priority 2: Cooldown check
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

        # Skip entries in ranging markets
        if self._current_regime == MarketRegime.RANGING and self._trade_direction_f is None:
            return Signal(
                signal_type=SignalType.HOLD,
                pair=context.pair,
                timestamp=current_time,
                price=current_price,
                confidence=Decimal("0"),
                metadata={"reason": "ranging_market"},
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

        # Check for crossover
        signal_type = SignalType.HOLD
        
        if self._prev_fast_ma_f is not None and self._prev_slow_ma_f is not None:
            # Golden cross
            if self._prev_fast_ma_f <= self._prev_slow_ma_f and fast_ma_f > slow_ma_f:
                signal_type = SignalType.LONG
            # Death cross
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

        # Filter 1: ADX confirmation
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

        # Filter 2: RSI confirmation
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

        # Filter 3: Volume confirmation
        if self.config.use_volume_filter:
            if not self._check_volume_confirmation(volumes):
                return Signal(
                    signal_type=SignalType.HOLD,
                    pair=context.pair,
                    timestamp=current_time,
                    price=current_price,
                    confidence=Decimal("0"),
                    metadata={"reason": "volume_too_low"},
                )

        # All filters passed - set ATR exit and return signal
        if signal_type in (SignalType.LONG, SignalType.SHORT):
            direction = "long" if signal_type == SignalType.LONG else "short"
            self._set_atr_exit_f(highs, lows, closes, direction, current_price_f)
        
        # Calculate confidence
        ma_spread = abs(fast_ma_f - slow_ma_f) / slow_ma_f * 100
        confidence = min(Decimal(str(ma_spread / 10)), Decimal("1.0"))
        
        metadata = {
            "fast_ma": fast_ma_f,
            "slow_ma": slow_ma_f,
            "ma_spread_pct": ma_spread,
            "strategy": "optimized_trend",
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
