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
    """Calculate moving average from candle data.

    Args:
        candles: List of OHLCV candles
        period: Number of periods for the moving average
        ma_type: Type of moving average ("sma", "ema")
        price_source: Price to use ("open", "high", "low", "close")

    Returns:
        Moving average value or None if insufficient data
    """
    if len(candles) < period:
        return None

    recent = candles[-period:]

    price_attr = {
        "open": "open_price",
        "high": "high_price",
        "low": "low_price",
        "close": "close_price",
    }.get(price_source, "close_price")

    prices = [getattr(c, price_attr) for c in recent]

    if ma_type.lower() == "sma":
        avg = sum(prices) / len(prices)
        return avg

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
    """Calculate Relative Strength Index (RSI).

    Args:
        candles: List of OHLCV candles
        period: RSI lookback period (default 14)

    Returns:
        RSI value (0-100) or None if insufficient data
    """
    if len(candles) < period + 1:
        return None

    closes = [c.close_price for c in candles[-(period + 1) :]]

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

    avg_gain = sum(gains) / period
    avg_loss = sum(losses) / period

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
    """Detect price breakout from support/resistance levels.

    Args:
        candles: List of OHLCV candles
        lookback: Number of periods to look back for levels
        mode: Detection mode ("resistance", "support", "both")

    Returns:
        Tuple of (is_breakout, level_price, breakout_strength)
        where is_breakout is True if breakout detected
    """
    if len(candles) < lookback + 1:
        return False, None, None

    recent = candles[-(lookback + 1) : -1]
    current = candles[-1]

    highs = [c.high_price for c in recent]
    lows = [c.low_price for c in recent]

    resistance = max(highs)
    support = min(lows)

    breakout_detected = False
    level_price = None
    strength = None

    if mode in ("resistance", "both"):
        if current.close_price > resistance:
            breakout_detected = True
            level_price = resistance
            strength = (current.close_price - resistance) / resistance

    if mode in ("support", "both") and not breakout_detected:
        if current.close_price < support:
            breakout_detected = True
            level_price = support
            strength = (support - current.close_price) / support

    return breakout_detected, level_price, strength


def calculate_atr(
    candles: List[OHLCVCandle],
    period: int = 14,
) -> Optional[Decimal]:
    """Calculate Average True Range (ATR).

    Args:
        candles: List of OHLCV candles
        period: ATR lookback period (default 14)

    Returns:
        ATR value or None if insufficient data
    """
    if len(candles) < period + 1:
        return None

    true_ranges = []
    for i in range(1, len(candles)):
        current = candles[i]
        previous = candles[i - 1]

        tr1 = current.high_price - current.low_price
        tr2 = abs(current.high_price - previous.close_price)
        tr3 = abs(current.low_price - previous.close_price)

        true_range = max(tr1, tr2, tr3)
        true_ranges.append(true_range)

    if len(true_ranges) < period:
        return None

    recent_tr = true_ranges[-period:]
    atr = sum(recent_tr) / period

    return atr


def calculate_bollinger_bands(
    candles: List[OHLCVCandle],
    period: int = 20,
    std_dev: Decimal = Decimal("2"),
) -> Tuple[Optional[Decimal], Optional[Decimal], Optional[Decimal]]:
    """Calculate Bollinger Bands.

    Args:
        candles: List of OHLCV candles
        period: Moving average period (default 20)
        std_dev: Number of standard deviations (default 2)

    Returns:
        Tuple of (middle_band, upper_band, lower_band) or None if insufficient data
    """
    if len(candles) < period:
        return None, None, None

    recent = candles[-period:]
    closes = [c.close_price for c in recent]

    sma = sum(closes) / len(closes)

    variance = sum((c - sma) ** 2 for c in closes) / len(closes)
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
    """Calculate MACD (Moving Average Convergence Divergence).

    Args:
        candles: List of OHLCV candles
        fast: Fast EMA period (default 12)
        slow: Slow EMA period (default 26)
        signal: Signal line period (default 9)

    Returns:
        Tuple of (macd_line, signal_line, histogram) or None if insufficient data
    """
    if len(candles) < slow + signal:
        return None, None, None

    closes = [c.close_price for c in candles]

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
