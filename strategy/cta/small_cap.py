
"""
Small Capital Strategy: Maximum hold, minimum trades.
Key principles:
1. SMA(200) trend filter — only trade when price strongly trends
2. Minimum hold 48 bars (2 days on 1h) — avoid whipsaws
3. Minimum profit 5% before considering exit
4. At most 1 trade per week
"""
import sys
sys.path.insert(0, '/home/roler/Code/CryptoQuant')

from data.repository import get_repository
from strategy.cta import calculate_ma_f, calculate_rsi_f, calculate_adx_f
from strategy.base import Signal, SignalType, StrategyBase, StrategyContext
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional
import structlog

logger = structlog.get_logger(__name__)

@dataclass
class SmallCapConfig:
    trend_ma: int = 200       # Long-term trend MA
    entry_ma: int = 50        # Entry signal MA
    adx_period: int = 14
    adx_threshold: float = 30.0  # Strong trend only
    min_hold_bars: int = 48    # Minimum hold (2 days on 1h)
    min_profit_pct: float = 0.05  # 5% minimum profit target
    cooldown_bars: int = 168   # 1 week cooldown between trades
    stop_loss_pct: float = 0.10  # 10% stop loss


class SmallCapStrategy(StrategyBase):
    """Ultra-low-frequency trend strategy for small capital.
    
    Only enters when:
    - Price > SMA(200) (bull trend)
    - ADX > 30 (strong trend)
    - SMA(50) crosses above SMA(200)
    
    Holds until:
    - Stop loss hit OR
    - 5%+ profit achieved AND trend weakens
    """
    
    def __init__(self, name: str = "small_cap", params: Optional[Dict[str, Any]] = None) -> None:
        super().__init__(name, params)
        self.config = SmallCapConfig(
            trend_ma=self.get_param("trend_ma", 200),
            entry_ma=self.get_param("entry_ma", 50),
            adx_period=self.get_param("adx_period", 14),
            adx_threshold=float(self.get_param("adx_threshold", 30.0)),
            min_hold_bars=self.get_param("min_hold_bars", 48),
            min_profit_pct=float(self.get_param("min_profit_pct", 0.05)),
            cooldown_bars=self.get_param("cooldown_bars", 168),
            stop_loss_pct=float(self.get_param("stop_loss_pct", 0.10)),
        )
        
        self._position: Optional[str] = None
        self._entry_price: Optional[float] = None
        self._stop_price: Optional[float] = None
        self._bars_held: int = 0
        self._cooldown_remaining: int = 0
        self._entry_ma_prev: Optional[float] = None
        self._trend_ma_prev: Optional[float] = None
    
    def initialize(self) -> None:
        self._position = None
        self._entry_price = None
        self._bars_held = 0
        self._cooldown_remaining = 0
    
    def generate_signal(self, context: StrategyContext) -> Signal:
        closes = context.closes_f
        highs = context.highs_f
        lows = context.lows_f
        price_f = float(context.current_price)
        current_time = context.current_time
        
        min_bars = self.config.trend_ma + 5
        if len(closes) < min_bars:
            return Signal(SignalType.HOLD, context.pair, current_time, 
                         context.current_price, Decimal("0"), {"reason": "insufficient_data"})
        
        # Cooldown
        if self._cooldown_remaining > 0:
            self._cooldown_remaining -= 1
        
        # Calculate indicators
        trend_ma = calculate_ma_f(closes, self.config.trend_ma, "sma")
        entry_ma = calculate_ma_f(closes, self.config.entry_ma, "sma")
        adx = calculate_adx_f(highs, lows, closes, self.config.adx_period)
        
        if trend_ma is None or entry_ma is None:
            return Signal(SignalType.HOLD, context.pair, current_time,
                         context.current_price, Decimal("0"), {"reason": "ma_failed"})
        
        # Track MA crosses
        entry_prev = self._entry_ma_prev
        trend_prev = self._trend_ma_prev
        self._entry_ma_prev = entry_ma
        self._trend_ma_prev = trend_ma
        
        # === EXIT LOGIC ===
        if self._position:
            self._bars_held += 1
            
            # Stop loss
            if self._position == "long" and self._stop_price and price_f <= self._stop_price:
                self._reset()
                return Signal(SignalType.CLOSE_LONG, "", current_time, context.current_price,
                             Decimal("1.0"), {"reason": "stop_loss"})
            
            # Take profit only after min hold
            if self._bars_held >= self.config.min_hold_bars:
                profit_pct = (price_f - self._entry_price) / self._entry_price
                if self._position == "long" and profit_pct > self.config.min_profit_pct:
                    # Exit if trend weakens
                    if adx and adx < self.config.adx_threshold * 0.7:
                        self._reset()
                        return Signal(SignalType.CLOSE_LONG, "", current_time, context.current_price,
                                     Decimal("0.8"), {"reason": "take_profit", "profit_pct": profit_pct})
            
            # Exit if trend reverses
            if self._position == "long" and entry_ma < trend_ma and price_f < trend_ma:
                self._reset()
                return Signal(SignalType.CLOSE_LONG, "", current_time, context.current_price,
                             Decimal("0.7"), {"reason": "trend_reversal"})
        
        # === ENTRY LOGIC (LONG ONLY for small cap simplicity) ===
        if self._position is None and self._cooldown_remaining <= 0:
            # Bullish conditions
            price_above_trend = price_f > trend_ma
            ma_bullish = entry_ma > trend_ma
            strong_trend = adx is not None and adx > self.config.adx_threshold
            
            # Entry: golden cross + strong trend
            if (price_above_trend and ma_bullish and strong_trend and 
                entry_prev is not None and trend_prev is not None and
                entry_prev <= trend_prev and entry_ma > trend_ma):  # Just crossed
                
                self._position = "long"
                self._entry_price = price_f
                self._stop_price = price_f * (1 - self.config.stop_loss_pct)
                self._bars_held = 0
                
                return Signal(SignalType.LONG, context.pair, current_time, context.current_price,
                             Decimal("0.9"), {"reason": "golden_cross", "adx": adx})
        
        return Signal(SignalType.HOLD, context.pair, current_time, context.current_price,
                     Decimal("0"), {"price_above_trend": price_f > trend_ma if trend_ma else False})
    
    def _reset(self):
        self._position = None
        self._entry_price = None
        self._stop_price = None
        self._bars_held = 0
        self._cooldown_remaining = self.config.cooldown_bars
