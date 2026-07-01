"""VIDYA Crossover Expansion strategy.

Trend-following strategy using VIDYA fast/slow crossover as the
primary entry trigger, confirmed by ATR expansion filter.  Exactly
2 entry conditions — matches the proven 2-condition template.

VIDYA (Chande, 1995) uses the Chande Momentum Oscillator (CMO) as
an efficiency ratio to adaptively smooth price.  Unlike KAMA (ER-based,
failed on 4h), VIDYA preserves directional information — it smooths
LESS during strong trends and MORE during choppy conditions.

Entry (long):  VIDYA(fast) crosses ABOVE VIDYA(slow) AND ATR expansion
Entry (short): VIDYA(fast) crosses BELOW VIDYA(slow) AND ATR expansion
Exit (long):   VIDYA fast crosses below VIDYA slow (reverse)
Exit (short):  VIDYA fast crosses above VIDYA slow (reverse)
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import atr, vidya


class VIDYACrossoverExpansion(Strategy):
    """VIDYA fast/slow crossover with ATR expansion confirmation.

    Parameters:
        vidya_fast_period: Effective period for fast VIDYA when CMO=1
            (default 6).
        vidya_slow_period: Effective period for slow VIDYA when CMO=1
            (default 24).
        vidya_cmo_period: CMO lookback for both VIDYAs (default 9).
        atr_period: ATR lookback (default 14).
        atr_percentile_window: Rolling percentile window for ATR (default 50).
        atr_percentile: Percentile threshold for expansion (default 80).
    """

    timeframe = "1h"
    min_bars = 200  # max(cmo=9, atr_window=50) + buffer + slow period
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "vidya_fast_period": 6,
        "vidya_slow_period": 24,
        "vidya_cmo_period": 9,
        "atr_period": 14,
        "atr_percentile_window": 50,
        "atr_percentile": 80,
    }

    @property
    def name(self) -> str:
        return "VIDYACrossoverExpansion"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from VIDYA crossover + ATR expansion.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        fast_period = self.params["vidya_fast_period"]
        slow_period = self.params["vidya_slow_period"]
        cmo_period = self.params["vidya_cmo_period"]
        atr_period = self.params["atr_period"]
        atr_window = self.params["atr_percentile_window"]
        atr_pct = self.params["atr_percentile"]

        # Compute indicators
        vidya_fast = vidya(close, vidya_period=fast_period, cmo_period=cmo_period)
        vidya_slow = vidya(close, vidya_period=slow_period, cmo_period=cmo_period)
        atr_val = atr(df, period=atr_period)
        bar_range = df["high"] - df["low"]

        # ATR expansion: bar_range > percentile of recent ATR
        atr_pctile = atr_val.rolling(atr_window, min_periods=atr_window).apply(
            lambda x: np.percentile(x, atr_pct), raw=True
        )
        expansion = bar_range > atr_pctile

        # Entry conditions (2 conditions: crossover + expansion)
        fast_above = vidya_fast > vidya_slow
        fast_below = vidya_fast < vidya_slow

        # Crossover detection: fast crosses above slow
        long_cross = fast_above & (~fast_above.shift(1).fillna(False).astype(bool))
        # Crossunder detection: fast crosses below slow
        short_cross = fast_below & (~fast_below.shift(1).fillna(False).astype(bool))

        long_entry = long_cross & expansion
        short_entry = short_cross & expansion

        # Exit: reverse crossover (no expansion requirement for exit)
        exit_long = short_cross
        exit_short = long_cross

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0

        for i in range(n):
            if (
                pd.isna(vidya_fast.iloc[i])
                or pd.isna(vidya_slow.iloc[i])
                or pd.isna(atr_val.iloc[i])
                or pd.isna(atr_pctile.iloc[i])
            ):
                signal_arr[i] = 0
                continue

            if position == 1:
                if exit_long.iloc[i]:
                    position = 0
                    if short_entry.iloc[i]:
                        position = -1
            elif position == -1:
                if exit_short.iloc[i]:
                    position = 0
                    if long_entry.iloc[i]:
                        position = 1
            elif position == 0:
                if long_entry.iloc[i]:
                    position = 1
                elif short_entry.iloc[i]:
                    position = -1

            signal_arr[i] = position

        return pd.Series(signal_arr, index=df.index, dtype=int)
