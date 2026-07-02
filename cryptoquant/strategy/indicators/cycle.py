"""Cycle indicators."""

import numpy as np
import pandas as pd

__all__ = [
    "hilbert_transform",
    "pfe",
]

def hilbert_transform(
    df: pd.DataFrame, price_col: str = "close"
) -> pd.DataFrame:
    """Compute Hilbert Transform InPhase (I) and Quadrature (Q) components.

    Follows John Ehlers' MESA algorithm:
      Smooth price → Detrend → InPhase → Quadrature

    The I and Q components represent the cyclical component of price
    as a complex phasor: I = real part, Q = imaginary part.

    Args:
        df: OHLCV DataFrame; uses `price_col` as the input series.
        price_col: Column name for price input (default "close").

    Returns:
        pd.DataFrame with columns [i, q, phase, delta_phase, smooth],
        same index as df.  i/q are the core Hilbert components;
        phase is in degrees (0-360); delta_phase is the phase change
        per bar (clamped to a minimum of 1).
    """
    price = df[price_col].values.astype(np.float64)
    n = len(price)

    # ── 1. Smooth with 4-bar WMA ──
    smooth = np.full(n, np.nan, dtype=np.float64)
    w = np.array([4.0, 3.0, 2.0, 1.0])
    w_sum = w.sum()
    for i in range(3, n):
        smooth[i] = np.dot(price[i - 3 : i + 1][::-1], w) / w_sum

    # ── 2. Detrend with 7-bar bandpass filter ──
    detrender = np.full(n, np.nan, dtype=np.float64)
    for i in range(7, n):
        detrender[i] = (
            0.0962 * smooth[i]
            + 0.5769 * smooth[i - 2]
            - 0.5769 * smooth[i - 4]
            - 0.0962 * smooth[i - 6]
        )

    # ── 3. InPhase (I) — 1-bar delay of detrender ──
    i_comp = np.full(n, np.nan, dtype=np.float64)
    for idx in range(8, n):
        i_comp[idx] = 0.25 * detrender[idx - 3] + 0.75 * detrender[idx - 1]

    # ── 4. Quadrature (Q) — Hilbert transform of detrender ──
    q_comp = np.full(n, np.nan, dtype=np.float64)
    for idx in range(8, n):
        # 5.5-bar Hilbert Transformer (Ehlers)
        q_comp[idx] = (
            0.0962 * detrender[idx]
            + 0.5769 * detrender[idx - 2]
            - 0.5769 * detrender[idx - 4]
            - 0.0962 * detrender[idx - 6]
        )

    # ── 5. Phase ──
    phase = np.full(n, np.nan, dtype=np.float64)
    delta_phase = np.full(n, np.nan, dtype=np.float64)
    for idx in range(8, n):
        if q_comp[idx] != 0.0:
            phase_rad = np.arctan(np.abs(i_comp[idx] / q_comp[idx]))
        else:
            phase_rad = np.pi / 2.0
        # Unwrap to 0-360 degrees
        deg = np.degrees(phase_rad)
        if q_comp[idx] < 0 and i_comp[idx] > 0:
            deg = 180.0 - deg
        elif q_comp[idx] < 0 and i_comp[idx] < 0:
            deg = -180.0 + deg
        elif q_comp[idx] > 0 and i_comp[idx] < 0:
            deg = -deg
        if deg < 0:
            deg += 360.0
        phase[idx] = deg

    # ── 6. Delta phase (clamped minimum 1) ──
    for idx in range(9, n):
        if np.isnan(phase[idx]) or np.isnan(phase[idx - 1]):
            continue
        dp = phase[idx - 1] - phase[idx]
        if dp < 1.0:
            dp = 1.0
        if dp > 50.0:
            dp = 50.0  # upper clamp — prevent insane alpha
        delta_phase[idx] = dp

    return pd.DataFrame(
        {
            "i": i_comp,
            "q": q_comp,
            "phase": phase,
            "delta_phase": delta_phase,
            "smooth": smooth,
        },
        index=df.index,
    )



def pfe(series: pd.Series, period: int = 10) -> pd.Series:
    """Polarized Fractal Efficiency — signed efficiency measure.

    PFE measures how efficiently price moves over N bars using fractal
    geometry. Unlike Kaufman's Efficiency Ratio (unsigned 0-1), PFE is
    signed (-100 to +100), making it a natural oscillator for trend-
    following entry.

    Formula:
        net = sqrt((C[t] - C[t-N])² + N²)
        gross = Σ sqrt((C[i] - C[i-1])² + 1)  for i = t-N+1..t
        PFE = 100 × (net / gross) × sign(C[t] - C[t-N])

    Reference: Hans Hannula — "Polarized Fractal Efficiency" (1994).

    Args:
        series: Price series (typically close).
        period: Lookback period for efficiency measurement.

    Returns:
        pd.Series of PFE values (-100 to +100), same index as input.
    """
    n = period
    if n < 2:
        raise ValueError(f"PFE period must be >= 2, got {n}")

    close = series.values.astype(float)
    length = len(close)
    result = np.full(length, np.nan)

    for i in range(n, length):
        c_now = close[i]
        c_prev = close[i - n]
        net = np.sqrt((c_now - c_prev) ** 2 + n ** 2)

        gross = 0.0
        for j in range(i - n + 1, i + 1):
            diff = close[j] - close[j - 1]
            gross += np.sqrt(diff ** 2 + 1.0)

        if gross > 0:
            eff = net / gross
            pfe_val = 100.0 * eff * (1.0 if c_now >= c_prev else -1.0)
            result[i] = pfe_val

    return pd.Series(result, index=series.index)
