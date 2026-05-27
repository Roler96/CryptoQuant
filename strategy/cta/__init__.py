"""CTA (Commodity Trading Advisor) indicator utilities.

Technical analysis helpers for calculating moving averages, RSI, and detecting
breakouts. Used by CTA-style trading strategies.

Two sets of functions are provided:
- Decimal-based (calculate_ma, calculate_rsi, etc.) — for live trading precision
- Float-based (calculate_ma_f, calculate_rsi_f, etc.) — for backtest speed
"""

import math
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


# ============================================================================
# Float-based indicator functions for backtest performance
# ============================================================================
# These functions use native float arithmetic instead of Decimal,
# providing 50-100x speedup for backtesting with negligible precision loss.


def calculate_ma_f(
    closes: List[float],
    period: int,
    ma_type: str = "sma",
) -> Optional[float]:
    """Float-based moving average calculation."""
    if len(closes) < period:
        return None

    recent = closes[-period:]

    if ma_type.lower() == "sma":
        return sum(recent) / period
    elif ma_type.lower() == "ema":
        multiplier = 2.0 / (period + 1)
        ema_val = recent[0]
        for price in recent[1:]:
            ema_val = (price - ema_val) * multiplier + ema_val
        return ema_val
    else:
        raise ValueError(f"Unknown MA type: {ma_type}")


def calculate_rsi_f(
    closes: List[float],
    period: int = 14,
) -> Optional[float]:
    """Float-based RSI calculation."""
    if len(closes) < period + 1:
        return None

    recent = closes[-(period + 1):]
    gains = 0.0
    losses = 0.0

    for i in range(1, len(recent)):
        change = recent[i] - recent[i - 1]
        if change > 0:
            gains += change
        else:
            losses += abs(change)

    avg_gain = gains / period
    avg_loss = losses / period

    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0

    rs = avg_gain / avg_loss
    return 100.0 - (100.0 / (1.0 + rs))


def detect_breakout_f(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    lookback: int = 20,
    mode: str = "resistance",
) -> Tuple[bool, Optional[float], Optional[float]]:
    """Float-based breakout detection."""
    if len(closes) < lookback + 1:
        return False, None, None

    recent_highs = highs[-(lookback + 1):-1]
    recent_lows = lows[-(lookback + 1):-1]
    current_close = closes[-1]

    resistance = max(recent_highs)
    support = min(recent_lows)

    breakout_detected = False
    level_price = None
    strength = None

    if mode in ("resistance", "both"):
        if current_close > resistance:
            breakout_detected = True
            level_price = resistance
            strength = (current_close - resistance) / resistance

    if mode in ("support", "both") and not breakout_detected:
        if current_close < support:
            breakout_detected = True
            level_price = support
            strength = (support - current_close) / support

    return breakout_detected, level_price, strength


def calculate_atr_f(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    period: int = 14,
) -> Optional[float]:
    """Float-based ATR calculation."""
    n = len(closes)
    if n < period + 1:
        return None

    # Only compute for the last period+1 bars
    start = n - period - 1
    true_ranges = []
    for i in range(start + 1, n):
        tr1 = highs[i] - lows[i]
        tr2 = abs(highs[i] - closes[i - 1])
        tr3 = abs(lows[i] - closes[i - 1])
        true_ranges.append(max(tr1, tr2, tr3))

    if len(true_ranges) < period:
        return None

    return sum(true_ranges[-period:]) / period


def calculate_adx_f(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    period: int = 14,
) -> Optional[float]:
    """Float-based ADX calculation."""
    if len(closes) < period + 2:
        return None

    plus_dm_list: List[float] = []
    minus_dm_list: List[float] = []
    tr_list: List[float] = []

    for i in range(1, len(closes)):
        high_diff = highs[i] - highs[i - 1]
        low_diff = lows[i - 1] - lows[i]

        plus_dm = high_diff if (high_diff > low_diff and high_diff > 0) else 0.0
        minus_dm = low_diff if (low_diff > high_diff and low_diff > 0) else 0.0

        tr1 = highs[i] - lows[i]
        tr2 = abs(highs[i] - closes[i - 1])
        tr3 = abs(lows[i] - closes[i - 1])
        tr = max(tr1, tr2, tr3)

        plus_dm_list.append(plus_dm)
        minus_dm_list.append(minus_dm)
        tr_list.append(tr)

    smooth_multiplier = float(period - 1)
    divisor = float(period)

    plus_di_smoothed = sum(plus_dm_list[:period])
    minus_di_smoothed = sum(minus_dm_list[:period])
    tr_smoothed = sum(tr_list[:period])

    dx_values: List[float] = []

    if tr_smoothed == 0:
        dx_values.append(0.0)
    else:
        plus_di = (plus_di_smoothed / tr_smoothed) * 100.0
        minus_di = (minus_di_smoothed / tr_smoothed) * 100.0
        di_sum = plus_di + minus_di
        if di_sum == 0:
            dx_values.append(0.0)
        else:
            dx_values.append(abs(plus_di - minus_di) / di_sum * 100.0)

    for i in range(period, len(plus_dm_list)):
        plus_di_smoothed = (plus_di_smoothed * smooth_multiplier + plus_dm_list[i]) / divisor
        minus_di_smoothed = (minus_di_smoothed * smooth_multiplier + minus_dm_list[i]) / divisor
        tr_smoothed = (tr_smoothed * smooth_multiplier + tr_list[i]) / divisor

        if tr_smoothed == 0:
            dx_values.append(0.0)
        else:
            plus_di = (plus_di_smoothed / tr_smoothed) * 100.0
            minus_di = (minus_di_smoothed / tr_smoothed) * 100.0
            di_sum = plus_di + minus_di
            if di_sum == 0:
                dx_values.append(0.0)
            else:
                dx_values.append(abs(plus_di - minus_di) / di_sum * 100.0)

    if len(dx_values) < period:
        return None

    return sum(dx_values[-period:]) / period


def calculate_choppiness_f(
    highs: List[float],
    lows: List[float],
    closes: List[float],
    period: int = 14,
) -> Optional[float]:
    """Float-based Choppiness Index calculation."""
    if len(closes) < period + 1:
        return None

    atr_sum = 0.0
    for i in range(-period, 0):
        tr1 = highs[i] - lows[i]
        tr2 = abs(highs[i] - closes[i - 1])
        tr3 = abs(lows[i] - closes[i - 1])
        atr_sum += max(tr1, tr2, tr3)

    window_start = -(period + 1)
    high_range = max(highs[window_start:])
    low_range = min(lows[window_start:])
    price_range = high_range - low_range

    if price_range == 0 or atr_sum == 0:
        return 100.0

    log_period = math.log(period)
    log_ratio = math.log(atr_sum / price_range)
    return 100.0 * (log_ratio / log_period)
