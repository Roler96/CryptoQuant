"""Tests for cryptoquant.data.fetcher module."""

from unittest.mock import MagicMock, patch

import ccxt
import numpy as np
import pandas as pd
import pytest

from cryptoquant.data.fetcher import OHLCVFetcher, validate_ohlcv
from cryptoquant.exceptions import DataFetchError, DataValidationError


@pytest.fixture
def mock_exchange():
    """Create a mock ccxt exchange."""
    with patch("cryptoquant.data.fetcher.ccxt") as mock_ccxt:
        mock_cls = MagicMock()
        mock_instance = MagicMock()
        mock_cls.return_value = mock_instance
        mock_ccxt.okx = mock_cls
        setattr(mock_ccxt, "okx", mock_cls)
        # Preserve real ccxt exception classes for except clauses
        mock_ccxt.BadSymbol = ccxt.BadSymbol
        mock_ccxt.NetworkError = ccxt.NetworkError
        mock_ccxt.RateLimitExceeded = ccxt.RateLimitExceeded
        mock_ccxt.ExchangeError = ccxt.ExchangeError
        yield mock_instance


@pytest.fixture
def fetcher(mock_exchange):
    """Create fetcher with mocked exchange."""
    return OHLCVFetcher(exchange="okx", testnet=True)


def _make_ohlcv(n=10, start_price=100.0):
    """Generate valid OHLCV data."""
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
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


def _make_raw_ohlcv(n=10, start_price=100.0, base_ts=1704067200000):
    """Generate raw ccxt-format OHLCV data (list of lists)."""
    raw = []
    for i in range(n):
        ts = base_ts + i * 3600000
        close = start_price + i
        raw.append([ts, close - 0.5, close + 1.0, close - 1.0, close, 1000.0])
    return raw


class TestValidateOHLCV:
    def test_valid_data_passes(self):
        df = _make_ohlcv()
        validate_ohlcv(df)

    def test_empty_df_passes(self):
        df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        validate_ohlcv(df)

    def test_missing_columns_raises(self):
        df = pd.DataFrame({"open": [1], "close": [1]})
        with pytest.raises(DataValidationError, match="Missing columns"):
            validate_ohlcv(df)

    def test_high_less_than_low_raises(self):
        df = _make_ohlcv(3)
        df.loc[df.index[0], "high"] = df.loc[df.index[0], "low"] - 1
        with pytest.raises(DataValidationError, match="high < low"):
            validate_ohlcv(df)

    def test_open_outside_range_raises(self):
        df = _make_ohlcv(3)
        df.loc[df.index[0], "open"] = df.loc[df.index[0], "high"] + 10
        with pytest.raises(DataValidationError, match="open outside"):
            validate_ohlcv(df)

    def test_close_outside_range_raises(self):
        df = _make_ohlcv(3)
        df.loc[df.index[0], "close"] = df.loc[df.index[0], "low"] - 10
        with pytest.raises(DataValidationError, match="close outside"):
            validate_ohlcv(df)

    def test_negative_volume_raises(self):
        df = _make_ohlcv(3)
        df.loc[df.index[0], "volume"] = -1.0
        with pytest.raises(DataValidationError, match="Negative volume"):
            validate_ohlcv(df)

    def test_nan_values_raise(self):
        df = _make_ohlcv(3)
        df.loc[df.index[0], "close"] = np.nan
        with pytest.raises(DataValidationError, match="NaN"):
            validate_ohlcv(df)


class TestOHLCVFetcherFetch:
    def test_fetch_returns_dataframe(self, fetcher, mock_exchange):
        raw = _make_raw_ohlcv(10)
        mock_exchange.fetch_ohlcv.return_value = raw

        df = fetcher.fetch("BTC/USDT", "1h", limit=10)
        assert isinstance(df, pd.DataFrame)
        assert len(df) == 10
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]

    def test_fetch_datetime_index(self, fetcher, mock_exchange):
        raw = _make_raw_ohlcv(5)
        mock_exchange.fetch_ohlcv.return_value = raw

        df = fetcher.fetch("BTC/USDT", "1h", limit=5)
        assert isinstance(df.index, pd.DatetimeIndex)

    def test_fetch_sorted_ascending(self, fetcher, mock_exchange):
        raw = _make_raw_ohlcv(10)
        mock_exchange.fetch_ohlcv.return_value = raw

        df = fetcher.fetch("BTC/USDT", "1h", limit=10)
        assert df.index.is_monotonic_increasing

    def test_fetch_empty_result(self, fetcher, mock_exchange):
        mock_exchange.fetch_ohlcv.return_value = []

        df = fetcher.fetch("BTC/USDT", "1h", limit=10)
        assert df.empty
        assert list(df.columns) == ["open", "high", "low", "close", "volume"]

    def test_fetch_invalid_symbol_raises(self, fetcher, mock_exchange):
        mock_exchange.fetch_ohlcv.side_effect = ccxt.BadSymbol("invalid")

        with pytest.raises(DataFetchError, match="Invalid symbol"):
            fetcher.fetch("INVALID/PAIR", "1h")

    def test_fetch_network_error_raises(self, fetcher, mock_exchange):
        mock_exchange.fetch_ohlcv.side_effect = ccxt.NetworkError("timeout")

        with pytest.raises(DataFetchError, match="Network error"):
            fetcher.fetch("BTC/USDT", "1h")

    def test_fetch_dtypes_are_float64(self, fetcher, mock_exchange):
        raw = _make_raw_ohlcv(5)
        mock_exchange.fetch_ohlcv.return_value = raw

        df = fetcher.fetch("BTC/USDT", "1h", limit=5)
        for col in ["open", "high", "low", "close", "volume"]:
            assert df[col].dtype == np.float64


class TestOHLCVFetcherFetchRange:
    def test_fetch_range_concatenates(self, fetcher, mock_exchange):
        raw1 = _make_raw_ohlcv(5, start_price=100)
        raw2 = _make_raw_ohlcv(5, start_price=105, base_ts=1704067200000 + 5 * 3600000)
        mock_exchange.fetch_ohlcv.side_effect = [raw1, raw2, []]

        start = 1704067200000
        end = start + 20 * 3600000

        df = fetcher.fetch_range("BTC/USDT", "1h", start, end)
        assert len(df) == 10

    def test_fetch_range_deduplicates(self, fetcher, mock_exchange):
        raw1 = _make_raw_ohlcv(5, start_price=100)
        raw2 = _make_raw_ohlcv(5, start_price=104)
        mock_exchange.fetch_ohlcv.side_effect = [raw1, raw2, []]

        start = 1704067200000
        end = start + 20 * 3600000

        df = fetcher.fetch_range("BTC/USDT", "1h", start, end)
        assert not df.index.duplicated().any()

    def test_fetch_range_empty(self, fetcher, mock_exchange):
        mock_exchange.fetch_ohlcv.return_value = []

        df = fetcher.fetch_range("BTC/USDT", "1h", 0, 1000)
        assert df.empty
