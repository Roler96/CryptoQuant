"""Technical indicators library -- pure NumPy/pandas, zero external dependencies."""

import numpy as np
import pandas as pd


# === Trend Indicators ===


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


# === Volatility Indicators ===


def atr(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Average True Range (Wilder's RMA smoothing)."""
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)

    tr = pd.concat(
        [
            high - low,
            (high - prev_close).abs(),
            (low - prev_close).abs(),
        ],
        axis=1,
    ).max(axis=1)

    return tr.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()


def bollinger_bands(
    df: pd.DataFrame, period: int = 20, std: float = 2.0
) -> pd.DataFrame:
    """Bollinger Bands.

    Returns DataFrame with columns: [middle, upper, lower, width, pct_b]
    """
    close = df["close"]
    middle = close.rolling(period).mean()
    std_dev = close.rolling(period).std()

    upper = middle + std * std_dev
    lower = middle - std * std_dev
    width = (upper - lower) / middle
    pct_b = (close - lower) / (upper - lower)

    return pd.DataFrame(
        {
            "middle": middle,
            "upper": upper,
            "lower": lower,
            "width": width,
            "pct_b": pct_b,
        },
        index=df.index,
    )


def historical_volatility(
    series: pd.Series, period: int = 20, annualize: bool = True
) -> pd.Series:
    """Historical volatility (log returns std dev)."""
    log_returns = np.log(series / series.shift(1))
    vol = log_returns.rolling(period).std()
    if annualize:
        vol = vol * np.sqrt(365 * 24)  # hourly data annualization
    return vol


# === Momentum Indicators ===


def rsi(series: pd.Series, period: int = 14) -> pd.Series:
    """Relative Strength Index (0-100)."""
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = (-delta).where(delta < 0, 0.0)

    avg_gain = gain.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1 / period, min_periods=period, adjust=False).mean()

    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))


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


# === Trend Strength Indicators ===


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


# === Volume Indicators ===


