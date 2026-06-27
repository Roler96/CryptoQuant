"""Z-Score Momentum Trend Following strategy.

Trend-following strategy using a Z-score normalized momentum oscillator
confirmed by an EMA200 trend filter. Exactly 2 entry conditions.

Entry (long):  Z-score crosses ABOVE 0 AND close > EMA200
Entry (short): Z-score crosses BELOW 0 AND close < EMA200
Exit (long):   Z-score crosses BELOW 0 (reverse signal)
Exit (short):  Z-score crosses ABOVE 0 (reverse signal)

Z-score formula:
    z_score = (rolling_mean(returns, 20) - rolling_mean(returns, 100))
              / rolling_std(returns, 100)

The normalization by rolling standard deviation makes the signal
adaptive to changing volatility regimes without parameter switching.

Reference: Adapted from "Systematic Crypto Trading Strategies"
(Brian Plotnik, Medium, Jun 2025).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import atr, ema


class ZScoreTrend(Strategy):
    """Z-Score normalized momentum oscillator with EMA200 trend filter.

    The Z-score measures how many standard deviations the short-term
    mean return is from the long-term mean return. This normalizes
    momentum across different volatility regimes. Entry requires
    both the Z-score zero-cross AND price trend alignment (close
    vs EMA200).

    Parameters:
        zscore_short: Short lookback for rolling mean (default 20)
        zscore_long: Long lookback for rolling mean/std (default 100)
        trend_period: EMA trend filter lookback (default 200)
        atr_period: ATR period for trailing stop (default 14)
        trailing_mult: ATR multiplier for trailing stop (default 2.0)
    """

    timeframe = "1h"
    min_bars = 300  # trend_period + zscore_long warmup + buffer
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "zscore_short": 20,
        "zscore_long": 100,
        "trend_period": 200,
        "atr_period": 14,
        "trailing_mult": 2.0,
    }

    @property
    def name(self) -> str:
        return "ZScoreTrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from Z-score zero-crosses + EMA trend filter.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        zscore_short = self.params["zscore_short"]
        zscore_long = self.params["zscore_long"]
        trend_period = self.params["trend_period"]
        atr_period = self.params["atr_period"]
        trailing_mult = self.params["trailing_mult"]

        # Compute Z-score
        returns = close.pct_change()
        roll_mean_short = returns.rolling(zscore_short).mean()
        roll_mean_long = returns.rolling(zscore_long).mean()
        roll_std = returns.rolling(zscore_long).std()
        zscore: pd.Series = (roll_mean_short - roll_mean_long) / roll_std  # type: ignore[no-redef]

        # Compute indicators
        ema_trend: pd.Series = ema(close, period=trend_period)  # type: ignore[no-redef]
        atr_vals: pd.Series = atr(df, period=atr_period)  # type: ignore[no-redef]

        # Zero-cross detection
        zscore_above_zero: pd.Series = zscore > 0  # type: ignore[no-redef]
        zscore_below_zero: pd.Series = zscore < 0  # type: ignore[no-redef]
        prev_above = zscore_above_zero.shift(1).fillna(False)
        prev_below = zscore_below_zero.shift(1).fillna(False)

        cross_up = zscore_above_zero & ~prev_above.astype(bool)
        cross_down = zscore_below_zero & ~prev_below.astype(bool)

        # Entry signals (2 conditions: Z-score cross + EMA trend)
        trend_up = close > ema_trend
        trend_down = close < ema_trend

        long_entry = cross_up & trend_up
        short_entry = cross_down & trend_down

        # Exit signals: reverse Z-score zero-cross
        exit_long = cross_down
        exit_short = cross_up

        # Stateful signal generation with trailing stop
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short
        entry_price = 0.0
        trailing_stop_long = np.inf
        trailing_stop_short = -np.inf

        for i in range(n):
            cur_close = close.iloc[i]
            cur_high = df["high"].iloc[i]
            cur_low = df["low"].iloc[i]

            if pd.isna(zscore.iloc[i]) or pd.isna(ema_trend.iloc[i]):
                signal_arr[i] = 0
                continue

            # Check trailing stop exits
            if position == 1:
                trail = entry_price - trailing_mult * atr_vals.iloc[i]
                if not pd.isna(trail) and trail > trailing_stop_long:
                    trailing_stop_long = trail
                if cur_low <= trailing_stop_long:
                    position = 0
                    entry_price = 0.0
                    trailing_stop_long = np.inf
                    signal_arr[i] = position
                    continue

                if exit_long.iloc[i]:
                    position = 0
                    entry_price = 0.0
                    trailing_stop_long = np.inf
                    if short_entry.iloc[i]:
                        position = -1
                        entry_price = cur_close
                        trailing_stop_short = cur_high + trailing_mult * atr_vals.iloc[i]
            elif position == -1:
                trail = entry_price + trailing_mult * atr_vals.iloc[i]
                if not pd.isna(trail) and trail < trailing_stop_short:
                    trailing_stop_short = trail
                if cur_high >= trailing_stop_short:
                    position = 0
                    entry_price = 0.0
                    trailing_stop_short = -np.inf
                    signal_arr[i] = position
                    continue

                if exit_short.iloc[i]:
                    position = 0
                    entry_price = 0.0
                    trailing_stop_short = -np.inf
                    if long_entry.iloc[i]:
                        position = 1
                        entry_price = cur_close
                        trailing_stop_long = cur_low - trailing_mult * atr_vals.iloc[i]
            elif position == 0:
                if long_entry.iloc[i]:
                    position = 1
                    entry_price = cur_close
                    trailing_stop_long = cur_low - trailing_mult * atr_vals.iloc[i]
                elif short_entry.iloc[i]:
                    position = -1
                    entry_price = cur_close
                    trailing_stop_short = cur_high + trailing_mult * atr_vals.iloc[i]

            signal_arr[i] = position

        return pd.Series(signal_arr, index=df.index, dtype=int)
