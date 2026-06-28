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


# === KST (Know Sure Thing) ===


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


# === TRIX (Triple Exponential Average) ===


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


# === Williams %R ===


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


# === Keltner Channel ===


def keltner_channel(
    df: pd.DataFrame,
    ema_period: int = 20,
    atr_period: int = 10,
    atr_multiplier: float = 2.0,
) -> pd.DataFrame:
    """Keltner Channel with normalized position (%K).

    Middle band = EMA(close, ema_period).
    Width = ATR(atr_period) × atr_multiplier.
    Upper/Lower = middle ± width.
    %K = (close - lower) / (upper - lower) — normalized 0-1 position.

    Args:
        df: OHLCV DataFrame with 'open', 'high', 'low', 'close', 'volume'.
        ema_period: EMA period for the middle band (default 20).
        atr_period: ATR period for the channel width (default 10).
        atr_multiplier: Multiplier applied to ATR for channel width (default 2.0).

    Returns:
        pd.DataFrame with columns [middle, upper, lower, width, pct_k], same index as df.
    """
    close = df["close"]
    middle = ema(close, ema_period)
    width = atr(df, period=atr_period) * atr_multiplier
    upper = middle + width
    lower = middle - width
    denom = upper - lower
    pct_k = (close - lower) / denom.replace(0, np.nan)

    return pd.DataFrame(
        {"middle": middle, "upper": upper, "lower": lower, "width": width, "pct_k": pct_k},
        index=df.index,
    )


# === Connors RSI Components ===


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


# === True Strength Index (TSI) ===


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


# === Bollinger Band Squeeze ===


def bb_squeeze(
    df: pd.DataFrame,
    bb_period: int = 20,
    bb_std: float = 2.0,
    squeeze_lookback: int = 125,
) -> pd.Series:
    """Bollinger Band Squeeze — low-volatility consolidation detection.

    Returns True when BB width (normalized) reaches a multi-period
    minimum, signalling a low-volatility consolidation that often
    precedes a breakout.

    Args:
        df: OHLCV DataFrame with 'close' column.
        bb_period: BB moving average period (default 20).
        bb_std: BB standard deviation multiplier (default 2.0).
        squeeze_lookback: Bars for minimum BB width detection (default 125).

    Returns:
        pd.Series of boolean values, same index as df.
    """
    close = df["close"]
    middle = close.rolling(bb_period).mean()
    std_dev = close.rolling(bb_period).std()
    upper = middle + bb_std * std_dev
    lower = middle - bb_std * std_dev

    # Normalized BB width
    bb_width = (upper - lower) / middle

    # Rolling minimum of BB width (shift by 1 to avoid look-ahead)
    rolling_min_width = bb_width.rolling(squeeze_lookback).min().shift(1)

    # Squeeze: current width == the minimum seen in the lookback
    is_squeeze = bb_width <= rolling_min_width

    return is_squeeze


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


# === TTM Squeeze ===


