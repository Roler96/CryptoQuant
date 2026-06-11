"""Tests for cryptoquant.data.store module."""
import pytest
import pandas as pd
import numpy as np

from cryptoquant.data.store import OHLCVStore, _table_name
from cryptoquant.exceptions import DataValidationError


@pytest.fixture
def store():
    """In-memory store for testing."""
    s = OHLCVStore(db_path=":memory:")
    _ = s.conn
    yield s
    s.close()


def _make_df(n=10, start_price=100.0):
    """Generate valid OHLCV DataFrame."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    close = np.linspace(start_price, start_price + n, n)
    return pd.DataFrame({
        "open": close - 0.5,
        "high": close + 1.0,
        "low": close - 1.0,
        "close": close,
        "volume": np.full(n, 1000.0),
    }, index=dates)


class TestTableName:
    def test_basic(self):
        assert _table_name("okx", "BTC/USDT", "1h") == "ohlcv_okx_BTC_USDT_1h"

    def test_dash_symbol(self):
        assert _table_name("binance", "ETH-USDT", "4h") == "ohlcv_binance_ETH_USDT_4h"

    def test_invalid_name_raises(self):
        with pytest.raises(DataValidationError, match="Invalid table name"):
            _table_name("okx", "BTC/USDT; DROP TABLE", "1h")


class TestSave:
    def test_save_and_count(self, store):
        df = _make_df(10)
        count = store.save(df, "okx", "BTC/USDT", "1h")
        assert count == 10

    def test_save_empty_df(self, store):
        df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        count = store.save(df, "okx", "BTC/USDT", "1h")
        assert count == 0

    def test_save_upsert_overwrites(self, store):
        df1 = _make_df(5, start_price=100)
        store.save(df1, "okx", "BTC/USDT", "1h")

        df2 = _make_df(5, start_price=200)
        store.save(df2, "okx", "BTC/USDT", "1h")

        loaded = store.load("okx", "BTC/USDT", "1h")
        assert len(loaded) == 5
        assert loaded["close"].iloc[0] == pytest.approx(200.0, abs=1)


class TestLoad:
    def test_load_roundtrip(self, store):
        df = _make_df(10)
        store.save(df, "okx", "BTC/USDT", "1h")

        loaded = store.load("okx", "BTC/USDT", "1h")
        assert len(loaded) == 10
        assert list(loaded.columns) == ["open", "high", "low", "close", "volume"]
        pd.testing.assert_frame_equal(
            df, loaded, check_exact=False, atol=1e-6,
            check_index_type=False, check_names=False, check_freq=False
        )

    def test_load_empty_table(self, store):
        loaded = store.load("okx", "BTC/USDT", "1h")
        assert loaded.empty

    def test_load_range_filter(self, store):
        df = _make_df(20)
        store.save(df, "okx", "BTC/USDT", "1h")

        ts_start = int(df.index[5].timestamp() * 1000)
        ts_end = int(df.index[14].timestamp() * 1000)

        loaded = store.load("okx", "BTC/USDT", "1h", start=ts_start, end=ts_end)
        assert len(loaded) == 10


class TestGetLatest:
    def test_get_latest_empty(self, store):
        assert store.get_latest("okx", "BTC/USDT", "1h") is None

    def test_get_latest_after_save(self, store):
        df = _make_df(10)
        store.save(df, "okx", "BTC/USDT", "1h")

        latest = store.get_latest("okx", "BTC/USDT", "1h")
        expected = int(df.index[-1].timestamp() * 1000)
        assert latest == expected


class TestGetRange:
    def test_get_range_empty(self, store):
        assert store.get_range("okx", "BTC/USDT", "1h") is None

    def test_get_range_after_save(self, store):
        df = _make_df(10)
        store.save(df, "okx", "BTC/USDT", "1h")

        range_ = store.get_range("okx", "BTC/USDT", "1h")
        assert range_ is not None
        assert range_[0] == int(df.index[0].timestamp() * 1000)
        assert range_[1] == int(df.index[-1].timestamp() * 1000)


class TestDelete:
    def test_delete_existing(self, store):
        df = _make_df(10)
        store.save(df, "okx", "BTC/USDT", "1h")
        count = store.delete("okx", "BTC/USDT", "1h")
        assert count == 10
        assert store.load("okx", "BTC/USDT", "1h").empty

    def test_delete_nonexistent(self, store):
        count = store.delete("okx", "BTC/USDT", "1h")
        assert count == 0


class TestListTables:
    def test_list_empty(self, store):
        assert store.list_tables() == []

    def test_list_after_save(self, store):
        df = _make_df(5)
        store.save(df, "okx", "BTC/USDT", "1h")
        store.save(df, "okx", "ETH/USDT", "4h")

        tables = store.list_tables()
        assert len(tables) == 2
        assert "ohlcv_okx_BTC_USDT_1h" in tables
        assert "ohlcv_okx_ETH_USDT_4h" in tables
