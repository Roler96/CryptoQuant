"""Tests for CorrelationCheck."""
import numpy as np
import pandas as pd
import pytest

from cryptoquant.risk.correlation import CorrelationCheck


def _make_df(n=20, start_price=100.0, trend=0.05):
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    close = np.cumsum(np.random.randn(n) * trend + 1) + start_price
    return pd.DataFrame({"open": close - 1, "high": close + 2, "low": close - 2, "close": close, "volume": np.full(n, 1000.0)}, index=dates)


@pytest.fixture
def checker():
    return CorrelationCheck(threshold=0.7, lookback=10)


class TestShouldEnter:
    def test_no_existing_positions_allowed(self, checker):
        df = _make_df(20)
        allowed, reason = checker.should_enter(df, [])
        assert allowed
        assert "no existing" in reason

    def test_high_correlation_blocked(self, checker):
        np.random.seed(42)
        df_a = _make_df(20)
        df_b = df_a.copy()

        allowed, reason = checker.should_enter(df_a, [df_b])
        assert not allowed
        assert "correlation" in reason

    def test_low_correlation_allowed(self, checker):
        np.random.seed(42)
        df_a = _make_df(20)
        df_b = _make_df(20, start_price=200.0)

        allowed, reason = checker.should_enter(df_a, [df_b])
        assert allowed
        assert "passed" in reason

    def test_multiple_existing_symbols(self, checker):
        np.random.seed(42)
        df_a = _make_df(20)
        df_b = df_a.copy()
        df_c = _make_df(20, start_price=200.0)

        allowed, reason = checker.should_enter(df_a, [df_b, df_c])
        assert not allowed
        assert "correlation" in reason


class TestComputeCorrelation:
    def test_perfect_correlation(self, checker):
        df = _make_df(20)
        corr = checker.compute_correlation(df, df)
        assert corr == pytest.approx(1.0, abs=1e-6)

    def test_insufficient_data_returns_zero(self, checker):
        empty_df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        corr = checker.compute_correlation(empty_df, empty_df)
        assert corr == 0.0

    def test_short_data_returns_zero(self, checker):
        df = _make_df(5)
        corr = checker.compute_correlation(df, df)
        assert corr == 0.0

    def test_zero_std_returns_zero(self, checker):
        n = 20
        dates = pd.date_range("2024-01-01", periods=n, freq="1h")
        df = pd.DataFrame(
            {
                "open": [100.0] * n,
                "high": [101.0] * n,
                "low": [99.0] * n,
                "close": [100.0] * n,
                "volume": [1000.0] * n,
            },
            index=dates,
        )
        corr = checker.compute_correlation(df, df)
        assert corr == 0.0

    def test_negative_correlation(self, checker):
        np.random.seed(42)
        n = 20
        dates = pd.date_range("2024-01-01", periods=n, freq="1h")
        noise = np.random.randn(n)
        a = np.cumsum(noise) + 100
        b = np.cumsum(-noise) + 100
        df_a = pd.DataFrame(
            {
                "open": a - 1,
                "high": a + 2,
                "low": a - 2,
                "close": a,
                "volume": np.full(n, 1000.0),
            },
            index=dates,
        )
        df_b = pd.DataFrame(
            {
                "open": b - 1,
                "high": b + 2,
                "low": b - 2,
                "close": b,
                "volume": np.full(n, 1000.0),
            },
            index=dates,
        )

        corr = checker.compute_correlation(df_a, df_b)
        assert corr < -0.5
