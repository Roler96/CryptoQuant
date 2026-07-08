"""Technical indicators library -- pure NumPy/pandas, zero external dependencies.

Composite signal functions remain here; pure indicators are in the
`cryptoquant.strategy.indicators` sub-package and re-exported below for
backward compatibility.
"""
# pyright: reportAttributeAccessIssue=false, reportReturnType=false, reportArgumentType=false

import numpy as np
import pandas as pd

# Backward-compat re-export: all indicator functions from the indicators package
from cryptoquant.strategy.indicators import *  # re-export for backward compat

# Explicit imports for functions used by composite signals below
from cryptoquant.strategy.indicators.trend import sma
from cryptoquant.strategy.indicators.volatility import atr
from cryptoquant.strategy.indicators.momentum import adx


def detect_regime(
    df: pd.DataFrame,
    adx_period: int = 14,
    vol_period: int = 20,
    sma_period: int = 200,
    adx_threshold: float = 25.0,
    vol_high_pct: float = 70.0,
    vol_low_pct: float = 30.0,
) -> pd.Series:
    """Detect market regime for each bar.

    Uses ADX for trend strength, volatility percentile for regime classification,
    and SMA200 for directional bias.

    Regimes:
    - "trending_bull": ADX > threshold and close > SMA200
    - "trending_bear": ADX > threshold and close < SMA200
    - "mean_reverting": ADX <= threshold and volatility in middle range
    - "volatile": ADX <= threshold and volatility > high percentile
    - "quiet": ADX <= threshold and volatility < low percentile

    Args:
        df: OHLCV DataFrame with columns [open, high, low, close, volume]
        adx_period: Period for ADX calculation
        vol_period: Period for volatility percentile
        sma_period: Period for SMA200
        adx_threshold: ADX level above which market is considered trending
        vol_high_pct: Volatility percentile threshold for "volatile"
        vol_low_pct: Volatility percentile threshold for "quiet"

    Returns:
        String Series with regime labels, same index as df.
    """
    close = df["close"]

    adx_df = adx(df, period=adx_period)
    adx_val = adx_df["adx"]
    sma_line = sma(close, period=sma_period)

    atr_val = atr(df, period=vol_period)
    vol_pct = atr_val.rolling(vol_period).apply(
        lambda x: np.mean(x <= x.iloc[-1]) * 100, raw=False
    )

    regimes = pd.Series("quiet", index=df.index, dtype=object)

    trending = adx_val > adx_threshold
    above_sma = close > sma_line

    regimes[trending & above_sma] = "trending_bull"
    regimes[trending & ~above_sma] = "trending_bear"

    non_trending = ~trending
    volatile = non_trending & (vol_pct > vol_high_pct)
    quiet = non_trending & (vol_pct < vol_low_pct)
    mean_reverting = non_trending & ~volatile & ~quiet

    regimes[volatile] = "volatile"
    regimes[quiet] = "quiet"
    regimes[mean_reverting] = "mean_reverting"

    return regimes
