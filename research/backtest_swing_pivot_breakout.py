"""Swing Pivot Breakout strategy.

Price action-based breakout strategy using swing pivot detection —
the simplest form of market structure analysis. A swing high occurs
when a bar's high is the highest of the surrounding N bars; a swing
low when a bar's low is the lowest. Price breaking above/below a
confirmed swing pivot signals a structural regime shift.

Entry (long):  close > previous swing high AND close > prev close
Entry (short): close < previous swing low AND close < prev close
Exit:          trailing stop at 2× ATR(14)

This is breakout-based (not oscillator/crossover) — proven family
for 4h viability. Swing pivot levels represent market-agreed
support/resistance, fundamentally different from channel-based
breakouts (Donchian, BB, Keltner) tested in previous loops.

Reference: Market structure / price action — Wyckoff methodology;
swing pivot detection common in technical analysis literature.
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import atr


class SwingPivotBreakout(Strategy):
    """Swing pivot breakout with trailing stop exit.

    Entry requires price breaking above/below a confirmed swing
    pivot level AND close direction confirmation.
    Exactly 2 entry conditions.

    Parameters:
        pivot_window: N bars each side for pivot detection (default 5).
        atr_period: ATR period for trailing stop (default 14).
        trailing_mult: Trailing stop ATR multiplier (default 2.0).
    """

    timeframe = "1h"
    min_bars = 50  # pivot_window * 2 + atr_period + buffer
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "pivot_window": 5,
        "atr_period": 14,
        "trailing_mult": 2.0,
    }

    @property
    def name(self) -> str:
        return "SwingPivotBreakout"

    def _find_swing_highs(self, high: pd.Series, n: int) -> pd.Series:
        """Find swing highs: bar i is a swing high if its high is the
        highest in [i-n, i+n]. Returns boolean Series.
        """
        is_peak = pd.Series(False, index=high.index)
        for i in range(n, len(high) - n):
            window = high.iloc[i-n:i+n+1]
            if high.iloc[i] == window.max():
                # Ensure it's strictly higher than neighbors to avoid
                # adjacent equal highs producing multiple peaks
                if (high.iloc[i] > high.iloc[i-1] or
                    high.iloc[i] > high.iloc[i+1]):
                    is_peak.iloc[i] = True
        return is_peak

    def _find_swing_lows(self, low: pd.Series, n: int) -> pd.Series:
        """Find swing lows: bar i is a swing low if its low is the
        lowest in [i-n, i+n]. Returns boolean Series.
        """
        is_trough = pd.Series(False, index=low.index)
        for i in range(n, len(low) - n):
            window = low.iloc[i-n:i+n+1]
            if low.iloc[i] == window.min():
                if (low.iloc[i] < low.iloc[i-1] or
                    low.iloc[i] < low.iloc[i+1]):
                    is_trough.iloc[i] = True
        return is_trough

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from swing pivot breakout.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]
        high: pd.Series = df["high"]    # type: ignore[assignment]
        low: pd.Series = df["low"]      # type: ignore[assignment]

        n = self.params["pivot_window"]
        atr_period = self.params["atr_period"]
        trailing_mult = self.params["trailing_mult"]

        # Find swing points
        swing_highs = self._find_swing_highs(high, n)
        swing_lows = self._find_swing_lows(low, n)

        # Track the most recent swing pivot level
        # A pivot is "confirmed" n bars after it occurs
        prev_high = pd.Series(np.nan, index=df.index)
        prev_low = pd.Series(np.nan, index=df.index)
        last_swing_high = np.nan
        last_swing_low = np.nan

        for i in range(len(df)):
            if i >= n and swing_highs.iloc[i - n]:
                last_swing_high = high.iloc[i - n]
            if i >= n and swing_lows.iloc[i - n]:
                last_swing_low = low.iloc[i - n]
            prev_high.iloc[i] = last_swing_high
            prev_low.iloc[i] = last_swing_low

        # ATR for trailing stop
        atr_val = atr(df, period=atr_period)
        trail_dist = atr_val * trailing_mult

        # Entry signals (2 conditions: breakout + close direction)
        breakout_long = close > prev_high
        breakout_short = close < prev_low

        close_rising = close > close.shift(1)
        close_falling = close < close.shift(1)

        long_entry = breakout_long & close_rising
        short_entry = breakout_short & close_falling

        # Stateful signal generation with trailing stop
        n_bars = len(df)
        signal_arr = np.zeros(n_bars, dtype=int)
        position = 0
        entry_price = 0.0
        best_price = 0.0  # Best price since entry (high for long, low for short)

        for i in range(n_bars):
            if pd.isna(prev_high.iloc[i]) or pd.isna(atr_val.iloc[i]):
                signal_arr[i] = 0
                continue

            if position == 1:
                # Update trailing stop
                if close.iloc[i] > best_price:
                    best_price = close.iloc[i]
                stop_level = best_price - trail_dist.iloc[i]
                if close.iloc[i] <= stop_level:
                    position = 0
                    if short_entry.iloc[i]:
                        position = -1
                        entry_price = close.iloc[i]
                        best_price = close.iloc[i]
                elif short_entry.iloc[i]:
                    # Flip directly if opposite breakout fires
                    position = -1
                    entry_price = close.iloc[i]
                    best_price = close.iloc[i]

            elif position == -1:
                if close.iloc[i] < best_price:
                    best_price = close.iloc[i]
                stop_level = best_price + trail_dist.iloc[i]
                if close.iloc[i] >= stop_level:
                    position = 0
                    if long_entry.iloc[i]:
                        position = 1
                        entry_price = close.iloc[i]
                        best_price = close.iloc[i]
                elif long_entry.iloc[i]:
                    position = 1
                    entry_price = close.iloc[i]
                    best_price = close.iloc[i]

            elif position == 0:
                if long_entry.iloc[i]:
                    position = 1
                    entry_price = close.iloc[i]
                    best_price = close.iloc[i]
                elif short_entry.iloc[i]:
                    position = -1
                    entry_price = close.iloc[i]
                    best_price = close.iloc[i]

            signal_arr[i] = position

        return pd.Series(signal_arr, index=df.index, dtype=int)
