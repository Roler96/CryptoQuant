"""Trend indicators."""
# pyright: reportAttributeAccessIssue=false, reportReturnType=false, reportArgumentType=false

import numpy as np
import pandas as pd

__all__ = [
    "sma",
    "ema",
    "wma",
    "kama",
    "hma",
    "alma",
    "mcginley_dynamic",
    "vidya",
    "ichimoku",
    "supertrend",
    "psar",
    "decycler",
    "vhf",
    "choppiness_index",
    "efficiency_ratio",
    "vortex",
    "linreg",
]

def sma(series: pd.Series, period: int) -> pd.Series:
    """Simple Moving Average."""
    return series.rolling(period).mean()



def ema(series: pd.Series, period: int) -> pd.Series:
    """Exponential Moving Average."""
    return series.ewm(span=period, adjust=False).mean()



def wma(series: pd.Series, period: int) -> pd.Series:
    """Weighted Moving Average."""
    weights = np.arange(1, period + 1, dtype=float)
    return series.rolling(period).apply(
        lambda x: np.dot(x, weights) / weights.sum(), raw=True
    )



def kama(
    series: pd.Series,
    er_period: int = 10,
    fast_ema: int = 2,
    slow_ema: int = 30,
) -> pd.Series:
    """Kaufman's Adaptive Moving Average (KAMA).

    Dynamically adjusts smoothing based on the Efficiency Ratio (ER),
    which measures how directional price movement is relative to total
    volatility.  In trending markets (high ER), KAMA follows price
    closely; in choppy/noisy markets (low ER), it lags more.

    Reference: Perry Kaufman — "Trading Systems and Methods" (1998).

    Args:
        series: Price series (typically close).
        er_period: Lookback for Efficiency Ratio calculation.
        fast_ema: Fastest EMA period for the smoothing constant.
        slow_ema: Slowest EMA period for the smoothing constant.

    Returns:
        pd.Series of KAMA values, same index as input.
    """
    # Efficiency Ratio: |Δprice| / sum of |Δprice_i|
    direction = (series - series.shift(er_period)).abs()
    volatility = series.diff().abs().rolling(er_period).sum()
    er = direction / volatility.replace(0, np.nan)
    er = er.clip(0.0, 1.0)

    # Smoothing constant
    fastest_sc = 2.0 / (fast_ema + 1)
    slowest_sc = 2.0 / (slow_ema + 1)
    sc = (er * (fastest_sc - slowest_sc) + slowest_sc) ** 2

    # Recursive KAMA
    n = len(series)
    result = pd.Series(np.nan, index=series.index, dtype=float)
    if n == 0:
        return result

    val = series.values
    sc_val = sc.values
    kama_vals = np.full(n, np.nan)

    # Seed KAMA with the first valid value
    seed_idx = er_period
    if seed_idx < n:
        kama_vals[seed_idx] = val[seed_idx]

    for i in range(seed_idx + 1, n):
        if np.isnan(sc_val[i]) or np.isnan(val[i - 1]):
            continue
        prev = kama_vals[i - 1]
        if np.isnan(prev):
            kama_vals[i] = val[i]
        else:
            kama_vals[i] = prev + sc_val[i] * (val[i] - prev)

    result.iloc[:] = kama_vals
    return result



def hma(series: pd.Series, period: int) -> pd.Series:
    """Hull Moving Average — zero-lag moving average.

    HMA uses weighted moving averages with a square-root smoothing
    period to achieve near-zero lag compared to traditional EMAs.

    Formula: HMA = WMA(2 * WMA(close, n/2) - WMA(close, n), sqrt(n))

    Reference: Alan Hull (2005), "The Hull Moving Average".

    Args:
        series: Price series (typically close).
        period: Lookback period for the HMA.

    Returns:
        pd.Series of HMA values, same index as input.
    """
    half = int(period / 2)
    sqrt_n = int(np.sqrt(period))

    if half < 1 or sqrt_n < 1:
        raise ValueError(f"HMA period {period} is too small (need >= 4)")

    wma_half = wma(series, half)
    wma_full = wma(series, period)

    raw_hma = 2.0 * wma_half - wma_full

    return wma(raw_hma, sqrt_n)



