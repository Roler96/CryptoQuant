"""CCI Trend strategy.

Uses Commodity Channel Index (CCI) threshold crossing confirmed by
EMA200 trend filter. Exactly 2 entry conditions.

Entry (long):  CCI(20) > +100 AND Close > EMA(200)
Entry (short): CCI(20) < -100 AND Close < EMA(200)
Exit (long):   CCI falls back below +100 (momentum exhausted)
Exit (short):  CCI rises back above -100

CCI is a self-scaling normalized oscillator — it uses mean absolute
deviation instead of standard deviation, making it adaptive across
timeframes and volatility regimes. Similar to %B (Loop 11: 4/4 gate
pass) and Stochastic (Loop 7: 3/4 pass), but measures deviation from
the mean rather than position within a fixed range.

Reference: Donald Lambert (1980).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import cci, ema


class CCITrend(Strategy):
    """CCI threshold crossover with EMA200 trend filter.

    Entry requires CCI above +100 (long) / below -100 (short) AND
    EMA200 directional alignment.

    Parameters:
        cci_period: CCI lookback period (default 20)
        cci_entry_long: CCI threshold for long entry (default 100)
        cci_entry_short: CCI threshold for short entry (default -100)
        trend_period: Period for trend filter EMA (default 200)
    """

    timeframe = "1h"
    min_bars = 200  # trend_period
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "cci_period": 20,
        "cci_entry_long": 100,
        "cci_entry_short": -100,
        "trend_period": 200,
    }

    @property
    def name(self) -> str:
        return "CCITrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from CCI threshold + EMA200 trend filter.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        cci_period = self.params["cci_period"]
        cci_entry_long = self.params["cci_entry_long"]
        cci_entry_short = self.params["cci_entry_short"]
        trend_period = self.params["trend_period"]

        # Compute indicators
        ema_trend = ema(close, period=trend_period)
        cci_val = cci(df, period=cci_period)

        # Entry signals: 2 conditions (CCI threshold + trend filter)
        long_entry = (cci_val > cci_entry_long) & (close > ema_trend)
        short_entry = (cci_val < cci_entry_short) & (close < ema_trend)

        # Exit signals: CCI crosses back through threshold
        exit_long = cci_val <= cci_entry_long
        exit_short = cci_val >= cci_entry_short

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(ema_trend.iloc[i]) or pd.isna(cci_val.iloc[i]):
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
