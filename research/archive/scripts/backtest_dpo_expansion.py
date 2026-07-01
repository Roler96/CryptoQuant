"""DPO Expansion — Detrended Price Oscillator + ATR Trend Expansion.

Combines the Detrended Price Oscillator (DPO) with an ATR expansion filter
that uses ATR exceeding its own SMA (trending volatility), distinct from
the bar-range-vs-ATR expansion used in DPOTrend.

Exactly 2 entry conditions:
  - DPO(20) zero-cross (cycle turn detection)
  - ATR(14) > SMA(ATR(14), 50) — volatility is expanding above its long-term baseline

Entry (long):   DPO(20) crosses ABOVE 0 AND ATR(14) > SMA(ATR(14), 50)
Entry (short):  DPO(20) crosses BELOW 0 AND ATR(14) > SMA(ATR(14), 50)
Exit (long):    DPO(20) crosses BELOW 0
Exit (short):   DPO(20) crosses ABOVE 0

DPO = Close - SMA(Close, N/2+1).shift(N/2+1)  — backward-centered to remove trend.
The centered SMA isolates cycles without future leakage — the displacement
is backward (positive shift), not forward.

Reference: William Blau — "Momentum, Direction, and Divergence" (1995).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import atr, sma


class DPOExpansion(Strategy):
    """DPO zero-cross with ATR-trend expansion confirmation.

    Entry requires DPO to cross zero (cycle turn) AND ATR to be above its
    long-term SMA (volatility expansion).  This is a different expansion
    filter than DPOTrend's bar_range > multiplier*ATR — it uses the broader
    volatility regime rather than bar-level expansion.

    Parameters:
        dpo_period: DPO lookback period (default 20)
        atr_period: ATR period (default 14)
        atr_ma_period: SMA period on ATR for expansion baseline (default 50)
    """

    timeframe = "1h"
    min_bars = 300  # atr_ma_period + dpo_period + ATR warmup + buffer
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "dpo_period": 20,
        "atr_period": 14,
        "atr_ma_period": 50,
    }

    @property
    def name(self) -> str:
        return "DPOExpansion"

    def _compute_dpo(self, close: pd.Series, period: int) -> pd.Series:
        """Compute Detrended Price Oscillator (DPO).

        Standard formula: DPO = Close - SMA(Close, period).shift(period/2+1).
        The backward displacement centers the SMA, making the oscillator
        oscillate around zero without any forward-looking bias.

        Reference: StockCharts DPO definition.
        """
        n = period
        half = n // 2 + 1
        sma_val = sma(close, period=n)
        # Displace SMA backward by half bars to center it (no future leak)
        sma_shifted = sma_val.shift(half)
        dpo = close - sma_shifted
        return dpo

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from DPO zero-crosses + ATR trend expansion.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        dpo_period = self.params["dpo_period"]
        atr_period = self.params["atr_period"]
        atr_ma_period = self.params["atr_ma_period"]

        # Compute DPO
        dpo = self._compute_dpo(close, period=dpo_period)

        # Compute ATR expansion check: ATR > SMA(ATR, 50)
        atr_val = atr(df, period=atr_period)
        atr_sma = sma(atr_val, period=atr_ma_period)
        atr_expanding = atr_val > atr_sma

        # DPO zero-cross detection
        dpo_above = dpo > 0
        dpo_below = dpo < 0
        prev_above = dpo_above.shift(1).fillna(False)
        prev_below = dpo_below.shift(1).fillna(False)

        cross_up = dpo_above & ~prev_above.astype(bool)
        cross_down = dpo_below & ~prev_below.astype(bool)

        # Entry signals (2 conditions: DPO cross + ATR expanding)
        long_entry = cross_up & atr_expanding
        short_entry = cross_down & atr_expanding

        # Exit signals: reverse DPO zero-cross
        exit_long = cross_down
        exit_short = cross_up

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0

        for i in range(n):
            if pd.isna(dpo.iloc[i]) or pd.isna(atr_expanding.iloc[i]):
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
