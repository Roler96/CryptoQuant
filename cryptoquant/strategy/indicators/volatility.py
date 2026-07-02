"""Volatility indicators."""
# pyright: reportAttributeAccessIssue=false, reportReturnType=false, reportArgumentType=false

import numpy as np
import pandas as pd
from cryptoquant.strategy.indicators.trend import ema

__all__ = [
    "atr",
    "bollinger_bands",
    "historical_volatility",
    "keltner_channel",
    "donchian",
    "bb_squeeze",
    "ttm_squeeze",
]

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
