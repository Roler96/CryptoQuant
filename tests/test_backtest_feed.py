"""Tests for cryptoquant.data.backtest_feed module."""

import numpy as np
import pandas as pd
import pytest
from unittest.mock import MagicMock

from cryptoquant.data.backtest_feed import BacktestDataFeed


def _make_df(n=20, start_price=100.0, trend=0.05):
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    close = np.cumsum(np.random.randn(n) * trend + 1) + start_price
    return pd.DataFrame({"open": close - 1, "high": close + 2, "low": close - 2, "close": close, "volume": np.full(n, 1000.0)}, index=dates)


@pytest.fixture
def mock_fetcher():
    return MagicMock()


@pytest.fixture
def mock_store():
    return MagicMock()


@pytest.fixture
def feed(mock_fetcher, mock_store):
    return BacktestDataFeed(
        fetcher=mock_fetcher,
        store=mock_store,
        exchange="okx",
        symbol="BTC/USDT",
        timeframe="1h",
    )


class TestLoad:
    def test_load_delegates_to_store(self, feed, mock_store):
        df = _make_df(10)
        mock_store.load.return_value = df

        result = feed.load(start=1704067200000, end=1704153600000)
        assert len(result) == 10
        mock_store.load.assert_called_once_with("okx", "BTC/USDT", "1h", start=1704067200000, end=1704153600000)


class TestFetchRange:
    def test_fetch_range_calls_fetcher(self, feed, mock_fetcher):
        df = _make_df(10)
        mock_fetcher.fetch_range.return_value = df

        result = feed.fetch_range(start=1704067200000, end=1704153600000)
        assert len(result) == 10
        mock_fetcher.fetch_range.assert_called_once_with("BTC/USDT", "1h", 1704067200000, 1704153600000)

    def test_fetch_range_saves_to_store(self, feed, mock_fetcher, mock_store):
        df = _make_df(10)
        mock_fetcher.fetch_range.return_value = df

        feed.fetch_range(start=1704067200000, end=1704153600000)
        mock_store.save.assert_called_once_with(df, "okx", "BTC/USDT", "1h")
