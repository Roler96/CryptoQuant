"""Tests for cryptoquant.utils module."""
import time

import ccxt
import pandas as pd
import pytest

from cryptoquant.exceptions import DataValidationError
from cryptoquant.utils import (
    REQUIRED_OHLCV_COLUMNS,
    get_proxy_from_env,
    missing_ohlcv_columns,
    retry_on_network,
    safe_filename,
    timeframe_to_timedelta,
)

_PROXY_ENV_VARS = ("HTTPS_PROXY", "https_proxy", "HTTP_PROXY", "http_proxy")


@pytest.fixture
def clean_proxy_env(monkeypatch):
    """Ensure no proxy env vars leak in from the test environment."""
    for var in _PROXY_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


class TestGetProxyFromEnv:
    def test_no_env_vars_returns_none(self, clean_proxy_env):
        assert get_proxy_from_env() is None

    def test_reads_https_proxy(self, clean_proxy_env, monkeypatch):
        monkeypatch.setenv("HTTPS_PROXY", "http://proxy:8080")
        assert get_proxy_from_env() == "http://proxy:8080"

    def test_reads_lowercase_https_proxy(self, clean_proxy_env, monkeypatch):
        monkeypatch.setenv("https_proxy", "http://proxy:8081")
        assert get_proxy_from_env() == "http://proxy:8081"

    def test_reads_http_proxy_fallback(self, clean_proxy_env, monkeypatch):
        monkeypatch.setenv("HTTP_PROXY", "http://proxy:8082")
        assert get_proxy_from_env() == "http://proxy:8082"

    def test_https_proxy_takes_precedence(self, clean_proxy_env, monkeypatch):
        monkeypatch.setenv("HTTPS_PROXY", "http://https-proxy:8080")
        monkeypatch.setenv("HTTP_PROXY", "http://http-proxy:8080")
        assert get_proxy_from_env() == "http://https-proxy:8080"


class TestMissingOhlcvColumns:
    def test_all_present_returns_empty(self):
        df = pd.DataFrame(columns=pd.Index(REQUIRED_OHLCV_COLUMNS))
        assert missing_ohlcv_columns(df) == []

    def test_partial_columns(self):
        df = pd.DataFrame(columns=pd.Index(["open", "close"]))
        assert missing_ohlcv_columns(df) == ["high", "low", "volume"]

    def test_no_columns(self):
        df = pd.DataFrame()
        assert missing_ohlcv_columns(df) == list(REQUIRED_OHLCV_COLUMNS)

    def test_extra_columns_ignored(self):
        cols = [*REQUIRED_OHLCV_COLUMNS, "extra"]
        df = pd.DataFrame(columns=pd.Index(cols))
        assert missing_ohlcv_columns(df) == []


class TestSafeFilename:
    def test_replaces_slash(self):
        assert safe_filename("BTC/USDT") == "BTC_USDT"

    def test_no_change_without_extra_chars(self):
        assert safe_filename("BTC-USDT") == "BTC-USDT"

    def test_extra_chars_replaced(self):
        assert safe_filename("BTC-USDT", extra_chars="-") == "BTC_USDT"

    def test_multiple_extra_chars(self):
        assert safe_filename("My Strategy-v2", extra_chars=" -") == "My_Strategy_v2"

    def test_lower(self):
        assert safe_filename("BTC/USDT", lower=True) == "btc_usdt"

    def test_lower_with_extra_chars(self):
        assert (
            safe_filename("BTC-USDT/SWAP", extra_chars="-", lower=True) == "btc_usdt_swap"
        )


class TestRetryOnNetwork:
    def test_retries_then_raises(self):
        call_count = 0

        @retry_on_network(max_retries=3, base_delay=0.01, max_delay=0.05)
        def always_fails():
            nonlocal call_count
            call_count += 1
            raise ccxt.NetworkError("boom")

        with pytest.raises(ccxt.NetworkError):
            always_fails()

        assert call_count == 4  # 1 initial + 3 retries

    def test_stops_on_success(self):
        call_count = 0

        @retry_on_network(max_retries=3, base_delay=0.01, max_delay=0.05)
        def recovers_on_third_try():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ccxt.NetworkError("boom")
            return "ok"

        assert recovers_on_third_try() == "ok"
        assert call_count == 3

    def test_non_network_error_propagates_immediately(self):
        call_count = 0

        @retry_on_network(max_retries=3, base_delay=0.01, max_delay=0.05)
        def raises_value_error():
            nonlocal call_count
            call_count += 1
            raise ValueError("not a network error")

        with pytest.raises(ValueError):
            raises_value_error()

        assert call_count == 1

    def test_no_retries_on_immediate_success(self):
        call_count = 0

        @retry_on_network(max_retries=3, base_delay=0.01, max_delay=0.05)
        def succeeds():
            nonlocal call_count
            call_count += 1
            return "ok"

        assert succeeds() == "ok"
        assert call_count == 1

    def test_delay_is_bounded_by_max_delay(self, monkeypatch):
        sleeps = []
        monkeypatch.setattr(time, "sleep", lambda s: sleeps.append(s))

        call_count = 0

        @retry_on_network(max_retries=5, base_delay=10.0, max_delay=1.0, jitter=0.0)
        def always_fails():
            nonlocal call_count
            call_count += 1
            raise ccxt.NetworkError("boom")

        with pytest.raises(ccxt.NetworkError):
            always_fails()

        assert all(s <= 1.0 for s in sleeps)


class TestTimeframeToTimedelta:
    @pytest.mark.parametrize(
        "timeframe, expected",
        [
            ("5m", pd.Timedelta(minutes=5)),
            ("15m", pd.Timedelta(minutes=15)),
            ("1h", pd.Timedelta(hours=1)),
            ("4h", pd.Timedelta(hours=4)),
            ("1d", pd.Timedelta(days=1)),
            ("1w", pd.Timedelta(weeks=1)),
        ],
    )
    def test_converts_exchange_timeframes(self, timeframe, expected):
        assert timeframe_to_timedelta(timeframe) == expected

    @pytest.mark.parametrize("bad", ["5x", "h", "", "4 h", "1M", "abc", "-1h", "1.5h"])
    def test_rejects_unparseable(self, bad):
        with pytest.raises(DataValidationError):
            timeframe_to_timedelta(bad)

    def test_resample_buckets_minutes_not_months(self):
        """The reason this helper exists: df.resample("5m") reads 'm' as
        month-end and quietly collapses a year of bars into one, warning
        only via FutureWarning. The Timedelta must bucket by minutes."""
        idx = pd.date_range("2024-01-01", periods=2000, freq="1min")
        df = pd.DataFrame({"close": range(2000)}, index=idx)

        buckets = df.resample(timeframe_to_timedelta("5m")).last()

        assert len(buckets) == 400, "2000 one-minute bars must give 400 five-minute bars"
        assert buckets.index[1] - buckets.index[0] == pd.Timedelta(minutes=5)

    def test_hours_and_days_bucket_correctly(self):
        idx = pd.date_range("2024-01-01", periods=48, freq="1h")
        df = pd.DataFrame({"close": range(48)}, index=idx)

        assert len(df.resample(timeframe_to_timedelta("4h")).last()) == 12
        assert len(df.resample(timeframe_to_timedelta("1d")).last()) == 2
