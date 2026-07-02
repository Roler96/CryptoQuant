"""Fractal indicators."""

import numpy as np
import pandas as pd

__all__ = [
    "hurst_exponent",
]

def hurst_exponent(series: pd.Series, period: int = 100, max_lag: int = 20) -> pd.Series:
    """Rolling Hurst exponent via rescaled range (R/S) analysis.

    For each window of size *period*, subdivides into *max_lag* sub-windows
    of increasing size, computes the mean R/S statistic for each size, and
    fits log(R/S) vs log(size) via OLS.  The slope is the Hurst exponent:
      - H > 0.5 → trending / persistent (moves reinforce)
      - H ≈ 0.5 → random walk (no memory)
      - H < 0.5 → mean-reverting / anti-persistent (moves reverse)

    Uses a centred sliding window so the value for bar *i* reflects the
    period ending at *i* (no look-ahead).  OLS is computed with np.linalg
    in a vectorised-rolling fashion.
    """
    n = len(series)
    vals = np.asarray(series, dtype=float)
    result = np.full(n, np.nan)

    if n < period:
        return pd.Series(result, index=series.index)

    # Pre-allocate sub-window sizes (min 10 bars, max period // 2)
    min_sub = max(10, period // 10)
    lags = np.linspace(min_sub, period // 2, max_lag, dtype=int)
    lags = np.unique(np.clip(lags, min_sub, period // 2))
    log_lags = np.log(lags)

    for i in range(period - 1, n):
        window = vals[i - period + 1 : i + 1]
        rs_values = np.empty(len(lags))

        for j, lag in enumerate(lags):
            # Partition window into floor(period / lag) sub-series
            n_sub = period // lag
            rs_sum = 0.0
            count = 0
            for k in range(n_sub):
                sub = window[k * lag : (k + 1) * lag]
                if len(sub) < 2:
                    continue
                mean = sub.mean()
                deviate = sub - mean
                cum = np.cumsum(deviate)
                r = cum.max() - cum.min()
                s = np.std(sub, ddof=1)
                if s > 1e-10:
                    rs_sum += r / s
                    count += 1
            if count > 0:
                rs_values[j] = rs_sum / count
            else:
                rs_values[j] = np.nan

        # OLS: log(R/S) ~ log(lag)
        valid = ~np.isnan(rs_values) & (rs_values > 0)
        if valid.sum() >= 4:  # need at least 4 points for a stable fit
            # Simple OLS slope: cov(x, y) / var(x)
            x = log_lags[valid]
            y = np.log(rs_values[valid])
            x_mean = x.mean()
            y_mean = y.mean()
            slope = np.sum((x - x_mean) * (y - y_mean)) / np.sum((x - x_mean) ** 2)
            result[i] = float(slope)

    return pd.Series(result, index=series.index)
