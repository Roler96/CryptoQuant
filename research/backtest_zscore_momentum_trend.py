"""Z-Score Momentum Trend strategy.

Uses rolling Z-score of log returns confirmed by EMA200 trend filter.
Exactly 2 entry conditions.

Entry (long):  zscore > +1.0 AND Close > EMA(200)
Entry (short): zscore < -1.0 AND Close < EMA(200)
Exit:          zscore crosses back through 0 (momentum neutralized)

Z-score = (short_MA(returns) - long_MA(returns)) / long_std(returns)

Unlike RiskAdjustedMomentum (Loop 8) which used return/vol ratio, the
Z-score uses standard-deviation normalization, which is scale-invariant
across volatility regimes. The shorter windows (10/50 vs 63/20) should
generate more frequent signals suitable for higher trade counts.

Inspired by: RiskAdjustedMomentum (Loop 8, BTC 1h Sharpe=1.68) and
statistical arbitrage Z-score mean-reversion literature.

Reference: Brian Plotnik — "Systematic Crypto Trading Strategies" (2025).
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import ema


class ZScoreMomentumTrend(Strategy):
    """Z-Score rolling momentum with EMA200 trend filter.

    Entry requires zscore crosses ±1.0 threshold AND EMA200 alignment.

    Parameters:
        short_period: Lookback for short-term return average (default 10)
        long_period: Lookback for long-term return average + std (default 50)
        entry_threshold: Z-score threshold for entry (default 1.0)
        exit_threshold: Z-score threshold for exit (default 0.0)
        trend_period: Period for trend filter EMA (default 200)
    """

    timeframe = "1h"
    min_bars = 250  # trend_period + long_period
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "short_period": 10,
        "long_period": 50,
        "entry_threshold": 1.0,
        "exit_threshold": 0.0,
        "trend_period": 200,
    }

    @property
    def name(self) -> str:
        return "ZScoreMomentumTrend"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from Z-score threshold + EMA200 trend filter.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        short_period = self.params["short_period"]
        long_period = self.params["long_period"]
        entry_threshold = self.params["entry_threshold"]
        exit_threshold = self.params["exit_threshold"]
        trend_period = self.params["trend_period"]

        # Compute indicators
        ema_trend = ema(close, period=trend_period)

        # Log returns for Z-score
        log_returns = np.log(close / close.shift(1))

        # Z-score: (short_MA - long_MA) / long_std
        short_ma = log_returns.rolling(short_period).mean()
        long_ma = log_returns.rolling(long_period).mean()
        long_std = log_returns.rolling(long_period).std()

        zscore = (short_ma - long_ma) / long_std.replace(0, np.nan)

        # Entry signals: 2 conditions (zscore threshold + trend filter)
        long_entry = (zscore > entry_threshold) & (close > ema_trend)
        short_entry = (zscore < -entry_threshold) & (close < ema_trend)

        # Exit: zscore crosses back through exit_threshold
        exit_long = zscore <= exit_threshold
        exit_short = zscore >= -exit_threshold

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(ema_trend.iloc[i]) or pd.isna(zscore.iloc[i]):
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
