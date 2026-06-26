"""Keltner Channel %K Threshold + EMA200 Trend strategy.

Trend-following strategy using Keltner Channel %K (normalized position
within Keltner Channel) threshold + EMA200 trend filter. Exactly 2
entry conditions.

Keltner Channel: middle=EMA(20), width=ATR(10)×2.0
%K = (close - lower) / (upper - lower) — normalized 0-1 position.

Entry (long):  %K > 0.8 AND close > EMA200
Entry (short): %K < 0.2 AND close < EMA200
Exit (long):   %K < 0.5 (midpoint reversion)
Exit (short):  %K > 0.5

Normalized 0-1 indicator follows the successful BB %B pattern (4/4
gate pass). ATR-based channel width naturally adapts to volatility
without parameter switching.

Reference: Chester Keltner — "How to Make Money in Commodities" (1960).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import ema, keltner_channel


class KeltnerChannelTrend(Strategy):
    """Keltner Channel %K threshold with EMA200 trend filter.

    Entry requires %K above/below threshold AND price on correct
    side of EMA200. Exit when %K crosses back across midline (0.5).

    Parameters:
        kc_ema_period: EMA period for Keltner Channel middle band (default 20)
        kc_atr_period: ATR period for channel width (default 10)
        kc_multiplier: ATR multiplier for channel width (default 2.0)
        pct_k_entry: %K threshold for long entry (default 0.8)
        pct_k_short_entry: %K threshold for short entry (default 0.2)
        pct_k_exit: %K midline for exit (default 0.5)
        trend_period: EMA trend filter lookback (default 200)
    """

    timeframe = "1h"
    min_bars = 250  # trend_period(200) + kc_atr_period(10) + kc_ema_period(20) + buffer
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "kc_ema_period": 20,
        "kc_atr_period": 10,
        "kc_multiplier": 2.0,
        "pct_k_entry": 0.8,
        "pct_k_short_entry": 0.2,
        "pct_k_exit": 0.5,
        "trend_period": 200,
    }

    @property
    def name(self) -> str:
        return "KeltnerChannelTrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from Keltner %K thresholds + EMA200 trend.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        kc_ema_period = self.params["kc_ema_period"]
        kc_atr_period = self.params["kc_atr_period"]
        kc_multiplier = self.params["kc_multiplier"]
        pct_k_entry = self.params["pct_k_entry"]
        pct_k_short = self.params["pct_k_short_entry"]
        pct_k_exit = self.params["pct_k_exit"]
        trend_period = self.params["trend_period"]

        # Compute indicators
        kc = keltner_channel(
            df,
            ema_period=kc_ema_period,
            atr_period=kc_atr_period,
            atr_multiplier=kc_multiplier,
        )
        pct_k: pd.Series = kc["pct_k"]  # type: ignore[assignment]
        ema_trend = ema(close, period=trend_period)

        # Entry signals (2 conditions: %K threshold + EMA200 trend)
        trend_up = close > ema_trend
        trend_down = close < ema_trend

        long_entry = (pct_k > pct_k_entry) & trend_up
        short_entry = (pct_k < pct_k_short) & trend_down

        # Exit signals: %K crosses midline
        exit_long = pct_k < pct_k_exit
        exit_short = pct_k > pct_k_exit

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(pct_k.iloc[i]) or pd.isna(ema_trend.iloc[i]):
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
