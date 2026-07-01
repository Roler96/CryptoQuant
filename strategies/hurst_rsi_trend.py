"""Hurst RSI Trend — fractal regime filter + RSI momentum + ATR expansion.

Combines the three strongest findings from 73-strategy research:
1. Hurst exponent for statistical trend detection (4/4 OOS, universal)
2. RSI oscillator for momentum timing (top-1 research template)
3. ATR percentile for self-calibrating volatility confirmation

Entry (long):  Hurst(200) > 0.55 AND RSI(14) > 55 AND bar_range > ATR 80%ile
               AND close > SMA(100)
Entry (short): Hurst(200) > 0.55 AND RSI(14) < 45 AND bar_range > ATR 80%ile
               AND close < SMA(100)
Exit (long):   RSI < 45 OR Hurst < 0.45 OR close < SMA(100)
Exit (short):  RSI > 55 OR Hurst < 0.45 OR close > SMA(100)

The Hurst filter ensures we only trade in statistically trending regimes,
eliminating the mean-reverting noise that kills pure RSI strategies on 5m.
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import atr, rsi, sma, ema, hurst_exponent


class HurstRSITrend(Strategy):
    """Hurst regime filter + RSI momentum + ATR expansion + SMA trend.

    Parameters:
        hurst_period: Hurst exponent window (default 200 — 16.7h on 5m)
        hurst_entry: Hurst min for entry (default 0.55)
        hurst_exit: Hurst floor for exit (default 0.45)
        rsi_period: RSI lookback (default 14 — 70min on 5m)
        rsi_entry: RSI threshold for long (default 55)
        rsi_exit: RSI threshold for exit/short (default 45)
        atr_period: ATR lookback (default 14)
        atr_pct_window: Percentile window (default 50)
        atr_pct: Percentile threshold (default 80)
        sma_period: SMA trend filter (default 100 — 8.3h on 5m)
    """

    timeframe = "5m"
    min_bars = 300
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "hurst_period": 200,
        "hurst_entry": 0.55,
        "hurst_exit": 0.45,
        "rsi_period": 14,
        "rsi_entry": 55,
        "rsi_exit": 45,
        "atr_period": 14,
        "atr_pct_window": 50,
        "atr_pct": 80,
        "sma_period": 100,
    }

    @property
    def name(self) -> str:
        return "HurstRSITrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        df = self.preprocess(df)
        close: pd.Series = df["close"]

        hp = self.params["hurst_period"]
        he = self.params["hurst_entry"]
        hx = self.params["hurst_exit"]
        rp = self.params["rsi_period"]
        re = self.params["rsi_entry"]
        rx = self.params["rsi_exit"]
        ap = self.params["atr_period"]
        aw = self.params["atr_pct_window"]
        apct = self.params["atr_pct"]
        sp = self.params["sma_period"]

        # Indicators
        h = hurst_exponent(close, period=hp)
        rsi_val = rsi(close, period=rp)
        atr_val = atr(df, period=ap)
        bar_range = df["high"] - df["low"]
        sma_trend = sma(close, sp)

        atr_pct_threshold = atr_val.rolling(aw).apply(
            lambda x: np.percentile(x, apct), raw=True
        )

        # Conditions
        trending = h > he
        trend_lost = h < hx
        rsi_strong = rsi_val > re
        rsi_weak = rsi_val < rx
        expansion = bar_range > atr_pct_threshold
        above_trend = close > sma_trend
        below_trend = close < sma_trend
        valid = ~(h.isna() | rsi_val.isna() | atr_val.isna() |
                  atr_pct_threshold.isna() | sma_trend.isna())

        # Entry: 4 conditions
        long_entry = trending & rsi_strong & expansion & above_trend & valid
        short_entry = trending & rsi_weak & expansion & below_trend & valid

        # Exit
        exit_long = rsi_weak | trend_lost | below_trend
        exit_short = rsi_strong | trend_lost | above_trend

        # Stateful
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0

        for i in range(n):
            if not valid.iloc[i]:
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
