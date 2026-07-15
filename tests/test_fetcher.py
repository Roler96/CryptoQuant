"""Tests for cryptoquant.data.fetcher module."""

import math
from unittest.mock import MagicMock, patch

import ccxt
import numpy as np
import pandas as pd
import pytest

from cryptoquant.data.fetcher import (
    _LEADING_GAP_SKIP_MS,
    OHLCVFetcher,
    validate_ohlcv,
)
from cryptoquant.exceptions import DataFetchError, DataValidationError


@pytest.fixture
def mock_exchange():
    """Create a mock ccxt exchange."""
    with patch("cryptoquant.data.fetcher.ccxt") as mock_ccxt:
# pyright: reportAttributeAccessIssue=false, reportArgumentType=false
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
        # Real timeframe parsing: a MagicMock would make int() return 1 and
        # silently produce a nonsense probe stride.
        mock_instance.parse_timeframe.side_effect = ccxt.Exchange.parse_timeframe
        yield mock_instance


@pytest.fixture
def fetcher(mock_exchange):
    """Create fetcher with mocked exchange. retry_base_delay=0 keeps retries instant."""
    return OHLCVFetcher(exchange="okx", testnet=True, retry_base_delay=0)


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
    def test_market_type_is_passed_to_ccxt(self, mock_exchange):
        fetcher = OHLCVFetcher(exchange="okx", testnet=True, market_type="swap")

        assert fetcher.market_type == "swap"

    def test_invalid_market_type_fails(self, mock_exchange):
        with pytest.raises(ValueError, match="Unsupported market_type"):
            OHLCVFetcher(exchange="okx", testnet=True, market_type="margin")

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
        fetcher = OHLCVFetcher(
            exchange="okx", testnet=True, max_candles=5, retry_base_delay=0
        )
        raw1 = _make_raw_ohlcv(5, start_price=100)
        raw2 = _make_raw_ohlcv(5, start_price=105, base_ts=1704067200000 + 5 * 3600000)
        # Third chunk fails; its 4 entries are the initial attempt + 3 retries.
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


class TestRetry:
    """fetch() converts ccxt errors into DataFetchError, which retry_on_network
    does not recognize. Retries must therefore happen below that conversion."""

    def test_network_error_is_retried(self, fetcher, mock_exchange):
        mock_exchange.fetch_ohlcv.side_effect = ccxt.NetworkError("timeout")

        with pytest.raises(DataFetchError, match="Network error"):
            fetcher.fetch("BTC/USDT", "1h")

        # 1 initial attempt + 3 retries
        assert mock_exchange.fetch_ohlcv.call_count == 4

    def test_retry_recovers_and_returns_data(self, fetcher, mock_exchange):
        mock_exchange.fetch_ohlcv.side_effect = [
            ccxt.NetworkError("timeout"),
            ccxt.NetworkError("timeout"),
            _make_raw_ohlcv(5),
        ]

        df = fetcher.fetch("BTC/USDT", "1h", limit=5)
        assert len(df) == 5
        assert mock_exchange.fetch_ohlcv.call_count == 3

    def test_rate_limit_is_retried(self, fetcher, mock_exchange):
        """RateLimitExceeded subclasses NetworkError, so it backs off too."""
        mock_exchange.fetch_ohlcv.side_effect = ccxt.RateLimitExceeded("slow down")

        with pytest.raises(DataFetchError, match="Rate limit"):
            fetcher.fetch("BTC/USDT", "1h")

        assert mock_exchange.fetch_ohlcv.call_count == 4

    def test_bad_symbol_is_not_retried(self, fetcher, mock_exchange):
        """Permanent failures must fail fast rather than burn the backoff budget."""
        mock_exchange.fetch_ohlcv.side_effect = ccxt.BadSymbol("nope")

        with pytest.raises(DataFetchError, match="Invalid symbol"):
            fetcher.fetch("INVALID/PAIR", "1h")

        assert mock_exchange.fetch_ohlcv.call_count == 1

    def test_exchange_error_is_not_retried(self, fetcher, mock_exchange):
        mock_exchange.fetch_ohlcv.side_effect = ccxt.ExchangeError("boom")

        with pytest.raises(DataFetchError, match="Exchange error"):
            fetcher.fetch("BTC/USDT", "1h")

        assert mock_exchange.fetch_ohlcv.call_count == 1

    def test_max_retries_is_configurable(self, mock_exchange):
        fetcher = OHLCVFetcher(
            exchange="okx", testnet=True, max_retries=1, retry_base_delay=0
        )
        mock_exchange.fetch_ohlcv.side_effect = ccxt.NetworkError("timeout")

        with pytest.raises(DataFetchError):
            fetcher.fetch("BTC/USDT", "1h")

        assert mock_exchange.fetch_ohlcv.call_count == 2


