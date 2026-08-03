"""Timeframes and bar boundaries — the single authority on time.

Every timestamp in the system is epoch milliseconds, UTC, and refers to the
*open* of a bar. A bar labelled 04:00 on a 1h timeframe covers [04:00, 05:00)
and is closed once 05:00 has passed.

Keeping this in one module is deliberate: the recurring defect in the prior
system was each strategy deciding for itself whether a higher-timeframe value
was already knowable, which is how a daily gate ended up reading the same
day's final close.
"""

from __future__ import annotations

MINUTE_MS = 60_000
HOUR_MS = 60 * MINUTE_MS
DAY_MS = 24 * HOUR_MS

# Canonical timeframe names -> duration in milliseconds.
TIMEFRAMES: dict[str, int] = {
    "1m": MINUTE_MS,
    "5m": 5 * MINUTE_MS,
    "15m": 15 * MINUTE_MS,
    "30m": 30 * MINUTE_MS,
    "1h": HOUR_MS,
    "2h": 2 * HOUR_MS,
    "4h": 4 * HOUR_MS,
    "6h": 6 * HOUR_MS,
    "12h": 12 * HOUR_MS,
    "1d": DAY_MS,
}

# The default granularity fetched and stored. Other granularities can be synced
# explicitly; coarser research timeframes are normally derived from this base.
BASE_TIMEFRAME = "1h"

# OKX spells timeframes differently from our canonical names.
#
# The `utc` suffixes are not cosmetic. OKX aggregates 6H and above in Hong
# Kong time (UTC+8) unless the code says otherwise, while `resample()` here is
# epoch-anchored, so a plain `1D` live bar would cover 16:00-16:00 UTC and
# disagree with every historical daily bar this system builds. 4h and below
# divide the 8-hour offset evenly and are therefore unaffected.
_OKX_BAR = {
    "1m": "1m",
    "5m": "5m",
    "15m": "15m",
    "30m": "30m",
    "1h": "1H",
    "2h": "2H",
    "4h": "4H",
    "6h": "6Hutc",
    "12h": "12Hutc",
    "1d": "1Dutc",
}


class TimeframeError(ValueError):
    """Raised for a timeframe this system does not define."""


def duration_ms(timeframe: str) -> int:
    """Length of one bar, in milliseconds."""
    try:
        return TIMEFRAMES[timeframe]
    except KeyError:
        raise TimeframeError(
            f"unknown timeframe {timeframe!r}; known: {sorted(TIMEFRAMES)}"
        ) from None


def okx_bar(timeframe: str) -> str:
    """OKX's spelling of a timeframe."""
    try:
        return _OKX_BAR[timeframe]
    except KeyError:
        raise TimeframeError(f"no OKX bar code for timeframe {timeframe!r}") from None


def floor_to_bar(ts_ms: int, timeframe: str) -> int:
    """Open time of the bar containing `ts_ms`.

    UTC-anchored: 4h bars start at 00:00, 04:00, ... and daily bars at 00:00
    UTC, which is also how OKX aligns them.
    """
    step = duration_ms(timeframe)
    return (ts_ms // step) * step


def bar_close_time(bar_open_ms: int, timeframe: str) -> int:
    """The instant a bar stops accepting trades — its exclusive end."""
    return bar_open_ms + duration_ms(timeframe)


def is_closed(bar_open_ms: int, timeframe: str, now_ms: int) -> bool:
    """Whether a bar is complete as of `now_ms`.

    A bar is closed only once its end has *passed*: at exactly 05:00 the
    04:00 hourly bar has just finished, so it counts as closed.
    """
    return bar_close_time(bar_open_ms, timeframe) <= now_ms


def bars_per(timeframe: str, base: str = BASE_TIMEFRAME) -> int:
    """How many `base` bars make up one `timeframe` bar.

    Raises if the timeframe is not a whole multiple of the base, which would
    otherwise produce silently misaligned groups.
    """
    target, source = duration_ms(timeframe), duration_ms(base)
    if target % source != 0:
        raise TimeframeError(f"{timeframe} is not a whole multiple of {base}")
    return target // source
