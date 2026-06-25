"""Adaptive EMA Crossover with Volatility Regime Detection.

Trend-following strategy where EMA periods adapt to market volatility regime.
In high-volatility regimes, shorter EMA lookbacks capture trends faster.
In low-volatility regimes, longer lookbacks reduce false signals.

Regime detection: ATR(14) percentile over 100-bar rolling window.
  - High-vol: current ATR > 70th percentile
  - Low-vol:  current ATR <= 70th percentile

Adaptive EMA periods:
  - High-vol: fast=8,  slow=21
  - Low-vol:  fast=16, slow=34

Entry (Long):  Adaptive fast EMA crosses ABOVE adaptive slow EMA
Entry (Short): Adaptive fast EMA crosses BELOW adaptive slow EMA
Exit:          Reverse crossover signal

Reference: arxiv 2507.20202 — technical indicators with fixed lookback
periods underperform when volatility regimes shift.
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import atr, ema


def rolling_percentile_rank(series: pd.Series, period: int) -> pd.Series:
    """Rolling percentile rank of current value within the window.

    Returns 0-100 where 100 means current value exceeds all values in window.
    """
    result = pd.Series(np.nan, index=series.index, dtype=float)
    # Vectorized: for each point, what fraction of the last `period` values
    # are less than the current value?
    vals = series.values
    for i in range(period - 1, len(vals)):
        window = vals[i - period + 1 : i + 1]
        result.iloc[i] = (window < vals[i]).mean() * 100
    return result


class AdaptiveEmaVolRegime(Strategy):
    """Adaptive EMA Crossover with Volatility Regime gating.

    Parameters:
        fast_high: Fast EMA period in high-vol regime
        slow_high: Slow EMA period in high-vol regime
        fast_low:  Fast EMA period in low-vol regime
        slow_low:  Slow EMA period in low-vol regime
        atr_period: ATR lookback period
        regime_window: Window for ATR percentile rank
        regime_threshold_pct: Percentile above which = high-vol regime
        hysteresis_bars: Consecutive bars to confirm regime switch
    """

    timeframe = "1h"
    min_bars = 200  # regime_window(100) + max(slow_low=34) * 2 + buffer
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "fast_high": 8,
        "slow_high": 21,
        "fast_low": 16,
        "slow_low": 34,
        "atr_period": 14,
        "regime_window": 100,
        "regime_threshold_pct": 70.0,
        "hysteresis_bars": 3,
    }

    @property
    def name(self) -> str:
        return "AdaptiveEmaVolRegime"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals with adaptive EMA crossover.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        # Unpack params
        fast_high = self.params["fast_high"]
        slow_high = self.params["slow_high"]
        fast_low = self.params["fast_low"]
        slow_low = self.params["slow_low"]
        atr_period = self.params["atr_period"]
        regime_window = self.params["regime_window"]
        regime_threshold_pct = self.params["regime_threshold_pct"]
        hysteresis_bars = self.params["hysteresis_bars"]

        # Compute all EMA variants (fast & slow for both regimes)
        ema_fast_high = ema(close, period=fast_high)
        ema_slow_high = ema(close, period=slow_high)
        ema_fast_low = ema(close, period=fast_low)
        ema_slow_low = ema(close, period=slow_low)

        # Volatility regime detection
        atr_14 = atr(df, period=atr_period)
        atr_pct_rank = rolling_percentile_rank(atr_14, period=regime_window)

        # Raw regime: True = high-vol, False = low-vol
        raw_high_vol = atr_pct_rank > regime_threshold_pct

        # Hysteresis: require `hysteresis_bars` consecutive bars to switch regime
        regime_mode = np.zeros(len(df), dtype=bool)
        consecutive = 0

        for i in range(len(df)):
            if pd.isna(atr_pct_rank.iloc[i]):
                regime_mode[i] = False  # default to low-vol
                consecutive = 0
                continue

            if i == 0 or pd.isna(atr_pct_rank.iloc[i - 1]):
                regime_mode[i] = bool(raw_high_vol.iloc[i])
                consecutive = 1
                continue

            target = bool(raw_high_vol.iloc[i])
            prev = bool(raw_high_vol.iloc[i - 1])

            if target == prev:
                consecutive += 1
            else:
                consecutive = 1

            # Only switch after hysteresis_bars consecutive bars in new regime
            if consecutive >= hysteresis_bars or i < hysteresis_bars:
                # If enough consecutive or early in series, snap to current
                regime_mode[i] = target
            else:
                # Not enough consecutive — keep previous regime
                regime_mode[i] = regime_mode[i - 1]

        # Select adaptive EMAs based on regime
        ema_fast = pd.Series(np.where(regime_mode, ema_fast_high, ema_fast_low),
                             index=df.index, dtype=float)
        ema_slow = pd.Series(np.where(regime_mode, ema_slow_high, ema_slow_low),
                             index=df.index, dtype=float)

        # Mark NaN where indicators aren't ready
        min_bars_needed = max(slow_high, slow_low, regime_window, atr_period)
        ema_fast.iloc[:min_bars_needed] = np.nan
        ema_slow.iloc[:min_bars_needed] = np.nan

        # Signal generation: stateful EMA crossover
        n = len(df)
        signal = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(ema_fast.iloc[i]) or pd.isna(ema_slow.iloc[i]):
                signal[i] = 0
                continue

            fast_val = ema_fast.iloc[i]
            slow_val = ema_slow.iloc[i]
            fast_prev = ema_fast.iloc[i - 1] if i > 0 else fast_val
            slow_prev = ema_slow.iloc[i - 1] if i > 0 else slow_val

            long_cross = fast_val > slow_val and fast_prev <= slow_prev
            short_cross = fast_val < slow_val and fast_prev >= slow_prev

            if position == 1:
                if short_cross:
                    position = 0
                    if long_cross:
                        position = 1  # flip
            elif position == -1:
                if long_cross:
                    position = 0
                    if short_cross:
                        position = -1  # flip
            elif position == 0:
                if long_cross:
                    position = 1
                elif short_cross:
                    position = -1

            signal[i] = position

        return pd.Series(signal, index=df.index, dtype=int)
