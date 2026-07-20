"""Timeframe arithmetic and bar-closure rules."""

import pytest

from cq.core.clock import (
    DAY_MS,
    HOUR_MS,
    TimeframeError,
    bar_close_time,
    bars_per,
    duration_ms,
    floor_to_bar,
    is_closed,
    okx_bar,
)

# 2026-07-20 04:00:00 UTC
FOUR_AM = 1_784_520_000_000


def test_durations():
    assert duration_ms("1h") == HOUR_MS
    assert duration_ms("4h") == 4 * HOUR_MS
    assert duration_ms("1d") == DAY_MS


def test_unknown_timeframe_is_rejected_not_guessed():
    with pytest.raises(TimeframeError):
        duration_ms("3h")
    with pytest.raises(TimeframeError):
        okx_bar("3h")


def test_okx_spelling_differs_from_ours():
    assert okx_bar("1h") == "1H"
    assert okx_bar("15m") == "15m"


def test_timeframes_of_six_hours_and_up_ask_for_the_utc_aligned_bar():
    # OKX aggregates 6H and above in UTC+8 unless the code says otherwise, so
    # a plain "1D" is a 16:00-16:00 UTC bar. `resample()` here is epoch
    # anchored, so live and backtest boundaries would be eight hours apart on
    # exactly the timeframes a daily gate runs on.
    assert okx_bar("6h") == "6Hutc"
    assert okx_bar("12h") == "12Hutc"
    assert okx_bar("1d") == "1Dutc"


def test_timeframes_below_six_hours_need_no_suffix():
    # 4h and shorter divide the eight-hour offset evenly, so both alignments
    # produce the same boundaries and OKX offers no `utc` variant.
    assert okx_bar("4h") == "4H"
    assert okx_bar("2h") == "2H"


def test_floor_is_utc_anchored():
    # 04:00 UTC is itself a 4h boundary; 05:59 still belongs to that bar.
    assert floor_to_bar(FOUR_AM, "4h") == FOUR_AM
    assert floor_to_bar(FOUR_AM + 2 * HOUR_MS - 1, "4h") == FOUR_AM
    assert floor_to_bar(FOUR_AM + 4 * HOUR_MS, "4h") == FOUR_AM + 4 * HOUR_MS
    # The daily bar containing 04:00 opens at 00:00 UTC.
    assert floor_to_bar(FOUR_AM, "1d") == FOUR_AM - 4 * HOUR_MS


def test_bar_close_is_exclusive_end():
    assert bar_close_time(FOUR_AM, "1h") == FOUR_AM + HOUR_MS


def test_bar_is_closed_exactly_at_its_end_not_before():
    close = FOUR_AM + HOUR_MS
    assert not is_closed(FOUR_AM, "1h", now_ms=close - 1)
    # At exactly 05:00 the 04:00 bar has just finished.
    assert is_closed(FOUR_AM, "1h", now_ms=close)
    assert is_closed(FOUR_AM, "1h", now_ms=close + 1)


def test_a_daily_bar_is_not_closed_until_the_day_ends():
    midnight = FOUR_AM - 4 * HOUR_MS
    assert not is_closed(midnight, "1d", now_ms=FOUR_AM)
    assert is_closed(midnight, "1d", now_ms=midnight + DAY_MS)


def test_bars_per_counts_base_bars():
    assert bars_per("4h") == 4
    assert bars_per("1d") == 24
    assert bars_per("1h") == 1


def test_bars_per_rejects_non_multiples():
    # 1d is not a whole number of 4h... it is; use one that genuinely is not.
    with pytest.raises(TimeframeError):
        bars_per("1h", base="4h")