def alma(series: pd.Series, period: int = 9, offset: float = 0.85,
         sigma: float = 6.0) -> pd.Series:
    """Arnaud Legoux Moving Average — Gaussian-weighted zero-lag MA.

    Uses a Gaussian (normal distribution) weighting function with
    adjustable offset to eliminate lag while maintaining smoothness.
    Unlike EMAs (which lag ~period/2 bars), ALMA can achieve near-zero
    lag without introducing the whipsaw of standard zero-lag attempts.

    Formula:
        w[j] = exp(-((j - m)²) / (2 × σ²))
        m = offset × (period - 1)
        σ = period / sigma
        ALMA = Σ w[j] × price[i-(period-1)+j] / Σ w[j]

    Reference: Arnaud Legoux & Dimitris Kouzis-Loukas (2009).

    Args:
        series: Price series (typically close).
        period: Lookback window size.
        offset: Gaussian center position (0.0=full lag, 1.0=zero lag).
        sigma: Gaussian width parameter (higher = smoother).

    Returns:
        pd.Series of ALMA values, same index as input.
    """
    if period < 2:
        raise ValueError(f"ALMA period must be >= 2, got {period}")

    m = offset * (period - 1)
    s = period / sigma

    # Precompute Gaussian weights (same for every window)
    weights = np.zeros(period)
    for j in range(period):
        weights[j] = np.exp(-((j - m) ** 2) / (2.0 * s ** 2))
    w_sum = weights.sum()

    close = series.values.astype(float)
    length = len(close)
    result = np.full(length, np.nan)

    for i in range(period - 1, length):
        window = close[i - period + 1 : i + 1]
        alma_val = np.dot(window, weights) / w_sum
        result[i] = alma_val

    return pd.Series(result, index=series.index)



def mcginley_dynamic(
    df: pd.DataFrame,
    period: int = 20,
    k: float = 0.6,
    price_col: str = "close",
) -> pd.Series:
    """McGinley Dynamic — self-adjusting moving average.

    Unlike standard EMAs which use a fixed smoothing constant,
    McGinley Dynamic adjusts its **response force** based on how
    far price is from the current MA value.  It speeds up when price
    moves away from the MA (strong trend) and slows down when price
    hugs the MA (consolidation), reducing false crossovers during
    choppy periods.

    MD_t = MD_{t−1} + (Price − MD_{t−1}) / (k × N × (Price/MD_{t−1})^4)

    Reference: John R. McGinley — "McGinley Dynamic" (1990).

    Args:
        df: OHLCV DataFrame.
        period: Lookback period N (default 20).
        k: Adjustment constant (0.6 = standard; 0.5 = more aggressive).
        price_col: Column name for price (default 'close').

    Returns:
        pd.Series of McGinley Dynamic values, same index as df.
    """
    price = df[price_col].values.astype(np.float64)
    n = len(price)

    md = np.full(n, np.nan, dtype=np.float64)

    if n < period:
        return pd.Series(md, index=df.index)

    # Seed with SMA over first `period` bars
    md[period - 1] = np.mean(price[:period])

    divisor = k * period
    for i in range(period, n):
        prev_md = md[i - 1]
        if np.isnan(prev_md) or prev_md <= 0.0 or np.isnan(price[i]):
            continue
        ratio = price[i] / prev_md
        adjustment = (price[i] - prev_md) / (divisor * ratio ** 4)
        md[i] = prev_md + adjustment

    return pd.Series(md, index=df.index)



