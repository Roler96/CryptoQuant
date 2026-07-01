"""McGinley Dynamic Trend Following strategy.

Trend-following strategy using McGinley Dynamic MA crossover
confirmed by EMA200 trend filter.  Exactly 2 entry conditions.

McGinley Dynamic is a self-adjusting moving average that speeds up
its smoothing when price moves away from the MA (strong trend) and
slows down when price hugs the MA (consolidation).  Unlike KAMA/MAMA
which self-adjust the smoothing PERIOD, McGinley adjusts the response
FORCE — preserving crossover frequency on higher timeframes while
reducing false crossovers during chop.

Entry (long):  Close crosses above McGinley Dynamic AND close > EMA200
Entry (short): Close crosses below McGinley Dynamic AND close < EMA200
Exit (long):   Close crosses below McGinley Dynamic
Exit (short):  Close crosses above McGinley Dynamic

Reference: John R. McGinley — "McGinley Dynamic" (1990).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import ema, mcginley_dynamic


class McGinleyDynamicTrend(Strategy):
    """McGinley Dynamic crossover with EMA200 trend filter.

    Entry requires close/MD crossover AND EMA200 alignment.
    Two conditions total.

    Parameters:
        md_period: McGinley Dynamic lookback period (default 20).
        md_k: Adjustment constant (default 0.6; 0.5 = more aggressive).
        trend_period: EMA trend filter period (default 200).
    """

    timeframe = "1h"
    min_bars = 210  # max(md_period=20, trend_period=200) + 10
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "md_period": 20,
        "md_k": 0.6,
        "trend_period": 200,
    }

    @property
    def name(self) -> str:
        return "McGinleyDynamicTrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from McGinley Dynamic crossover + EMA trend.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        md_period = self.params["md_period"]
        md_k = self.params["md_k"]
        trend_period = self.params["trend_period"]

        # Compute indicators
        md_line = mcginley_dynamic(
            df, period=md_period, k=md_k, price_col="close"
        )
        ema_trend = ema(close, period=trend_period)

        # Entry signals (2 conditions: close crosses MD + EMA trend)
        close_above_md = close > md_line
        close_below_md = close < md_line

        trend_up = close > ema_trend
        trend_down = close < ema_trend

        long_entry = close_above_md & trend_up
        short_entry = close_below_md & trend_down

        # Exit: close crosses back across MD
        exit_long = close_below_md
        exit_short = close_above_md

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if (
                pd.isna(md_line.iloc[i])
                or pd.isna(ema_trend.iloc[i])
            ):
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
