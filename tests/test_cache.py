"""Tests for cryptoquant.data.cache module."""

import time

import numpy as np
import pandas as pd
import pytest
from unittest.mock import MagicMock

from cryptoquant.data.cache import CacheKey, DataCache, _lookback_to_start
from cryptoquant.data.store import OHLCVStore


@pytest.fixture
def mock_fetcher():
    """Mock OHLCVFetcher."""
    return MagicMock()


@pytest.fixture
def store():
    """In-memory store."""
    s = OHLCVStore(db_path=":memory:")
    _ = s.conn
    yield s
    s.close()


@pytest.fixture
def cache(store, mock_fetcher):
    """DataCache with mock fetcher and in-memory store."""
    return DataCache(store=store, fetcher=mock_fetcher, max_size=3, ttl=300)


def _make_df(n=10, start_price=100.0, freq="1h"):
    """Generate valid OHLCV DataFrame."""
    dates = pd.date_range("2024-01-01", periods=n, freq=freq)
    close = np.linspace(start_price, start_price + n, n)
    return pd.DataFrame(
        {
            "open": close - 0.5,
            "high": close + 1.0,
            "low": close - 1.0,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=dates,
    )


class TestL1Cache:
    def test_l1_hit_returns_cached(self, cache, mock_fetcher):
        df = _make_df(10)
        key = CacheKey("okx", "BTC/USDT", "1h")
        cache._set_l1(key, df)

        result = cache.get_ohlcv("okx", "BTC/USDT", "1h")
        assert len(result) == 10
        mock_fetcher.fetch.assert_not_called()

    def test_l1_ttl_expiry(self, cache, mock_fetcher):
        cache._ttl = 0
        df = _make_df(10)
        key = CacheKey("okx", "BTC/USDT", "1h")
        cache._set_l1(key, df)

        mock_fetcher.fetch.return_value = _make_df(5)
        cache.get_ohlcv("okx", "BTC/USDT", "1h")
        mock_fetcher.fetch.assert_called_once()

    def test_l1_lru_eviction(self, cache):
        for i in range(5):
            df = _make_df(5, start_price=100 + i * 10)
            cache._set_l1(CacheKey("okx", f"SYM{i}/USDT", "1h"), df)

        assert len(cache._l1) == 3
        assert CacheKey("okx", "SYM0/USDT", "1h") not in cache._l1
        assert CacheKey("okx", "SYM1/USDT", "1h") not in cache._l1
        assert CacheKey("okx", "SYM4/USDT", "1h") in cache._l1

    def test_l1_returns_copy(self, cache):
        df = _make_df(10)
        key = CacheKey("okx", "BTC/USDT", "1h")
        cache._set_l1(key, df)

        result1 = cache._get_l1(key)
        result2 = cache._get_l1(key)
        assert result1 is not result2


class TestL2Cache:
    def test_l2_hit_no_fetch(self, cache, store, mock_fetcher):
        df = _make_df(100)
        store.save(df, "okx", "BTC/USDT", "1h")

        result = cache.get_ohlcv("okx", "BTC/USDT", "1h", lookback=50)
        assert len(result) > 0
        mock_fetcher.fetch.assert_not_called()

    def test_l2_miss_falls_to_l3(self, cache, mock_fetcher):
        mock_fetcher.fetch.return_value = _make_df(10)

        cache.get_ohlcv("okx", "BTC/USDT", "1h", lookback=10)
        mock_fetcher.fetch.assert_called_once()

    def test_l2_populates_l1(self, cache, store, mock_fetcher):
        df = _make_df(100)
        store.save(df, "okx", "BTC/USDT", "1h")

        cache.get_ohlcv("okx", "BTC/USDT", "1h", lookback=50)
        key = CacheKey("okx", "BTC/USDT", "1h")
        assert key in cache._l1


class TestL3Fetch:
    def test_l3_fetch_and_save(self, cache, store, mock_fetcher):
        df = _make_df(10)
        mock_fetcher.fetch.return_value = df

        result = cache.get_ohlcv("okx", "BTC/USDT", "1h", lookback=10)
        assert len(result) == 10

        stored = store.load("okx", "BTC/USDT", "1h")
        assert len(stored) == 10

        key = CacheKey("okx", "BTC/USDT", "1h")
        assert key in cache._l1

    def test_l3_failure_returns_empty(self, cache, mock_fetcher):
        mock_fetcher.fetch.side_effect = ConnectionError("network down")

        result = cache.get_ohlcv("okx", "BTC/USDT", "1h", lookback=10)
        assert result.empty


class TestInvalidate:
    def test_invalidate_removes_l1(self, cache):
        df = _make_df(10)
        key = CacheKey("okx", "BTC/USDT", "1h")
        cache._set_l1(key, df)
        assert key in cache._l1

        cache.invalidate("okx", "BTC/USDT", "1h")
        assert key not in cache._l1


class TestStats:
    def test_stats_structure(self, cache):
        stats = cache.stats()
        assert "l1_entries" in stats
        assert "l1_max_size" in stats
        assert "db_tables" in stats


class TestLookbackToStart:
    def test_calculates_correctly(self):
        now_ms = int(time.time() * 1000)
        start = _lookback_to_start("1h", 24)
        expected = now_ms - 24 * 3_600_000
        assert abs(start - expected) < 1000
