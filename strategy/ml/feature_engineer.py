"""Feature engineering for ML-based trading strategies.

Extracts technical indicators, statistical features, and derived signals
from OHLCV data, producing a feature vector suitable for ML model input.

Two modes:
- Decimal-based (live trading): compute features from OHLCVCandle list
- Float-based (backtest): compute features from float arrays for speed
"""

import math
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional

import structlog

from data.models import OHLCVCandle
from strategy.cta import (
    calculate_adx,
    calculate_atr,
    calculate_bollinger_bands,
    calculate_ma,
    calculate_macd,
    calculate_rsi,
    calculate_choppiness,
)
from strategy.cta import (
    calculate_adx_f,
    calculate_atr_f,
    calculate_ma_f,
    calculate_rsi_f,
    calculate_choppiness_f,
)

logger = structlog.get_logger(__name__)


@dataclass
class FeatureConfig:
    """Configuration for feature engineering.

    Attributes:
        ma_periods: List of periods for moving average features
        rsi_period: RSI calculation period
        atr_period: ATR calculation period
        adx_period: ADX calculation period
        macd_fast/slow/signal: MACD parameters
        bb_period/std_dev: Bollinger Bands parameters
        chop_period: Choppiness Index period
        return_lookbacks: Lookback periods for return features
        volume_ma_period: Volume moving average period
        min_candles: Minimum candles required to compute features
    """
    ma_periods: List[int] = field(default_factory=lambda: [5, 10, 20, 50])
    rsi_period: int = 14
    atr_period: int = 14
    adx_period: int = 14
    macd_fast: int = 12
    macd_slow: int = 26
    macd_signal: int = 9
    bb_period: int = 20
    bb_std_dev: float = 2.0
    chop_period: int = 14
    return_lookbacks: List[int] = field(default_factory=lambda: [1, 3, 5, 10, 20])
    volume_ma_period: int = 20
    min_candles: int = 60  # Need enough data for longest indicator

    @property
    def feature_count(self) -> int:
        """Return approximate number of features generated."""
        # MA ratios: len(ma_periods) - 1 pairwise + len(ma_periods) price/MA ratios
        # RSI, ADX, CHOP: 3
        # MACD: 3 (line, signal, histogram)
        # BB: 3 (position, bandwidth, %B)
        # Returns: len(return_lookbacks)
        # Volume: 2 (ratio, change)
        # Volatility: 2 (realized, ATR ratio)
        # Price action: 3 (body ratio, upper/lower shadow)
        n_mas = len(self.ma_periods)
        return (
            n_mas  # price / MA ratios
            + (n_mas - 1)  # MA pair ratios
            + 3  # RSI, ADX, CHOP
            + 3  # MACD
            + 3  # BB
            + len(self.return_lookbacks)  # returns
            + 2  # volume features
            + 2  # volatility features
            + 3  # price action
        )


