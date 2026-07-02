"""Momentum indicators."""
# pyright: reportAttributeAccessIssue=false, reportReturnType=false, reportArgumentType=false

import numpy as np
import pandas as pd
from cryptoquant.strategy.indicators.trend import sma, ema
from cryptoquant.strategy.indicators.utilities import _closing_streak, _percent_rank
from cryptoquant.strategy.indicators.cycle import hilbert_transform

__all__ = [
    "rsi",
    "roc",
    "macd",
    "stochastic",
    "adx",
    "aroon",
    "cmo",
    "cci",
    "tsi",
    "connors_rsi",
    "williams_r",
    "ultimate_oscillator",
    "fisher_transform",
    "kst",
    "trix",
    "stc",
    "rmi",
    "mama_fama",
    "laguerre_rsi",
]

def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index (0-100)."""
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)

    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))



def roc(series: pd.Series, period: int = 20) -> pd.Series:
    """Rate of Change — raw momentum indicator.

    Computes (close[t] - close[t-N]) / close[t-N] * 100.
    Positive values indicate upward momentum, negative downward.

    Args:
        series: Price series (typically close).
        period: Lookback period (default 20).

    Returns:
        pd.Series of percentage change, same index as input.
    """
    return series.pct_change(periods=period) * 100



def macd(
    series: pd.Series,
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> pd.DataFrame:
    """MACD indicator.

    Returns DataFrame with columns: [macd, signal, histogram]
    """
    ema_fast = series.ewm(span=fast, adjust=False).mean()
    ema_slow = series.ewm(span=slow, adjust=False).mean()
    macd_line = ema_fast - ema_slow
    signal_line = macd_line.ewm(span=signal, adjust=False).mean()
    histogram = macd_line - signal_line

    return pd.DataFrame(
        {"macd": macd_line, "signal": signal_line, "histogram": histogram},
        index=series.index,
    )



def stochastic(
    df: pd.DataFrame, k_period: int = 14, d_period: int = 3
) -> pd.DataFrame:
    """Stochastic oscillator.

    Returns DataFrame with columns: [k, d]
    """
    low_min = df["low"].rolling(k_period).min()
    high_max = df["high"].rolling(k_period).max()

    k = 100 * (df["close"] - low_min) / (high_max - low_min)
    d = k.rolling(d_period).mean()

    return pd.DataFrame({"k": k, "d": d}, index=df.index)



def adx(df: pd.DataFrame, period: int = 14) -> pd.DataFrame:
    """Average Directional Index.

    Returns DataFrame with columns: [adx, pdi, mdi]
    """
    high, low, close = df["high"], df["low"], df["close"]

    # True Range
    prev_close = close.shift(1)
    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    # Directional Movement
    up_move = high.diff()
    down_move = -low.diff()

    plus_dm = pd.Series(0.0, index=df.index)
    minus_dm = pd.Series(0.0, index=df.index)

    mask_plus = (up_move > down_move) & (up_move > 0)
    mask_minus = (down_move > up_move) & (down_move > 0)

    plus_dm[mask_plus] = up_move[mask_plus]
    minus_dm[mask_minus] = down_move[mask_minus]

    # Smooth with RMA
    atr_smooth = tr.ewm(alpha=1 / period, adjust=False).mean()
    plus_di = 100 * plus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr_smooth
    minus_di = 100 * minus_dm.ewm(alpha=1 / period, adjust=False).mean() / atr_smooth

    # ADX
    dx = 100 * (plus_di - minus_di).abs() / (plus_di + minus_di)
    adx_val = dx.ewm(alpha=1 / period, adjust=False).mean()

    return pd.DataFrame(
        {"adx": adx_val, "pdi": plus_di, "mdi": minus_di}, index=df.index
    )



def aroon(df: pd.DataFrame, period: int = 25) -> pd.DataFrame:
    """Aroon indicator.

    Returns DataFrame with columns: [aroon_up, aroon_down]
    """
    aroon_up = df["high"].rolling(period + 1).apply(
        lambda x: (period - (period - x.argmax())) / period * 100, raw=True
    )
    aroon_down = df["low"].rolling(period + 1).apply(
        lambda x: (period - (period - x.argmin())) / period * 100, raw=True
    )

    return pd.DataFrame(
        {"aroon_up": aroon_up, "aroon_down": aroon_down}, index=df.index
    )



def cmo(series: pd.Series, period: int = 20) -> pd.Series:
    """Chande Momentum Oscillator — sum-based improvement over RSI.

    CMO = 100 × (sum_up - sum_down) / (sum_up + sum_down)

    Unlike RSI (which uses Wilder smoothing on average gains/losses),
    CMO uses raw sums over the lookback period, making it faster and
    more responsive to regime changes.  Returns values in [-100, 100].

    Reference: Tushar Chande — "The New Technical Trader" (1994).

    Args:
        series: Price series (typically close).
        period: Lookback period for sum calculation (default 20).

    Returns:
        pd.Series of CMO values, same index as input.
    """
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = (-delta).clip(lower=0)

    sum_up = gain.rolling(period).sum()
    sum_down = loss.rolling(period).sum()

    total = sum_up + sum_down
    cmo_val = 100.0 * (sum_up - sum_down) / total.replace(0, np.nan)
    return cmo_val



def cci(df: pd.DataFrame, period: int = 20, constant: float = 0.015) -> pd.Series:
    """Commodity Channel Index — normalized momentum oscillator.

    CCI = (TP - SMA(TP, N)) / (constant × mean_absolute_deviation(TP, N))

    CCI measures how far price has deviated from its statistical mean in
    units of mean absolute deviation.  Unlike RSI (fixed 0-100 range),
    CCI self-scales, making it naturally adaptive across timeframes and
    volatility regimes.

    Typical thresholds: +100 (overbought), -100 (oversold).
    ~70-80% of values fall within ±100.

    Reference: Donald Lambert (1980).

    Args:
        df: OHLCV DataFrame with columns [high, low, close].
        period: Lookback period for SMA and MAD (default 20).
        constant: Scaling constant (default 0.015, Lambert's standard).

    Returns:
        pd.Series of CCI values, same index as df.
    """
    high, low, close = df["high"], df["low"], df["close"]
    tp = (high + low + close) / 3.0
    tp_sma = tp.rolling(period).mean()
    mad = tp.rolling(period).apply(lambda x: np.mean(np.abs(x - x.mean())), raw=True)
    denom = constant * mad
    cci_val = (tp - tp_sma) / denom.replace(0, np.nan)
    return cci_val



def tsi(
    close: pd.Series,
    short_period: int = 13,
    long_period: int = 25,
    signal_period: int = 7,
) -> pd.DataFrame:
    """True Strength Index — double-EMA-smoothed momentum oscillator.

    TSI = 100 * EMA(EMA(Δp, short), long) / EMA(EMA(|Δp|, short), long)

    The double smoothing on both numerator and denominator produces
    cleaner zero-crosses than single-smoothed oscillators (RSI, CMO,
    Stochastic).

    Reference: William Blau — "The True Strength Index" (S&C, 1991).

    Args:
        close: Close price series.
        short_period: First EMA period for momentum (default 13).
        long_period: Second EMA period for smoothing (default 25).
        signal_period: EMA period for signal line (default 7).

    Returns:
        pd.DataFrame with columns [tsi, signal], same index as close.
    """
    delta = close.diff()
    abs_delta = delta.abs()

    # Double-smoothed momentum (numerator)
    ema_momentum = ema(ema(delta, short_period), long_period)

    # Double-smoothed absolute momentum (denominator)
    ema_abs = ema(ema(abs_delta, short_period), long_period)

    tsi_val = 100.0 * ema_momentum / ema_abs.replace(0, np.nan)
    signal_line = ema(tsi_val, signal_period)

    return pd.DataFrame(
        {"tsi": tsi_val, "signal": signal_line}, index=close.index
    )



def connors_rsi(
    df: pd.DataFrame,
    rsi_period: int = 3,
    streak_rsi_period: int = 2,
    percent_rank_period: int = 100,
) -> pd.Series:
    """Connors RSI (CRSI) composite oscillator.

    CRSI = [RSI(3) + RSI(Streak, 2) + PercentRank(ROC, 100)] / 3

    Combines three momentum dimensions into a single 0-100 signal:
      1. RSI(3): Ultra-short Wilder RSI — immediate overbought/oversold
      2. RSI(Streak, 2): RSI on consecutive close streak — trend persistence
      3. PercentRank(ROC, 100): Where current 1-bar return ranks in last 100 bars

    Reference: Larry Connors — "Connors RSI" (2010).

    Args:
        df: OHLCV DataFrame with 'close' column.
        rsi_period: Wilder RSI period on close (default 3).
        streak_rsi_period: RSI period on closing streak (default 2).
        percent_rank_period: Lookback for percent rank of 1-bar ROC (default 100).

    Returns:
        pd.Series of Connors RSI values (0-100), same index as df.
    """
    close = df["close"]

    # 1. RSI(3) on close
    rsi_close = rsi(close, period=rsi_period)

    # 2. RSI on closing streak
    streak = _closing_streak(close)
    rsi_streak = rsi(streak, period=streak_rsi_period)

    # 3. PercentRank of 1-bar ROC (0-1) converted to 0-100
    roc = close.pct_change()
    pct_rank = _percent_rank(roc, period=percent_rank_period) * 100.0

    crsi = (rsi_close + rsi_streak + pct_rank) / 3.0
    return crsi



def williams_r(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Williams %R — raw normalized momentum oscillator.

    %R = (HighestHigh(period) - Close) / (HighestHigh(period) - LowestLow(period)) * -100

    Unlike Stochastic (which uses %K/%D smoothing), Williams %R is a raw,
    unsmoothed reading of where close sits within the price range. Values
    range [-100, 0]: -100 means close at lowest low (oversold), 0 means
    close at highest high (overbought).

    Faster than Stochastic in detecting regime changes — no Wilder
    smoothing gate, no %K/%D delay. Midline (-50) cross generates
    ~2-3× more signals than extreme thresholds (-20/-80).

    Reference: Larry Williams — \"How I Made One Million Dollars Last
    Year Trading Commodities\" (1979).

    Args:
        df: OHLCV DataFrame with 'high', 'low', 'close' columns.
        period: Lookback for range detection (default 14).

    Returns:
        pd.Series of Williams %R values in [-100, 0], same index as df.
    """
    highest = df["high"].rolling(period).max()
    lowest = df["low"].rolling(period).min()
    denom = highest - lowest
    # Avoid division by zero (flat bars)
    wr = (highest - df["close"]) / denom.replace(0, np.nan) * -100
    return wr.clip(-100.0, 0.0)



def ultimate_oscillator(
    df: pd.DataFrame,
    short: int = 7,
    medium: int = 14,
    long: int = 28,
) -> pd.Series:
    """Ultimate Oscillator — multi-timeframe momentum composite.

    Combines three timeframes with weighted averaging
    (4× short + 2× medium + 1× long / 7) to reduce false divergences
    present in single-timeframe oscillators like RSI.

    Formula:
        BP = close - min(low, prev_close)
        TR = max(high, prev_close) - min(low, prev_close)
        avg7 = sum(BP,7) / sum(TR,7)
        UO = 100 × (4×avg7 + 2×avg14 + 1×avg28) / 7

    Reference: Larry Williams (1985),
    "The Ultimate Oscillator" (Stocks & Commodities).

    Args:
        df: OHLCV DataFrame with columns [high, low, close].
        short: Short period (default 7, weight 4).
        medium: Medium period (default 14, weight 2).
        long: Long period (default 28, weight 1).

    Returns:
        pd.Series of UO values in [0, 100], same index as df.
    """
    high = df["high"]
    low = df["low"]
    close = df["close"]
    prev_close = close.shift(1).fillna(close)

    # Buying Pressure and True Range
    bp = close - pd.concat([low, prev_close], axis=1).min(axis=1)
    tr = (
        pd.concat([high, prev_close], axis=1).max(axis=1)
        - pd.concat([low, prev_close], axis=1).min(axis=1)
    )

    # Rolling sums for each timeframe
    sum_bp_short = bp.rolling(short).sum()
    sum_tr_short = tr.rolling(short).sum()
    sum_bp_med = bp.rolling(medium).sum()
    sum_tr_med = tr.rolling(medium).sum()
    sum_bp_long = bp.rolling(long).sum()
    sum_tr_long = tr.rolling(long).sum()

    # Averages (with NaN-safe division)
    avg_short = sum_bp_short / sum_tr_short.replace(0, np.nan)
    avg_med = sum_bp_med / sum_tr_med.replace(0, np.nan)
    avg_long = sum_bp_long / sum_tr_long.replace(0, np.nan)

    # Weighted composite: 4×short + 2×med + 1×long / 7
    numerator = 4.0 * avg_short + 2.0 * avg_med + 1.0 * avg_long
    uo = 100.0 * numerator / 7.0

    return uo



def fisher_transform(
    df: pd.DataFrame,
    fisher_period: int = 10,
    signal_period: int = 5,
) -> pd.DataFrame:
    """Fisher Transform — Gaussian distribution of price for sharp turning points.

    Converts any price waveform into a Gaussian normal distribution using
    the inverse hyperbolic tangent transform.  Unlike smoothed oscillators
    (RSI, Stochastic), Fisher produces sharp, high-amplitude peaks at
    price reversals — making entry/exit timing more precise.

    Formula:
        median = (high + low) / 2
        normalized = 2 * (median - min(median,N)) / (max(median,N) - min(median,N)) - 1
        fisher = 0.5 * ln((1 + norm) / (1 - norm))
        signal = EMA(fisher, signal_period)

    Reference: John Ehlers — \"Using the Fisher Transform\"
    (Stocks & Commodities, Nov 2002).

    Args:
        df: OHLCV DataFrame with columns [high, low].
        fisher_period: Lookback for normalization window (default 10).
        signal_period: EMA smoothing period for signal line (default 5).

    Returns:
        pd.DataFrame with columns [fisher, signal], same index as df.
    """
    high = df["high"]
    low = df["low"]
    median = (high + low) / 2.0

    # Normalize to [-1, 1] range
    roll_min = median.rolling(fisher_period).min()
    roll_max = median.rolling(fisher_period).max()
    denom = (roll_max - roll_min).replace(0, np.nan)
    normalized = 2.0 * (median - roll_min) / denom - 1.0

    # Clip to avoid ln(0) / ln(∞)
    normalized = normalized.clip(-0.999, 0.999)

    # Fisher Transform: 0.5 * ln((1+x)/(1-x))
    fisher = 0.5 * np.log((1.0 + normalized) / (1.0 - normalized))

    # Signal line: EMA of fisher value
    signal_line = fisher.ewm(span=signal_period, adjust=False).mean()

    return pd.DataFrame(
        {"fisher": fisher, "signal": signal_line}, index=df.index
    )



def kst(
    close: pd.Series,
    roc1: int = 10, roc2: int = 15, roc3: int = 20, roc4: int = 30,
    ma1: int = 10, ma2: int = 10, ma3: int = 10, ma4: int = 15,
    signal_period: int = 9,
) -> pd.DataFrame:
    """KST (Know Sure Thing) — multi-timeframe momentum oscillator.

    Sums four Rate-of-Change measurements smoothed to their appropriate
    timescales into a single composite oscillator.  Crossovers of KST vs
    its signal line produce entry/exit triggers.

    Formula:
        ROC(n)  = (close - close.shift(n)) / close.shift(n) * 100
        KST     = SMA(ROC(roc1), ma1) + SMA(ROC(roc2), ma2)
                + SMA(ROC(roc3), ma3) + SMA(ROC(roc4), ma4)

    Reference: Martin Pring — "Martin Pring's Introduction to Technical
    Analysis" (1998).

    Args:
        close: Close price series.
        roc1..roc4: ROC periods (default 10, 15, 20, 30).
        ma1..ma4: Smoothing periods for each ROC (default 10, 10, 10, 15).
        signal_period: SMA period for the KST signal line (default 9).

    Returns:
        pd.DataFrame with columns [kst, signal], same index as close.
    """
    def _roc(series: pd.Series, period: int) -> pd.Series:
        return (series - series.shift(period)) / series.shift(period).replace(0, np.nan) * 100

    roc_vals = [
        _roc(close, roc1),
        _roc(close, roc2),
        _roc(close, roc3),
        _roc(close, roc4),
    ]
    kst_vals = (
        sma(roc_vals[0], ma1)
        + sma(roc_vals[1], ma2)
        + sma(roc_vals[2], ma3)
        + sma(roc_vals[3], ma4)
    )
    signal_line = sma(kst_vals, signal_period)

    return pd.DataFrame({"kst": kst_vals, "signal": signal_line}, index=close.index)



def trix(close: pd.Series, period: int = 15, signal_period: int = 9) -> pd.DataFrame:
    """TRIX (Triple Exponential Average) — triple-smoothed rate-of-change oscillator.

    Applies EMA smoothing three times before computing the 1-bar rate of
    change, creating a very smooth oscillator that nonetheless measures
    pure momentum (first derivative).  Extremely noise-resistant while
    preserving signal timeliness.

    Formula:
        EMA1 = EMA(close, period)
        EMA2 = EMA(EMA1, period)
        EMA3 = EMA(EMA2, period)
        TRIX = (EMA3 - EMA3.shift(1)) / EMA3.shift(1) * 100

    Reference: Jack Hutson — "Good Trix" (Stocks & Commodities, 1983).

    Args:
        close: Close price series.
        period: TRIX period (default 15, Hutson standard).
        signal_period: SMA period for TRIX signal line (default 9).

    Returns:
        pd.DataFrame with columns [trix, signal], same index as close.
    """
    ema1 = ema(close, period)
    ema2 = ema(ema1, period)
    ema3 = ema(ema2, period)
    trix_val = (ema3 - ema3.shift(1)) / ema3.shift(1).replace(0, np.nan) * 100
    signal_line = sma(trix_val, signal_period)

    return pd.DataFrame({"trix": trix_val, "signal": signal_line}, index=close.index)



def stc(
    df: pd.DataFrame,
    fast: int = 23,
    slow: int = 50,
    cycle: int = 10,
    d_period: int = 3,
) -> pd.Series:
    """Schaff Trend Cycle — Stochastic of MACD, a double-smoothed 0-100 oscillator.

    STC applies the Stochastic %K formula to the MACD line, producing a faster
    turning signal than MACD alone while retaining trend quality.

    Formula:
        MACD = EMA(close, fast) - EMA(close, slow)
        %K = 100 * (MACD - LLV(MACD, cycle)) / (HHV(MACD, cycle) - LLV(MACD, cycle))
        STC = EMA(%K, d_period)

    Reference: Doug Schaff — "Schaff Trend Cycle" (1999).

    Args:
        df: OHLCV DataFrame with 'close' column.
        fast: Fast EMA period for MACD (default 23).
        slow: Slow EMA period for MACD (default 50).
        cycle: Lookback for %K normalization (default 10).
        d_period: Smoothing period for final STC (default 3).

    Returns:
        pd.Series of STC values in [0, 100], same index as df.
    """
    close = df["close"]
    macd_line = ema(close, fast) - ema(close, slow)

    lowest = macd_line.rolling(cycle).min()
    highest = macd_line.rolling(cycle).max()
    denom = highest - lowest

    stoch_k = 100.0 * (macd_line - lowest) / denom.replace(0, np.nan)
    stc_val = stoch_k.ewm(span=d_period, adjust=False).mean()

    return stc_val



def rmi(
    df: pd.DataFrame,
    momentum_period: int = 5,
    rmi_period: int = 14,
    signal_period: int = 9,
) -> pd.DataFrame:
    """Relative Momentum Index (RMI) with signal line.

    RMI is a variation of RSI that uses momentum (price change over
    N bars) instead of single-bar price changes.  This provides
    additional smoothing and clearer turning points.

    Uses Wilder's EMA (alpha = 1/period) for the smoothing steps,
    matching the original RSI implementation.

    Reference: Roger Altman (1993).

    Args:
        df: OHLCV DataFrame with 'close' column.
        momentum_period: Bars for momentum calculation (default 5).
        rmi_period: Wilder's EMA period for smoothing (default 14).
        signal_period: Signal line EMA period (default 9).

    Returns:
        pd.DataFrame with columns [rmi, signal], same index as df.
    """
    close = df["close"].values.astype(np.float64)
    n = len(close)

    # Momentum: close - close[momentum_period] ago
    mom = np.full(n, np.nan, dtype=np.float64)
    for i in range(momentum_period, n):
        mom[i] = close[i] - close[i - momentum_period]

    # Separate up/down momentum
    up = np.maximum(mom, 0.0)
    down = np.abs(np.minimum(mom, 0.0))

    # Wilder's EMA smoothing (alpha = 1/rmi_period)
    rmi_alpha = 1.0 / rmi_period
    avg_up = np.full(n, np.nan, dtype=np.float64)
    avg_down = np.full(n, np.nan, dtype=np.float64)
    rmi_vals = np.full(n, np.nan, dtype=np.float64)

    first_valid = momentum_period + rmi_period
    if first_valid >= n:
        return pd.DataFrame(
            {"rmi": rmi_vals, "signal": pd.Series(np.nan, index=df.index)},
            index=df.index,
        )

    # Seed with SMA over first rmi_period valid bars
    start = momentum_period
    avg_up[start + rmi_period - 1] = np.mean(up[start : start + rmi_period])
    avg_down[start + rmi_period - 1] = np.mean(
        down[start : start + rmi_period]
    )

    for i in range(start + rmi_period, n):
        avg_up[i] = rmi_alpha * up[i] + (1.0 - rmi_alpha) * avg_up[i - 1]
        avg_down[i] = rmi_alpha * down[i] + (1.0 - rmi_alpha) * avg_down[i - 1]

    # RMI = 100 - 100 / (1 + avg_up / avg_down)
    epsilon = 1e-10
    for i in range(n):
        if np.isnan(avg_up[i]) or np.isnan(avg_down[i]):
            continue
        denom = avg_down[i]
        if denom < epsilon:
            denom = epsilon
        rmi_vals[i] = 100.0 - 100.0 / (1.0 + avg_up[i] / denom)

    rmi_series = pd.Series(rmi_vals, index=df.index)
    signal_series = ema(rmi_series, signal_period)

    return pd.DataFrame(
        {"rmi": rmi_vals, "signal": signal_series.values},
        index=df.index,
    )



def mama_fama(
    df: pd.DataFrame,
    fast_limit: float = 0.5,
    slow_limit: float = 0.05,
    price_col: str = "close",
) -> pd.DataFrame:
    """Compute MAMA and FAMA (MESA Adaptive / Following Moving Averages).

    MAMA adapts its EMA alpha based on the rate of phase change measured
    by the Hilbert Transform — fast attack at cycle turning points, slow
    decay during trend continuation.  FAMA is MAMA applied to MAMA with
    half the alpha.

    Reference: John Ehlers — "MAMA – The Mother of Adaptive Moving
    Averages" (MESA Software).

    Args:
        df: OHLCV DataFrame.
        fast_limit: Maximum alpha (default 0.5).
        slow_limit: Minimum alpha (default 0.05).
        price_col: Column name for price input (default "close").

    Returns:
        pd.DataFrame with columns [mama, fama], same index as df.
        Values before the Hilbert warmup (7 bars) are NaN.
    """
    price = df[price_col].values.astype(np.float64)
    n = len(price)

    # Pre-compute delta_phase from Hilbert Transform
    ht = hilbert_transform(df, price_col=price_col)
    delta_phase = ht["delta_phase"].values

    mama_vals = np.full(n, np.nan, dtype=np.float64)
    fama_vals = np.full(n, np.nan, dtype=np.float64)

    for i in range(n):
        dp = delta_phase[i]
        if np.isnan(dp):
            continue

        # Adaptive alpha: FastLimit / delta_phase, clamped
        alpha = fast_limit / dp
        if alpha < slow_limit:
            alpha = slow_limit
        if alpha > fast_limit:
            alpha = fast_limit

        # Seed the first valid bar
        if i == 0 or np.isnan(mama_vals[i - 1]):
            mama_vals[i] = price[i]
            fama_vals[i] = price[i]
        else:
            mama_vals[i] = alpha * price[i] + (1.0 - alpha) * mama_vals[i - 1]
            fama_vals[i] = (
                0.5 * alpha * mama_vals[i]
                + (1.0 - 0.5 * alpha) * fama_vals[i - 1]
            )

    return pd.DataFrame(
        {"mama": mama_vals, "fama": fama_vals}, index=df.index
    )



def laguerre_rsi(
    series: pd.Series,
    period: int = 14,
    gamma: float = 0.5,
) -> pd.Series:
    """Laguerre RSI — RSI with reduced lag via 4-pole Laguerre filter.

    Standard RSI uses Wilder's smoothing (EMA with alpha=1/period),
    introducing 5-8 bar lag.  Laguerre RSI applies a 4-pole gamma
    filter to the price, then computes RSI on the filtered FIR series.
    This produces earlier signals during trend transitions while
    maintaining smoothness.

    Algorithm (Ehlers, 2002):

      L0_t = (1-γ)·price_t + γ·L0_{t-1}
      L1_t = -γ·L0_t + L0_{t-1} + γ·L1_{t-1}
      L2_t = -γ·L1_t + L1_{t-1} + γ·L2_{t-1}
      L3_t = -γ·L2_t + L2_{t-1} + γ·L3_{t-1}
      FIR_t = (L0_t + 2·L1_t + 2·L2_t + L3_t) / 6

      RSI computed on FIR using EMA smoothing of up/down moves.

    Args:
        series: Price series (typically close).
        period: RSI EMA smoothing period (default 14).
        gamma: Laguerre pole location (0 < γ < 1, default 0.5).

    Returns:
        pd.Series of Laguerre RSI values (0-100), same index as input.
    """
    if not 0 < gamma < 1:
        raise ValueError(f"gamma must be in (0,1), got {gamma}")

    price = series.values.astype(float)
    n = len(price)

    l0 = np.full(n, np.nan)
    l1 = np.full(n, np.nan)
    l2 = np.full(n, np.nan)
    l3 = np.full(n, np.nan)

    # Initialize filters with first close price
    l0[0] = price[0]
    l1[0] = price[0]
    l2[0] = price[0]
    l3[0] = price[0]

    for i in range(1, n):
        l0[i] = (1.0 - gamma) * price[i] + gamma * l0[i - 1]
        l1[i] = -gamma * l0[i] + l0[i - 1] + gamma * l1[i - 1]
        l2[i] = -gamma * l1[i] + l1[i - 1] + gamma * l2[i - 1]
        l3[i] = -gamma * l2[i] + l2[i - 1] + gamma * l3[i - 1]

    fir = (l0 + 2.0 * l1 + 2.0 * l2 + l3) / 6.0

    # Compute RSI on FIR
    d_fir = np.diff(fir, prepend=fir[0])
    cu = np.where(d_fir > 0, d_fir, 0.0)
    cd = np.where(d_fir < 0, -d_fir, 0.0)

    # EMA smoothing via ewm
    cu_series = pd.Series(cu, index=series.index)
    cd_series = pd.Series(cd, index=series.index)

    alpha = 1.0 / period
    cu_ema = cu_series.ewm(alpha=alpha, min_periods=period, adjust=False).mean()
    cd_ema = cd_series.ewm(alpha=alpha, min_periods=period, adjust=False).mean()

    denom = cu_ema + cd_ema
    denom = denom.replace(0, np.nan)
    lrsi = 100.0 * cu_ema / denom

    return lrsi
