"""PullbackVolumeContraction — Trend pullback with volume contraction + breakout.

This strategy improves on TrendPullbackRSI by replacing RSI with volume
contraction confirmation and adding a breakout entry trigger. The result
should be fewer but higher-quality trades.

Entry Conditions (Long):
  1. Trend:  close > EMA(200)
  2. Pullback: Price within 2% of EMA(20) after being >3% above it in last 5 bars
  3. Volume contraction: Volume is the lowest in the last 20 bars
  4. Breakout: Close > highest high of last 3 bars

Entry Conditions (Short):
  1. Trend:  close < EMA(200)
  2. Pullback: Price within 2% of EMA(20) after being >3% below it in last 5 bars
  3. Volume contraction: Volume is the lowest in the last 20 bars
  4. Breakout: Close < lowest low of last 3 bars

Exit: Close crosses EMA(20) opposite direction

Reference: MDPI TFT paper (2025) — multi-factor confirmation reduces false
signals while maintaining win rate.
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import ema


class PullbackVolumeContraction(Strategy):
    """Pullback entry with volume contraction and breakout confirmation.

    Parameters:
        ema_trend: Trend EMA period (e.g. 200)
        ema_pullback: Pullback EMA period (e.g. 20)
        pullback_threshold_pct: Max % distance from EMA for pullback entry
        pullback_lookback: Bars to look back for prior extension
        extension_threshold_pct: Min % extension required before pullback
        volume_window: Window for volume minimum check
        breakout_bars: Bars for breakout high/low confirmation
    """

    timeframe = "1h"
    min_bars = 250  # ema_trend(200) + volume_window(20) + buffer
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "ema_trend": 200,
        "ema_pullback": 20,
        "pullback_threshold_pct": 2.0,
        "pullback_lookback": 5,
        "extension_threshold_pct": 3.0,
        "volume_window": 20,
        "breakout_bars": 3,
    }

    @property
    def name(self) -> str:
        return "PullbackVolumeContraction"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals: pullback + volume contraction + breakout.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]
        high: pd.Series = df["high"]
        low: pd.Series = df["low"]
        volume: pd.Series = df["volume"]

        # Unpack params
        ema_trend_p = self.params["ema_trend"]
        ema_pullback_p = self.params["ema_pullback"]
        pullback_threshold_pct = self.params["pullback_threshold_pct"]
        pullback_lookback = self.params["pullback_lookback"]
        extension_threshold_pct = self.params["extension_threshold_pct"]
        volume_window = self.params["volume_window"]
        breakout_bars = self.params["breakout_bars"]

        # Compute indicators
        ema_trend = ema(close, ema_trend_p)
        ema_pb = ema(close, ema_pullback_p)

        # Distance from pullback EMA as percentage
        dist_from_ema_pb = (close - ema_pb) / ema_pb * 100

        # Rolling volume minimum
        vol_rolling_min = volume.rolling(volume_window, min_periods=volume_window).min()

        # Rolling high/low for breakout
        rolling_high_breakout = high.rolling(breakout_bars).max().shift(1)
        rolling_low_breakout = low.rolling(breakout_bars).min().shift(1)

        n = len(df)
        signal = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if position != 0:
                # Exit check: price crosses EMA(pullback)
                if pd.notna(ema_pb.iloc[i]):
                    if position == 1 and close.iloc[i] < ema_pb.iloc[i]:
                        position = 0
                    elif position == -1 and close.iloc[i] > ema_pb.iloc[i]:
                        position = 0
                signal[i] = position
                continue

            # --- Entry checks (only when flat) ---
            # All indicators must be available
            if (pd.isna(ema_trend.iloc[i]) or pd.isna(ema_pb.iloc[i])
                    or pd.isna(vol_rolling_min.iloc[i])
                    or pd.isna(rolling_high_breakout.iloc[i])
                    or pd.isna(rolling_low_breakout.iloc[i])):
                signal[i] = 0
                continue

            # Condition 1: Trend direction
            is_uptrend = close.iloc[i] > ema_trend.iloc[i]
            is_downtrend = close.iloc[i] < ema_trend.iloc[i]

            # Condition 2: Pullback detection
            in_pullback_zone = abs(dist_from_ema_pb.iloc[i]) <= pullback_threshold_pct

            # Check if there was a prior extension (>3% away) in last N bars
            if i >= pullback_lookback:
                prev_dists = dist_from_ema_pb.iloc[i - pullback_lookback : i]
            else:
                prev_dists = dist_from_ema_pb.iloc[:i]

            long_extension = (prev_dists > extension_threshold_pct).any() if len(prev_dists) > 0 else False
            short_extension = (prev_dists < -extension_threshold_pct).any() if len(prev_dists) > 0 else False

            # Condition 3: Volume contraction (current volume = lowest in window)
            vol_contracted = volume.iloc[i] <= vol_rolling_min.iloc[i] * 1.001  # tiny epsilon

            # Condition 4: Breakout confirmation
            long_breakout = close.iloc[i] > rolling_high_breakout.iloc[i]
            short_breakout = close.iloc[i] < rolling_low_breakout.iloc[i]

            # Long entry: all 4 conditions
            if (is_uptrend and in_pullback_zone and long_extension
                    and vol_contracted and long_breakout):
                position = 1

            # Short entry: all 4 conditions (downtrend version)
            elif (is_downtrend and in_pullback_zone and short_extension
                    and vol_contracted and short_breakout):
                position = -1

            signal[i] = position

        return pd.Series(signal, index=df.index, dtype=int)
