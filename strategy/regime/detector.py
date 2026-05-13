"""Market Regime Detection module.

Identifies the current market state (trending, ranging, volatile) to help
select the appropriate trading strategy.
"""

from enum import Enum
from typing import List, Optional, Tuple

from data.models import OHLCVCandle
from strategy.cta import calculate_adx, calculate_atr, calculate_choppiness


class MarketRegime(Enum):
    """Detected market regime."""
    STRONG_TREND = "strong_trend"    # Clear directional movement
    WEAK_TREND = "weak_trend"        # Trending but with pullbacks
    RANGING = "ranging"              # Sideways / choppy
    HIGH_VOLATILITY = "high_vol"     # Erratic, high ATR
    UNKNOWN = "unknown"              # Insufficient data


class RegimeDetector:
    """Market regime detector combining ADX, CHOP, and ATR.

    Uses a multi-indicator approach for robust classification:
    - ADX: Trend strength (0-100)
    - CHOP: Choppiness index (0-100, high = choppy)
    - ATR percentile: Relative volatility

    Usage:
        detector = RegimeDetector()
        regime = detector.detect(candles)
        print(f"Market is: {regime.name}")
    """

    def __init__(
        self,
        adx_period: int = 14,
        chop_period: int = 14,
        atr_period: int = 14,
        adx_strong: float = 30,
        adx_weak: float = 20,
        chop_high: float = 61.8,
        chop_low: float = 38.2,
    ):
        self.adx_period = adx_period
        self.chop_period = chop_period
        self.atr_period = atr_period
        self.adx_strong = adx_strong
        self.adx_weak = adx_weak
        self.chop_high = chop_high
        self.chop_low = chop_low

    def detect(self, candles: List[OHLCVCandle]) -> MarketRegime:
        """Detect current market regime.

        Args:
            candles: Recent OHLCV candles (at least adx_period + chop_period + 2)

        Returns:
            Detected MarketRegime
        """
        adx = calculate_adx(candles, self.adx_period)
        chop = calculate_choppiness(candles, self.chop_period)
        atr = calculate_atr(candles, self.atr_period)

        if adx is None and chop is None:
            return MarketRegime.UNKNOWN

        # Rule-based classification
        # Priority 1: High choppiness overrides everything → RANGING
        if chop is not None and chop > self.chop_high:
            return MarketRegime.RANGING

        # Priority 2: Strong ADX → STRONG_TREND
        if adx is not None and adx > self.adx_strong:
            return MarketRegime.STRONG_TREND

        # Priority 3: Weak ADX → WEAK_TREND
        if adx is not None and adx > self.adx_weak:
            return MarketRegime.WEAK_TREND

        # Priority 4: Low ADX + low chop → could be weak trend building
        if chop is not None and chop < self.chop_low:
            return MarketRegime.WEAK_TREND

        # Fallback: RANGING
        if adx is not None:
            return MarketRegime.RANGING

        return MarketRegime.UNKNOWN

    def detect_with_scores(
        self, candles: List[OHLCVCandle],
    ) -> Tuple[MarketRegime, dict]:
        """Detect regime and return indicator scores.

        Args:
            candles: Recent OHLCV candles

        Returns:
            Tuple of (regime, scores_dict with adx/chop/atr values)
        """
        regime = self.detect(candles)

        adx = calculate_adx(candles, self.adx_period)
        chop = calculate_choppiness(candles, self.chop_period)
        atr = calculate_atr(candles, self.atr_period)

        scores = {
            "adx": float(adx) if adx is not None else None,
            "chop": float(chop) if chop is not None else None,
            "atr": float(atr) if atr is not None else None,
        }

        return regime, scores

    def summary(self, candles: List[OHLCVCandle]) -> str:
        """Human-readable regime summary.

        Args:
            candles: Recent OHLCV candles

        Returns:
            Formatted string with regime and indicator values
        """
        regime, scores = self.detect_with_scores(candles)

        adx_str = f"{scores['adx']:.1f}" if scores["adx"] is not None else "N/A"
        chop_str = f"{scores['chop']:.1f}" if scores["chop"] is not None else "N/A"
        atr_str = f"{scores['atr']:.2f}" if scores["atr"] is not None else "N/A"

        lines = [
            f"Market Regime: {regime.value}",
            f"  ADX({self.adx_period}):   {adx_str}",
            f"  CHOP({self.chop_period}): {chop_str}",
            f"  ATR({self.atr_period}):   {atr_str}",
            "",
        ]

        if regime == MarketRegime.STRONG_TREND:
            lines.append("  → Trend strategy (CTA) recommended")
        elif regime == MarketRegime.WEAK_TREND:
            lines.append("  → Trend strategy usable, but cautious")
        elif regime == MarketRegime.RANGING:
            lines.append("  → Mean-reversion strategy recommended")
        elif regime == MarketRegime.HIGH_VOLATILITY:
            lines.append("  → Reduce position size, widen stops")
        else:
            lines.append("  → Insufficient data for classification")

        return "\n".join(lines)
