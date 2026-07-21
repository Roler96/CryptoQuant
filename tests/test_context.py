"""Context: the strategy's only window onto the market.

These tests define the contract that makes lookahead unwritable rather than
merely detectable, so they are deliberately written before the implementation.
"""

import numpy as np
import pytest

from cq.context import Context, LookaheadError, Series
from cq.core.clock import DAY_MS, HOUR_MS

DAY0 = 1_609_459_200_000  # 2021-01-01 00:00 UTC


def series(inst_id, timeframe, count, step_ms, start=DAY0, close_base=100.0):
    ts = np.array([start + i * step_ms for i in range(count)], dtype=np.int64)
    closes = np.array([close_base + i for i in range(count)], dtype=float)
    return Series(
        inst_id=inst_id,
        timeframe=timeframe,
        ts=ts,
        open=closes - 0.5,
        high=closes + 1.0,
        low=closes - 1.0,
        close=closes,
        volume=np.full(count, 10.0),
    )


def hourly(count=48, **kw):
    return series("DOGE-USDT", "1h", count, HOUR_MS, **kw)


def daily(count=5, **kw):
    return series("DOGE-USDT", "1d", count, DAY_MS, **kw)


# ---- series integrity --------------------------------------------------


def test_series_rejects_non_ascending_timestamps():
    # Out-of-order bars would make the as-of search silently wrong: it relies
    # on close_times being sorted.
    good = hourly(5)
    scrambled = good.ts.copy()
    scrambled[2], scrambled[3] = scrambled[3], scrambled[2]
    with pytest.raises(ValueError, match="ascending"):
        Series(
            inst_id=good.inst_id,
            timeframe=good.timeframe,
            ts=scrambled,
            open=good.open,
            high=good.high,
            low=good.low,
            close=good.close,
            volume=good.volume,
        )


def test_series_rejects_duplicate_timestamps():
    good = hourly(5)
    duped = good.ts.copy()
    duped[3] = duped[2]
    with pytest.raises(ValueError, match="ascending"):
        Series(
            inst_id=good.inst_id,
            timeframe=good.timeframe,
            ts=duped,
            open=good.open,
            high=good.high,
            low=good.low,
            close=good.close,
            volume=good.volume,
        )


def test_series_columns_cannot_be_mutated_in_place():
    # frozen=True blocks rebinding the attribute but not writing into the array
    # it points at. A run's fingerprint is taken of these columns, so a bar
    # edited in place afterwards would leave the fingerprint describing data the
    # Series no longer holds. The columns are read-only, so the write raises.
    s = hourly(5)
    # numpy raises "assignment destination is read-only" on a locked array.
    with pytest.raises(ValueError, match="read-only"):
        s.close[0] = 999.0
    with pytest.raises(ValueError, match="read-only"):
        s.ts[0] = 0


def test_series_does_not_alias_the_arrays_it_was_given():
    # Copying the inputs means a later edit to the caller's own array cannot
    # reach into the Series and change it after the fingerprint was taken.
    closes = np.array([100.0, 101.0, 102.0], dtype=float)
    ts = np.array([DAY0, DAY0 + HOUR_MS, DAY0 + 2 * HOUR_MS], dtype=np.int64)
    s = Series(
        inst_id="X",
        timeframe="1h",
        ts=ts,
        open=closes,
        high=closes + 1,
        low=closes - 1,
        close=closes,
        volume=np.full(3, 10.0),
    )
    closes[0] = -1.0
    assert s.close[0] == 100.0


def test_series_rejects_columns_of_different_lengths():
    good = hourly(5)
    with pytest.raises(ValueError, match="lengths disagree"):
        Series(
            inst_id=good.inst_id,
            timeframe=good.timeframe,
            ts=good.ts,
            open=good.open[:3],
            high=good.high,
            low=good.low,
            close=good.close,
            volume=good.volume,
        )


def test_single_bar_series_is_valid():
    assert len(hourly(1)) == 1


# ---- physical isolation ------------------------------------------------


def test_context_shows_only_up_to_the_current_bar():
    ctx = Context(hourly(48))
    ctx.seek(10)

    window = ctx.close(11)
    assert len(window) == 11
    # Bar 10's close is the newest value visible, nothing beyond it.
    assert window[-1] == ctx.bar.close
    assert window[-1] == 110.0


def test_asking_for_more_history_than_exists_raises():
    ctx = Context(hourly(48))
    ctx.seek(5)

    # Only 6 bars exist up to the cursor; padding with NaN would silently
    # hand the strategy a shorter warmup than it asked for.
    with pytest.raises(LookaheadError):
        ctx.close(7)


def test_exactly_all_available_history_is_allowed():
    ctx = Context(hourly(48))
    ctx.seek(5)
    assert len(ctx.close(6)) == 6


def test_returned_windows_cannot_be_mutated():
    ctx = Context(hourly(48))
    ctx.seek(10)
    window = ctx.close(5)
    with pytest.raises(ValueError):
        window[0] = 999.0


def test_returned_window_does_not_expose_the_future_through_its_base():
    # A numpy view would let `window.base` reach the whole array, future
    # included. The window must not be a view onto the full series.
    ctx = Context(hourly(48))
    ctx.seek(10)
    window = ctx.close(5)
    assert window.base is None or len(window.base) == len(window)


def test_seeking_past_the_end_raises():
    ctx = Context(hourly(10))
    with pytest.raises(LookaheadError):
        ctx.seek(10)


def test_all_price_fields_respect_the_cursor():
    ctx = Context(hourly(48))
    ctx.seek(7)
    for accessor in (ctx.open, ctx.high, ctx.low, ctx.close, ctx.volume):
        assert len(accessor(8)) == 8
        with pytest.raises(LookaheadError):
            accessor(9)


