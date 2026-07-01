"""PPO (Percentage Price Oscillator) Trend Following strategy.

Trend-following strategy using PPO crossover confirmed by an EMA200
trend filter. Exactly 2 entry conditions.

Entry (long):  PPO crosses ABOVE Signal AND close > EMA200
Entry (short): PPO crosses BELOW Signal AND close < EMA200
Exit (long):   PPO crosses BELOW Signal (reverse signal)
Exit (short):  PPO crosses ABOVE Signal (reverse signal)

PPO formula:
    PPO = (EMA(12) - EMA(26)) / EMA(26) × 100
    Signal = EMA(PPO, 9)

PPO is the percentage-based variant of MACD — the normalization by
the slower EMA makes it scale-invariant and directly comparable across
different price levels (BTC vs ETH, different time periods).

Reference: Original synthesis. PPO is a well-known normalized MACD
variant (e.g., StockCharts.com PPO indicator).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import ema


class PPOTrend(Strategy):
    """PPO crossover with EMA200 trend filter.

    PPO measures the percentage distance between two EMAs. When PPO
    crosses above its signal line, short-term momentum is accelerating
    relative to long-term momentum. Entry requires both the PPO
    crossover AND price trend alignment (close vs EMA200).

    Parameters:
        ppo_fast: Fast EMA period (default 12)
        ppo_slow: Slow EMA period (default 26)
        ppo_signal: Signal line period (default 9)
        trend_period: EMA trend filter lookback (default 200)
    """

    timeframe = "1h"
    min_bars = 250  # trend_period + PPO warmup + buffer
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "ppo_fast": 12,
        "ppo_slow": 26,
        "ppo_signal": 9,
        "trend_period": 200,
    }

    @property
    def name(self) -> str:
        return "PPOTrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from PPO crossover + EMA trend filter.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        ppo_fast = self.params["ppo_fast"]
        ppo_slow = self.params["ppo_slow"]
        ppo_signal_period = self.params["ppo_signal"]
        trend_period = self.params["trend_period"]

        # Compute PPO
        ema_fast = ema(close, period=ppo_fast)
        ema_slow = ema(close, period=ppo_slow)
        ppo = (ema_fast - ema_slow) / ema_slow * 100.0
        ppo_signal_line = ema(ppo, period=ppo_signal_period)

        # Compute trend filter
        ema_trend = ema(close, period=trend_period)

        # PPO crossover detection
        ppo_above_signal = ppo > ppo_signal_line
        ppo_below_signal = ppo < ppo_signal_line
        prev_above = ppo_above_signal.shift(1).fillna(False)
        prev_below = ppo_below_signal.shift(1).fillna(False)

        cross_up = ppo_above_signal & ~prev_above.astype(bool)
        cross_down = ppo_below_signal & ~prev_below.astype(bool)

        # Entry signals (2 conditions: PPO cross + EMA trend)
        trend_up = close > ema_trend
        trend_down = close < ema_trend

        long_entry = cross_up & trend_up
        short_entry = cross_down & trend_down

        # Exit signals: reverse PPO cross
        exit_long = cross_down
        exit_short = cross_up

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(ppo.iloc[i]) or pd.isna(ema_trend.iloc[i]):
                signal_arr[i] = 0
                continue

            if position == 1:
                if exit_long.iloc[i]:
                    position = 0
                    # Check for immediate flip to short
                    if short_entry.iloc[i]:
                        position = -1
            elif position == -1:
                if exit_short.iloc[i]:
                    position = 0
                    # Check for immediate flip to long
                    if long_entry.iloc[i]:
                        position = 1
            elif position == 0:
                if long_entry.iloc[i]:
                    position = 1
                elif short_entry.iloc[i]:
                    position = -1

            signal_arr[i] = position

        return pd.Series(signal_arr, index=df.index, dtype=int)