class TestFetchRangeCursor:
    def test_stalled_cursor_terminates(self, fetcher, mock_exchange):
        """An exchange that ignores `since` must not spin the loop forever.

        Advancing to last_candle_ts + 1 makes no progress when the same window
        keeps coming back, so the loop needs an explicit stall guard.
        """
        base = 1704067200000
        calls = {"n": 0}

        def ignores_since(*args, **kwargs):
            # Same three candles regardless of `since`. Fail loudly rather than
            # hang the suite if the stall guard ever regresses.
            calls["n"] += 1
            if calls["n"] > 10:
                raise AssertionError("fetch_range did not terminate on a stalled cursor")
            return _make_raw_ohlcv(3, base_ts=base)

        mock_exchange.fetch_ohlcv.side_effect = ignores_since

        df = fetcher.fetch_range("BTC/USDT", "1h", base, base + 30 * 86400000)

        assert calls["n"] <= 3
        assert len(df) == 3

    def test_normal_cursor_advances_through_chunks(self, fetcher, mock_exchange):
        base = 1704067200000
        mock_exchange.fetch_ohlcv.side_effect = [
            _make_raw_ohlcv(5, base_ts=base),
            _make_raw_ohlcv(5, base_ts=base + 5 * 3600000),
            [],
        ]

        df = fetcher.fetch_range("BTC/USDT", "1h", base, base + 20 * 3600000)
        assert len(df) == 10


class TestFetchRangeLeadingGap:
    def test_skips_leading_gap_before_listing(self, fetcher, mock_exchange):
        """A range starting before the symbol listed must not return empty.

        The exchange answers empty until the listing date; fetch_range should
        probe forward and still return the data that does exist.
        """
        base = 1704067200000
        listed_at = base + 60 * 86400000
        mock_exchange.fetch_ohlcv.side_effect = [
            [],  # nothing at base
            [],  # nothing 30d later
            _make_raw_ohlcv(5, base_ts=listed_at),
            [],
        ]

        df = fetcher.fetch_range("BTC/USDT", "1h", base, base + 200 * 86400000)
        assert len(df) == 5

    def test_all_empty_returns_empty_and_terminates(self, fetcher, mock_exchange):
        """Probing forward is bounded by `end` rather than looping forever."""
        mock_exchange.fetch_ohlcv.return_value = []
        base = 1704067200000
        span_ms = 90 * 86400000

        df = fetcher.fetch_range("BTC/USDT", "1h", base, base + span_ms)

        assert df.empty
        stride_ms = 300 * 3600 * 1000  # max_candles x 1h
        assert mock_exchange.fetch_ohlcv.call_count == math.ceil(span_ms / stride_ms)

    def test_probe_stride_matches_request_window(self, fetcher):
        """The stride must never exceed what one request actually covers,
        or a probe jumps over bars nobody looked at."""
        assert fetcher._probe_stride_ms("1m", 300) == 300 * 60 * 1000  # 5h
        assert fetcher._probe_stride_ms("4h", 300) == 300 * 4 * 3600 * 1000  # 50d

    def test_probe_stride_falls_back_on_unknown_timeframe(self, fetcher, mock_exchange):
        mock_exchange.parse_timeframe.side_effect = ccxt.NotSupported("unknown")

        assert fetcher._probe_stride_ms("7x", 300) == _LEADING_GAP_SKIP_MS

    def test_trailing_empty_keeps_earlier_chunks(self, fetcher, mock_exchange):
        """An empty chunk after real data means caught-up, not 'skip ahead'."""
        base = 1704067200000
        mock_exchange.fetch_ohlcv.side_effect = [
            _make_raw_ohlcv(5, base_ts=base),
            [],
        ]

        df = fetcher.fetch_range("BTC/USDT", "1h", base, base + 200 * 86400000)
        assert len(df) == 5
        assert mock_exchange.fetch_ohlcv.call_count == 2


class TestTimeframeValidation:
    def test_unsupported_timeframe_raises(self, mock_exchange):
        mock_exchange.timeframes = {"1m": 60, "1h": 3600}
        fetcher = OHLCVFetcher(exchange="okx", testnet=True, retry_base_delay=0)

        with pytest.raises(DataFetchError, match="not supported"):
            fetcher.fetch("BTC/USDT", "7h")

        mock_exchange.fetch_ohlcv.assert_not_called()

    def test_supported_timeframe_passes(self, mock_exchange):
        mock_exchange.timeframes = {"1m": 60, "1h": 3600}
        mock_exchange.fetch_ohlcv.return_value = _make_raw_ohlcv(5)
        fetcher = OHLCVFetcher(exchange="okx", testnet=True, retry_base_delay=0)

        df = fetcher.fetch("BTC/USDT", "1h", limit=5)
        assert len(df) == 5

    def test_no_validation_when_exchange_reports_none(self, mock_exchange):
        """Exchanges that don't advertise timeframes shouldn't be second-guessed."""
        mock_exchange.timeframes = None
        mock_exchange.fetch_ohlcv.return_value = _make_raw_ohlcv(5)
        fetcher = OHLCVFetcher(exchange="okx", testnet=True, retry_base_delay=0)

        df = fetcher.fetch("BTC/USDT", "anything", limit=5)
        assert len(df) == 5


