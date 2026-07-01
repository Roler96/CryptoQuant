"""PFE Trend — Polarized Fractal Efficiency Crossover + Trend Filter.

Trend-following strategy using PFE zero-cross as entry trigger confirmed
by EMA200 trend direction. Exactly 2 entry conditions, following the
proven template across 15+ loops of research.

Entry (long):  PFE crosses above 0 AND close > EMA200
Entry (short): PFE crosses below 0 AND close < EMA200
Exit (long):   PFE crosses below 0 (reverse direction)
Exit (short):  PFE crosses above 0 (reverse direction)
Stop-loss:     2× ATR(14) (handled by engine)
Take-profit:   3× ATR(14) (handled by engine)

PFE (Polarized Fractal Efficiency, Hans Hannula, 1994) — signed
efficiency measure using fractal geometry. Unlike unsigned ER (0-1),
PFE's signed output (-100 to +100) makes zero-cross a mechanical
and unambiguous entry trigger.
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import atr, ema, pfe


class PFETrend(Strategy):
    """Polarized Fractal Efficiency zero-cross strategy with EMA200 filter.

    PFE measures how efficiently price moves using fractal geometry.
    Positive PFE = price moved up efficiently (uptrend).
    Negative PFE = price moved down efficiently (downtrend).
    Near-zero PFE = choppy/inefficient movement.

    The zero-cross provides a natural entry/exit oscillator that requires
    no threshold tuning. Combined with EMA200 for trend confirmation,
    this uses exactly 2 entry conditions.

    Parameters:
        pfe_period: PFE lookback period (default 10).
        trend_period: EMA trend filter period (default 200).
    """

    timeframe = "1h"
    min_bars = 210  # max(pfe_period, trend_period) + 10
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "pfe_period": 10,
        "trend_period": 200,
    }

    @property
    def name(self) -> str:
        return "PFETrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from PFE zero-cross + EMA200 trend filter.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        pfe_period = self.params["pfe_period"]
        trend_period = self.params["trend_period"]

        # Compute indicators
        pfe_vals = pfe(close, period=pfe_period)
        ema_trend = ema(close, period=trend_period)

        # Entry signals (2 conditions: PFE zero-cross + trend filter)
        trend_up = close > ema_trend
        trend_down = close < ema_trend

        pfe_pos = pfe_vals > 0
        pfe_neg = pfe_vals < 0
        pfe_prev_pos = pfe_vals.shift(1) > 0
        pfe_prev_neg = pfe_vals.shift(1) < 0

        # PFE crosses above zero
        pfe_cross_up = pfe_pos & ~pfe_prev_pos.fillna(False).astype(bool)
        # PFE crosses below zero
        pfe_cross_down = pfe_neg & ~pfe_prev_neg.fillna(False).astype(bool)

        long_entry = trend_up & pfe_cross_up
        short_entry = trend_down & pfe_cross_down

        # Exit: PFE reverse cross
        exit_long = pfe_cross_down
        exit_short = pfe_cross_up

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(pfe_vals.iloc[i]) or pd.isna(ema_trend.iloc[i]):
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
