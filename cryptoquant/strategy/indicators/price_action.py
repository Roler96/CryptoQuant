"""Price Action indicators."""
# pyright: reportAttributeAccessIssue=false, reportReturnType=false, reportArgumentType=false

import numpy as np
import pandas as pd

__all__ = [
    "wick_imbalance",
    "heikin_ashi",
    "pivot_high",
    "pivot_low",
    "pivot_levels",
]

def wick_imbalance(df: pd.DataFrame, window: int = 6) -> pd.Series:
    """Wick pressure imbalance ratio (-1 to +1).

    Positive = seller wick pressure dominates.
    Negative = buyer wick pressure dominates.
    """
    high = df["high"]
    low = df["low"]
    open_ = df["open"]
    close = df["close"]
    volume = df["volume"]

    bar_range = (high - low).clip(lower=1e-8)
    upper_wick = (high - np.maximum(open_, close)) / bar_range
    lower_wick = (np.minimum(open_, close) - low) / bar_range

    bear_pressure = upper_wick * np.log1p(volume)
    bull_pressure = lower_wick * np.log1p(volume)

    bear_roll = bear_pressure.rolling(window).sum()
    bull_roll = bull_pressure.rolling(window).sum()

    total = bear_roll + bull_roll
    imbalance = (bear_roll - bull_roll) / total.replace(0, np.nan)

    return imbalance.fillna(0)



def heikin_ashi(df: pd.DataFrame) -> pd.DataFrame:
    """Heikin-Ashi candle transformation.

    HA candles apply a smoothing formula to OHLC data, reducing noise
    and producing consecutive same-color candles during strong trends.

    HA_close = (O + H + L + C) / 4
    HA_open = (prev_HA_open + prev_HA_close) / 2
    HA_high = max(H, HA_open, HA_close)
    HA_low = min(L, HA_open, HA_close)

    Args:
        df: OHLCV DataFrame with columns [open, high, low, close].

    Returns:
        pd.DataFrame with columns [ha_open, ha_high, ha_low, ha_close],
        same index as input.
    """
    open_, high, low, close = df["open"], df["high"], df["low"], df["close"]

    ha_close = (open_ + high + low + close) / 4.0
    n = len(df)
    ha_open = pd.Series(np.nan, index=df.index, dtype=float)

    # Seed the first HA open with the first bar's open
    if n > 0:
        ha_open.iloc[0] = open_.iloc[0]

    # Recursive: HA_open = (prev_HA_open + prev_HA_close) / 2
    for i in range(1, n):
        prev_o = ha_open.iloc[i - 1]
        prev_c = ha_close.iloc[i - 1]
        if not pd.isna(prev_o) and not pd.isna(prev_c):
            ha_open.iloc[i] = (prev_o + prev_c) / 2.0

    ha_high = pd.concat([high, ha_open, ha_close], axis=1).max(axis=1)
    ha_low = pd.concat([low, ha_open, ha_close], axis=1).min(axis=1)

    return pd.DataFrame(
        {"ha_open": ha_open, "ha_high": ha_high, "ha_low": ha_low, "ha_close": ha_close},
        index=df.index,
    )



def pivot_high(df: pd.DataFrame, left_bars: int = 5, right_bars: int = 5) -> pd.Series:
    """Detect swing pivot highs (confirmed when a bar's high exceeds the
    highs of *left_bars* bars on each side).

    Returns a boolean Series where True marks a confirmed pivot high.
    The confirmation is only available *right_bars* bars after the pivot
    bar — the Series stores True at the pivot bar's index (the look-back
    is valid for backtesting because the strategy reads the pivot at
    bar i - right_bars when generating signals at bar i).
    """
    high = df["high"]
    n = len(high)
    result = pd.Series(False, index=df.index)

    vals = high.values
    left_bars + right_bars
    for i in range(left_bars, n - right_bars):
        centre = vals[i]
        lhs = vals[i - left_bars : i]
        rhs = vals[i + 1 : i + right_bars + 1]
        if centre > lhs.max() and centre > rhs.max():
            result.iloc[i] = True

    return result



def pivot_low(df: pd.DataFrame, left_bars: int = 5, right_bars: int = 5) -> pd.Series:
    """Detect swing pivot lows (mirror of pivot_high for lows)."""
    low = df["low"]
    n = len(low)
    result = pd.Series(False, index=df.index)

    vals = low.values
    for i in range(left_bars, n - right_bars):
        centre = vals[i]
        lhs = vals[i - left_bars : i]
        rhs = vals[i + 1 : i + right_bars + 1]
        if centre < lhs.min() and centre < rhs.min():
            result.iloc[i] = True

    return result



def pivot_levels(df: pd.DataFrame, left_bars: int = 5, right_bars: int = 5) -> pd.DataFrame:
    """Return a DataFrame with pivot high and low levels.

    Columns:
        pivot_high_level  — most recent confirmed pivot high level
        pivot_low_level   — most recent confirmed pivot low level
        is_pivot_high     — True at confirmed pivot high bar
        is_pivot_low      — True at confirmed pivot low bar
    """
    is_high = pivot_high(df, left_bars, right_bars)
    is_low = pivot_low(df, left_bars, right_bars)

    high_level = df["high"].where(is_high).ffill()
    low_level = df["low"].where(is_low).ffill()

    return pd.DataFrame(
        {
            "pivot_high_level": high_level,
            "pivot_low_level": low_level,
            "is_pivot_high": is_high,
            "is_pivot_low": is_low,
        },
        index=df.index,
    )
