"""RSI + Bollinger Band Mean-Reversion strategy.

Combines RSI oversold/overbought signals with Bollinger Band confirmation
for entry, using RSI 50-line crossover for exit. Generates both long and
short signals.

When RSI drops below oversold threshold AND price closes below the lower
Bollinger Band, a long entry is triggered (mean-reversion to the upside).
When RSI rises above overbought threshold AND price closes above the upper
Bollinger Band, a short entry is triggered (mean-reversion to the downside).

Exit occurs when RSI crosses back through 50, or when the opposite signal
triggers (long exits on short signal and vice versa).

Reference: arxiv 2503.18096 — RSI with small window sizes (5-34) works best
for crypto mean-reversion; BB provides statistical context for extremes.
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import bollinger_bands, rsi


class RSIBBMeanReversion(Strategy):
    """RSI + Bollinger Band Mean-Reversion strategy.

    Parameters:
        rsi_period: RSI lookback period (10-21 typical)
        bb_period: Bollinger Band rolling window
        bb_std: Standard deviation multiplier for BB width
        oversold: RSI level below which to consider long entry
        overbought: RSI level above which to consider short entry
    """

    timeframe = "1h"
    min_bars = 200  # max(rsi_period + bb_period * 2, 100)
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "rsi_period": 14,
        "bb_period": 20,
        "bb_std": 2.0,
        "oversold": 35,
        "overbought": 65,
    }

    @property
    def name(self) -> str:
        return "RSIBBMeanReversion"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from RSI + Bollinger Band mean-reversion logic.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close = df["close"]

        rsi_period = self.params["rsi_period"]
        bb_period = self.params["bb_period"]
        bb_std = self.params["bb_std"]
        oversold = self.params["oversold"]
        overbought = self.params["overbought"]

        # Compute indicators
        rsi_series = rsi(close, period=rsi_period)
        bb = bollinger_bands(df, period=bb_period, std=bb_std)

        rsi_lower = bb["lower"]
        rsi_upper = bb["upper"]

        # Entry conditions
        long_entry = (rsi_series < oversold) & (close < rsi_lower)
        short_entry = (rsi_series > overbought) & (close > rsi_upper)

        # Stateful signal generation: hold position until RSI crosses 50
        # or opposite signal triggers
        n = len(df)
        signal = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(rsi_series.iloc[i]):
                signal[i] = 0
                continue

            rsi_val = rsi_series.iloc[i]

            # Exit checks
            if position == 1:
                # Exit long: RSI crosses above 50 or short entry triggers
                if rsi_val > 50:
                    position = 0
                elif short_entry.iloc[i]:
                    position = -1  # flip to short
            elif position == -1:
                # Exit short: RSI crosses below 50 or long entry triggers
                if rsi_val < 50:
                    position = 0
                elif long_entry.iloc[i]:
                    position = 1  # flip to long
            elif position == 0:
                # Entry from flat
                if long_entry.iloc[i]:
                    position = 1
                elif short_entry.iloc[i]:
                    position = -1

            signal[i] = position

        return pd.Series(signal, index=df.index, dtype=int)
