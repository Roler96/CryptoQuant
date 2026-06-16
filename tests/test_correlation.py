"""Tests for CorrelationCheck."""
import numpy as np
import pandas as pd
import pytest
from unittest.mock import MagicMock

from cryptoquant.risk.correlation import CorrelationCheck


@pytest.fixture
def mock_cache():
    cache = MagicMock()
    return cache


@pytest.fixture
def checker(mock_cache):
    return CorrelationCheck(
        cache=mock_cache,
        threshold=0.7,
        lookback=100,
        exchange="okx",
        timeframe="1h",
    )


def _make_df(n, start_price, corr_with=None):
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    noise = np.random.normal(0, 1, n)
    if corr_with is not None:
        close = start_price + np.cumsum(corr_with * 0.5 + noise * 0.5)
    else:
        close = start_price + np.cumsum(noise)
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


class TestShouldEnter:
    def test_no_existing_positions_allowed(self, checker):
        allowed, reason = checker.should_enter("BTC/USDT", [])
        assert allowed
        assert "no existing" in reason

    def test_high_correlation_blocked(self, checker, mock_cache):
        n = 100
        df_a = _make_df(n, 100)
        df_b = df_a.copy()
        mock_cache.get_ohlcv.side_effect = lambda exchange, symbol, tf, lookback: (
            df_a if symbol == "BTC/USDT" else df_b
        )

        allowed, reason = checker.should_enter("BTC/USDT", ["ETH/USDT"])
        assert not allowed
        assert "correlation" in reason

    def test_low_correlation_allowed(self, checker, mock_cache):
        n = 100
        np.random.seed(42)
        df_a = _make_df(n, 100)
        df_b = _make_df(n, 200)
        mock_cache.get_ohlcv.side_effect = lambda exchange, symbol, tf, lookback: (
            df_a if symbol == "BTC/USDT" else df_b
        )

        allowed, reason = checker.should_enter("BTC/USDT", ["ETH/USDT"])
        assert allowed
        assert "passed" in reason

    def test_multiple_existing_symbols(self, checker, mock_cache):
        n = 100
        df_a = _make_df(n, 100)
        df_b = df_a.copy()
        df_c = _make_df(n, 200)

        def side_effect(exchange, symbol, tf, lookback):
            if symbol == "BTC/USDT":
                return df_a
            if symbol == "ETH/USDT":
                return df_b
            return df_c

        mock_cache.get_ohlcv.side_effect = side_effect

        allowed, reason = checker.should_enter("BTC/USDT", ["ETH/USDT", "SOL/USDT"])
        assert not allowed
        assert "ETH/USDT" in reason


class TestComputeCorrelation:
    def test_perfect_correlation(self, checker, mock_cache):
        n = 100
        df = _make_df(n, 100)
        mock_cache.get_ohlcv.return_value = df

        corr = checker.compute_correlation("BTC/USDT", "ETH/USDT")
        assert corr == pytest.approx(1.0, abs=1e-6)

    def test_insufficient_data_returns_zero(self, checker, mock_cache):
        mock_cache.get_ohlcv.return_value = pd.DataFrame(
            columns=["open", "high", "low", "close", "volume"]
        )

        corr = checker.compute_correlation("BTC/USDT", "ETH/USDT")
        assert corr == 0.0

    def test_short_data_returns_zero(self, checker, mock_cache):
        dates = pd.date_range("2024-01-01", periods=5, freq="1h")
        df = pd.DataFrame(
            {
                "open": [100] * 5,
                "high": [101] * 5,
                "low": [99] * 5,
                "close": [100] * 5,
                "volume": [1000] * 5,
            },
            index=dates,
        )
        mock_cache.get_ohlcv.return_value = df

        corr = checker.compute_correlation("BTC/USDT", "ETH/USDT")
        assert corr == 0.0

    def test_zero_std_returns_zero(self, checker, mock_cache):
        n = 100
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
        mock_cache.get_ohlcv.return_value = df

        corr = checker.compute_correlation("BTC/USDT", "ETH/USDT")
        assert corr == 0.0

    def test_negative_correlation(self, checker, mock_cache):
        n = 100
        np.random.seed(42)
        dates = pd.date_range("2024-01-01", periods=n, freq="1h")
        noise = np.random.normal(0, 1, n)
        a = 100 + np.cumsum(noise)
        b = 100 + np.cumsum(-noise)
        df_a = pd.DataFrame(
            {
                "open": a - 0.1,
                "high": a + 0.5,
                "low": a - 0.5,
                "close": a,
                "volume": np.full(n, 1000.0),
            },
            index=dates,
        )
        df_b = pd.DataFrame(
            {
                "open": b - 0.1,
                "high": b + 0.5,
                "low": b - 0.5,
                "close": b,
                "volume": np.full(n, 1000.0),
            },
            index=dates,
        )

        def side_effect(exchange, symbol, tf, lookback):
            return df_a if symbol == "BTC/USDT" else df_b

        mock_cache.get_ohlcv.side_effect = side_effect

        corr = checker.compute_correlation("BTC/USDT", "ETH/USDT")
        assert corr < -0.5
