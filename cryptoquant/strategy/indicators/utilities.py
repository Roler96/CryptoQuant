"""Utilities indicators."""
# pyright: reportAttributeAccessIssue=false, reportReturnType=false, reportArgumentType=false

import numpy as np
import pandas as pd

__all__ = [
    "crossover",
    "crossunder",
    "rolling_max",
    "rolling_min",
    "pct_change_rolling",
    "_closing_streak",
    "_percent_rank",
]

def crossover(series_a: pd.Series, series_b: pd.Series) -> pd.Series:
    """Detect when series_a crosses ABOVE series_b.

    Returns: 1 at crossover points, 0 elsewhere.
    """
    above = series_a > series_b
    prev_above = above.shift(1, fill_value=False)
    cross = above & ~prev_above
    return cross.astype(int)



def crossunder(series_a: pd.Series, series_b: pd.Series) -> pd.Series:
    """Detect when series_a crosses BELOW series_b.

    Returns: -1 at crossunder points, 0 elsewhere.
    """
    below = series_a < series_b
    prev_below = below.shift(1, fill_value=False)
    cross = below & ~prev_below
    return cross.astype(int) * -1



def rolling_max(series: pd.Series, period: int) -> pd.Series:
    """Rolling maximum."""
    return series.rolling(period).max()



def rolling_min(series: pd.Series, period: int) -> pd.Series:
    """Rolling minimum."""
    return series.rolling(period).min()



def pct_change_rolling(series: pd.Series, period: int) -> pd.Series:
    """Rolling percentage change."""
    return series.pct_change(period) * 100



def _closing_streak(close: pd.Series) -> pd.Series:
    """Compute closing streak: consecutive up (positive) or down (negative) closes.

    +1 for each consecutive up-close, +2 for 2-up streak, etc.
    -1 for each consecutive down-close, -2 for 2-down streak, etc.
    Zero on flat close resets the streak.
    """
    diff = close.diff()
    streak = pd.Series(0, index=close.index, dtype=float)

    for i in range(1, len(close)):
        if pd.isna(diff.iloc[i]):
            streak.iloc[i] = 0
        elif diff.iloc[i] > 0:
            streak.iloc[i] = max(streak.iloc[i - 1] + 1, 1)
        elif diff.iloc[i] < 0:
            streak.iloc[i] = min(streak.iloc[i - 1] - 1, -1)
        else:
            streak.iloc[i] = 0

    return streak



def _percent_rank(series: pd.Series, period: int = 100) -> pd.Series:
    """Percent rank: where the current value ranks in the past `period` values.

    Returns 0-1 where 1 means current value is at the top of the recent range.
    """
    result = pd.Series(np.nan, index=series.index)

    for i in range(period, len(series)):
        window = series.iloc[i - period : i + 1]
        result.iloc[i] = (window <= window.iloc[-1]).sum() / (period + 1)

    return result
