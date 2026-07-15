"""Tests for causal alignment of auxiliary closed-bar feeds."""

from unittest.mock import MagicMock

import numpy as np
import pandas as pd
import pytest

from cryptoquant.data.closed_bar import BarFetchMeta
from cryptoquant.data.context_feed import ContextualClosedBarFeed
from cryptoquant.data.quality import QualityReport
from cryptoquant.exceptions import DataFetchError, DataValidationError
from cryptoquant.strategy.base import MarketContext


def _bars(index: pd.DatetimeIndex, scale: float = 1.0) -> pd.DataFrame:
    values = np.arange(1, len(index) + 1, dtype=float) * scale
    return pd.DataFrame(
        {
            "open": values,
            "high": values + 1,
            "low": values - 1,
            "close": values,
            "volume": values * 10,
        },
        index=index,
    )


def _feed(frame: pd.DataFrame, *, new: bool = True, fetch_ts: int = 100):
    feed = MagicMock()
    feed.fetch.return_value = (
        frame,
        BarFetchMeta(has_new_closed=new, stripped=0),
    )
    feed.last_fetch_ts = fetch_ts
    feed.last_quality_report = None
    feed.symbol = "TEST/USDT"
    feed.timeframe = "1h"
    feed.stats.return_value = {"symbol": feed.symbol}
    return feed


def _market(alias: str, columns: tuple[str, ...]) -> MarketContext:
    return MarketContext(alias, f"{alias}-history", f"{alias}/live", columns)


def test_joins_declared_columns_and_keeps_primary_execution_prices():
    index = pd.date_range("2025-01-01", periods=5, freq="1h")
    primary = _feed(_bars(index))
    primary.fetch.return_value = (
        _bars(index),
        BarFetchMeta(
            has_new_closed=True,
            stripped=1,
            execution_price=5.25,
        ),
    )
    swap = _feed(_bars(index, 10))
    btc = _feed(_bars(index, 100))
    feed = ContextualClosedBarFeed(
        primary,
        [
            (_market("swap", ("volume",)), swap),
            (_market("btc", ("close",)), btc),
        ],
    )

    result, meta = feed.fetch(5)

    assert list(result.columns) == [
        "open", "high", "low", "close", "volume", "swap_volume", "btc_close"
    ]
    assert result["close"].equals(_bars(index)["close"])
    assert result["swap_volume"].equals(_bars(index, 10)["volume"])
    assert result["btc_close"].equals(_bars(index, 100)["close"])
    assert meta.has_new_closed is True
    assert meta.execution_price == pytest.approx(5.25)


def test_missing_context_timestamp_stays_nan_instead_of_forward_filling():
    index = pd.date_range("2025-01-01", periods=5, freq="1h")
    primary = _feed(_bars(index))
    btc = _feed(_bars(index[:-1], 100))
    feed = ContextualClosedBarFeed(
        primary,
        [(_market("btc", ("close",)), btc)],
    )

    result, _meta = feed.fetch(5)

    assert pd.isna(result["btc_close"].iloc[-1])


def test_common_bar_controls_decision_and_slowest_fetch_controls_freshness():
    index = pd.date_range("2025-01-01", periods=5, freq="1h")
    primary = _feed(_bars(index), new=True, fetch_ts=200)
    context = _feed(_bars(index[:-1]), new=True, fetch_ts=150)
    feed = ContextualClosedBarFeed(
        primary,
        [(_market("btc", ("close",)), context)],
    )

    _result, meta = feed.fetch(5)

    assert meta.has_new_closed is False
    assert feed.last_fetch_ts == 150


