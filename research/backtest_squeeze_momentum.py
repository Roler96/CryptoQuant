"""TTM Squeeze Momentum strategy.

Volatility compression → expansion breakout strategy based on
John Carter's TTM Squeeze indicator. Detects when Bollinger Bands
contract inside Keltner Channels (squeeze), then enter when they
expand (squeeze fires) — the start of a new directional move.

Entry (long):  squeeze fires AND close > EMA200
Entry (short): squeeze fires AND close < EMA200
Exit (long):   opposite squeeze fire OR trailing stop at 2× ATR(14)
Exit (short):  opposite squeeze fire OR trailing stop at 2× ATR(14)

2 conditions total: squeeze fire + trend direction.
This strategy tests the interaction of BB and KC — fundamentally
different from either BBPercentBVolatility (Loop 11) or
KeltnerBreakoutADX (Loop 2), which use these channels independently.

Reference: John Carter — "Mastering the Trade" (2006).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import atr, ema, ttm_squeeze


class SqueezeMomentum(Strategy):
    """TTM Squeeze Momentum — volatility compression/expansion entry.

    Parameters:
        bb_period: BB period (default 20)
        bb_std: BB std multiplier (default 2.0)
        kc_period: KC period (default 20)
        kc_multiplier: KC ATR multiplier (default 1.5)
        trend_period: EMA trend filter period (default 200)
        trailing_stop_atr: ATR period for trailing stop (default 14)
        trailing_stop_mult: ATR multiplier for trailing stop (default 2.0)
    """

    timeframe = "1h"
    min_bars = 250  # max(trend_period, kc_period) + buffer
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "bb_period": 20,
        "bb_std": 2.0,
        "kc_period": 20,
        "kc_multiplier": 1.5,
        "trend_period": 200,
        "trailing_stop_atr": 14,
        "trailing_stop_mult": 2.0,
    }

    @property
    def name(self) -> str:
        return "SqueezeMomentum"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from TTM Squeeze fire + EMA trend.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]
        high: pd.Series = df["high"]    # type: ignore[assignment]
        low: pd.Series = df["low"]      # type: ignore[assignment]

        bb_period = self.params["bb_period"]
        bb_std = self.params["bb_std"]
        kc_period = self.params["kc_period"]
        kc_multiplier = self.params["kc_multiplier"]
        trend_period = self.params["trend_period"]
        ts_atr = self.params["trailing_stop_atr"]
        ts_mult = self.params["trailing_stop_mult"]

        # Compute indicators
        squeeze = ttm_squeeze(
            df,
            bb_period=bb_period,
            bb_std=bb_std,
            kc_period=kc_period,
            kc_multiplier=kc_multiplier,
        )
        squeeze_fire = squeeze["squeeze_fire"]
        ema_trend = ema(close, period=trend_period)
        atr_val = atr(df, period=ts_atr)

        # Entry signals (2 conditions: squeeze fire + trend direction)
        trend_up = close > ema_trend
        trend_down = close < ema_trend

        long_entry = squeeze_fire & trend_up
        short_entry = squeeze_fire & trend_down

        # Stateful signal generation with trailing stop exits
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short
        entry_price = np.nan
        trailing_stop_price = np.nan

        for i in range(n):
            # Skip bars where indicators are not yet computed
            if pd.isna(ema_trend.iloc[i]) or pd.isna(atr_val.iloc[i]):
                signal_arr[i] = 0
                continue

            c = close.iloc[i]
            h = high.iloc[i]
            l = low.iloc[i]

            if position == 1:
                # Update trailing stop (highest high since entry minus ATR multiple)
                if not np.isnan(entry_price):
                    highest_since_entry = high.iloc[max(0, i - ts_atr):i + 1].max()
                    trailing_stop_price = highest_since_entry - ts_mult * atr_val.iloc[i]
                    # Stop hit
                    if l <= trailing_stop_price:
                        position = 0
                        entry_price = np.nan
                        trailing_stop_price = np.nan
                        # Check for reverse entry on same bar
                        if short_entry.iloc[i]:
                            position = -1
                            entry_price = c
                            # Initialize trailing stop for short
                            lowest_since_entry = low.iloc[i]
                            trailing_stop_price = lowest_since_entry + ts_mult * atr_val.iloc[i]

                # Squeeze fire exit: opposite squeeze fire closes position
                if position == 1 and squeeze_fire.iloc[i]:
                    position = 0
                    entry_price = np.nan
                    trailing_stop_price = np.nan
                    if short_entry.iloc[i]:
                        position = -1
                        entry_price = c

            elif position == -1:
                # Update trailing stop (lowest low since entry plus ATR multiple)
                if not np.isnan(entry_price):
                    lowest_since_entry = low.iloc[max(0, i - ts_atr):i + 1].min()
                    trailing_stop_price = lowest_since_entry + ts_mult * atr_val.iloc[i]
                    # Stop hit
                    if h >= trailing_stop_price:
                        position = 0
                        entry_price = np.nan
                        trailing_stop_price = np.nan
                        # Check for reverse entry on same bar
                        if long_entry.iloc[i]:
                            position = 1
                            entry_price = c
                            # Initialize trailing stop for long
                            highest_since_entry = high.iloc[i]
                            trailing_stop_price = highest_since_entry - ts_mult * atr_val.iloc[i]

                # Squeeze fire exit
                if position == -1 and squeeze_fire.iloc[i]:
                    position = 0
                    entry_price = np.nan
                    trailing_stop_price = np.nan
                    if long_entry.iloc[i]:
                        position = 1
                        entry_price = c

            elif position == 0:
                if long_entry.iloc[i]:
                    position = 1
                    entry_price = c
                    highest_since_entry = h
                    trailing_stop_price = highest_since_entry - ts_mult * atr_val.iloc[i]
                elif short_entry.iloc[i]:
                    position = -1
                    entry_price = c
                    lowest_since_entry = l
                    trailing_stop_price = lowest_since_entry + ts_mult * atr_val.iloc[i]

            signal_arr[i] = position

        return pd.Series(signal_arr, index=df.index, dtype=int)
