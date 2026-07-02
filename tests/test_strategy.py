"""Tests for strategy base class and signals library."""

import numpy as np
import pandas as pd
import pytest

from cryptoquant.exceptions import StrategyError
from cryptoquant.strategy import signals
from cryptoquant.strategy.base import Strategy


# ---- Fixtures ----


def _make_df(n=200, start_price=100.0, trend="flat"):
    """Generate OHLCV DataFrame with configurable trend."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
# pyright: reportAttributeAccessIssue=false, reportArgumentType=false
    if trend == "up":
        close = np.linspace(start_price, start_price + n * 0.5, n)
    elif trend == "down":
        close = np.linspace(start_price, start_price - n * 0.5, n)
    else:
        close = np.full(n, start_price)
        # Add some noise
        np.random.seed(42)
        close = close + np.random.randn(n) * 0.5

    df = pd.DataFrame(
        {
            "open": close - 0.1,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=dates,
    )
    return df


# ---- Concrete strategy for testing ----


class DummyStrategy(Strategy):
    timeframe = "1h"
    min_bars = 50
    DEFAULT_PARAMS = {"threshold": 0.5}

    @property
    def name(self) -> str:
        return "DummyStrategy"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        df = self.preprocess(df)
        return pd.Series(0, index=df.index, dtype=int)


# ---- Strategy Base Tests ----


class TestStrategyBase:
    def test_init_with_defaults(self):
        s = DummyStrategy()
        assert s.params == {"threshold": 0.5}

    def test_init_with_overrides(self):
        s = DummyStrategy({"threshold": 1.0})
        assert s.params["threshold"] == 1.0

    def test_name_property(self):
        s = DummyStrategy()
        assert s.name == "DummyStrategy"

    def test_generate_signal_returns_series(self):
        s = DummyStrategy()
        df = _make_df(100)
        signal = s.generate_signal(df)
        assert isinstance(signal, pd.Series)
        assert len(signal) == len(df)
        assert (signal.index == df.index).all()

    def test_preprocess_insufficient_bars(self):
        s = DummyStrategy()
        df = _make_df(10)  # Less than min_bars=50
        with pytest.raises(StrategyError, match="at least"):
            s.generate_signal(df)

    def test_preprocess_missing_columns(self):
        s = DummyStrategy()
        df = pd.DataFrame({"close": [1, 2, 3] * 20})
        with pytest.raises(StrategyError, match="missing required columns"):
            s.generate_signal(df)

    def test_get_param(self):
        s = DummyStrategy()
        assert s.get_param("threshold") == 0.5
        assert s.get_param("nonexistent", 42) == 42

    def test_repr(self):
        s = DummyStrategy()
        assert "DummyStrategy" in repr(s)
        assert "threshold=0.5" in repr(s)

    def test_class_variables(self):
        assert DummyStrategy.timeframe == "1h"
        assert DummyStrategy.min_bars == 50
        assert DummyStrategy.version == "1.0.0"


# ---- Signals Tests ----


class TestSMA:
    def test_basic(self):
        s = pd.Series([1.0, 2, 3, 4, 5, 6, 7, 8, 9, 10])
        result = signals.sma(s, 3)
        assert result.iloc[2] == pytest.approx(2.0)
        assert result.iloc[9] == pytest.approx(9.0)

    def test_nan_at_start(self):
        s = pd.Series([1.0, 2, 3, 4, 5])
        result = signals.sma(s, 3)
        assert pd.isna(result.iloc[0])
        assert pd.isna(result.iloc[1])


class TestEMA:
    def test_basic(self):
        s = pd.Series([1.0, 2, 3, 4, 5, 6, 7, 8, 9, 10])
        result = signals.ema(s, 3)
        assert len(result) == 10
        # EMA should be close to but not exactly SMA
        assert result.iloc[-1] > 0


class TestWMA:
    def test_basic(self):
        s = pd.Series([1.0, 2, 3, 4, 5])
        result = signals.wma(s, 3)
        # WMA of [3,4,5] with weights [1,2,3] = (3+8+15)/6 = 26/6 ~ 4.333
        assert result.iloc[4] == pytest.approx(4.333, abs=0.01)


class TestATR:
    def test_basic(self):
        df = _make_df(50)
        result = signals.atr(df, 14)
        assert len(result) == 50
        assert result.iloc[-1] > 0

    def test_nan_at_start(self):
        df = _make_df(20)
        result = signals.atr(df, 14)
        assert pd.isna(result.iloc[0])


class TestBollingerBands:
    def test_returns_correct_columns(self):
        df = _make_df(50)
        result = signals.bollinger_bands(df, 20)
        assert set(result.columns) == {"middle", "upper", "lower", "width", "pct_b"}

    def test_upper_above_lower(self):
        df = _make_df(50)
        result = signals.bollinger_bands(df, 20)
        valid = result.dropna()
        assert (valid["upper"] > valid["lower"]).all()


class TestRSI:
    def test_range(self):
        df = _make_df(100, trend="up")
        result = signals.rsi(df["close"], 14)
        valid = result.dropna()
        assert (valid >= 0).all()
        assert (valid <= 100).all()

    def test_uptrend_high_rsi(self):
        df = _make_df(100, trend="up")
        result = signals.rsi(df["close"], 14)
        # In strong uptrend, RSI should be high
        assert result.iloc[-1] > 50


class TestMACD:
    def test_returns_correct_columns(self):
        s = pd.Series(np.random.randn(100).cumsum() + 100)
        result = signals.macd(s)
        assert set(result.columns) == {"macd", "signal", "histogram"}


class TestStochastic:
    def test_returns_correct_columns(self):
        df = _make_df(50)
        result = signals.stochastic(df)
        assert set(result.columns) == {"k", "d"}


class TestADX:
    def test_returns_correct_columns(self):
        df = _make_df(50)
        result = signals.adx(df)
        assert set(result.columns) == {"adx", "pdi", "mdi"}


class TestAroon:
    def test_returns_correct_columns(self):
        df = _make_df(50)
        result = signals.aroon(df)
        assert set(result.columns) == {"aroon_up", "aroon_down"}


class TestVolumeIndicators:
    def test_volume_sma(self):
        df = _make_df(50)
        result = signals.volume_sma(df, 20)
        assert len(result) == 50

    def test_volume_profile_ratio(self):
        df = _make_df(50)
        result = signals.volume_profile_ratio(df, 20)
        valid = result.dropna()
        # Ratio of volume to its own average should be ~1.0 for constant volume
        assert valid.iloc[-1] == pytest.approx(1.0, abs=0.01)


class TestCrossover:
    def test_crossover_detects(self):
        a = pd.Series([1.0, 2, 3, 4, 5, 6, 7, 8, 9, 10])
        b = pd.Series([5.0, 5, 5, 5, 5, 5, 5, 5, 5, 5])
        result = signals.crossover(a, b)
        # a[4]=5 == b[4]=5 (not above), a[5]=6 > b[5]=5 → crossover at 5
        assert result.iloc[5] == 1

    def test_no_crossover(self):
        a = pd.Series([1.0, 2, 3, 4, 5])
        b = pd.Series([10.0, 10, 10, 10, 10])
        result = signals.crossover(a, b)
        assert result.sum() == 0


class TestCrossunder:
    def test_crossunder_detects(self):
        a = pd.Series([10.0, 8, 6, 4, 2])
        b = pd.Series([5.0, 5, 5, 5, 5])
        result = signals.crossunder(a, b)
        # a[0]=10>5, a[1]=8>5, a[2]=6>5, a[3]=4<5, a[4]=2<5
        # crossunder at index 3
        assert result.iloc[3] == -1


class TestRollingUtils:
    def test_rolling_max(self):
        s = pd.Series([1.0, 3, 2, 5, 4])
        result = signals.rolling_max(s, 3)
        assert result.iloc[4] == pytest.approx(5.0)

    def test_rolling_min(self):
        s = pd.Series([3.0, 1, 2, 0, 4])
        result = signals.rolling_min(s, 3)
        assert result.iloc[4] == pytest.approx(0.0)

    def test_pct_change_rolling(self):
        s = pd.Series([100.0, 110, 121, 133.1])
        result = signals.pct_change_rolling(s, 1)
        assert result.iloc[1] == pytest.approx(10.0)  # 10% increase


class TestDetectRegime:
    def _make_regime_df(self, n=300, trend="flat", volatility="low"):
        """Generate synthetic OHLCV for regime testing."""
        dates = pd.date_range("2024-01-01", periods=n, freq="1h")
        np.random.seed(42)
        if trend == "up":
            close = np.linspace(100, 200, n) + np.random.randn(n) * 0.5
        elif trend == "down":
            close = np.linspace(200, 100, n) + np.random.randn(n) * 0.5
        else:
            close = np.full(n, 100.0) + np.random.randn(n) * 0.5

        if volatility == "high":
            noise = np.random.randn(n) * 5.0
        elif volatility == "medium":
            noise = np.random.randn(n) * 1.0
        else:
            noise = np.random.randn(n) * 0.1

        close = close + noise
        df = pd.DataFrame(
            {
                "open": close - 0.1,
                "high": close + 1.0,
                "low": close - 1.0,
                "close": close,
                "volume": np.full(n, 1000.0),
            },
            index=dates,
        )
        return df

    def test_trending_bull(self):
        df = self._make_regime_df(n=300, trend="up", volatility="low")
        result = signals.detect_regime(df)
        valid = result.dropna().iloc[-50:]
        assert (valid == "trending_bull").sum() > 0

    def test_trending_bear(self):
        df = self._make_regime_df(n=300, trend="down", volatility="low")
        result = signals.detect_regime(df)
        valid = result.dropna().iloc[-50:]
        assert (valid == "trending_bear").sum() > 0

    def test_mean_reverting(self):
        df = self._make_regime_df(n=300, trend="flat", volatility="medium")
        result = signals.detect_regime(df)
        valid = result.dropna().iloc[-50:]
        assert (valid == "mean_reverting").sum() > 0

    def test_volatile(self):
        df = self._make_regime_df(n=300, trend="flat", volatility="high")
        result = signals.detect_regime(df)
        valid = result.dropna().iloc[-50:]
        assert (valid == "volatile").sum() > 0

    def test_quiet(self):
        df = self._make_regime_df(n=300, trend="flat", volatility="low")
        result = signals.detect_regime(df)
        valid = result.dropna().iloc[-50:]
        assert (valid == "quiet").sum() > 0

    def test_returns_series_same_length(self):
        df = self._make_regime_df(n=300)
        result = signals.detect_regime(df)
        assert len(result) == len(df)
        assert (result.index == df.index).all()

    def test_all_labels_present(self):
        df = self._make_regime_df(n=300, trend="up", volatility="high")
        result = signals.detect_regime(df)
        valid = result.dropna()
        labels = {"trending_bull", "trending_bear", "mean_reverting", "volatile", "quiet"}
        assert set(valid.unique()).issubset(labels)


class TestWickInversionSignal:
    def _make_df(self, n=300, start_price=100.0):
        dates = pd.date_range("2024-01-01", periods=n, freq="1h")
        np.random.seed(42)
        close = np.linspace(start_price, start_price + n * 0.5, n)
        close = close + np.random.randn(n) * 0.5
        return pd.DataFrame(
            {
                "open": close - 0.1,
                "high": close + 0.5,
                "low": close - 0.5,
                "close": close,
                "volume": np.full(n, 1000.0),
            },
            index=dates,
        )

    def test_wick_inversion_signal_equivalence(self):
        from strategies.wick import WickInversion

        df = self._make_df(300)
        params = {
            "imbalance_window": 6,
            "imbalance_threshold": 0.25,
            "price_lookback": 6,
            "price_floor": -0.5,
            "stop_pct": 3.0,
            "target_pct": 1.5,
            "hold_hours": 12,
            "commission": 0.0005,
            "vol_gate_enabled": True,
            "trend_filter_enabled": True,
        }

        strategy = WickInversion(params)
        expected = strategy.generate_signal(df)
        result = signals.wick_inversion_signal(df, **params)

        pd.testing.assert_series_equal(result, expected)
