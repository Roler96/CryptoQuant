"""CTA (Commodity Trading Advisor) indicator utilities.

Technical analysis helpers for calculating moving averages, RSI, and detecting
breakouts. Used by CTA-style trading strategies.
"""

from decimal import Decimal
from typing import List, Optional, Tuple

import structlog

from data.models import OHLCVCandle

logger = structlog.get_logger(__name__)


def calculate_ma(
    candles: List[OHLCVCandle],
    period: int,
    ma_type: str = "sma",
    price_source: str = "close",
) -> Optional[Decimal]:
    """Calculate moving average from candle data."""
    if len(candles) < period:
        return None

    recent = candles[-period:]
    price_attr = {"open": "open", "high": "high", "low": "low", "close": "close"}.get(price_source, "close")
    prices = [getattr(c, price_attr) for c in recent]

    if ma_type.lower() == "sma":
        return sum(prices, Decimal("0")) / len(prices)
    elif ma_type.lower() == "ema":
        multiplier = Decimal("2") / Decimal(period + 1)
        ema = prices[0]
        for price in prices[1:]:
            ema = (price - ema) * multiplier + ema
        return ema
    else:
        raise ValueError(f"Unknown MA type: {ma_type}")


def calculate_rsi(
    candles: List[OHLCVCandle],
    period: int = 14,
) -> Optional[Decimal]:
    """Calculate Relative Strength Index (RSI)."""
    if len(candles) < period + 1:
        return None

    closes = [c.close for c in candles[-(period + 1) :]]
    gains = []
    losses = []
    for i in range(1, len(closes)):
        change = closes[i] - closes[i - 1]
        if change > 0:
            gains.append(change)
            losses.append(Decimal("0"))
        else:
            gains.append(Decimal("0"))
            losses.append(abs(change))

    avg_gain = sum(gains, Decimal("0")) / period
    avg_loss = sum(losses, Decimal("0")) / period

    if avg_loss == 0:
        return Decimal("100") if avg_gain > 0 else Decimal("50")

    rs = avg_gain / avg_loss
    rsi = Decimal("100") - (Decimal("100") / (Decimal("1") + rs))
    return rsi


def detect_breakout(
    candles: List[OHLCVCandle],
    lookback: int = 20,
    mode: str = "resistance",
) -> Tuple[bool, Optional[Decimal], Optional[Decimal]]:
    """Detect price breakout from support/resistance levels."""
    if len(candles) < lookback + 1:
        return False, None, None

    recent = candles[-(lookback + 1) : -1]
    current = candles[-1]
    highs = [c.high for c in recent]
    lows = [c.low for c in recent]
    resistance = max(highs)
    support = min(lows)

    breakout_detected = False
    level_price = None
    strength = None

    if mode in ("resistance", "both"):
        if current.close > resistance:
            breakout_detected = True
            level_price = resistance
            strength = (current.close - resistance) / resistance

    if mode in ("support", "both") and not breakout_detected:
        if current.close < support:
            breakout_detected = True
            level_price = support
            strength = (support - current.close) / support

    return breakout_detected, level_price, strength


def calculate_atr(
    candles: List[OHLCVCandle],
    period: int = 14,
) -> Optional[Decimal]:
    """Calculate Average True Range (ATR)."""
    if len(candles) < period + 1:
        return None

    true_ranges = []
    for i in range(1, len(candles)):
        current = candles[i]
        previous = candles[i - 1]
        tr1 = current.high - current.low
        tr2 = abs(current.high - previous.close)
        tr3 = abs(current.low - previous.close)
        true_range = max(tr1, tr2, tr3)
        true_ranges.append(true_range)

    if len(true_ranges) < period:
        return None

    recent_tr = true_ranges[-period:]
    return sum(recent_tr, Decimal("0")) / period


def calculate_bollinger_bands(
    candles: List[OHLCVCandle],
    period: int = 20,
    std_dev: Decimal = Decimal("2"),
) -> Tuple[Optional[Decimal], Optional[Decimal], Optional[Decimal]]:
    """Calculate Bollinger Bands."""
    if len(candles) < period:
        return None, None, None

    recent = candles[-period:]
    closes = [c.close for c in recent]
    sma = sum(closes, Decimal("0")) / len(closes)
    variance = sum(((c - sma) ** 2 for c in closes), Decimal("0")) / len(closes)
    std = variance.sqrt()
    upper = sma + (std * std_dev)
    lower = sma - (std * std_dev)
    return sma, upper, lower


