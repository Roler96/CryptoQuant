"""Candle Conviction Breakout strategy.

Trend-following strategy based on candle body ratio — a measure of
market conviction. Large bodies with small wicks indicate directional
agreement; small bodies with large wicks indicate indecision.

Unlike CLV (Close Location Value, which failed in Loop 6), body ratio
measures conviction independent of where the close sits within the bar
range. A large bullish body = conviction regardless of whether it's at
the top or middle of the range.

Entry (long):  avg_body_ratio > threshold AND close > open AND close > EMA(trend)
Entry (short): avg_body_ratio > threshold AND close < open AND close < EMA(trend)
Exit:          avg_body_ratio drops below exit_threshold (conviction lost)

2 entry conditions total.
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import ema


class CandleConvictionBreakout(Strategy):
    """Candle body conviction with EMA trend filter.

    Averages the candle body ratio (|close-open| / (high-low)) over
    a lookback window and enters when conviction exceeds a threshold
    in the direction of the trend.

    Parameters:
        body_lookback: Lookback for body ratio average (default 14)
        threshold: Minimum avg body ratio for entry (default 0.55)
        exit_threshold: Body ratio below which conviction is lost (default 0.35)
        trend_period: EMA trend filter lookback (default 200)
    """

    timeframe = "1h"
    min_bars = 280  # trend_period + body_lookback + buffer
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "body_lookback": 14,
        "threshold": 0.55,
        "exit_threshold": 0.35,
        "trend_period": 200,
    }

    @property
    def name(self) -> str:
        return "CandleConvictionBreakout"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from candle conviction + EMA trend filter.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        open_: pd.Series = df["open"]  # type: ignore[assignment]
        high: pd.Series = df["high"]  # type: ignore[assignment]
        low: pd.Series = df["low"]  # type: ignore[assignment]
        close: pd.Series = df["close"]  # type: ignore[assignment]

        body_lookback = self.params["body_lookback"]
        threshold = self.params["threshold"]
        exit_threshold = self.params["exit_threshold"]
        trend_period = self.params["trend_period"]

        # Compute indicators
        bar_range = high - low
        # Avoid division by zero for doji-like bars
        bar_range_safe = bar_range.replace(0, np.nan)
        body_ratio = (close - open_).abs() / bar_range_safe
        # Cap body_ratio at 1.0 (in case open==high or open==low)
        body_ratio = body_ratio.clip(upper=1.0)

        avg_body = body_ratio.rolling(body_lookback).mean()

        ema_trend = ema(close, period=trend_period)

        # Directional close
        bullish_close = close > open_
        bearish_close = close < open_

        # Entry signals (2 conditions: conviction + trend direction)
        trend_up = close > ema_trend
        trend_down = close < ema_trend

        long_entry = (avg_body > threshold) & bullish_close & trend_up
        short_entry = (avg_body > threshold) & bearish_close & trend_down

        # Exit signals: conviction lost
        exit_long = avg_body < exit_threshold
        exit_short = avg_body < exit_threshold

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(avg_body.iloc[i]) or pd.isna(ema_trend.iloc[i]):
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
