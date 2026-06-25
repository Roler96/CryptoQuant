"""KAMA Trend Following strategy.

Trend-following strategy using KAMA (Kaufman's Adaptive Moving Average)
crossover confirmed by an EMA200 trend filter.  Exactly 2 entry conditions.

Entry (long):  KAMA_fast crosses ABOVE KAMA_slow AND close > EMA200
Entry (short): KAMA_fast crosses BELOW KAMA_slow AND close < EMA200
Exit (long):   KAMA_fast crosses BELOW KAMA_slow
Exit (short):  KAMA_fast crosses ABOVE KAMA_slow

KAMA adapts its smoothing constant based on the Efficiency Ratio, which
measures trend directionality vs noise.  In trending markets, KAMA follows
price closely; in choppy markets, it lags more.  This self-adaptation
eliminates the need for parameter switching across volatility regimes.

Reference: Perry Kaufman — "Trading Systems and Methods" (1998);
SSRN 5694583 (2025) — KAMA on Bitcoin with bootstrap validation.
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import ema, kama


class KamaTrend(Strategy):
    """KAMA crossover with EMA200 trend filter.

    Two KAMA lines — one fast (slow_ema=30) and one slow (slow_ema=50) —
    are computed from the close price.  A crossover of the fast KAMA above
    the slow KAMA signals a bullish trend transition.  Entry requires both
    the KAMA crossover AND price above the EMA200 trend filter.

    Parameters:
        er_period: Efficiency Ratio lookback (default 10)
        fast_ema: Fast EMA for SC computation (default 2)
        slow_ema_fast: Slow EMA for fast KAMA (default 30)
        slow_ema_slow: Slow EMA for slow KAMA (default 50)
        trend_period: EMA trend filter lookback (default 200)
    """

    timeframe = "1h"
    min_bars = 200  # trend_period + KAMA warmup
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "er_period": 10,
        "fast_ema": 2,
        "slow_ema_fast": 30,
        "slow_ema_slow": 50,
        "trend_period": 200,
    }

    @property
    def name(self) -> str:
        return "KamaTrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from KAMA crossovers + EMA trend filter.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        er_period = self.params["er_period"]
        fast_ema = self.params["fast_ema"]
        slow_ema_fast = self.params["slow_ema_fast"]
        slow_ema_slow = self.params["slow_ema_slow"]
        trend_period = self.params["trend_period"]

        # Compute indicators
        kama_fast = kama(close, er_period=er_period, fast_ema=fast_ema, slow_ema=slow_ema_fast)
        kama_slow = kama(close, er_period=er_period, fast_ema=fast_ema, slow_ema=slow_ema_slow)
        ema_trend = ema(close, period=trend_period)

        # Cross detection (fast crosses above/below slow)
        fast_above = kama_fast > kama_slow
        fast_below = kama_fast < kama_slow
        prev_fast_above = fast_above.shift(1).fillna(False)
        prev_fast_below = fast_below.shift(1).fillna(False)

        cross_up = fast_above & ~prev_fast_above.astype(bool)
        cross_down = fast_below & ~prev_fast_below.astype(bool)

        # Entry signals (2 conditions: KAMA cross + EMA trend)
        trend_up = close > ema_trend
        trend_down = close < ema_trend

        long_entry = cross_up & trend_up
        short_entry = cross_down & trend_down

        # Exit signals: reverse KAMA cross
        exit_long = cross_down
        exit_short = cross_up

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(kama_fast.iloc[i]) or pd.isna(kama_slow.iloc[i]) or pd.isna(ema_trend.iloc[i]):
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
