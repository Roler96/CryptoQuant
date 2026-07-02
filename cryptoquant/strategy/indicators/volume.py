"""Volume indicators."""
# pyright: reportAttributeAccessIssue=false, reportReturnType=false, reportArgumentType=false

import numpy as np
import pandas as pd
from cryptoquant.strategy.indicators.trend import sma, ema

__all__ = [
    "volume_sma",
    "volume_profile_ratio",
    "mfi",
    "cmf",
    "vwap",
    "obv",
    "obv_sma",
    "ad_line",
    "ad_line_sma",
    "ease_of_movement",
    "emv_sma",
    "twiggs_money_flow",
    "chaikin_oscillator",
    "chaikin_oscillator_signal",
    "pvt",
    "pvt_sma",
    "kvo",
    "qstick",
    "force_index",
]

def volume_sma(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Volume Simple Moving Average."""
    return df["volume"].rolling(period).mean()



def volume_profile_ratio(df: pd.DataFrame, period: int = 20) -> pd.Series:
    """Current volume / average volume over period."""
    avg_vol = df["volume"].rolling(period).mean()
    return df["volume"] / avg_vol



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
