"""Tests for cryptoquant.data.live_feed module."""

import numpy as np
import pandas as pd
import pytest
from unittest.mock import MagicMock

from cryptoquant.data.live_feed import LiveDataFeed


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
    return LiveDataFeed(
        fetcher=mock_fetcher,
        store=mock_store,
        exchange="okx",
        symbol="BTC/USDT",
        timeframe="1h",
    )


class TestFetch:
    def test_fetch_calls_fetcher(self, feed, mock_fetcher):
        df = _make_df(10)
        mock_fetcher.fetch.return_value = df

        result = feed.fetch(lookback=10)
        assert len(result) == 10
        mock_fetcher.fetch.assert_called_once_with("BTC/USDT", "1h", limit=10)

    def test_fetch_saves_to_store(self, feed, mock_fetcher, mock_store):
        df = _make_df(10)
        mock_fetcher.fetch.return_value = df

        feed.fetch(lookback=10)
        mock_store.save.assert_called_once_with(df, "okx", "BTC/USDT", "1h")

    def test_last_fetch_ts_updated(self, feed, mock_fetcher):
        df = _make_df(10)
        mock_fetcher.fetch.return_value = df

        assert feed.last_fetch_ts == 0
        feed.fetch(lookback=10)
        assert feed.last_fetch_ts > 0

    def test_empty_fetch(self, feed, mock_fetcher, mock_store):
        empty_df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        mock_fetcher.fetch.return_value = empty_df

        result = feed.fetch(lookback=10)
        assert result.empty
        mock_store.save.assert_not_called()


class TestStats:
    def test_stats_returns_dict(self, feed):
        stats = feed.stats()
        assert isinstance(stats, dict)
        assert "last_fetch_ts" in stats
        assert "exchange" in stats
        assert "symbol" in stats
        assert stats["exchange"] == "okx"
        assert stats["symbol"] == "BTC/USDT"
