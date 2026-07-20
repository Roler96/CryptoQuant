"""Quality reporting and timeframe aggregation."""

import pandas as pd
import pytest

from cq.data.quality import check_ohlcv, find_gaps
from cq.data.resample import resample


def frame_from(hours, **overrides):
    """Build an hourly OHLCV frame at the given hour offsets from epoch day 0."""
    index = pd.to_datetime([h * 3_600_000 for h in hours], unit="ms", utc=True)
    data = {
        "open": [1.0] * len(hours),
        "high": [2.0] * len(hours),
        "low": [0.5] * len(hours),
        "close": [1.5] * len(hours),
        "volume": [10.0] * len(hours),
        "quote_volume": [15.0] * len(hours),
    }
    data.update(overrides)
    return pd.DataFrame(data, index=index)


def hours_index(hours) -> pd.DatetimeIndex:
    return pd.DatetimeIndex(frame_from(hours).index)


# ---- gaps -------------------------------------------------------------


def test_contiguous_series_has_no_gaps():
    report = check_ohlcv(frame_from(range(10)), "DOGE-USDT", "1h")
    assert report.gaps == []
    assert report.missing_bars == 0
    assert report.clean


def test_gap_is_located_precisely():
    # Hours 3, 4, 5 are missing.
    report = check_ohlcv(frame_from([0, 1, 2, 6, 7]), "DOGE-USDT", "1h")

    assert len(report.gaps) == 1
    gap = report.gaps[0]
    assert gap.missing == 3
    assert gap.start == pd.Timestamp("1970-01-01 03:00", tz="UTC")
    assert gap.end == pd.Timestamp("1970-01-01 05:00", tz="UTC")
    assert not report.clean


def test_multiple_gaps_are_all_reported():
    report = check_ohlcv(frame_from([0, 1, 5, 6, 10]), "DOGE-USDT", "1h")
    assert [g.missing for g in report.gaps] == [3, 3]
    assert report.missing_bars == 6


def test_single_bar_series_has_no_gaps():
    assert find_gaps(hours_index([0]), "1h") == []


def test_gaps_are_measured_against_the_declared_timeframe():
    # The same index is contiguous at 4h and full of holes at 1h.
    index = hours_index([0, 4, 8])
    assert find_gaps(index, "4h") == []
    assert len(find_gaps(index, "1h")) == 2


# ---- anomalies --------------------------------------------------------


def test_inconsistent_ohlc_is_flagged():
    bad = frame_from([0, 1], high=[2.0, 0.1])  # high below low and close
    report = check_ohlcv(bad, "DOGE-USDT", "1h")
    assert len(report.inconsistent_ohlc) == 1
    assert not report.clean


# Each bound is checked separately: a bar violating several at once would let
# any single broken clause hide behind the others.


def test_high_below_close_is_flagged_on_its_own():
    # Only `high < close` is violated: high still bounds low and open.
    bad = frame_from([0, 1], high=[2.0, 2.0], close=[1.5, 3.0])
    report = check_ohlcv(bad, "DOGE-USDT", "1h")
    assert report.inconsistent_ohlc == [pd.Timestamp("1970-01-01 01:00", tz="UTC")]


def test_low_above_open_is_flagged_on_its_own():
    # Only `low > open` is violated: high still bounds everything.
    bad = frame_from([0, 1], low=[0.5, 1.5], open=[1.0, 1.0], close=[1.5, 1.8])
    report = check_ohlcv(bad, "DOGE-USDT", "1h")
    assert report.inconsistent_ohlc == [pd.Timestamp("1970-01-01 01:00", tz="UTC")]


def test_low_above_close_is_flagged_on_its_own():
    bad = frame_from([0, 1], low=[0.5, 1.9], open=[1.0, 1.95], close=[1.5, 1.8])
    report = check_ohlcv(bad, "DOGE-USDT", "1h")
    assert report.inconsistent_ohlc == [pd.Timestamp("1970-01-01 01:00", tz="UTC")]


def test_high_below_open_is_flagged_on_its_own():
    bad = frame_from([0, 1], high=[2.0, 2.0], open=[1.0, 2.5], close=[1.5, 1.5])
    report = check_ohlcv(bad, "DOGE-USDT", "1h")
    assert report.inconsistent_ohlc == [pd.Timestamp("1970-01-01 01:00", tz="UTC")]