def vidya(
    series: pd.Series,
    vidya_period: int = 9,
    cmo_period: int = 9,
) -> pd.Series:
    """VIDYA — Variable Index Dynamic Average (Chande).

    Unlike KAMA (which uses Kaufman's Efficiency Ratio — a non-directional
    noise measure), VIDYA uses the Chande Momentum Oscillator (CMO) as the
    efficiency ratio.  CMO measures directional trend strength, meaning
    VIDYA smooths LESS in strong directional trends (faster response) and
    smooths MORE in choppy conditions (noise reduction).

    Algorithm:

      up_moves = Σ max(close_t - close_{t-1}, 0) over cmo_period
      down_moves = Σ max(close_{t-1} - close_t, 0) over cmo_period
      CMO = (up_moves - down_moves) / (up_moves + down_moves)  → [-1, 1]
      alpha_t = 2/(vidya_period+1) · |CMO_t|
      VIDYA_t = alpha_t · close_t + (1-alpha_t) · VIDYA_{t-1}

    When CMO = 1 (pure uptrend): alpha = 2/(period+1), fastest tracking.
    When CMO = 0 (choppy): α → 0, maximum smoothing (near-constant).

    Args:
        series: Price series (typically close).
        vidya_period: Effective EMA period when CMO=1 (default 9).
        cmo_period: Lookback for CMO calculation (default 9).

    Returns:
        pd.Series of VIDYA values, same index as input.
    """
    close = series.values.astype(float)
    n = len(close)

    # CMO: (Σup - Σdown) / (Σup + Σdown)
    delta = np.diff(close, prepend=close[0])
    up = np.where(delta > 0, delta, 0.0)
    down = np.where(delta < 0, -delta, 0.0)

    up_roll = pd.Series(up, index=series.index).rolling(cmo_period).sum()
    down_roll = pd.Series(down, index=series.index).rolling(cmo_period).sum()
    up_sum: np.ndarray = np.asarray(up_roll, dtype=float)  # type: ignore[arg-type]
    down_sum: np.ndarray = np.asarray(down_roll, dtype=float)  # type: ignore[arg-type]

    total = up_sum + down_sum
    cmo = np.full(n, np.nan)
    mask = total > 0
    cmo[mask] = (up_sum[mask] - down_sum[mask]) / total[mask]
    cmo[~mask] = 0.0  # No moves → zero momentum

    # VIDYA recursion
    vidya_vals = np.full(n, np.nan)
    # Initialize: first valid CMO bar sets seed
    first_valid = cmo_period  # where rolling sum first completes
    if first_valid < n:
        vidya_vals[first_valid - 1] = close[first_valid - 1]

    sc = 2.0 / (vidya_period + 1.0)
    for i in range(max(first_valid, 1), n):
        if np.isnan(cmo[i]):
            vidya_vals[i] = vidya_vals[i - 1]
        else:
            alpha = sc * abs(cmo[i])
            alpha = min(alpha, 1.0)  # clamp for numerical safety
            vidya_vals[i] = alpha * close[i] + (1.0 - alpha) * vidya_vals[i - 1]

    return pd.Series(vidya_vals, index=series.index)



def ichimoku(
    df: pd.DataFrame,
    tenkan_period: int = 9,
    kijun_period: int = 26,
    senkou_b_period: int = 52,
    displacement: int = 26,
) -> pd.DataFrame:
    """Ichimoku Kinko Hyo (Ichimoku Cloud) indicator.

    Computes the five Ichimoku lines.

    Args:
        df: OHLCV DataFrame with columns [high, low, close]
        tenkan_period: Tenkan-sen (conversion line) period (default 9)
        kijun_period: Kijun-sen (base line) period (default 26)
        senkou_b_period: Senkou Span B period (default 52)
        displacement: Cloud displacement in bars (default 26)

    Returns:
        pd.DataFrame with columns:
            [tenkan, kijun, senkou_a, senkou_b, chikou]
        All aligned to the input DataFrame index.
    """
    high = df["high"]
    low = df["low"]
    close = df["close"]

    # Tenkan-sen: (highest high + lowest low) / 2 over tenkan_period
    tenkan_high = high.rolling(tenkan_period).max()
    tenkan_low = low.rolling(tenkan_period).min()
    tenkan = (tenkan_high + tenkan_low) / 2.0

    # Kijun-sen: (highest high + lowest low) / 2 over kijun_period
    kijun_high = high.rolling(kijun_period).max()
    kijun_low = low.rolling(kijun_period).min()
    kijun = (kijun_high + kijun_low) / 2.0

    # Senkou Span A: (Tenkan + Kijun) / 2, plotted displacement bars forward
    senkou_a_raw = (tenkan + kijun) / 2.0
    senkou_a = senkou_a_raw.shift(displacement)

    # Senkou Span B: (highest high + lowest low) / 2 over senkou_b_period,
    # plotted displacement bars forward
    senkou_b_high = high.rolling(senkou_b_period).max()
    senkou_b_low = low.rolling(senkou_b_period).min()
    senkou_b_raw = (senkou_b_high + senkou_b_low) / 2.0
    senkou_b = senkou_b_raw.shift(displacement)

    # Chikou Span: close plotted displacement bars backward
    chikou = close.shift(-displacement)

    return pd.DataFrame(
        {
            "tenkan": tenkan,
            "kijun": kijun,
            "senkou_a": senkou_a,
            "senkou_b": senkou_b,
            "chikou": chikou,
        },
        index=df.index,
    )



