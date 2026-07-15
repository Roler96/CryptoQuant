"""Tests for cryptoquant.data.live_feed module."""

# pyright: reportAttributeAccessIssue=false, reportArgumentType=false
import numpy as np
import pandas as pd
import pytest
from unittest.mock import MagicMock

from cryptoquant.data.live_feed import LiveDataFeed
from cryptoquant.exceptions import DataFetchError, DataValidationError


def _make_df(n=20, start_price=100.0, trend=0.05):
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    close = np.cumsum(np.random.randn(n) * trend + 1) + start_price
    return pd.DataFrame({"open": close - 1, "high": close + 2, "low": close - 2, "close": close, "volume": np.full(n, 1000.0)}, index=dates)


@pytest.fixture
def mock_fetcher():
    fetcher = MagicMock()
    fetcher.max_candles = 300
    return fetcher


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

        with pytest.raises(DataFetchError, match="returned no OHLCV"):
            feed.fetch(lookback=10)
        assert feed.last_quality_report is None
        mock_store.save.assert_not_called()

    def test_empty_fetch_does_not_fall_back_to_stale_cache(self, feed, mock_fetcher):
        mock_fetcher.fetch.return_value = _make_df(50)
        feed.fetch(lookback=50)
        assert feed.last_quality_report is not None

        mock_fetcher.fetch.return_value = pd.DataFrame(
            columns=["open", "high", "low", "close", "volume"]
        )
        with pytest.raises(DataFetchError, match="returned no OHLCV"):
            feed.fetch(lookback=10)

    def test_fetch_exception_is_not_hidden_by_cache(self, feed, mock_fetcher):
        mock_fetcher.fetch.return_value = _make_df(20)
        feed.fetch(lookback=20)
        previous_fetch_ts = feed.last_fetch_ts
        mock_fetcher.fetch.side_effect = RuntimeError("exchange down")

        with pytest.raises(DataFetchError, match="exchange down"):
            feed.fetch(lookback=20)

        assert feed.last_fetch_ts == previous_fetch_ts

    def test_strict_validation_rejects_gaps(self, feed, mock_fetcher, mock_store):
        dates = pd.DatetimeIndex(
            ["2024-01-01 00:00", "2024-01-01 01:00", "2024-01-01 03:00"]
        )
        df = pd.DataFrame(
            {
                "open": [100.0, 101.0, 103.0],
                "high": [101.0, 102.0, 104.0],
                "low": [99.0, 100.0, 102.0],
                "close": [100.5, 101.5, 103.5],
                "volume": [1000.0, 1000.0, 1000.0],
            },
            index=dates,
        )
        mock_fetcher.fetch.return_value = df

        with pytest.raises(DataValidationError, match="gap"):
            feed.fetch(lookback=3)
        mock_store.save.assert_not_called()

    def test_quality_report_recorded(self, feed, mock_fetcher):
        df = _make_df(50)
        mock_fetcher.fetch.return_value = df

        feed.fetch(lookback=50)

        assert feed.last_quality_report is not None
        assert feed.last_quality_report.is_healthy is True

    def test_fail_on_quality_rejects_unhealthy_data(self, mock_fetcher, mock_store):
        feed = LiveDataFeed(
            fetcher=mock_fetcher,
            store=mock_store,
            exchange="okx",
            symbol="BTC/USDT",
            timeframe="1h",
            fail_on_quality=True,
        )
        df = _make_df(50)
        df.loc[df.index[5:12], ["open", "close"]] = 100.0
        df.loc[df.index[5:12], "high"] = 101.0
        df.loc[df.index[5:12], "low"] = 99.0
        mock_fetcher.fetch.return_value = df

        with pytest.raises(DataValidationError, match="quality"):
            feed.fetch(lookback=50)
        mock_store.save.assert_not_called()


class TestStats:
    def test_stats_returns_dict(self, feed):
        stats = feed.stats()
        assert isinstance(stats, dict)
        assert "last_fetch_ts" in stats
        assert "exchange" in stats
        assert "symbol" in stats
        assert "quality_healthy" in stats
        assert stats["exchange"] == "okx"
        assert stats["symbol"] == "BTC/USDT"
        assert stats["storage_symbol"] == "BTC/USDT"


def test_storage_symbol_can_differ_from_ccxt_symbol(mock_fetcher, mock_store):
    feed = LiveDataFeed(
        fetcher=mock_fetcher,
        store=mock_store,
        exchange="okx",
        symbol="DOGE/USDT:USDT",
        storage_symbol="DOGE-USDT-SWAP",
        timeframe="1h",
    )
    frame = _make_df(10)
    mock_fetcher.fetch.return_value = frame

    feed.fetch(lookback=10)

    mock_fetcher.fetch.assert_called_once_with("DOGE/USDT:USDT", "1h", limit=10)
    mock_store.save.assert_called_once_with(
        frame, "okx", "DOGE-USDT-SWAP", "1h"
    )


def test_long_lookback_uses_stored_window_then_one_recent_fetch(
    mock_fetcher, mock_store
):
    feed = LiveDataFeed(
        fetcher=mock_fetcher,
        store=mock_store,
        exchange="okx",
        symbol="DOGE/USDT:USDT",
        storage_symbol="DOGE-USDT-SWAP",
        timeframe="1h",
    )
    stored = _make_df(2300)
    recent = stored.iloc[-300:].copy()
    mock_store.load.return_value = stored
    mock_fetcher.fetch.return_value = recent

    result = feed.fetch(lookback=2200)

    assert len(result) == 2200
    mock_fetcher.fetch.assert_called_once_with(
        "DOGE/USDT:USDT", "1h", limit=300
    )
    mock_fetcher.fetch_range.assert_not_called()
    mock_store.load.assert_called_once()
