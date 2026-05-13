"""Market Regime Detection.

Provides MarketRegime enum and RegimeDetector for classifying
market states (trending, ranging, volatile) to guide strategy selection.

Usage:
    from strategy.regime import RegimeDetector, MarketRegime

    detector = RegimeDetector()
    regime = detector.detect(candles)
    print(detector.summary(candles))
"""

from strategy.regime.detector import MarketRegime, RegimeDetector

__all__ = ["MarketRegime", "RegimeDetector"]