def supertrend(
    df: pd.DataFrame,
    atr_period: int = 10,
    multiplier: float = 3.0,
) -> pd.Series:
    """SuperTrend indicator — acceleration-based trailing stop using ATR.

    Computes a trailing stop line that flips sides when price closes
    through it.  In an uptrend, the SuperTrend line is below price
    (final_lower_band).  In a downtrend, it is above price
    (final_upper_band).

    Args:
        df: OHLCV DataFrame with columns [high, low, close].
        atr_period: Period for the ATR calculation.
        multiplier: ATR multiplier controlling band distance.

    Returns:
        pd.Series of SuperTrend values (trailing stop level),
        same index as df.
    """
    high = df["high"]
    low = df["low"]
    close = df["close"]

    from cryptoquant.strategy.indicators.volatility import atr

    atr_val = atr(df, period=atr_period)
    hl2 = (high + low) / 2.0

    upper_band = hl2 + multiplier * atr_val
    lower_band = hl2 - multiplier * atr_val

    n = len(df)
    final_upper = np.full(n, np.nan)
    final_lower = np.full(n, np.nan)
    st = np.full(n, np.nan)
    uptrend = np.full(n, True)  # direction: True=uptrend, False=downtrend

    # Seed first bar
    for i in range(n):
        if pd.isna(atr_val.iloc[i]):
            continue
        # Initialize first valid bar
        if i == 0 or pd.isna(st[i - 1]):
            final_upper[i] = upper_band.iloc[i]
            final_lower[i] = lower_band.iloc[i]
            if close.iloc[i] > upper_band.iloc[i]:
                uptrend[i] = True
                st[i] = final_lower[i]
            elif close.iloc[i] < lower_band.iloc[i]:
                uptrend[i] = False
                st[i] = final_upper[i]
            else:
                uptrend[i] = True
                st[i] = final_lower[i]
            continue

        # Trailing: final bands never decrease (upper) / increase (lower)
        # within their respective trends
        prev_upper = final_upper[i - 1]
        prev_lower = final_lower[i - 1]

        if close.iloc[i - 1] > prev_upper:
            # Previous close was above final_upper → still in uptrend
            uptrend[i] = True
        elif close.iloc[i - 1] < prev_lower:
            # Previous close was below final_lower → still in downtrend
            uptrend[i] = False
        else:
            # No flip signal: maintain previous trend
            uptrend[i] = uptrend[i - 1]

        if uptrend[i]:
            # In uptrend: lower band trails up, upper band resets
            final_lower[i] = max(lower_band.iloc[i], prev_lower) if not pd.isna(prev_lower) else lower_band.iloc[i]
            final_upper[i] = upper_band.iloc[i]
            st[i] = final_lower[i]
        else:
            # In downtrend: upper band trails down, lower band resets
            final_upper[i] = min(upper_band.iloc[i], prev_upper) if not pd.isna(prev_upper) else upper_band.iloc[i]
            final_lower[i] = lower_band.iloc[i]
            st[i] = final_upper[i]

    return pd.Series(st, index=df.index)