class TestStrictPassthrough:
    def test_fetch_strict_raises_on_gap(self, fetcher, mock_exchange):
        base = 1704067200000
        raw = _make_raw_ohlcv(3, base_ts=base)
        raw[2][0] = base + 5 * 3600000  # jump: 1h, 1h, then 4h
        mock_exchange.fetch_ohlcv.return_value = raw

        with pytest.raises(DataValidationError, match="gap"):
            fetcher.fetch("BTC/USDT", "1h", limit=3, strict=True)

    def test_fetch_default_tolerates_gap(self, fetcher, mock_exchange):
        base = 1704067200000
        raw = _make_raw_ohlcv(3, base_ts=base)
        raw[2][0] = base + 5 * 3600000
        mock_exchange.fetch_ohlcv.return_value = raw

        df = fetcher.fetch("BTC/USDT", "1h", limit=3)
        assert len(df) == 3

    def test_fetch_range_strict_raises_on_cross_chunk_gap(self, fetcher, mock_exchange):
        """A gap straddling two chunks is invisible per-chunk, so fetch_range
        validates the assembled series."""
        base = 1704067200000
        mock_exchange.fetch_ohlcv.side_effect = [
            _make_raw_ohlcv(3, base_ts=base),
            _make_raw_ohlcv(3, base_ts=base + 20 * 3600000),  # 17h hole
            [],
        ]

        with pytest.raises(DataValidationError, match="gap"):
            fetcher.fetch_range(
                "BTC/USDT", "1h", base, base + 30 * 3600000, strict=True
            )


class TestOHLCVFetcherConfig:
    def test_max_candles_parameter(self, mock_exchange):
        """max_candles should be stored on the fetcher."""
        fetcher = OHLCVFetcher(exchange="okx", testnet=True, max_candles=500)
        assert fetcher.max_candles == 500

    def test_max_candles_minimum_is_one(self, mock_exchange):
        """max_candles should be at least 1."""
        fetcher = OHLCVFetcher(exchange="okx", testnet=True, max_candles=0)
        assert fetcher.max_candles == 1

    def test_timeout_parameter(self):
        """timeout should be passed through to the ccxt exchange config.

        Uses the real ccxt exchange (not the mocked fixture) since ccxt's
        own Exchange base class is what actually stores `.timeout` from
        the config dict — mocking it would only tell us the config dict
        was built, not that ccxt understood it.
        """
        fetcher = OHLCVFetcher(exchange="okx", testnet=True, timeout=60_000)
        assert fetcher.exchange.timeout == 60_000

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


class TestStrictMode:
    def test_strict_false_warns(self):
        """strict=False should warn on gaps without raising."""
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
                ]
            )
            df = pd.DataFrame(
                {
                    "open": [100, 101, 103],
                    "high": [101, 102, 104],
                    "low": [99, 100, 102],
                    "close": [101, 102, 104],
                    "volume": [1000, 1000, 1000],
                },
                index=dates,
            )
            validate_ohlcv(df, strict=False)

            log_content = output.getvalue()
            assert "gap" in log_content.lower()
        finally:
            logger.remove(handler_id)

    def test_strict_true_raises_on_gap(self):
        """strict=True should raise DataValidationError on gaps."""
        dates = pd.DatetimeIndex(
            [
                "2024-01-01 00:00",
                "2024-01-01 01:00",
                "2024-01-01 03:00",
            ]
        )
        df = pd.DataFrame(
            {
                "open": [100, 101, 103],
                "high": [101, 102, 104],
                "low": [99, 100, 102],
                "close": [101, 102, 104],
                "volume": [1000, 1000, 1000],
            },
            index=dates,
        )
        with pytest.raises(DataValidationError, match="gap"):
            validate_ohlcv(df, strict=True)

    def test_strict_true_no_gap_passes(self):
        """strict=True should not raise on continuous data."""
        df = _make_ohlcv(10)
        validate_ohlcv(df, strict=True)

    def test_strict_true_empty_passes(self):
        """strict=True should not raise on empty DataFrame."""
        df = pd.DataFrame(columns=["open", "high", "low", "close", "volume"])
        validate_ohlcv(df, strict=True)
