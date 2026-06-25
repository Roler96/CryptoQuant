"""Risk-Adjusted Momentum strategy.

Trend-following strategy using volatility-normalized momentum,
inspired by arXiv:2603.15848's finding that momentum/volatility
ratio deciles produce the strongest forward returns.

Core insight: a 10% return is more meaningful in a low-volatility
regime than in a high-volatility regime. Normalizing momentum by
historical volatility produces a signal that adapts to market conditions.

Entry (long):  risk_adj_momentum > threshold AND close > EMA(trend)
Entry (short): risk_adj_momentum < -threshold AND close < EMA(trend)
Exit:          risk_adj_momentum crosses zero (momentum exhausted)

2 entry conditions total.
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import ema, historical_volatility


class RiskAdjustedMomentum(Strategy):
    """Volatility-normalized momentum with EMA trend filter.

    Computes 63-bar return divided by 20-bar annualized volatility
    to produce a risk-adjusted momentum signal. Entry requires both
    signal exceeding threshold and trend alignment (close vs EMA).

    Parameters:
        momentum_period: Lookback for momentum calculation (default 63)
        vol_period: Lookback for volatility estimation (default 20)
        threshold: Minimum risk-adjusted momentum for entry (default 1.0)
        trend_period: EMA trend filter lookback (default 200)
    """

    timeframe = "1h"
    min_bars = 300  # trend_period + momentum_period + buffer
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "momentum_period": 63,
        "vol_period": 20,
        "threshold": 1.0,
        "trend_period": 200,
    }

    @property
    def name(self) -> str:
        return "RiskAdjustedMomentum"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate signals from risk-adjusted momentum + EMA trend filter.

        Args:
            df: OHLCV DataFrame with DatetimeIndex.

        Returns:
            pd.Series of int: 1=long, -1=short, 0=flat, same index as df.
        """
        df = self.preprocess(df)
        close: pd.Series = df["close"]  # type: ignore[assignment]

        momentum_period = self.params["momentum_period"]
        vol_period = self.params["vol_period"]
        threshold = self.params["threshold"]
        trend_period = self.params["trend_period"]

        # Compute indicators
        momentum = close / close.shift(momentum_period) - 1.0
        vol = historical_volatility(close, period=vol_period, annualize=False)
        risk_adj = momentum / vol.replace(0, np.nan)

        ema_trend = ema(close, period=trend_period)

        # Entry signals (2 conditions: risk-adj signal + trend direction)
        trend_up = close > ema_trend
        trend_down = close < ema_trend

        long_entry = (risk_adj > threshold) & trend_up
        short_entry = (risk_adj < -threshold) & trend_down

        # Exit signals: risk-adj crosses zero (momentum exhausted)
        exit_long = risk_adj < 0.0
        exit_short = risk_adj > 0.0

        # Stateful signal generation
        n = len(df)
        signal_arr = np.zeros(n, dtype=int)
        position = 0  # 0=flat, 1=long, -1=short

        for i in range(n):
            if pd.isna(risk_adj.iloc[i]) or pd.isna(ema_trend.iloc[i]):
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