def psar(
    df: pd.DataFrame,
    af_start: float = 0.02,
    af_step: float = 0.02,
    af_max: float = 0.20,
) -> pd.Series:
    """Parabolic SAR (Stop and Reverse).

    Computes the PSAR indicator which acts as a trailing stop that
    accelerates as the trend develops.

    Args:
        df: OHLCV DataFrame with columns [high, low]
        af_start: Initial acceleration factor (default 0.02)
        af_step: Acceleration factor increment per new extreme (default 0.02)
        af_max: Maximum acceleration factor (default 0.20)

    Returns:
        pd.Series of PSAR values, same index as df.
    """
    high = df["high"].values
    low = df["low"].values
    n = len(df)

    psar_vals = np.full(n, np.nan)
    # Initialization: use the first bar's high/low to determine trend
    # Assume downtrend initially if first close is below open, else uptrend
    if n < 2:
        return pd.Series(psar_vals, index=df.index)

    # Determine initial trend from first two bars
    close = df["close"].values
    if close[1] > close[0]:
        # Uptrend start
        psar_vals[1] = low[0]
        ep = high[1]  # extreme point
        af = af_start
        uptrend = True
    else:
        # Downtrend start
        psar_vals[1] = high[0]
        ep = low[1]
        af = af_start
        uptrend = False

    for i in range(2, n):
        prev_psar = psar_vals[i - 1]

        if uptrend:
            # Compute SAR for next bar
            psar_vals[i] = prev_psar + af * (ep - prev_psar)
            # SAR must be below the low of prior two bars
            psar_vals[i] = min(psar_vals[i], low[i - 1])
            if i >= 2:
                psar_vals[i] = min(psar_vals[i], low[i - 2])

            # Check for reversal: price goes below SAR
            if low[i] < psar_vals[i]:
                # Reverse to downtrend
                uptrend = False
                psar_vals[i] = ep  # SAR becomes the prior extreme
                ep = low[i]
                af = af_start
            else:
                # Continue uptrend: update extreme point and AF
                if high[i] > ep:
                    ep = high[i]
                    af = min(af + af_step, af_max)
        else:
            # Downtrend
            psar_vals[i] = prev_psar - af * (prev_psar - ep)
            # SAR must be above the high of prior two bars
            psar_vals[i] = max(psar_vals[i], high[i - 1])
            if i >= 2:
                psar_vals[i] = max(psar_vals[i], high[i - 2])

            # Check for reversal: price goes above SAR
            if high[i] > psar_vals[i]:
                # Reverse to uptrend
                uptrend = True
                psar_vals[i] = ep
                ep = high[i]
                af = af_start
            else:
                # Continue downtrend: update extreme point and AF
                if low[i] < ep:
                    ep = low[i]
                    af = min(af + af_step, af_max)

    return pd.Series(psar_vals, index=df.index)



