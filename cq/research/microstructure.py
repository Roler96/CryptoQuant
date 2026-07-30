"""Microstructure quantities readable from 5m OHLCV alone.

`close` is the last tick of a bar — an estimate with sample size one. The
volume-weighted centroid of the same bar carries far more of what happened
inside it, and on DOGE spot 5m the two are nearly orthogonal (measured
correlation 0.1415 between their in-bar positions over the explore window).
That orthogonality is the whole reason this module exists.
"""

from __future__ import annotations

import numpy as np


def log_returns(close: np.ndarray) -> np.ndarray:
    """Log returns, additive across aggregation so scales stay comparable."""
    prices = np.asarray(close, dtype=np.float64)
    return np.diff(np.log(prices))


def vwap(quote_volume: np.ndarray, volume: np.ndarray) -> np.ndarray:
    """Volume-weighted average price; NaN where the bar traded nothing."""
    qv = np.asarray(quote_volume, dtype=np.float64)
    vol = np.asarray(volume, dtype=np.float64)
    return np.divide(qv, vol, out=np.full_like(qv, np.nan), where=vol > 0)


def centroid_delta(
    high: np.ndarray,
    low: np.ndarray,
    close: np.ndarray,
    quote_volume: np.ndarray,
    volume: np.ndarray,
) -> np.ndarray:
    """(C - VWAP) / (H - L): where the close sits relative to where volume traded.

    Large delta means the bar's late move outran its volume — displacement the
    order flow did not confirm. Zero by definition when the bar has no range or
    no trades, so callers never see a NaN they must special-case.
    """
    hi = np.asarray(high, dtype=np.float64)
    lo = np.asarray(low, dtype=np.float64)
    cl = np.asarray(close, dtype=np.float64)
    centre = vwap(quote_volume, volume)
    span = hi - lo
    usable = (span > 0) & np.isfinite(centre)
    out = np.zeros_like(hi)
    np.divide(cl - centre, span, out=out, where=usable)
    return out