def ttm_squeeze(
    df: pd.DataFrame,
    bb_period: int = 20,
    bb_std: float = 2.0,
    kc_period: int = 20,
    kc_multiplier: float = 1.5,
) -> pd.DataFrame:
    """TTM Squeeze — volatility compression/expansion detection.

    Compares Bollinger Band width to Keltner Channel width.
    When BB width < KC width, the market is "squeezed" (compressing).
    When BB width expands back above KC width, the squeeze "fires"
    (volatility expansion), signalling a breakout.

    Based on John Carter's TTM Squeeze indicator.

    Args:
        df: OHLCV DataFrame with 'high', 'low', 'close' columns.
        bb_period: BB moving average period (default 20).
        bb_std: BB standard deviation multiplier (default 2.0).
        kc_period: KC EMA period (default 20).
        kc_multiplier: KC ATR multiplier (default 1.5).

    Returns:
        pd.DataFrame with columns:
            [bb_width, kc_width, is_squeezed, squeeze_fire]
        All aligned to the input DataFrame index.
    """
    import numpy as np

    close = df["close"]
    high = df["high"]
    low = df["low"]

    # Bollinger Band width (normalized: (upper-lower)/middle)
    bb_middle = close.rolling(bb_period).mean()
    bb_std_val = close.rolling(bb_period).std()
    bb_upper = bb_middle + bb_std * bb_std_val
    bb_lower = bb_middle - bb_std * bb_std_val
    bb_width = (bb_upper - bb_lower) / bb_middle

    # Keltner Channel width: ATR(period) * multiplier
    # Use ATR-like: TR then EMA(TR, kc_period)
    prev_close = close.shift(1)
    tr = pd.concat(
        [high - low, (high - prev_close).abs(), (low - prev_close).abs()],
        axis=1,
    ).max(axis=1)
    atr_kc = tr.ewm(alpha=1 / kc_period, min_periods=kc_period, adjust=False).mean()
    kc_width = atr_kc * kc_multiplier

    # Squeeze: BB width < KC width (Bollinger is inside Keltner = compression)
    is_squeezed = bb_width < kc_width

    # Squeeze fire: squeeze was on last bar and is now off (BB expands above KC)
    was_squeezed = is_squeezed.shift(1).fillna(False).astype(bool)
    squeeze_fire = was_squeezed & ~is_squeezed

    return pd.DataFrame(
        {
            "bb_width": bb_width,
            "kc_width": kc_width,
            "is_squeezed": is_squeezed,
            "squeeze_fire": squeeze_fire,
        },
        index=df.index,
    )


# === On-Balance Volume (OBV) ===


def obv(df: pd.DataFrame) -> pd.Series:
    """On-Balance Volume — cumulative volume-flow indicator.

    OBV adds volume on up-days and subtracts volume on down-days,
    measuring whether volume is flowing into or out of the asset.

    Reference: Joseph Granville — "Granville's New Key to Stock
    Market Profits" (1963).

    Args:
        df: OHLCV DataFrame with 'close' and 'volume' columns.

    Returns:
        pd.Series of cumulative OBV values, same index as df.
    """
    close = df["close"]
    volume = df["volume"]

    direction = pd.Series(np.sign(close.diff()), index=df.index).fillna(0)
    raw_obv = (direction * volume)
    return raw_obv.cumsum()