# ---- prefix invariance -------------------------------------------------


def test_truncating_the_data_does_not_change_earlier_windows():
    # The invariant that catches lookahead: what the strategy sees at bar k
    # must not depend on data after bar k.
    full = Context(hourly(48))
    truncated = Context(hourly(20))

    for k in range(5, 20):
        full.seek(k)
        truncated.seek(k)
        np.testing.assert_array_equal(full.close(5), truncated.close(5))
        assert full.now == truncated.now
        assert full.bar.close == truncated.bar.close


def test_prefix_invariance_holds_for_auxiliary_markets():
    full = Context(hourly(48), aux=[daily(5)])
    truncated = Context(hourly(20), aux=[daily(2)])

    for k in range(0, 20):
        full.seek(k)
        truncated.seek(k)
        a = full.market("DOGE-USDT", "1d")
        b = truncated.market("DOGE-USDT", "1d")
        assert a.available == b.available
        if a.available:
            assert a.bar.ts == b.bar.ts
            assert a.bar.close == b.bar.close


# ---- as-of alignment ---------------------------------------------------


def test_daily_context_excludes_the_day_still_in_progress():
    # The defect this system exists to prevent: an intraday bar reading the
    # same day's final close. On 2021-01-02 at 04:00 the newest knowable
    # daily bar is 2021-01-01, which closed at 2021-01-02 00:00.
    ctx = Context(series("DOGE-USDT", "4h", 12, 4 * HOUR_MS), aux=[daily(5)])
    ctx.seek(6)  # 2021-01-02 00:00 .. 04:00

    assert ctx.now == DAY0 + DAY_MS
    view = ctx.market("DOGE-USDT", "1d")
    assert view.bar.ts == DAY0, "must be 2021-01-01, not the in-progress day"


def test_last_bar_of_the_day_may_see_that_day_because_both_end_together():
    # A boundary worth stating explicitly: the 20:00-24:00 bar decides at
    # 24:00, and that day's daily bar also closes at 24:00. Both are final at
    # the same instant, so this is knowledge, not lookahead — excluding it
    # would throw away a full day of legitimate information.
    ctx = Context(series("DOGE-USDT", "4h", 12, 4 * HOUR_MS), aux=[daily(5)])
    ctx.seek(5)  # 2021-01-01 20:00 .. 24:00

    assert ctx.decision_time == DAY0 + DAY_MS
    assert ctx.market("DOGE-USDT", "1d").bar.ts == DAY0

    # ...but the first bar of that same day must not, and that is the defect
    # that cost this project two strategies.
    ctx.seek(0)
    assert not ctx.market("DOGE-USDT", "1d").available


def test_daily_context_advances_once_the_day_has_closed():
    ctx = Context(series("DOGE-USDT", "4h", 18, 4 * HOUR_MS), aux=[daily(5)])
    # 2021-01-03 00:00 .. 04:00: the 01-02 daily closed exactly at 01-03 00:00.
    ctx.seek(12)
    assert ctx.market("DOGE-USDT", "1d").bar.ts == DAY0 + DAY_MS


def test_same_timeframe_context_is_not_artificially_lagged():
    # A 1h auxiliary market on a 1h primary closes at the same instant the
    # decision is made, so it is knowable. Excluding it would lag every
    # cross-market signal by a full bar.
    ctx = Context(hourly(48), aux=[series("BTC-USDT", "1h", 48, HOUR_MS)])
    ctx.seek(10)
    view = ctx.market("BTC-USDT", "1h")
    assert view.bar.ts == ctx.now


def test_auxiliary_market_is_unavailable_before_its_first_close():
    ctx = Context(series("DOGE-USDT", "4h", 12, 4 * HOUR_MS), aux=[daily(5)])
    ctx.seek(0)  # 2021-01-01 00:00; no daily bar has closed yet
    view = ctx.market("DOGE-USDT", "1d")
    assert not view.available
    with pytest.raises(LookaheadError):
        _ = view.bar


def test_auxiliary_window_respects_its_own_cursor():
    ctx = Context(series("DOGE-USDT", "4h", 30, 4 * HOUR_MS), aux=[daily(5)])
    ctx.seek(18)  # 2021-01-04 00:00 -> dailies 01-01..01-03 are closed
    view = ctx.market("DOGE-USDT", "1d")
    assert len(view.close(3)) == 3
    with pytest.raises(LookaheadError):
        view.close(4)


def test_unknown_auxiliary_market_raises():
    ctx = Context(hourly(48))
    ctx.seek(3)
    with pytest.raises(KeyError):
        ctx.market("ETH-USDT", "1h")


def test_auxiliary_market_with_a_gap_does_not_look_forward():
    # Aux bars missing around the decision point must not cause a later bar
    # to be selected.
    sparse = series("DOGE-USDT", "1d", 5, DAY_MS)
    keep = np.array([0, 3, 4])
    gapped = Series(
        inst_id="DOGE-USDT",
        timeframe="1d",
        ts=sparse.ts[keep],
        open=sparse.open[keep],
        high=sparse.high[keep],
        low=sparse.low[keep],
        close=sparse.close[keep],
        volume=sparse.volume[keep],
    )
    ctx = Context(series("DOGE-USDT", "4h", 24, 4 * HOUR_MS), aux=[gapped])
    ctx.seek(12)  # 2021-01-03 00:00; only the 01-01 daily has closed
    assert ctx.market("DOGE-USDT", "1d").bar.ts == DAY0
