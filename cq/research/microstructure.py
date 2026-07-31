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


def vwap_position(
    high: np.ndarray,
    low: np.ndarray,
    quote_volume: np.ndarray,
    volume: np.ndarray,
) -> np.ndarray:
    """(VWAP - L) / (H - L): where the bar's volume-weighted centroid sits in its range.

    `H == L` (no range) or zero volume (nothing traded) leaves this
    undefined, and it is reported as `np.nan` there -- deliberately unlike
    `centroid_delta`, which returns 0 for its own undefined case. `delta`'s 0
    is meant to flow straight into further arithmetic as a neutral value; the
    VWAP-position protocol instead requires undefined bars to be *dropped*
    from the statistics that consume this (see `VWAP_POSITION_PROTOCOL`
    Sec. 1), and a silent 0 would be indistinguishable from a genuine
    bottom-of-range reading, hiding exactly the bars the protocol wants
    excluded. NaN forces every caller to make that exclusion explicit.
    """
    hi = np.asarray(high, dtype=np.float64)
    lo = np.asarray(low, dtype=np.float64)
    centre = vwap(quote_volume, volume)
    span = hi - lo
    usable = (span > 0) & np.isfinite(centre)
    out = np.full_like(hi, np.nan)
    np.divide(centre - lo, span, out=out, where=usable)
    return out


_CS_K = 3.0 - 2.0 * np.sqrt(2.0)


def corwin_schultz_spread(high: np.ndarray, low: np.ndarray) -> np.ndarray:
    """Effective spread estimated from two consecutive bars' high-low ranges.

    Corwin & Schultz (2012). The point of estimating it at all is that this
    project's cost wall has always been a constant 15 bps assumption; a spread
    that varies bar to bar turns cost into a state variable, and a strategy can
    then decline to trade when trading is expensive.

    Negative estimates are a known small-sample artefact of the estimator and
    are truncated to zero rather than propagated.

    Raises ValueError on non-positive prices, high < low, or mismatched
    array lengths: those are data corruption, not market fact, and must not
    be folded into a valid spread value by silent NaN/inf suppression.
    """
    hi = np.asarray(high, dtype=np.float64)
    lo = np.asarray(low, dtype=np.float64)

    if hi.shape != lo.shape:
        raise ValueError(f"high and low must have the same shape, got {hi.shape} vs {lo.shape}")

    bad_hi = int(np.sum(hi <= 0))
    if bad_hi:
        raise ValueError(f"high must be strictly positive, found {bad_hi} non-positive value(s)")

    bad_lo = int(np.sum(lo <= 0))
    if bad_lo:
        raise ValueError(f"low must be strictly positive, found {bad_lo} non-positive value(s)")

    bad_order = int(np.sum(hi < lo))
    if bad_order:
        raise ValueError(f"high must be >= low, found {bad_order} bar(s) with high < low")

    single = np.log(hi / lo) ** 2
    beta = single[:-1] + single[1:]
    hi2 = np.maximum(hi[:-1], hi[1:])
    lo2 = np.minimum(lo[:-1], lo[1:])
    gamma = np.log(hi2 / lo2) ** 2

    alpha = (np.sqrt(2.0 * beta) - np.sqrt(beta)) / _CS_K - np.sqrt(gamma / _CS_K)
    # Algebraically 2(e^a - 1) / (1 + e^a) == tanh(a/2), but the exp(alpha) form
    # overflows to inf for large alpha, making the ratio NaN and forcing the
    # isfinite guard below to zero it out -- reading the widest spreads as
    # zero cost, the worst possible direction for a cost gate. tanh has no
    # such overflow branch, so it needs no special-casing.
    spread = 2.0 * np.tanh(alpha / 2.0)
    return np.where(np.isfinite(spread), np.maximum(spread, 0.0), 0.0)