class FeatureEngineer:
    """Feature extraction engine for ML trading strategies.

    Computes a comprehensive feature vector from OHLCV data, including:
    - Moving average ratios (price relative to MAs, MA crossovers)
    - Momentum indicators (RSI, MACD histogram)
    - Volatility indicators (ATR, Bollinger Bands, realized volatility)
    - Trend strength (ADX, Choppiness Index)
    - Price returns at multiple lookbacks
    - Volume features
    - Candlestick pattern features

    Usage:
        fe = FeatureEngineer()
        features = fe.extract(candles)  # Returns Dict[str, float]
    """

    def __init__(self, config: Optional[FeatureConfig] = None) -> None:
        self.config = config or FeatureConfig()
        self.logger = structlog.get_logger(__name__)

    def extract(self, candles: List[OHLCVCandle]) -> Optional[Dict[str, float]]:
        """Extract feature vector from OHLCV candles (Decimal-based, for live).

        Args:
            candles: List of OHLCV candles (need at least config.min_candles)

        Returns:
            Dictionary of feature name -> value, or None if insufficient data
        """
        if len(candles) < self.config.min_candles:
            return None

        try:
            features: Dict[str, float] = {}
            current = candles[-1]
            close = current.close
            close_f = float(close)

            # --- MA features ---
            ma_values: Dict[int, Optional[Decimal]] = {}
            for period in self.config.ma_periods:
                ma_val = calculate_ma(candles, period, "ema")
                ma_values[period] = ma_val
                if ma_val is not None:
                    features[f"price_ema{period}_ratio"] = close_f / float(ma_val) - 1.0
                else:
                    features[f"price_ema{period}_ratio"] = 0.0

            # MA pair ratios (shorter MA / longer MA)
            sorted_periods = sorted(self.config.ma_periods)
            for i in range(len(sorted_periods) - 1):
                p1, p2 = sorted_periods[i], sorted_periods[i + 1]
                v1, v2 = ma_values.get(p1), ma_values.get(p2)
                key = f"ema{p1}_ema{p2}_ratio"
                if v1 is not None and v2 is not None and v2 != 0:
                    features[key] = float(v1) / float(v2) - 1.0
                else:
                    features[key] = 0.0

            # --- RSI ---
            rsi = calculate_rsi(candles, self.config.rsi_period)
            features["rsi"] = float(rsi) / 100.0 if rsi is not None else 0.5
            features["rsi_overbought"] = 1.0 if rsi is not None and rsi > Decimal("70") else 0.0
            features["rsi_oversold"] = 1.0 if rsi is not None and rsi < Decimal("30") else 0.0

            # --- ADX ---
            adx = calculate_adx(candles, self.config.adx_period)
            features["adx"] = float(adx) / 100.0 if adx is not None else 0.0

            # --- Choppiness ---
            chop = calculate_choppiness(candles, self.config.chop_period)
            features["chop"] = float(chop) / 100.0 if chop is not None else 0.5

            # --- MACD ---
            macd_line, signal_line, histogram = calculate_macd(
                candles, self.config.macd_fast, self.config.macd_slow, self.config.macd_signal
            )
            if macd_line is not None:
                features["macd_line"] = float(macd_line) / close_f
                features["macd_signal"] = float(signal_line) / close_f if signal_line else 0.0
                features["macd_histogram"] = float(histogram) / close_f if histogram else 0.0
            else:
                features["macd_line"] = 0.0
                features["macd_signal"] = 0.0
                features["macd_histogram"] = 0.0

            # --- Bollinger Bands ---
            bb_mid, bb_upper, bb_lower = calculate_bollinger_bands(
                candles, self.config.bb_period, Decimal(str(self.config.bb_std_dev))
            )
            if bb_mid is not None and bb_upper is not None and bb_lower is not None:
                bb_width = float(bb_upper - bb_lower) / float(bb_mid)
                features["bb_position"] = (close_f - float(bb_lower)) / (float(bb_upper) - float(bb_lower))
                features["bb_bandwidth"] = bb_width
                features["bb_pct_b"] = features["bb_position"]  # alias
            else:
                features["bb_position"] = 0.5
                features["bb_bandwidth"] = 0.0
                features["bb_pct_b"] = 0.5

            # --- Returns ---
            closes = [float(c.close) for c in candles]
            for lookback in self.config.return_lookbacks:
                if len(closes) > lookback:
                    ret = (closes[-1] / closes[-1 - lookback]) - 1.0
                    features[f"return_{lookback}"] = ret
                else:
                    features[f"return_{lookback}"] = 0.0

            # --- Volume features ---
            volumes = [float(c.volume) for c in candles]
            if len(volumes) >= self.config.volume_ma_period:
                vol_ma = sum(volumes[-self.config.volume_ma_period:]) / self.config.volume_ma_period
                features["volume_ratio"] = volumes[-1] / vol_ma if vol_ma > 0 else 1.0
                if len(volumes) >= 2:
                    features["volume_change"] = (volumes[-1] / volumes[-2]) - 1.0 if volumes[-2] > 0 else 0.0
                else:
                    features["volume_change"] = 0.0
            else:
                features["volume_ratio"] = 1.0
                features["volume_change"] = 0.0

            # --- Realized volatility ---
            if len(closes) >= 21:
                daily_rets = [
                    closes[i] / closes[i - 1] - 1.0
                    for i in range(-20, 0)
                ]
                mean_ret = sum(daily_rets) / len(daily_rets)
                realized_var = sum((r - mean_ret) ** 2 for r in daily_rets) / len(daily_rets)
                features["realized_vol"] = math.sqrt(realized_var)
            else:
                features["realized_vol"] = 0.0

            # ATR ratio (ATR / close)
            atr = calculate_atr(candles, self.config.atr_period)
            features["atr_ratio"] = float(atr) / close_f if atr is not None and close_f > 0 else 0.0

            # --- Price action features ---
            high_f = float(current.high)
            low_f = float(current.low)
            open_f = float(current.open)
            body = abs(close_f - open_f)
            total_range = high_f - low_f

            features["body_ratio"] = body / total_range if total_range > 0 else 0.0
            upper_shadow = high_f - max(close_f, open_f)
            lower_shadow = min(close_f, open_f) - low_f
            features["upper_shadow_ratio"] = upper_shadow / total_range if total_range > 0 else 0.0
            features["lower_shadow_ratio"] = lower_shadow / total_range if total_range > 0 else 0.0

            return features

        except Exception as e:
            self.logger.error("feature_extraction_failed", error=str(e))
            return None

    def extract_f(
        self,
        opens: List[float],
        highs: List[float],
        lows: List[float],
        closes: List[float],
        volumes: List[float],
    ) -> Optional[Dict[str, float]]:
        """Extract feature vector from float arrays (for backtest speed).

        Args:
            opens: List of open prices
            highs: List of high prices
            lows: List of low prices
            closes: List of close prices
            volumes: List of volumes

        Returns:
            Dictionary of feature name -> value, or None if insufficient data
        """
        n = len(closes)
        if n < self.config.min_candles:
            return None

        try:
            features: Dict[str, float] = {}
            close_f = closes[-1]
            open_f = opens[-1]
            high_f = highs[-1]
            low_f = lows[-1]

            # --- MA features ---
            ma_values: Dict[int, Optional[float]] = {}
            for period in self.config.ma_periods:
                ma_val = calculate_ma_f(closes, period, "ema")
                ma_values[period] = ma_val
                key = f"price_ema{period}_ratio"
                if ma_val is not None and ma_val != 0:
                    features[key] = close_f / ma_val - 1.0
                else:
                    features[key] = 0.0

            sorted_periods = sorted(self.config.ma_periods)
            for i in range(len(sorted_periods) - 1):
                p1, p2 = sorted_periods[i], sorted_periods[i + 1]
                v1, v2 = ma_values.get(p1), ma_values.get(p2)
                key = f"ema{p1}_ema{p2}_ratio"
                if v1 is not None and v2 is not None and v2 != 0:
                    features[key] = v1 / v2 - 1.0
                else:
                    features[key] = 0.0

            # --- RSI ---
            rsi_f = calculate_rsi_f(closes, self.config.rsi_period)
            features["rsi"] = rsi_f / 100.0 if rsi_f is not None else 0.5
            features["rsi_overbought"] = 1.0 if rsi_f is not None and rsi_f > 70.0 else 0.0
            features["rsi_oversold"] = 1.0 if rsi_f is not None and rsi_f < 30.0 else 0.0

            # --- ADX ---
            adx_f = calculate_adx_f(highs, lows, closes, self.config.adx_period)
            features["adx"] = adx_f / 100.0 if adx_f is not None else 0.0

            # --- Choppiness ---
            chop_f = calculate_choppiness_f(highs, lows, closes, self.config.chop_period)
            features["chop"] = chop_f / 100.0 if chop_f is not None else 0.5

            # --- MACD (float, simplified) ---
            if n >= self.config.macd_slow + self.config.macd_signal:
                macd_h = self._calc_macd_histogram_f(closes)
                features["macd_histogram"] = macd_h / close_f if close_f > 0 else 0.0
            else:
                features["macd_histogram"] = 0.0
            # Use simplified MACD line/signal for speed
            features["macd_line"] = features["macd_histogram"]  # approximation
            features["macd_signal"] = 0.0

            # --- Bollinger Bands ---
            bb_features = self._calc_bollinger_f(closes)
            features.update(bb_features)

            # --- Returns ---
            for lookback in self.config.return_lookbacks:
                if n > lookback:
                    features[f"return_{lookback}"] = closes[-1] / closes[-1 - lookback] - 1.0
                else:
                    features[f"return_{lookback}"] = 0.0

            # --- Volume features ---
            if len(volumes) >= self.config.volume_ma_period:
                vol_ma = sum(volumes[-self.config.volume_ma_period:]) / self.config.volume_ma_period
                features["volume_ratio"] = volumes[-1] / vol_ma if vol_ma > 0 else 1.0
                if len(volumes) >= 2:
                    features["volume_change"] = (volumes[-1] / volumes[-2]) - 1.0 if volumes[-2] > 0 else 0.0
                else:
                    features["volume_change"] = 0.0
            else:
                features["volume_ratio"] = 1.0
                features["volume_change"] = 0.0

            # --- Realized volatility ---
            if n >= 21:
                daily_rets = [closes[i] / closes[i - 1] - 1.0 for i in range(-20, 0)]
                mean_ret = sum(daily_rets) / 20.0
                realized_var = sum((r - mean_ret) ** 2 for r in daily_rets) / 20.0
                features["realized_vol"] = math.sqrt(realized_var)
            else:
                features["realized_vol"] = 0.0

            # ATR ratio
            atr_f = calculate_atr_f(highs, lows, closes, self.config.atr_period)
            features["atr_ratio"] = atr_f / close_f if atr_f is not None and close_f > 0 else 0.0

            # --- Price action features ---
            body = abs(close_f - open_f)
            total_range = high_f - low_f
            features["body_ratio"] = body / total_range if total_range > 0 else 0.0
            upper_shadow = high_f - max(close_f, open_f)
            lower_shadow = min(close_f, open_f) - low_f
            features["upper_shadow_ratio"] = upper_shadow / total_range if total_range > 0 else 0.0
            features["lower_shadow_ratio"] = lower_shadow / total_range if total_range > 0 else 0.0

            return features

        except Exception as e:
            self.logger.error("feature_extraction_f_failed", error=str(e))
            return None

    def get_feature_names(self) -> List[str]:
        """Return ordered list of feature names.

        Generates the same feature names as extract() would produce,
        useful for ensuring consistent column ordering.
        """
        names: List[str] = []

        for period in self.config.ma_periods:
            names.append(f"price_ema{period}_ratio")

        sorted_periods = sorted(self.config.ma_periods)
        for i in range(len(sorted_periods) - 1):
            names.append(f"ema{sorted_periods[i]}_ema{sorted_periods[i+1]}_ratio")

        names.extend(["rsi", "rsi_overbought", "rsi_oversold", "adx", "chop"])
        names.extend(["macd_line", "macd_signal", "macd_histogram"])
        names.extend(["bb_position", "bb_bandwidth", "bb_pct_b"])

        for lookback in self.config.return_lookbacks:
            names.append(f"return_{lookback}")

        names.extend(["volume_ratio", "volume_change", "realized_vol", "atr_ratio"])
        names.extend(["body_ratio", "upper_shadow_ratio", "lower_shadow_ratio"])

        return names

    def features_to_vector(self, features: Dict[str, float]) -> List[float]:
        """Convert feature dict to ordered vector matching get_feature_names().

        Args:
            features: Feature dictionary from extract() or extract_f()

        Returns:
            Ordered list of feature values
        """
        names = self.get_feature_names()
        return [features.get(name, 0.0) for name in names]

    # --- Private float helpers for speed ---

    def _calc_macd_histogram_f(self, closes: List[float]) -> float:
        """Fast MACD histogram calculation."""
        fast = self.config.macd_fast
        slow = self.config.macd_slow
        signal = self.config.macd_signal

        if len(closes) < slow + signal:
            return 0.0

        def ema_f(data: List[float], period: int) -> List[float]:
            mult = 2.0 / (period + 1)
            vals = [data[0]]
            for p in data[1:]:
                vals.append((p - vals[-1]) * mult + vals[-1])
            return vals

        ema_fast = ema_f(closes, fast)
        ema_slow = ema_f(closes, slow)

        min_len = min(len(ema_fast), len(ema_slow))
        macd_line = [ema_fast[-(min_len - i)] - ema_slow[-(min_len - i)]
                     for i in range(min_len)]

        if len(macd_line) < signal:
            return 0.0

        signal_line = ema_f(macd_line, signal)
        return macd_line[-1] - signal_line[-1]

    def _calc_bollinger_f(self, closes: List[float]) -> Dict[str, float]:
        """Fast Bollinger Band features."""
        period = self.config.bb_period
        result: Dict[str, float] = {}

        if len(closes) < period:
            result["bb_position"] = 0.5
            result["bb_bandwidth"] = 0.0
            result["bb_pct_b"] = 0.5
            return result

        recent = closes[-period:]
        sma = sum(recent) / period
        variance = sum((c - sma) ** 2 for c in recent) / period
        std = math.sqrt(variance)

        upper = sma + std * self.config.bb_std_dev
        lower = sma - std * self.config.bb_std_dev

        bb_width = (upper - lower) / sma if sma > 0 else 0.0
        bb_position = (closes[-1] - lower) / (upper - lower) if (upper - lower) > 0 else 0.5

        result["bb_position"] = bb_position
        result["bb_bandwidth"] = bb_width
        result["bb_pct_b"] = bb_position

        return result
