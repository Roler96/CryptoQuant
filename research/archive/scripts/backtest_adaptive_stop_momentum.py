"""AdaptiveStopMomentum — momentum entry with dynamic ATR trailing stop.

Based on: "Systematic Trend-Following with Adaptive Portfolio Construction" (Nguyen, 2026).
Simplified to single-asset: simple momentum entry + adaptive trailing stop that
widens in high-volatility and tightens in low-volatility regimes.

Entry: |pct_change(lookback)| > entry_threshold
Exit: dynamic trailing stop = max(prev_stop, close - alpha * ATR) for longs
                               min(prev_stop, close + alpha * ATR) for shorts
"""

import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import atr


class AdaptiveStopMomentum(Strategy):
    """Momentum strategy with adaptive ATR trailing stop.

    Entry fires when price moves > threshold% over lookback. Once in position,
    a trailing stop trails the price at `atr_multiplier * ATR` distance,
    ratcheting in the profitable direction but never widening against it.

    Parameters:
        momentum_lookback: int = 20       Lookback bars for momentum calculation
        entry_threshold: float = 0.02      Min absolute pct change for entry (2%)
        atr_period: int = 14               ATR smoothing period
        atr_multiplier: float = 2.5        Stop distance multiplier (paper optimal)
    """

    timeframe = "1h"
    min_bars = 100       # enough for ATR(14) + momentum_lookback(20) warmup
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "momentum_lookback": 20,
        "entry_threshold": 0.02,       # 2% price change
        "atr_period": 14,
        "atr_multiplier": 2.5,         # from Nguyen (2026) optimal range 2.0-3.0
    }

    @property
    def name(self) -> str:
        return "AdaptiveStopMomentum"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        df = self.preprocess(df)

        lookback = self.params["momentum_lookback"]
        threshold = self.params["entry_threshold"]
        atr_period = self.params["atr_period"]
        atr_mult = self.params["atr_multiplier"]

        close = df["close"]
        high = df["high"]
        low = df["low"]

        # Calculate indicators
        momentum = (close - close.shift(lookback)) / close.shift(lookback)
        atr_vals = atr(df, atr_period)

        n = len(df)
        signal = pd.Series(0, index=df.index, dtype=int)

        in_position = False
        position_side = 0   # 1=long, -1=short
        trailing_stop = None

        for i in range(n):
            if in_position:
                # Update trailing stop (ratchet only in profitable direction)
                if position_side == 1:  # long
                    new_stop = close.iloc[i] - atr_mult * atr_vals.iloc[i]
                    if trailing_stop is None or new_stop > trailing_stop:
                        trailing_stop = new_stop
                    # Check if stop hit against bar low (no look-ahead)
                    if low.iloc[i] <= trailing_stop:
                        signal.iloc[i] = 0  # exit via signal_reverse
                        in_position = False
                        trailing_stop = None
                    else:
                        signal.iloc[i] = 1  # stay long
                else:  # short
                    new_stop = close.iloc[i] + atr_mult * atr_vals.iloc[i]
                    if trailing_stop is None or new_stop < trailing_stop:
                        trailing_stop = new_stop
                    # Check if stop hit against bar high
                    if high.iloc[i] >= trailing_stop:
                        signal.iloc[i] = 0  # exit via signal_reverse
                        in_position = False
                        trailing_stop = None
                    else:
                        signal.iloc[i] = -1  # stay short
            else:
                # Check for entry signals
                if pd.notna(momentum.iloc[i]) and pd.notna(atr_vals.iloc[i]):
                    if momentum.iloc[i] > threshold:
                        signal.iloc[i] = 1
                        in_position = True
                        position_side = 1
                        trailing_stop = close.iloc[i] - atr_mult * atr_vals.iloc[i]
                    elif momentum.iloc[i] < -threshold:
                        signal.iloc[i] = -1
                        in_position = True
                        position_side = -1
                        trailing_stop = close.iloc[i] + atr_mult * atr_vals.iloc[i]

        return signal