def calculate_macd(
    candles: List[OHLCVCandle],
    fast: int = 12,
    slow: int = 26,
    signal: int = 9,
) -> Tuple[Optional[Decimal], Optional[Decimal], Optional[Decimal]]:
    """Calculate MACD."""
    if len(candles) < slow + signal:
        return None, None, None

    closes = [c.close for c in candles]

    def ema(prices: List[Decimal], period: int) -> List[Decimal]:
        multiplier = Decimal("2") / Decimal(period + 1)
        ema_values = [prices[0]]
        for price in prices[1:]:
            ema_values.append((price - ema_values[-1]) * multiplier + ema_values[-1])
        return ema_values

    ema_fast = ema(closes, fast)
    ema_slow = ema(closes, slow)
    macd_line = [f - s for f, s in zip(ema_fast[-(slow + signal) :], ema_slow)]
    signal_line_values = ema(macd_line, signal)

    macd_current = macd_line[-1]
    signal_current = signal_line_values[-1]
    histogram = macd_current - signal_current
    return macd_current, signal_current, histogram


def calculate_adx(
    candles: List[OHLCVCandle],
    period: int = 14,
) -> Optional[Decimal]:
    """Calculate Average Directional Index (ADX)."""
    if len(candles) < period + 2:
        return None

    plus_dm_list: List[Decimal] = []
    minus_dm_list: List[Decimal] = []
    tr_list: List[Decimal] = []

    for i in range(1, len(candles)):
        current = candles[i]
        previous = candles[i - 1]
        high_diff = current.high - previous.high
        low_diff = previous.low - current.low

        if high_diff > low_diff and high_diff > 0:
            plus_dm = high_diff
        else:
            plus_dm = Decimal("0")

        if low_diff > high_diff and low_diff > 0:
            minus_dm = low_diff
        else:
            minus_dm = Decimal("0")

        tr1 = current.high - current.low
        tr2 = abs(current.high - previous.close)
        tr3 = abs(current.low - previous.close)
        tr = max(tr1, tr2, tr3)

        plus_dm_list.append(plus_dm)
        minus_dm_list.append(minus_dm)
        tr_list.append(tr)

    smooth_multiplier = Decimal(period - 1)
    divisor = Decimal(period)

    plus_di_smoothed = sum(plus_dm_list[:period])
    minus_di_smoothed = sum(minus_dm_list[:period])
    tr_smoothed = sum(tr_list[:period])

    dx_values: List[Decimal] = []

    if tr_smoothed == 0:
        dx_values.append(Decimal("0"))
    else:
        plus_di = (plus_di_smoothed / tr_smoothed) * Decimal("100")
        minus_di = (minus_di_smoothed / tr_smoothed) * Decimal("100")
        di_sum = plus_di + minus_di
        if di_sum == 0:
            dx_values.append(Decimal("0"))
        else:
            dx_values.append(abs(plus_di - minus_di) / di_sum * Decimal("100"))

    for i in range(period, len(plus_dm_list)):
        plus_di_smoothed = (plus_di_smoothed * smooth_multiplier + plus_dm_list[i]) / divisor
        minus_di_smoothed = (minus_di_smoothed * smooth_multiplier + minus_dm_list[i]) / divisor
        tr_smoothed = (tr_smoothed * smooth_multiplier + tr_list[i]) / divisor

        if tr_smoothed == 0:
            dx_values.append(Decimal("0"))
        else:
            plus_di = (plus_di_smoothed / tr_smoothed) * Decimal("100")
            minus_di = (minus_di_smoothed / tr_smoothed) * Decimal("100")
            di_sum = plus_di + minus_di
            if di_sum == 0:
                dx_values.append(Decimal("0"))
            else:
                dx_values.append(abs(plus_di - minus_di) / di_sum * Decimal("100"))

    if len(dx_values) < period:
        return None

    return sum(dx_values[-period:], Decimal("0")) / period


def calculate_choppiness(
    candles: List[OHLCVCandle],
    period: int = 14,
) -> Optional[Decimal]:
    """Calculate Choppiness Index (CHOP).

    CHOP measures whether price is choppy/ranging or trending.
    Values range 0-100:
    - > 61.8: Ranging / choppy market
    - 38.2 - 61.8: Neutral
    - < 38.2: Trending market

    Args:
        candles: List of OHLCV candles
        period: Lookback period (default 14)

    Returns:
        CHOP value or None if insufficient data
    """
    if len(candles) < period + 1:
        return None

    atr_sum = Decimal("0")
    for i in range(-period, 0):
        current = candles[i]
        previous = candles[i - 1]
        tr1 = current.high - current.low
        tr2 = abs(current.high - previous.close)
        tr3 = abs(current.low - previous.close)
        atr_sum += max(tr1, tr2, tr3)

    window = candles[-(period + 1) :]
    high_range = max(c.high for c in window)
    low_range = min(c.low for c in window)
    price_range = high_range - low_range

    if price_range == 0 or atr_sum == 0:
        return Decimal("100")

    log_period = Decimal(str(period)).ln()
    log_ratio = (atr_sum / price_range).ln()
    chop = Decimal("100") * (log_ratio / log_period)

    return chop