def decycler(series: pd.Series, cutoff_period: int) -> pd.Series:
    """Ehlers Decycler — 2-pole Butterworth low-pass filter.

    Extracts the trend component from price by removing cycles
    shorter than cutoff_period using a zero-phase-lag Butterworth
    filter. The result has near-zero lag compared to MA-based
    smoothing because it's a frequency-domain filter, not a
    time-domain averager.

    Computation (Ehlers, 2004):
      1. Design 2-pole Butterworth low-pass filter at cutoff_period.
      2. Apply filter to price -> Decycler = trend component.
      3. The filter has zero phase lag at DC by design.

    Args:
        series: Price series (typically close).
        cutoff_period: Cutoff period in bars. Cycles shorter than
            this are attenuated; longer cycles (trend) pass through.

    Returns:
        pd.Series of Decycler values, same index as input.
    """
    if cutoff_period < 2:
        raise ValueError(
            f"Decycler cutoff_period must be >= 2, got {cutoff_period}"
        )

    close = series.values.astype(float)
    n = len(close)

    # 2-pole Butterworth low-pass filter via bilinear transform.
    # Transfer function in s-domain: H(s) = 1 / (s² + √2·s + 1)
    # Bilinear transform s = 2/T * (1-z⁻¹)/(1+z⁻¹) with T = 1:
    #   H(z) = (b0 + b1·z⁻¹ + b2·z⁻²) / (1 + a1·z⁻¹ + a2·z⁻²)
    # where c = 1/tan(π/cutoff_period) and d = 1 + √2·c + c²
    omega = np.pi / cutoff_period
    c = 1.0 / np.tan(omega)
    c2 = c * c
    SQRT2 = np.sqrt(2.0)
    d = 1.0 + SQRT2 * c + c2

    # Feed-forward coefficients (numerator)
    b0 = 1.0 / d
    b1 = 2.0 / d
    b2 = 1.0 / d

    # Feedback coefficients (denominator, sign convention: + in denominator)
    # y[n] = b0*x[n] + b1*x[n-1] + b2*x[n-2] - a1*y[n-1] - a2*y[n-2]
    a1 = 2.0 * (1.0 - c2) / d
    a2 = (1.0 - SQRT2 * c + c2) / d

    decycler_vals = np.full(n, np.nan)

    # Initialize filter state with the first two input values
    # (standard practice for low-pass Butterworth filters)
    if n >= 2:
        decycler_vals[0] = close[0]
        decycler_vals[1] = close[1]

    for i in range(2, n):
        decycler_vals[i] = (
            b0 * close[i]
            + b1 * close[i - 1]
            + b2 * close[i - 2]
            - a1 * decycler_vals[i - 1]
            - a2 * decycler_vals[i - 2]
        )

    return pd.Series(decycler_vals, index=series.index)



