"""Connors RSI Trend Following strategy.

Trend-following strategy using Connors RSI (CRSI) composite oscillator
threshold + EMA200 trend filter. Exactly 2 entry conditions.

Connors RSI = [RSI(3) + RSI(Streak, 2) + PercentRank(ROC, 100)] / 3

CRSI combines three momentum dimensions into one 0-100 signal:
  1. RSI(3): Ultra-short Wilder RSI — immediate overbought/oversold
  2. RSI(Streak, 2): RSI on consecutive close streak — trend persistence
  3. PercentRank(ROC, 100): Momentum percentile — self-scaling

Entry (long):  CRSI > 70 AND close > EMA200
Entry (short): CRSI < 30 AND close < EMA200
Exit (long):   CRSI < 50 (momentum neutral)
Exit (short):  CRSI > 50

Reference: Larry Connors — "Connors RSI" (2010).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import connors_rsi, ema


class ConnorsRSITrend(Strategy):
    """Connors RSI threshold with EMA200 trend filter.

    Connors RSI (CRSI) is a composite oscillator that aggregates
    short-term RSI, streak persistence, and momentum percentile
    into a single 0-100 signal. Entry requires CRSI crossing
    extreme thresholds AND price trend alignment (EMA200).

    Parameters:
        crsi_rsi_period: RSI period on close (default 3)
        crsi_streak_period: RSI period on streak (default 2)
        crsi_rank_period: Percent rank lookback (default 100)
        crsi_entry: CRSI threshold for long entry (default 70)
        crsi_short_entry: CRSI threshold for short entry (default 30)
        crsi_exit: CRSI midline for exit (default 50)
        trend_period: EMA trend filter lookback (default 200)
    """

    timeframe = "1h"
    min_bars = 250  # trend_period(200) + rank_period(100) + warmup buffer
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "crsi_rsi_period": 3,
        "crsi_streak_period": 2,
        "crsi_rank_period": 100,
        "crsi_entry": 70,
        "crsi_short_entry": 30,
        "crsi_exit": 50,
        "trend_period": 200,
    }

    @property
    def name(self) -> str:
        return "ConnorsRSITrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from CRSI thresholds + EMA200 trend.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        crsi_rsi_period = self.params["crsi_rsi_period"]
        crsi_streak_period = self.params["crsi_streak_period"]
        crsi_rank_period = self.params["crsi_rank_period"]
        crsi_entry = self.params["crsi_entry"]
        crsi_short = self.params["crsi_short_entry"]
        crsi_exit = self.params["crsi_exit"]
        trend_period = self.params["trend_period"]

        # Compute indicators
        crsi = connors_rsi(
            df,
            rsi_period=crsi_rsi_period,
            streak_rsi_period=crsi_streak_period,
            percent_rank_period=crsi_rank_period,
        )
        ema_trend = ema(close, period=trend_period)

        # Entry signals (2 conditions: CRSI threshold + EMA200 trend)
        trend_up = close > ema_trend
        trend_down = close < ema_trend

        long_entry = (crsi > crsi_entry) & trend_up
        short_entry = (crsi < crsi_short) & trend_down

        # Exit signals: CRSI crosses midline
        exit_long = crsi < crsi_exit
        exit_short = crsi > crsi_exit

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(crsi.iloc[i]) or pd.isna(ema_trend.iloc[i]):
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