def obv_sma(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    """On-Balance Volume with signal SMA for crossover detection.

    Args:
        df: OHLCV DataFrame with 'close' and 'volume' columns.
        period: SMA period on OBV (default 20).

    Returns:
        pd.DataFrame with columns [obv, signal], same index as df.
    """
    obv_val = obv(df)
    signal_line = sma(obv_val, period)
    return pd.DataFrame(
        {"obv": obv_val, "signal": signal_line}, index=df.index
    )


# === Accumulation/Distribution Line (A/D Line) ===


def ad_line(df: pd.DataFrame) -> pd.Series:
    """Accumulation/Distribution Line — cumulative volume-flow indicator.

    Unlike OBV which only uses sign(Δclose), A/D Line weights each bar by
    close position within the bar range (Money Flow Multiplier).  Close
    near high → full volume added; close near low → full volume subtracted;
    close at midpoint → zero contribution.

    Money Flow Multiplier = ((Close - Low) - (High - Close)) / (High - Low)
    Money Flow Volume = MFM × Volume_t
    A/D Line = cumulative sum of MFV

    Reference: Marc Chaikin — \"Technical Analysis from A to Z\" (1995).

    Args:
        df: OHLCV DataFrame with 'high', 'low', 'close', 'volume' columns.

    Returns:
        pd.Series of cumulative A/D Line values, same index as df.
    """
    high = df["high"]
    low = df["low"]
    close = df["close"]
    volume = df["volume"]

    bar_range = (high - low).replace(0, np.nan)
    mfm = ((close - low) - (high - close)) / bar_range
    mfv = mfm * volume
    return mfv.fillna(0).cumsum()


def ad_line_sma(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    """Accumulation/Distribution Line with signal SMA for crossover detection.

    Args:
        df: OHLCV DataFrame with 'high', 'low', 'close', 'volume' columns.
        period: SMA period on A/D Line (default 20).

    Returns:
        pd.DataFrame with columns [ad_line, signal], same index as df.
    """
    ad = ad_line(df)
    signal_line = sma(ad, period)
    return pd.DataFrame(
        {"ad_line": ad, "signal": signal_line}, index=df.index
    )


# === Ease of Movement (EMV) ===


def ease_of_movement(df: pd.DataFrame, smooth: int = 5) -> pd.Series:
    """Ease of Movement — volume-normalized price movement indicator.

    Measures how much price moved relative to the volume required to
    move it. High EMV → price moves easily (low friction / strong trend).
    Low EMV → price struggles (high friction / chop / distribution).

    Distance Moved = (High+Low)/2 - (Prev_High+Prev_Low)/2
    Box Ratio = Volume / (High - Low)
    EMV = Distance Moved / Box Ratio (smoothed with EMA)

    Reference: Richard Arms — \"Volume Cycles in the Stock Market\" (1994).

    Args:
        df: OHLCV DataFrame with 'high', 'low', 'volume' columns.
        smooth: EMA smoothing period for raw EMV (default 5).

    Returns:
        pd.Series of smoothed EMV values, same index as df.
    """
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    midpoint = (high + low) / 2.0
    distance_moved = midpoint.diff()

    bar_range = (high - low).replace(0, np.nan)
    box_ratio = volume / bar_range

    raw_emv = distance_moved / box_ratio.replace(0, np.nan)
    smoothed = raw_emv.ewm(span=smooth, adjust=False).mean()

    return smoothed


def emv_sma(df: pd.DataFrame, emv_smooth: int = 5, sma_period: int = 20) -> pd.DataFrame:
    """Ease of Movement with signal line for zero-cross / crossover detection.

    Args:
        df: OHLCV DataFrame with 'high', 'low', 'volume' columns.
        emv_smooth: EMA smoothing period for raw EMV (default 5).
        sma_period: SMA period on EMV for signal line (default 20).

    Returns:
        pd.DataFrame with columns [emv, signal], same index as df.
        Signal line is EMA of EMV for smoother crossover detection.
    """
    emv_val = ease_of_movement(df, smooth=emv_smooth)
    signal_line = sma(emv_val, sma_period)
    return pd.DataFrame(
        {"emv": emv_val, "signal": signal_line}, index=df.index
    )


# === Donchian Channel ===


def donchian(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    """Donchian Channel — N-period highest high / lowest low.

    Args:
        df: OHLCV DataFrame with 'high' and 'low' columns.
        period: Lookback period for highs/lows (default 20).

    Returns:
        pd.DataFrame with columns [upper, lower, middle], same index.
        Values are shifted by 1 bar to avoid look-ahead bias.
    """
    high = df["high"]
    low = df["low"]

    upper = high.rolling(period).max().shift(1)
    lower = low.rolling(period).min().shift(1)
    middle = (upper + lower) / 2.0

    return pd.DataFrame(
        {"upper": upper, "lower": lower, "middle": middle}, index=df.index
    )


# === Choppiness Index ===


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


# === Schaff Trend Cycle (STC) ===


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


# === Twiggs Money Flow (TMF) ===


def twiggs_money_flow(
    df: pd.DataFrame,
    period: int = 21,
) -> pd.Series:
    """Twiggs Money Flow — volume-weighted money flow with True Range normalization.

    TMF improves on Chaikin Money Flow (CMF) by using True Range instead of
    High-Low range for the denominator and Wilder EMA smoothing instead of
    a simple sum. The True Range denominator handles gap-driven bars and
    wick-heavy candles better than High-Low range.

    Formula:
        TR = max(H-L, |H-prevC|, |L-prevC|)
        dm = close - open
        raw = volume * (2*dm - TR) / TR
        TMF = 100 * EMA(raw, period) / EMA(volume, period)

    Reference: Colin Twiggs — "Twiggs Money Flow" (Incredible Charts).

    Args:
        df: OHLCV DataFrame with columns [open, high, low, close, volume].
        period: Wilder EMA smoothing period (default 21).

    Returns:
        pd.Series of TMF values, same index as df. Positive = accumulation,
        negative = distribution.
    """
    high = df["high"]
    low = df["low"]
    close = df["close"]
    volume = df["volume"]
    open_ = df["open"]

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

    dm = close - open_
    raw_mf = volume * (2.0 * dm - tr) / tr.replace(0, np.nan)

    # Wilder EMA smoothing (alpha = 1/period)
    ema_raw = raw_mf.ewm(alpha=1.0 / period, adjust=False).mean()
    ema_vol = volume.ewm(alpha=1.0 / period, adjust=False).mean()

    tmf = 100.0 * ema_raw / ema_vol.replace(0, np.nan)
    return tmf


# === Vertical Horizontal Filter (VHF) ===


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


# === Chaikin Oscillator ===


def chaikin_oscillator(
    df: pd.DataFrame, fast: int = 3, slow: int = 10
) -> pd.Series:
    """Chaikin Oscillator — momentum of the Accumulation/Distribution Line.

    Chaikin Oscillator = EMA(fast, A/D Line) − EMA(slow, A/D Line).

    Measures the rate of change of accumulation/distribution pressure.
    Positive oscillator → buying pressure accelerating; negative →
    distribution pressure accelerating. Zero-cross signals precede
    price moves by 1-3 bars in trending markets.

    Reference: Marc Chaikin — "Technical Analysis from A to Z" (1995).

    Args:
        df: OHLCV DataFrame with 'high', 'low', 'close', 'volume' columns.
        fast: Fast EMA period (default 3, standard Chaikin).
        slow: Slow EMA period (default 10, standard Chaikin).

    Returns:
        pd.Series of Chaikin Oscillator values, same index as df.
    """
    ad = ad_line(df)
    ema_fast = ema(ad, period=fast)
    ema_slow = ema(ad, period=slow)
    return ema_fast - ema_slow


def chaikin_oscillator_signal(
    df: pd.DataFrame, fast: int = 3, slow: int = 10
) -> pd.DataFrame:
    """Chaikin Oscillator with zero-line for crossover detection.

    Args:
        df: OHLCV DataFrame with 'high', 'low', 'close', 'volume' columns.
        fast: Fast EMA period (default 3).
        slow: Slow EMA period (default 10).

    Returns:
        pd.DataFrame with columns [chaikin, zero].
        Zero is always 0.0 (the crossover reference line).
    """
    co = chaikin_oscillator(df, fast=fast, slow=slow)
    return pd.DataFrame(
        {"chaikin": co, "zero": pd.Series(0.0, index=df.index)},
        index=df.index,
    )


# === Price Volume Trend (PVT) ===


def pvt(df: pd.DataFrame) -> pd.Series:
    """Price Volume Trend — cumulative volume-weighted price change.

    PVT = cumulative sum of (volume_t × pct_change_t).

    Unlike OBV which only uses sign(Δclose) — binary accumulation,
    PVT uses proportional price change. More granular signals than
    OBV while retaining the cumulative noise-smoothing property.

    PVT_t = PVT_{t-1} + volume_t × (close_t − close_{t-1}) / close_{t-1}

    Reference: David L. Markstein — "How to Chart Your Way to Stock
    Market Profits" (1965).

    Args:
        df: OHLCV DataFrame with 'close' and 'volume' columns.

    Returns:
        pd.Series of cumulative PVT values, same index as df.
    """
    close = df["close"]
    volume = df["volume"]
    pct_change = close.pct_change().fillna(0.0)
    raw_pvt = volume * pct_change
    return raw_pvt.cumsum()


def pvt_sma(df: pd.DataFrame, period: int = 20) -> pd.DataFrame:
    """Price Volume Trend with signal SMA for crossover detection.

    Args:
        df: OHLCV DataFrame with 'close' and 'volume' columns.
        period: SMA period on PVT (default 20).

    Returns:
        pd.DataFrame with columns [pvt, signal], same index as df.
    """
    pvt_val = pvt(df)
    signal_line = sma(pvt_val, period)
    return pd.DataFrame(
        {"pvt": pvt_val, "signal": signal_line}, index=df.index
    )


# === Hilbert Transform & MAMA/FAMA ===


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


# === Relative Momentum Index (RMI) ===


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


# === Klinger Volume Oscillator (KVO) ===


def kvo(
    df: pd.DataFrame,
    fast: int = 34,
    slow: int = 55,
) -> pd.DataFrame:
    """Klinger Volume Oscillator (KVO).

    KVO uses Volume Force — a volume-directional measure that weights
    volume by intra-bar price range and trend direction.  EMA(34, VF) -
    EMA(55, VF) produces an oscillator that acts as a zero-line
    crossover signal for volume-flow direction changes.

    Volume Force: VF = Volume × Trend × |2 × DM/CM − 1| × 100
      DM = high − low (bar range)
      CM = rolling sum of DM over `slow` bars
      Trend = +1 when typical price rises, −1 when it falls

    Reference: Stephen Klinger — "Klinger Volume Oscillator" (1997).

    Args:
        df: OHLCV DataFrame with 'high', 'low', 'close', 'volume'.
        fast: Fast EMA period (default 34).
        slow: Slow EMA period (default 55).

    Returns:
        pd.DataFrame with columns [kvo, zero], same index as df.
    """
    high = df["high"]
    low = df["low"]
    close = df["close"]
    volume = df["volume"]

    # Trend direction: +1 when typical price rises, -1 when falls
    typical = (high + low + close) / 3.0
    trend = pd.Series(
        np.where(typical.diff().fillna(0) >= 0, 1, -1),
        index=df.index,
        dtype=float,
    )

    # Bar range
    bar_range = high - low

    # Cumulative measure: rolling sum of bar ranges over slow period
    cm = bar_range.rolling(slow, min_periods=1).sum()
    cm = cm.clip(lower=1e-10)

    # Volume Force
    vf = volume * trend * np.abs(2.0 * bar_range / cm - 1.0) * 100.0

    # Dual-EMA smoothing: KVO = EMA(fast, VF) - EMA(slow, VF)
    ema_fast = vf.ewm(span=fast, adjust=False).mean()
    ema_slow = vf.ewm(span=slow, adjust=False).mean()
    kvo_val = ema_fast - ema_slow

    return pd.DataFrame(
        {"kvo": kvo_val, "zero": pd.Series(0.0, index=df.index)},
        index=df.index,
    )


# === McGinley Dynamic ===


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


# === Qstick (Quantitative Candlestick Oscillator) ===


def qstick(df: pd.DataFrame, period: int = 14) -> pd.Series:
    """Qstick — SMA of close-open difference (Chande's quantitative candlestick).

    Qstick = SMA(close - open, N).  It measures the running average of
    the candle's directional bias over N periods.  Positive Qstick means
    the average candle closes above its open (buying pressure dominates).
    Negative Qstick means selling pressure dominates.

    Unlike momentum oscillators that compare close[t] vs close[t-N],
    Qstick captures per-bar conviction — whether buyers or sellers
    are winning bar-by-bar.

    Reference: Tushar Chande — \"Beyond Technical Analysis\" (1997).

    Args:
        df: OHLCV DataFrame with columns [close, open].
        period: SMA period for Qstick (default 14).

    Returns:
        pd.Series of Qstick values, same index as df.
    """
    close = df["close"]
    open_ = df["open"]
    diff = close - open_
    return diff.rolling(period).mean()


# === Polarized Fractal Efficiency (PFE) ===


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


# === Arnaud Legoux Moving Average (ALMA) ===


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
