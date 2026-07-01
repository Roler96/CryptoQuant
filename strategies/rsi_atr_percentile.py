"""RSI ATR Percentile — oscillator + self-calibrating volatility filter for 5m.

Adapted from the winning research template: normalized oscillator (RSI) +
ATR expansion at 80th percentile + trend filter. Designed for 5m timeframe
where high-frequency noise demands stricter filtering.

v1.0.0 — 5m-optimized variant of the RSIExpansionTrend family.
          Entry (long):  RSI(28) > 55 AND bar_range > 80th_pctile ATR(14,50)
                         AND close > SMA(100)
          Entry (short): RSI(28) < 45 AND bar_range > 80th_pctile ATR
                         AND close < SMA(100)
          Exit (long):   RSI < 45 OR close < SMA(100)
          Exit (short):  RSI > 55 OR close > SMA(100)

The ATR percentile filter is self-calibrating: "80th percentile of ATR(14)
over last 50 bars" adapts to changing volatility regimes without hardcoding
a fixed multiplier. This avoids the commission fragility of fixed-threshold
expansion filters on 5m.
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import atr, rsi, sma


class RSIATRPercentile(Strategy):
    """RSI oscillator + ATR percentile volatility filter + SMA trend.

    Parameters:
        rsi_period: RSI lookback (default 28 — ~2.3h on 5m)
        rsi_entry: RSI threshold for long entry (default 55)
        rsi_exit: RSI threshold for exit (default 45)
        atr_period: ATR lookback (default 14)
        atr_percentile_window: Rolling window for percentile calc (default 50)
        atr_percentile: Percentile threshold (default 80)
        sma_period: SMA trend filter period (default 100 — ~8.3h on 5m)
    """

    timeframe = "5m"
    min_bars = 200
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "rsi_period": 28,
        "rsi_entry": 55,
        "rsi_exit": 45,
        "atr_period": 14,
        "atr_percentile_window": 50,
        "atr_percentile": 80,
        "sma_period": 100,
    }

    @property
    def name(self) -> str:
        return "RSIATRPercentile"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        df = self.preprocess(df)
        close: pd.Series = df["close"]

        rsi_period = self.params["rsi_period"]
        rsi_entry = self.params["rsi_entry"]
        rsi_exit = self.params["rsi_exit"]
        atr_period = self.params["atr_period"]
        atr_pct_window = self.params["atr_percentile_window"]
        atr_pct = self.params["atr_percentile"]
        sma_period = self.params["sma_period"]

        # Indicators
        rsi_val = rsi(close, period=rsi_period)
        atr_val = atr(df, period=atr_period)
        bar_range = df["high"] - df["low"]
        sma_trend = sma(close, sma_period)

        # ATR percentile: rolling 80th percentile of ATR over window
        atr_pct_threshold = atr_val.rolling(atr_pct_window).apply(
            lambda x: np.percentile(x, atr_pct), raw=True
        )

        # Conditions
        expansion = bar_range > atr_pct_threshold
        rsi_strong = rsi_val > rsi_entry
        rsi_weak = rsi_val < rsi_exit
        above_trend = close > sma_trend
        below_trend = close < sma_trend
        valid = ~(rsi_val.isna() | atr_val.isna() | atr_pct_threshold.isna() | sma_trend.isna())

        # Entry: 3 conditions (RSI + ATR expansion + trend)
        long_entry = rsi_strong & expansion & above_trend & valid
        short_entry = rsi_weak & expansion & below_trend & valid

        # Exit
        exit_long = rsi_weak | below_trend
        exit_short = rsi_strong | above_trend

        # Stateful signal generation
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
