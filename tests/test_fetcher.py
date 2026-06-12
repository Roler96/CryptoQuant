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

    def test_fetch_range_error_includes_chunk_count(self, mock_exchange):
        """fetch_range error message should include number of successful chunks."""
        fetcher = OHLCVFetcher(exchange="okx", testnet=True, max_candles=5)
        raw1 = _make_raw_ohlcv(5, start_price=100)
        raw2 = _make_raw_ohlcv(5, start_price=105, base_ts=1704067200000 + 5 * 3600000)
        # First two chunks succeed, third fails
        mock_exchange.fetch_ohlcv.side_effect = [
            raw1,
            raw2,
            ccxt.NetworkError("timeout"),
            ccxt.NetworkError("timeout"),
            ccxt.NetworkError("timeout"),
            ccxt.NetworkError("timeout"),
        ]

        start = 1704067200000
        end = start + 30 * 3600000

        with pytest.raises(DataFetchError, match="2 successful chunk"):
            fetcher.fetch_range("BTC/USDT", "1h", start, end)


class TestOHLCVFetcherConfig:
    def test_max_candles_parameter(self, mock_exchange):
        """max_candles should be stored on the fetcher."""
        fetcher = OHLCVFetcher(exchange="okx", testnet=True, max_candles=500)
        assert fetcher.max_candles == 500

    def test_max_candles_minimum_is_one(self, mock_exchange):
        """max_candles should be at least 1."""
        fetcher = OHLCVFetcher(exchange="okx", testnet=True, max_candles=0)
        assert fetcher.max_candles == 1

    def test_timeout_parameter(self, mock_exchange):
        """timeout should be passed to ccxt exchange."""
        fetcher = OHLCVFetcher(exchange="okx", testnet=True, timeout=60_000)
        assert fetcher.timeout == 60_000

    def test_limit_clamped_to_max_candles(self, fetcher, mock_exchange):
        """limit should be clamped to [1, max_candles]."""
        fetcher.max_candles = 100
        raw = _make_raw_ohlcv(5)
        mock_exchange.fetch_ohlcv.return_value = raw

        # Request more than max_candles
        fetcher.fetch("BTC/USDT", "1h", limit=500)

        # Should have been clamped to max_candles
        call_args = mock_exchange.fetch_ohlcv.call_args
        assert call_args.kwargs["limit"] == 100

    def test_limit_clamped_to_minimum_one(self, fetcher, mock_exchange):
        """limit should be at least 1."""
        raw = _make_raw_ohlcv(5)
        mock_exchange.fetch_ohlcv.return_value = raw

        # Request 0 candles
        fetcher.fetch("BTC/USDT", "1h", limit=0)

        # Should have been clamped to 1
        call_args = mock_exchange.fetch_ohlcv.call_args
        assert call_args.kwargs["limit"] == 1


class TestAvailableTimeframes:
    def test_available_timeframes_returns_list(self, mock_exchange):
        """available_timeframes should return list of supported timeframes."""
        mock_exchange.timeframes = {"1m": 60, "5m": 300, "1h": 3600, "1d": 86400}
        fetcher = OHLCVFetcher(exchange="okx", testnet=True)

        result = fetcher.available_timeframes()
        assert isinstance(result, list)
        assert "1h" in result
        assert "1d" in result

    def test_available_timeframes_empty_when_none(self, mock_exchange):
        """available_timeframes should return empty list if exchange has none."""
        mock_exchange.timeframes = None
        fetcher = OHLCVFetcher(exchange="okx", testnet=True)

        result = fetcher.available_timeframes()
        assert result == []


class TestGapDetection:
    def test_gap_detection_warns(self):
        """validate_ohlcv should warn on timestamp gaps."""
        import io
        from loguru import logger

        output = io.StringIO()
        handler_id = logger.add(output, level="WARNING")

        try:
            dates = pd.DatetimeIndex(
                [
                    "2024-01-01 00:00",
                    "2024-01-01 01:00",
                    "2024-01-01 03:00",
                    "2024-01-01 04:00",
                ]
            )
            df = pd.DataFrame(
                {
                    "open": [100, 101, 103, 104],
                    "high": [101, 102, 104, 105],
                    "low": [99, 100, 102, 103],
                    "close": [101, 102, 104, 105],
                    "volume": [1000, 1000, 1000, 1000],
                },
                index=dates,
            )
            validate_ohlcv(df)

            log_content = output.getvalue()
            assert "gap" in log_content.lower()
        finally:
            logger.remove(handler_id)

    def test_no_gap_no_warning(self):
        """validate_ohlcv should not warn on continuous data."""
        import io
        from loguru import logger

        output = io.StringIO()
        handler_id = logger.add(output, level="WARNING")

        try:
            df = _make_ohlcv(10)
            validate_ohlcv(df)

            log_content = output.getvalue()
            assert "gap" not in log_content.lower()
        finally:
            logger.remove(handler_id)
