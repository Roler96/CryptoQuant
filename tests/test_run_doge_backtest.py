"""Research-runner data assembly regression tests."""

import pandas as pd
import pytest

from cryptoquant.exceptions import DataValidationError
from run_doge_backtest import resample_complete_ohlcv


def _hourly() -> pd.DataFrame:
    index = pd.date_range("2025-01-01", periods=8, freq="1h")
    values = list(range(8))
    return pd.DataFrame(
        {
            "open": values,
            "high": [value + 1 for value in values],
            "low": [value - 1 for value in values],
            "close": values,
            "volume": [1.0] * 8,
        },
        index=index,
    )


def test_partial_aggregate_bucket_is_rejected():
    hourly = _hourly().drop(pd.Timestamp("2025-01-01 02:00"))

    result = resample_complete_ohlcv(hourly, "1h", "4h")

    assert list(result.index) == [pd.Timestamp("2025-01-01 04:00")]
    assert result.iloc[0]["open"] == 4
    assert result.iloc[0]["close"] == 7


def test_source_timeframe_must_evenly_divide_target():
    with pytest.raises(DataValidationError, match="Cannot build complete"):
        resample_complete_ohlcv(_hourly(), "3h", "4h")