def vhf(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Vertical Horizontal Filter — trendiness indicator (0 to 1).

    VHF measures whether the market is trending directionally (high VHF)
    or choppy/mean-reverting (low VHF).  It is the ratio of net directional
    movement to total path length.

    Formula:
        VHF = |close - close.shift(period-1)| / sum(|close - close.shift(1)|, period)

    A VHF near 1.0 means price moved in a straight line (strong trend).
    A VHF near 0.0 means price oscillated but went nowhere (chop).

    Reference: Adam White — \"The Vertical Horizontal Filter\" (TASC, 1991).

    Args:
        df: OHLCV DataFrame with 'close' column.
        period: Lookback for trendiness measurement (default 20).

    Returns:
        pd.Series of VHF values in [0, 1], same index as df.
    """
    close = df["close"]
    # Net directional change over period (bars 0 to period-1 inclusive)
    net_change = (close - close.shift(period - 1)).abs()
    # Total path length: sum of absolute 1-bar changes
    total_path = close.diff().abs().rolling(period).sum()
    # VHF = net directional / total path
    vhf_vals = net_change / total_path.replace(0.0, np.nan)
    return vhf_vals.clip(0.0, 1.0)



def choppiness_index(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Choppiness Index — measures market trending vs. ranging.

    CI = 100 * log10( sum(ATR(1), n) / (HH(n) - LL(n)) ) / log10(n)

    Values: CI < 38.2 → trending, CI > 61.8 → choppy/ranging.

    Reference: E.W. Dreiss — "The Choppiness Index" (S&C, 1993).

    Args:
        df: OHLCV DataFrame with 'high', 'low', 'close' columns.
        period: Lookback for ATR sum and HH/LL range (default 14).

    Returns:
        pd.Series of Choppiness Index values (0-100), same index.
    """
    high = df["high"]
    low = df["low"]
    close = df["close"]

    prev_close = close.shift(1)
    tr = pd.concat([
        high - low,
        (high - prev_close).abs(),
        (low - prev_close).abs(),
    ], axis=1).max(axis=1)

    sum_tr_n = tr.rolling(period).sum()
    hh_n = high.rolling(period).max()
    ll_n = low.rolling(period).min()
    range_n = hh_n - ll_n

    # Avoid division by zero
    ratio = sum_tr_n / range_n.replace(0, np.nan)

    ci = 100.0 * np.log10(ratio) / np.log10(period)
    return ci



def efficiency_ratio(series: pd.Series, period: int = 20) -> pd.Series:
    """Kaufman Efficiency Ratio — directional noise vs trend measurement.

    ER = |Δprice| / sum(|Δprice_i|) over `period` bars.

    Values range [0, 1]:
        0 = pure noise (price returns to start after N bars)
        1 = pure trend (straight line over N bars, zero path overhead)

    Unlike KAMA (which uses ER internally as a smoothing coefficient),
    this returns ER directly as a standalone metric of trend quality.

    Reference: Perry Kaufman — \"Trading Systems and Methods\" (1998).

    Args:
        series: Price series (typically close).
        period: Lookback for ER measurement (default 20).

    Returns:
        pd.Series of ER values in [0, 1], same index as input.
    """
    direction = (series - series.shift(period)).abs()
    volatility = series.diff().abs().rolling(period).sum()
    er = direction / volatility.replace(0, np.nan)
    return er.clip(0.0, 1.0)



def vortex(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Vortex Indicator — measures trend direction and strength.

    VI+ = sum(|High - Previous Low|) / sum(True Range) over `period` bars
    VI- = sum(|Low - Previous High|) / sum(True Range) over `period` bars

    A bullish trend is signaled when VI+ > VI- (positive vortex crosses
    above negative vortex).

    Reference: Etzkorn (2010), "The Vortex Indicator".

    Args:
        df: OHLCV DataFrame with columns [high, low, close].
        period: Lookback period for summing vortex movement (default 14).

    Returns:
        pd.DataFrame with columns [vip, vim], same index as input.
    """
    high, low, close = df["high"], df["low"], df["close"]
    prev_high = high.shift(1)
    prev_low = low.shift(1)
    prev_close = close.shift(1)

    # True Range
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    # Vortex movement
    vm_plus = (high - prev_low).abs()
    vm_minus = (low - prev_high).abs()

    # Sum over period
    tr_sum = tr.rolling(period).sum()
    vip = vm_plus.rolling(period).sum() / tr_sum
    vim = vm_minus.rolling(period).sum() / tr_sum

    return pd.DataFrame({"vip": vip, "vim": vim}, index=df.index)



def linreg(
    series: pd.Series, period: int = 30
) -> pd.DataFrame:
    """Rolling linear regression — slope and R² over a moving window.

    Computes ordinary least-squares regression of `series` against
    bar index (x = 0, 1, 2, ..., period-1) over each rolling window.

    Uses bar index as the independent variable (x = range(period))
    and the series values as the dependent variable (y).

    Args:
        series: Price or indicator series.
        period: Rolling window length (default 30).

    Returns:
        pd.DataFrame with columns [slope, r2], same index as input.
    """
    x = np.arange(period, dtype=float)
    x_mean = x.mean()
    x_diff = x - x_mean
    ssx = float((x_diff * x_diff).sum())

    n = len(series)
    slope_arr = np.full(n, np.nan)
    r2_arr = np.full(n, np.nan)

    if n < period:
        return pd.DataFrame({"slope": slope_arr, "r2": r2_arr}, index=series.index)

    values = series.values

    for i in range(period - 1, n):
        y = values[i - period + 1 : i + 1].astype(float)
        y_mean = y.mean()
        y_diff = y - y_mean
        sxy = float((x_diff * y_diff).sum())
        ssy = float((y_diff * y_diff).sum())

        slope_val = sxy / ssx if ssx != 0 else 0.0
        slope_arr[i] = slope_val

        if ssy == 0.0:
            r2_arr[i] = 0.0
        else:
            y_pred = y_mean + slope_val * x_diff
            ss_res = float(((y - y_pred) ** 2).sum())
            r2_arr[i] = 1.0 - ss_res / ssy

    return pd.DataFrame(
        {"slope": slope_arr, "r2": r2_arr}, index=series.index
    )
