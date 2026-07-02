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
from cryptoquant.strategy.indicators.price_action import wick_imbalance
from cryptoquant.strategy.indicators.utilities import pct_change_rolling


def wick_inversion_signal(
    df: pd.DataFrame,
    imbalance_window: int = 6,
    imbalance_threshold: float = 0.25,
    price_lookback: int = 6,
    price_floor: float = -0.5,
    vol_gate_enabled: bool = True,
    trend_filter_enabled: bool = True,
    **kwargs: object,
) -> pd.Series:
    """Generate Wick Inversion trading signals.

    Detects seller exhaustion via upper wick pressure + volume,
    enters long when imbalance exceeds threshold and price is not
    in free-fall.

    Args:
        df: OHLCV DataFrame with columns [open, high, low, close, volume]
        imbalance_window: Rolling sum window for wick pressure
        imbalance_threshold: Min seller/buyer imbalance
        price_lookback: Price change calculation window (hours)
        price_floor: Min price change (%) to allow entry
        vol_gate_enabled: Enable volatility gating (ATR > median)
        trend_filter_enabled: Enable SMA200 trend filter

    Returns:
        pd.Series of int signals (1 = long, 0 = flat)
    """
    imb = wick_imbalance(df, window=imbalance_window)
    price_chg = pct_change_rolling(df["close"], price_lookback)

    signal = (imb > imbalance_threshold) & (price_chg > price_floor)

    if vol_gate_enabled:
        atr14 = atr(df, 14)
        median_atr = atr14.rolling(200).median()
        vol_ratio = atr14 / median_atr
        vol_ok = vol_ratio > 1.0
        signal = signal & vol_ok

    if trend_filter_enabled:
        sma200 = sma(df["close"], 200)
        trend_ok = df["close"] > sma200
        signal = signal & trend_ok

    return signal.astype(int)



def spring_reversal_signal(
    df: pd.DataFrame,
    lookback: int = 20,
    vol_mult: float = 1.5,
    close_pct: float = 0.5,
) -> pd.Series:
    """Detect Wyckoff Spring reversal pattern.

    A Spring forms when price makes a new low below recent support but
    closes bullish with high volume — this is a "failed breakdown" that
    traps sellers and signals a reversal.

    Conditions:
    1. New low: current low < lowest low of previous `lookback` bars
    2. Bullish close: close > open (buyers stepped in)
    3. Close near high: close position in upper `close_pct` of bar range
    4. High volume: volume > `vol_mult` × average volume over lookback

    Args:
        df: OHLCV DataFrame with columns [open, high, low, close, volume]
        lookback: Number of bars for support level and volume average
        vol_mult: Volume multiplier threshold (e.g., 1.5 = 150% of avg)
        close_pct: Close must be above this fraction of bar range (0.0-1.0)

    Returns:
        Boolean Series, same index as df. True at Spring signal bars.
    """
    opens = df["open"]
    highs = df["high"]
    lows = df["low"]
    closes = df["close"]
    volumes = df["volume"]

    # Condition 1: New low (breakdown below recent support)
    rolling_low = lows.rolling(lookback).min().shift(1)
    new_low = lows < rolling_low

    # Condition 2: Bullish close
    bullish_close = closes > opens

    # Condition 3: Close in upper portion of bar
    bar_range = highs - lows
    close_position = (closes - lows) / bar_range.replace(0, np.nan)
    close_near_high = close_position > close_pct

    # Condition 4: High volume (confirmation)
    avg_vol = volumes.rolling(lookback).mean().shift(1)
    high_volume = volumes > (vol_mult * avg_vol)

    signal = new_low & bullish_close & close_near_high & high_volume
    return signal



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
