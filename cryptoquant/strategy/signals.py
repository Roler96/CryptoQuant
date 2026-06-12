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


def new_low_bullish(df: pd.DataFrame, lookback: int = 30) -> pd.Series:
    """Failed breakdown reversal signal (Wyckoff Spring).

    Returns 1 where: new N-bar low + bullish close + above-average volume.
    """
    low = df["low"]
    open_ = df["open"]
    close = df["close"]
    volume = df["volume"]

    prev_low_min = low.rolling(lookback).min().shift(1)
    new_low = low < prev_low_min
    bullish = close > open_
    vol_mean = volume.rolling(20).mean()
    high_vol = volume > vol_mean

    return (new_low & bullish & high_vol).astype(int)
