"""SupertrendRegime — Supertrend with ADX Regime Gate (long-only).

Supertrend is an ATR-based trailing stop indicator. It computes upper and lower
bands from the median price ± (factor × ATR), then trails these bands: when
price closes above the upper band, an uptrend begins and the lower band becomes
the trailing stop. When price closes below the lower band, the trend reverses.

The ADX regime gate filters out signals from mean-reverting, volatile, or quiet
markets, only entering longs during trending_bull regimes.

Signal convention: 1 = long, 0 = flat. NO shorts.
"""

import numpy as np
import pandas as pd

from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.signals import atr, detect_regime


class SupertrendRegime(Strategy):
    """Supertrend ATR-based trailing stop with ADX regime gate.

    Parameters
    ----------
    atr_period : int (default 10)
        ATR period for band width calculation. Range: 7–21.
    factor : float (default 3.0)
        Multiplier for ATR bands. Range: 1.5–4.0.
    adx_period : int (default 14)
        ADX period for regime detection. Range: 7–21.
    adx_threshold : int (default 25)
        ADX threshold above which market is considered trending.
        Range: 15–35.
    regime_filter_enabled : bool (default True)
        When True, only enter longs during "trending_bull" regimes.
    """

    timeframe = "1h"
    min_bars = 600
    version = "1.0.0"

    DEFAULT_PARAMS = {
        "atr_period": 10,
        "factor": 3.0,
        "adx_period": 14,
        "adx_threshold": 25,
        "regime_filter_enabled": True,
    }

    @property
    def name(self) -> str:
        return "SupertrendRegime"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        """Generate trading signals from OHLCV DataFrame.

        Returns pd.Series with 1 = long, 0 = flat, same length/index as df.
        """
        df = self.preprocess(df)

        atr_period = self.params["atr_period"]
        factor = self.params["factor"]
        adx_period = self.params["adx_period"]
        adx_threshold = self.params["adx_threshold"]
        regime_filter_enabled = self.params["regime_filter_enabled"]

        # ── ATR ──────────────────────────────────────────────
        atr_val = atr(df, period=atr_period)

        # ── Supertrend bands ─────────────────────────────────
        high = df["high"].values
        low = df["low"].values
        close = df["close"].values
        atr_arr = atr_val.values

        median = (high + low) / 2.0
        upper_band = median + factor * atr_arr
        lower_band = median - factor * atr_arr

        n = len(df)
        trend = np.zeros(n, dtype=np.int8)
        trailing_stop = np.full(n, np.nan)

        # Initialize first bar: no trend
        # trailing_stop[0] stays NaN

        for i in range(1, n):
            if close[i] > upper_band[i - 1]:
                # Uptrend begins
                trend[i] = 1
                trailing_stop[i] = lower_band[i]
            elif close[i] < lower_band[i - 1]:
                # Downtrend begins
                trend[i] = -1
                trailing_stop[i] = upper_band[i]
            else:
                # Continue previous trend
                trend[i] = trend[i - 1]
                if trend[i] == 1:
                    # Uptrend: trail stop upward
                    trailing_stop[i] = max(
                        trailing_stop[i - 1], lower_band[i]
                    )
                elif trend[i] == -1:
                    # Downtrend: trail stop downward
                    trailing_stop[i] = min(
                        trailing_stop[i - 1], upper_band[i]
                    )

        signal = trend == 1  # long when in uptrend

        # ── ADX Regime Gate ──────────────────────────────────
        if regime_filter_enabled:
            regime = detect_regime(
                df,
                adx_period=adx_period,
                adx_threshold=adx_threshold,
            )
            signal = signal & (regime == "trending_bull")

        return pd.Series(signal.astype(int), index=df.index)