def test_high_below_low_is_flagged():
    # Cannot be isolated: a bar with high < low always violates one of the
    # open/close bounds too, since open cannot lie between them. See the note
    # in quality.check_ohlcv.
    bad = frame_from([0, 1], high=[2.0, 0.4], low=[0.5, 0.5], open=[1.0, 0.3], close=[1.5, 0.3])
    report = check_ohlcv(bad, "DOGE-USDT", "1h")
    assert pd.Timestamp("1970-01-01 01:00", tz="UTC") in report.inconsistent_ohlc


def test_non_positive_price_is_flagged():
    bad = frame_from([0, 1], close=[1.5, 0.0])
    report = check_ohlcv(bad, "DOGE-USDT", "1h")
    assert len(report.non_positive_prices) == 1
    assert not report.clean


def test_zero_volume_is_reported_but_not_unclean():
    # Legal on an illiquid instrument; worth seeing, not worth failing on.
    quiet = frame_from([0, 1], volume=[10.0, 0.0])
    report = check_ohlcv(quiet, "DOGE-USDT", "1h")
    assert len(report.zero_volume_bars) == 1
    assert report.clean


def test_empty_frame_reports_no_data():
    report = check_ohlcv(frame_from([]), "DOGE-USDT", "1h")
    assert report.bars == 0
    assert "no data" in report.summary()


# ---- resampling -------------------------------------------------------


def test_four_hour_bar_aggregates_its_four_hours():
    frame = frame_from(range(4))
    frame["open"] = [1.0, 2.0, 3.0, 4.0]
    frame["high"] = [1.0, 9.0, 3.0, 4.0]
    frame["low"] = [1.0, 2.0, 0.1, 4.0]
    frame["close"] = [1.0, 2.0, 3.0, 7.0]

    out = resample(frame, "4h")

    assert len(out) == 1
    row = out.iloc[0]
    assert row["open"] == 1.0  # first
    assert row["high"] == 9.0  # max
    assert row["low"] == 0.1  # min
    assert row["close"] == 7.0  # last
    assert row["volume"] == 40.0  # sum


def test_incomplete_trailing_period_is_dropped():
    # Five hours: one full 4h bar plus one hour of an in-progress period.
    out = resample(frame_from(range(5)), "4h")
    assert len(out) == 1
    assert out.index[0] == pd.Timestamp("1970-01-01 00:00", tz="UTC")


def test_period_with_an_internal_gap_is_dropped():
    # Hour 2 missing: the 00:00 period would understate its range.
    out = resample(frame_from([0, 1, 3, 4, 5, 6, 7]), "4h")
    assert len(out) == 1
    assert out.index[0] == pd.Timestamp("1970-01-01 04:00", tz="UTC")


def test_incomplete_periods_can_be_kept_deliberately():
    out = resample(frame_from(range(5)), "4h", require_complete=False)
    assert len(out) == 2


def test_gaps_do_not_become_empty_bars():
    # resample() materialises empty periods; none may survive as a bar.
    out = resample(frame_from([0, 1, 2, 3, 16, 17, 18, 19]), "4h", require_complete=False)
    assert len(out) == 2
    assert not bool(out.isna().to_numpy().any())


def test_resampling_to_the_base_timeframe_is_identity():
    frame = frame_from(range(5))
    pd.testing.assert_frame_equal(resample(frame, "1h"), frame)


def test_daily_bars_are_utc_anchored():
    out = resample(frame_from(range(48)), "1d")
    assert len(out) == 2
    assert out.index[0] == pd.Timestamp("1970-01-01 00:00", tz="UTC")
    assert out.index[1] == pd.Timestamp("1970-01-02 00:00", tz="UTC")


def test_resampled_bar_count_matches_the_declared_ratio():
    # 24 hourly bars make exactly one daily bar, never two.
    assert len(resample(frame_from(range(24)), "1d")) == 1
    assert len(resample(frame_from(range(23)), "1d")) == 0


def test_empty_frame_resamples_to_empty():
    assert resample(frame_from([]), "4h").empty


def test_unknown_timeframe_is_rejected():
    from cq.core.clock import TimeframeError

    with pytest.raises(TimeframeError):
        resample(frame_from(range(4)), "3h")
