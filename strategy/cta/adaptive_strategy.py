"""Aggressive optimized strategy with regime-adaptive logic.

Uses regime detection to switch between:
- STRONG_TREND: MA crossover (trend following)
- RANGING: Bollinger Bands mean reversion
- HIGH_VOLATILITY: Stay out of market

Also uses:
- Trailing stop to lock in profits
- Position sizing based on volatility
- Multi-timeframe confirmation
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
class AdaptiveConfig:
    """Configuration for regime-adaptive strategy."""
    # Trend mode
    trend_fast_ma: int = 5
    trend_slow_ma: int = 20
    trend_ma_type: str = "ema"
    
    # Ranging mode - Bollinger Bands
    bb_period: int = 20
    bb_std_dev: float = 2.0
    
    # Common filters
    rsi_period: int = 14
    rsi_overbought: float = 70.0
    rsi_oversold: float = 30.0
    
    # ADX
    adx_period: int = 14
    adx_trend_threshold: float = 25.0
    
    # ATR exits
    atr_period: int = 14
    atr_stop_multiplier: float = 2.0
    atr_trail_multiplier: float = 2.5
    atr_take_multiplier: float = 3.0
    
    # Regime
    regime_adx_period: int = 14
    regime_chop_period: int = 14
    regime_atr_period: int = 14


class AdaptiveStrategy(StrategyBase):
    """Regime-adaptive strategy that switches logic based on market state."""

    def __init__(self, name: str = "adaptive", params: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(name, params)
        
        self.config = AdaptiveConfig(
            trend_fast_ma=self.get_param("trend_fast_ma", 5),
            trend_slow_ma=self.get_param("trend_slow_ma", 20),
            trend_ma_type=self.get_param("trend_ma_type", "ema"),
            bb_period=self.get_param("bb_period", 20),
            bb_std_dev=float(self.get_param("bb_std_dev", 2.0)),
            rsi_period=self.get_param("rsi_period", 14),
            rsi_overbought=float(self.get_param("rsi_overbought", 70.0)),
            rsi_oversold=float(self.get_param("rsi_oversold", 30.0)),
            adx_period=self.get_param("adx_period", 14),
            adx_trend_threshold=float(self.get_param("adx_trend_threshold", 25.0)),
            atr_period=self.get_param("atr_period", 14),
            atr_stop_multiplier=float(self.get_param("atr_stop_multiplier", 2.0)),
            atr_trail_multiplier=float(self.get_param("atr_trail_multiplier", 2.5)),
            atr_take_multiplier=float(self.get_param("atr_take_multiplier", 3.0)),
            regime_adx_period=self.get_param("regime_adx_period", 14),
            regime_chop_period=self.get_param("regime_chop_period", 14),
            regime_atr_period=self.get_param("regime_atr_period", 14),
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
        self._trade_high_watermark_f: Optional[float] = None  # For trailing stop
        
        # Regime detector
        self._regime_detector = RegimeDetector(
            adx_period=self.config.regime_adx_period,
            chop_period=self.config.regime_chop_period,
            atr_period=self.config.regime_atr_period,
        )
        self._current_regime: MarketRegime = MarketRegime.UNKNOWN
        
        self.logger = structlog.get_logger(__name__).bind(strategy=name)

    def initialize(self) -> None:
        self.logger.info("Initializing adaptive strategy")
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
        self._trade_high_watermark_f = None

    def _calculate_bb(self, closes, period, std_dev_mult):
        """Calculate Bollinger Bands."""
        if len(closes) < period:
            return None, None, None
        
        recent = closes[-period:]
        sma = sum(recent) / period
        
        variance = sum((x - sma) ** 2 for x in recent) / period
        std = variance ** 0.5
        
        upper = sma + (std * std_dev_mult)
        lower = sma - (std * std_dev_mult)
        
        return sma, upper, lower

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
        """Update trailing stop based on price movement."""
        if self._trade_direction_f is None or self._trade_high_watermark_f is None:
            return
        
        atr = self._trade_stop_price_f  # Approximate ATR from stop distance
        if self._trade_direction_f == "long":
            if current_price_f > self._trade_high_watermark_f:
                self._trade_high_watermark_f = current_price_f
                new_stop = current_price_f - (atr * self.config.atr_trail_multiplier / self.config.atr_stop_multiplier)
                if new_stop > self._trade_stop_price_f:
                    self._trade_stop_price_f = new_stop

    def _check_atr_exit(self, current_price_f, current_time) -> Optional[Signal]:
        if self._trade_direction_f is None or self._trade_stop_price_f is None:
            return None
        
        # Update trailing stop
        self._update_trailing_stop(current_price_f)
        
        direction = self._trade_direction_f
        if direction == "long":
            if current_price_f <= self._trade_stop_price_f:
                self._reset_trade_state_f()
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

        if len(closes) < max(self.config.trend_slow_ma, self.config.bb_period) + 1:
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

        # Priority 2: Detect regime
        self._current_regime, scores = self._regime_detector.detect_with_scores_f(highs, lows, closes)

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

        # Priority 3: Generate signals based on regime
        signal_type = SignalType.HOLD
        metadata = {"regime": self._current_regime.value}

        if self._current_regime in (MarketRegime.STRONG_TREND, MarketRegime.WEAK_TREND):
            # Trend following mode
            signal_type, metadata = self._trend_logic(closes, highs, lows, current_price_f, current_time, scores)
        elif self._current_regime == MarketRegime.RANGING:
            # Mean reversion mode
            signal_type, metadata = self._ranging_logic(closes, highs, lows, current_price_f, current_time, scores)
        
        metadata["regime"] = self._current_regime.value
        
        if signal_type == SignalType.HOLD:
            return Signal(
                signal_type=SignalType.HOLD,
                pair=context.pair,
                timestamp=current_time,
                price=current_price,
                confidence=Decimal("0"),
                metadata=metadata,
            )

        # Set ATR exit on new entry
        if signal_type in (SignalType.LONG, SignalType.SHORT):
            direction = "long" if signal_type == SignalType.LONG else "short"
            self._set_atr_exit(highs, lows, closes, direction, current_price_f)

        return Signal(
            signal_type=signal_type,
            pair=context.pair,
            timestamp=current_time,
            price=current_price,
            confidence=metadata.get("confidence", Decimal("0.5")),
            metadata=metadata,
        )

    def _trend_logic(self, closes, highs, lows, current_price_f, current_time, scores):
        """Trend following logic using MA crossover."""
        metadata = {}
        
        fast_ma_f = calculate_ma_f(closes, self.config.trend_fast_ma, self.config.trend_ma_type)
        slow_ma_f = calculate_ma_f(closes, self.config.trend_slow_ma, self.config.trend_ma_type)

        if fast_ma_f is None or slow_ma_f is None:
            return SignalType.HOLD, metadata

        # Update MA history
        if self._fast_ma_history_f:
            self._prev_fast_ma_f = self._fast_ma_history_f[-1]
            self._prev_slow_ma_f = self._slow_ma_history_f[-1]

        self._fast_ma_history_f.append(fast_ma_f)
        self._slow_ma_history_f.append(slow_ma_f)

        max_history = max(self.config.trend_fast_ma, self.config.trend_slow_ma) * 2
        if len(self._fast_ma_history_f) > max_history:
            self._fast_ma_history_f = self._fast_ma_history_f[-max_history:]
            self._slow_ma_history_f = self._slow_ma_history_f[-max_history:]

        signal_type = SignalType.HOLD
        
        # Check for crossover only if not already in a position
        if self._trade_direction_f is None and self._prev_fast_ma_f is not None and self._prev_slow_ma_f is not None:
            if self._prev_fast_ma_f <= self._prev_slow_ma_f and fast_ma_f > slow_ma_f:
                signal_type = SignalType.LONG
            elif self._prev_fast_ma_f >= self._prev_slow_ma_f and fast_ma_f < slow_ma_f:
                signal_type = SignalType.SHORT

        # ADX filter
        adx = scores.get("adx")
        if adx is not None and adx < self.config.adx_trend_threshold:
            signal_type = SignalType.HOLD
            metadata["reason"] = "adx_too_low"

        # RSI filter
        if signal_type != SignalType.HOLD:
            rsi = calculate_rsi_f(closes, self.config.rsi_period)
            if rsi is not None:
                metadata["rsi"] = rsi
                if signal_type == SignalType.LONG and rsi > self.config.rsi_overbought:
                    signal_type = SignalType.HOLD
                    metadata["reason"] = "rsi_overbought"
                elif signal_type == SignalType.SHORT and rsi < self.config.rsi_oversold:
                    signal_type = SignalType.HOLD
                    metadata["reason"] = "rsi_oversold"

        if signal_type != SignalType.HOLD:
            ma_spread = abs(fast_ma_f - slow_ma_f) / slow_ma_f * 100
            metadata["confidence"] = min(Decimal(str(ma_spread / 10)), Decimal("1.0"))
            metadata["fast_ma"] = fast_ma_f
            metadata["slow_ma"] = slow_ma_f

        return signal_type, metadata

    def _ranging_logic(self, closes, highs, lows, current_price_f, current_time, scores):
        """Mean reversion logic using Bollinger Bands."""
        metadata = {}
        
        sma, bb_upper, bb_lower = self._calculate_bb(closes, self.config.bb_period, self.config.bb_std_dev)
        
        if sma is None or bb_upper is None or bb_lower is None:
            return SignalType.HOLD, metadata

        metadata["bb_upper"] = bb_upper
        metadata["bb_lower"] = bb_lower
        metadata["bb_middle"] = sma

        # Mean reversion: buy at lower band, sell at upper band
        signal_type = SignalType.HOLD
        
        # Only enter if not already in position
        if self._trade_direction_f is None:
            if current_price_f <= bb_lower:
                signal_type = SignalType.LONG
                metadata["reason"] = "bb_lower_touch"
            elif current_price_f >= bb_upper:
                signal_type = SignalType.SHORT
                metadata["reason"] = "bb_upper_touch"

        # RSI confirmation
        if signal_type != SignalType.HOLD:
            rsi = calculate_rsi_f(closes, self.config.rsi_period)
            if rsi is not None:
                metadata["rsi"] = rsi
                # For mean reversion, we want oversold to buy, overbought to sell
                if signal_type == SignalType.LONG and rsi > 50:
                    signal_type = SignalType.HOLD
                    metadata["reason"] = "rsi_not_oversold"
                elif signal_type == SignalType.SHORT and rsi < 50:
                    signal_type = SignalType.HOLD
                    metadata["reason"] = "rsi_not_overbought"

        if signal_type != SignalType.HOLD:
            bb_width = (bb_upper - bb_lower) / sma * 100
            metadata["confidence"] = min(Decimal(str(bb_width / 10)), Decimal("1.0"))

        return signal_type, metadata