def test_late_context_triggers_common_bar_even_without_new_primary_bar():
    index = pd.date_range("2025-01-01", periods=5, freq="1h")
    primary = _feed(_bars(index), new=True)
    context = _feed(_bars(index[:-1]), new=True)
    feed = ContextualClosedBarFeed(
        primary,
        [(_market("btc", ("close",)), context)],
    )
    _result, first = feed.fetch(5)
    assert first.has_new_closed is False

    primary.fetch.return_value = (
        _bars(index),
        BarFetchMeta(has_new_closed=False, stripped=0),
    )
    context.fetch.return_value = (
        _bars(index),
        BarFetchMeta(has_new_closed=True, stripped=0),
    )
    result, second = feed.fetch(5)

    assert second.has_new_closed is True
    assert result["btc_close"].iloc[-1] == _bars(index)["close"].iloc[-1]


def test_context_that_misses_a_bar_is_not_replayed_after_primary_advances():
    index = pd.date_range("2025-01-01", periods=6, freq="1h")
    primary = _feed(_bars(index[:5]))
    context = _feed(_bars(index[:4]))
    feed = ContextualClosedBarFeed(
        primary,
        [(_market("btc", ("close",)), context)],
    )
    _result, first = feed.fetch(5)
    assert first.decision_ready is False

    primary.fetch.return_value = (
        _bars(index),
        BarFetchMeta(has_new_closed=True, stripped=0),
    )
    context.fetch.return_value = (
        _bars(index[:5]),
        BarFetchMeta(has_new_closed=True, stripped=0),
    )
    _result, late = feed.fetch(5)

    assert late.decision_ready is False
    assert late.common_bar_ts == 0


def test_repeated_common_frame_is_consumed_once_and_context_ahead_waits():
    index = pd.date_range("2025-01-01", periods=6, freq="1h")
    primary = _feed(_bars(index[:5]))
    context = _feed(_bars(index[:5]))
    feed = ContextualClosedBarFeed(
        primary,
        [(_market("btc", ("close",)), context)],
    )
    _result, first = feed.fetch(5)
    _result, repeated = feed.fetch(5)

    assert first.has_new_closed is True
    assert first.decision_ready is True
    assert repeated.has_new_closed is False

    context.fetch.return_value = (
        _bars(index),
        BarFetchMeta(has_new_closed=True, stripped=0),
    )
    _result, ahead = feed.fetch(5)
    assert ahead.decision_ready is False


def test_context_fetch_failure_blocks_decision_but_preserves_primary_frame():
    index = pd.date_range("2025-01-01", periods=5, freq="1h")
    primary_frame = _bars(index)
    primary = _feed(primary_frame)
    context = _feed(_bars(index))
    context.fetch.side_effect = DataFetchError("swap unavailable")
    feed = ContextualClosedBarFeed(
        primary,
        [(_market("swap", ("volume",)), context)],
    )

    result, meta = feed.fetch(5)

    assert result["close"].equals(primary_frame["close"])
    assert bool(result["swap_volume"].isna().to_numpy().all())
    assert meta.decision_ready is False
    report = feed.last_quality_report
    assert report is not None
    assert report.is_healthy is False


def test_unhealthy_context_makes_combined_quality_unhealthy():
    index = pd.date_range("2025-01-01", periods=5, freq="1h")
    primary = _feed(_bars(index))
    context = _feed(_bars(index))
    primary.last_quality_report = QualityReport(True, 0, 0, 1, 0)
    context.last_quality_report = QualityReport(False, 1, 0, 0, 0)
    feed = ContextualClosedBarFeed(
        primary,
        [(_market("btc", ("close",)), context)],
    )

    report = feed.last_quality_report

    assert report is not None
    assert report.is_healthy is False
    assert report.gap_count == 1
    assert report.outlier_count == 1


def test_duplicate_or_missing_context_columns_fail_closed():
    index = pd.date_range("2025-01-01", periods=5, freq="1h")
    primary = _feed(_bars(index))
    context = _feed(_bars(index))
    duplicate = _market("same", ("close",))
    with pytest.raises(DataValidationError, match="duplicate"):
        ContextualClosedBarFeed(primary, [(duplicate, context), (duplicate, context)])

    missing = ContextualClosedBarFeed(
        primary,
        [(_market("btc", ("not_there",)), context)],
    )
    with pytest.raises(DataValidationError, match="missing columns"):
        missing.fetch(5)
