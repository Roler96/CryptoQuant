"""PVTTrend strategy — PVT (Price Volume Trend) crossover + EMA200.

Trend-following strategy using Price Volume Trend (PVT) crossover
confirmed by EMA200 trend filter. Exactly 2 entry conditions.

PVT = cumulative sum of (volume × %price_change) uses proportional
price change rather than binary sign (like OBV). This makes PVT a
middle ground between OBV (binary accumulation) and Force Index
(per-bar reset) — cumulative noise-smoothing with proportional
weighting for more nuanced signals.

OBV (4/4 main gate pass) proved cumulative volume works. PVT is the
natural extension with proportional weighting — should generate more
signals than OBV's binary crossings.

Entry (long):  PVT crosses above SMA(PVT, 20) AND close > EMA200
Entry (short): PVT crosses below SMA(PVT, 20) AND close < EMA200
Exit:          PVT crosses opposite SMA OR trailing stop at 2× ATR(14)

Reference: David L. Markstein — "How to Chart Your Way to Stock
Market Profits" (1965).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import (
    atr,
    ema,
    pvt_sma,
)


class PVTTrend(Strategy):
    """PVT crossover with EMA200 trend filter.

    Entry requires PVT crossover AND EMA200 alignment.
    Two conditions total.

    Parameters:
        pvt_sma_period: SMA period for PVT signal line (default 20).
        trend_period: EMA trend filter period (default 200).
        atr_period: ATR period for trailing stop (default 14).
        trailing_mult: ATR multiplier for trailing stop (default 2.0).
    """

    timeframe = "1h"
    min_bars = 210  # max(pvt_sma_period, trend_period) + buffer
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "pvt_sma_period": 20,
        "trend_period": 200,
        "atr_period": 14,
        "trailing_mult": 2.0,
    }

    @property
    def name(self) -> str:
        return "PVTTrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from PVT crossover + EMA trend.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        pvt_sma_period = self.params["pvt_sma_period"]
        trend_period = self.params["trend_period"]
        atr_period = self.params["atr_period"]
        trailing_mult = self.params["trailing_mult"]

        # Compute indicators
        pvt_df = pvt_sma(df, period=pvt_sma_period)
        pvt_val = pvt_df["pvt"]
        pvt_signal = pvt_df["signal"]
        ema_trend = ema(close, period=trend_period)
        atr_val = atr(df, period=atr_period)

        # Entry signals (2 conditions: PVT crossover + EMA trend)
        pvt_above = pvt_val > pvt_signal
        pvt_below = pvt_val < pvt_signal

        trend_up = close > ema_trend
        trend_down = close < ema_trend

        long_entry = pvt_above & trend_up
        short_entry = pvt_below & trend_down

        # Exit: PVT crosses back
        exit_long = pvt_below
        exit_short = pvt_above

        # Stateful signal generation with trailing stop
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short
        entry_price = 0.0
        trail_stop: float = float("inf")

        for i in range(n):
            if (
                pd.isna(pvt_val.iloc[i])
                or pd.isna(pvt_signal.iloc[i])
                or pd.isna(ema_trend.iloc[i])
                or pd.isna(atr_val.iloc[i])
            ):
                signal_arr[i] = 0
                continue

            bar_high = df["high"].iloc[i]
            bar_low = df["low"].iloc[i]

            if position == 1:
                # Update trailing stop
                if close.iloc[i] > entry_price:
                    trail_stop = min(
                        trail_stop, close.iloc[i] - trailing_mult * atr_val.iloc[i]
                    )
                else:
                    trail_stop = min(
                        trail_stop,
                        entry_price - trailing_mult * atr_val.iloc[i],
                    )

                exited = False
                if bar_low <= trail_stop:
                    position = 0
                    exited = True
                elif exit_long.iloc[i]:
                    position = 0
                    exited = True

                if exited and short_entry.iloc[i] and bar_high > trail_stop:
                    position = -1
                    entry_price = close.iloc[i]
                    trail_stop = close.iloc[i] + trailing_mult * atr_val.iloc[i]

            elif position == -1:
                # Update trailing stop
                if close.iloc[i] < entry_price:
                    trail_stop = max(
                        trail_stop, close.iloc[i] + trailing_mult * atr_val.iloc[i]
                    )
                else:
                    trail_stop = max(
                        trail_stop,
                        entry_price + trailing_mult * atr_val.iloc[i],
                    )

                exited = False
                if bar_high >= trail_stop:
                    position = 0
                    exited = True
                elif exit_short.iloc[i]:
                    position = 0
                    exited = True

                if exited and long_entry.iloc[i] and bar_low < trail_stop:
                    position = 1
                    entry_price = close.iloc[i]
                    trail_stop = close.iloc[i] - trailing_mult * atr_val.iloc[i]

            elif position == 0:
                if long_entry.iloc[i]:
                    position = 1
                    entry_price = close.iloc[i]
                    trail_stop = close.iloc[i] - trailing_mult * atr_val.iloc[i]
                elif short_entry.iloc[i]:
                    position = -1
                    entry_price = close.iloc[i]
                    trail_stop = close.iloc[i] + trailing_mult * atr_val.iloc[i]

            signal_arr[i] = position

        return pd.Series(signal_arr, index=df.index, dtype=int)