def volume_sma(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Volume Simple Moving Average."""
    return df["volume"].rolling(period).mean()


def volume_profile_ratio(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Current volume / average volume over period."""
    avg_vol = df["volume"].rolling(period).mean()
    return df["volume"] / avg_vol


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


# === Utility Functions ===


def crossover(series_a: pd.Series, series_b: pd.Series) -> pd.Series:
    """Detect when series_a crosses ABOVE series_b.

    Returns: 1 at crossover points, 0 elsewhere.
    """
    above = series_a > series_b
    prev_above = above.shift(1).fillna(False).astype(bool)
    cross = above & ~prev_above
    return cross.astype(int)


def crossunder(series_a: pd.Series, series_b: pd.Series) -> pd.Series:
    """Detect when series_a crosses BELOW series_b.

    Returns: -1 at crossunder points, 0 elsewhere.
    """
    below = series_a < series_b
    prev_below = below.shift(1).fillna(False).astype(bool)
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


# === Pattern Recognition ===


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


# === Parabolic SAR ===

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


# === Ichimoku Kinko Hyo ===

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


# === SuperTrend ===


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


# === CMO (Chande Momentum Oscillator) ===


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


# === Adaptive Indicators ===


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


# === Volume-Weighted Momentum ===


def force_index(
    df: pd.DataFrame,
    period: int = 13,
) -> pd.Series:
    """Elder's Force Index — volume-weighted price momentum.

    Raw Force Index = (Close_t - Close_t-1) × Volume_t.
    Smoothed with EMA to filter noise and reveal sustained
    buying/selling pressure.

    Reference: Alexander Elder — "Trading for a Living" (1993).

    Args:
        df: OHLCV DataFrame with columns [close, volume].
        period: EMA smoothing period for the raw Force Index.

    Returns:
        pd.Series of smoothed Force Index values, same index as df.
    """
    close = df["close"]
    volume = df["volume"]
    raw_fi = close.diff() * volume
    smoothed = raw_fi.ewm(span=period, adjust=False).mean()
    return smoothed


# === Money Flow Index (MFI) ===


def mfi(
    df: pd.DataFrame,
    period: int = 14,
) -> pd.Series:
    """Money Flow Index — volume-weighted RSI oscillator (0-100).

    MFI incorporates both price change direction AND volume magnitude
    into a normalized oscillator.  Typical Price = (H+L+C)/3 is multiplied
    by volume to get Money Flow; positive/negative money flows are summed
    over the period to compute the Money Ratio.

    Reference: Gene Quong & Avrum Soudack (1989).

    Args:
        df: OHLCV DataFrame with columns [high, low, close, volume].
        period: Lookback period (default 14).

    Returns:
        pd.Series of MFI values in [0, 100], same index as df.
    """
    high, low, close, volume = df["high"], df["low"], df["close"], df["volume"]

    # Typical Price
    typical_price = (high + low + close) / 3.0

    # Raw Money Flow = Typical Price × Volume
    raw_money_flow = typical_price * volume

    # Money flow direction: positive when TP rises, negative when TP falls
    tp_diff = typical_price.diff()

    positive_flow = raw_money_flow.where(tp_diff > 0, 0.0)
    negative_flow = raw_money_flow.where(tp_diff < 0, 0.0)

    pos_sum = positive_flow.rolling(period).sum()
    neg_sum = negative_flow.rolling(period).sum()

    money_ratio = pos_sum / neg_sum.replace(0, np.nan)
    mfi_val = 100.0 - (100.0 / (1.0 + money_ratio))

    return mfi_val


# === Chaikin Money Flow (CMF) ===


def cmf(
    df: pd.DataFrame,
    period: int = 21,
) -> pd.Series:
    """Chaikin Money Flow — volume-weighted accumulation/distribution indicator.

    CMF measures buying/selling pressure by accumulating the Chaikin A/D
    formula over N periods: CMF = sum(AD_t) / sum(Volume_t) for t in [t-N+1, t].
    AD_t = ((Close-Low) - (High-Close)) / (High-Low) × Volume_t.

    Positive CMF indicates accumulation (net buying pressure);
    negative CMF indicates distribution (net selling pressure).

    Reference: Marc Chaikin (1980s).

    Args:
        df: OHLCV DataFrame with columns [high, low, close, volume].
        period: Lookback period for sum (default 21).

    Returns:
        pd.Series of CMF values roughly in [-1, +1], same index as df.
    """
    high, low, close, volume = df["high"], df["low"], df["close"], df["volume"]

    # Money Flow Multiplier
    bar_range = (high - low).replace(0, np.nan)
    mfm = ((close - low) - (high - close)) / bar_range

    # Money Flow Volume = MFM × Volume
    mfv = mfm * volume

    # CMF = sum(MFV, N) / sum(Volume, N)
    cmf_val = mfv.rolling(period).sum() / volume.rolling(period).sum()

    return cmf_val


# === CCI (Commodity Channel Index) ===


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


# === Heikin-Ashi Candles ===


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


# === Volume-Weighted Average Price (VWAP) ===


def vwap(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Anchored VWAP — volume-weighted average price over a rolling window.

    VWAP = cumulative(P*V) / cumulative(V) over `period` bars.

    Args:
        df: OHLCV DataFrame with columns [high, low, close, volume].
        period: Rolling window for VWAP calculation.

    Returns:
        pd.Series of VWAP values, same index as input.
    """
    typical_price = (df["high"] + df["low"] + df["close"]) / 3.0
    pv = typical_price * df["volume"]
    vwap_val = pv.rolling(period).sum() / df["volume"].rolling(period).sum()
    return vwap_val


# === Vortex Indicator ===


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


# === Linear Regression ===


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


# === Hull Moving Average (HMA) ===


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


# === Ultimate Oscillator ===


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


# === Fisher Transform ===


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


# === Kaufman Efficiency Ratio ===


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
