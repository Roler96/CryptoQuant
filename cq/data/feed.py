"""Bar feeds.

Backtest and live share one iteration protocol so the engine loop cannot tell
them apart — that is what makes "backtest and live run the same code" true
rather than aspirational.

Both feeds guarantee the same thing: every bar they yield has closed. The
historical feed inherits it from storage, which never accepts an unclosed
candle; the live feed enforces it against a clock, because the exchange will
happily serve a candle that is still forming.
"""

from __future__ import annotations

import time
from collections.abc import Callable, Iterator
from typing import Protocol

import numpy as np
from loguru import logger

from cq.context import Bar, Series
from cq.core.clock import BASE_TIMEFRAME, duration_ms, is_closed, okx_bar
from cq.data.fetch import _CONFIRM, _TS, CONFIRM_CLOSED
from cq.data.okx import RETRYABLE
from cq.data.protocols import CandleSource
from cq.data.resample import resample
from cq.data.store import Store


class Feed(Protocol):
    """What the engine loop needs from any source of bars."""

    def __iter__(self) -> Iterator[Bar]: ...


def load_series(
    store: Store,
    inst_id: str,
    timeframe: str = BASE_TIMEFRAME,
    start_ms: int | None = None,
    end_ms: int | None = None,
) -> Series:
    """Read one instrument from storage, resampling from the 1h base."""
    frame = store.load_ohlcv(inst_id, BASE_TIMEFRAME, start_ms, end_ms)
    if timeframe != BASE_TIMEFRAME:
        frame = resample(frame, timeframe)
    return Series(
        inst_id=inst_id,
        timeframe=timeframe,
        ts=(frame.index.astype("int64") // 1_000_000).to_numpy(),
        open=frame["open"].to_numpy(dtype=float),
        high=frame["high"].to_numpy(dtype=float),
        low=frame["low"].to_numpy(dtype=float),
        close=frame["close"].to_numpy(dtype=float),
        volume=frame["volume"].to_numpy(dtype=float),
    )


class HistoricalFeed:
    """Replays a stored series in order."""

    def __init__(self, series: Series):
        self._series = series

    @property
    def series(self) -> Series:
        return self._series

    def __len__(self) -> int:
        return len(self._series)

    def __iter__(self) -> Iterator[Bar]:
        s = self._series
        for i in range(len(s)):
            yield Bar(
                ts=int(s.ts[i]),
                open=float(s.open[i]),
                high=float(s.high[i]),
                low=float(s.low[i]),
                close=float(s.close[i]),
                volume=float(s.volume[i]),
            )


class FeedStalledError(RuntimeError):
    """A successful venue poll is no longer advancing closed bars."""


class LiveFeed:
    """Polls the exchange, yielding each bar exactly once, after it closes.

    Two independent guards, because either alone has failed before:
    the exchange's own `confirm` flag, and the clock. A bar is emitted only
    when both agree it is done.
    """

    def __init__(
        self,
        client: CandleSource,
        inst_id: str,
        timeframe: str = BASE_TIMEFRAME,
        poll_seconds: float = 5.0,
        stall_grace_seconds: float = 120.0,
        now_ms: Callable[[], int] | None = None,
        sleep: Callable[[float], None] = time.sleep,
    ):
        if poll_seconds <= 0:
            raise ValueError(f"poll_seconds must be positive, got {poll_seconds}")
        if stall_grace_seconds < 0:
            raise ValueError(
                f"stall_grace_seconds must be non-negative, got {stall_grace_seconds}"
            )
        self._client = client
        self._inst_id = inst_id
        self._timeframe = timeframe
        self._poll_seconds = poll_seconds
        self._duration_ms = duration_ms(timeframe)
        self._stall_grace_ms = int(stall_grace_seconds * 1000)
        self._now_ms = now_ms or client.milliseconds
        self._sleep = sleep
        self._last_emitted_ts: int | None = None
        self._empty_since_ms: int | None = None

    def poll(self) -> list[Bar]:
        """Bars that have closed since the last call, oldest first."""
        page = self._client.history_candles(
            self._inst_id, bar=okx_bar(self._timeframe), limit=100
        )
        now = self._now_ms()
        fresh: list[Bar] = []
        for entry in page:
            ts = int(entry[_TS])
            if entry[_CONFIRM] != CONFIRM_CLOSED:
                continue
            if not is_closed(ts, self._timeframe, now):
                # The exchange said closed, the clock disagrees. Trust
                # neither on its own.
                continue
            if self._last_emitted_ts is not None and ts <= self._last_emitted_ts:
                continue
            fresh.append(
                Bar(
                    ts=ts,
                    open=float(entry[1]),
                    high=float(entry[2]),
                    low=float(entry[3]),
                    close=float(entry[4]),
                    volume=float(entry[5]),
                )
            )
        fresh.sort(key=lambda bar: bar.ts)
        if fresh:
            self._last_emitted_ts = fresh[-1].ts
            self._empty_since_ms = None
        elif self._last_emitted_ts is None and self._empty_since_ms is None:
            self._empty_since_ms = now
        self._raise_if_stalled(now)
        return fresh

    def prime(self) -> list[Bar]:
        """Arm the high-water mark, retrying transient startup failures."""
        return self._poll_resiliently()

    def __iter__(self) -> Iterator[Bar]:
        while True:
            yield from self._poll_resiliently()
            self._sleep(self._poll_seconds)

    def _poll_resiliently(self) -> list[Bar]:
        """Wait for one successful poll; never mistake failure for no data."""
        failures = 0
        while True:
            try:
                bars = self.poll()
            except RETRYABLE as exc:
                failures += 1
                logger.warning(
                    "live feed {} {} poll failed ({}), attempt {} will retry in {:.1f}s",
                    self._inst_id,
                    self._timeframe,
                    type(exc).__name__,
                    failures,
                    self._poll_seconds,
                )
                self._sleep(self._poll_seconds)
                continue
            if failures:
                logger.info(
                    "live feed {} {} recovered after {} failed poll(s)",
                    self._inst_id,
                    self._timeframe,
                    failures,
                )
            return bars

    def _raise_if_stalled(self, now_ms: int) -> None:
        """Fail once a closed bar is overdue beyond the configured grace."""
        last = self._last_emitted_ts
        if last is None:
            empty_since = self._empty_since_ms
            if empty_since is None or now_ms - empty_since < self._stall_grace_ms:
                return
            raise FeedStalledError(
                f"{self._inst_id} {self._timeframe}: no closed bar was visible for "
                f"{(now_ms - empty_since) / 1000:.1f}s"
            )

        # A bar timestamp is its open. If `last` is the most recent bar, the
        # next one opens at last+D and is expected to close at last+2D.
        expected_close = last + 2 * self._duration_ms
        deadline = expected_close + self._stall_grace_ms
        if now_ms < deadline:
            return
        overdue_seconds = (now_ms - expected_close) / 1000
        raise FeedStalledError(
            f"{self._inst_id} {self._timeframe}: no closed bar newer than {last}; "
            f"the next bar is overdue by {overdue_seconds:.1f}s"
        )


def series_from_bars(inst_id: str, timeframe: str, bars: list[Bar]) -> Series:
    """Build a Series from bars, for feeding a Context incrementally."""
    return Series(
        inst_id=inst_id,
        timeframe=timeframe,
        ts=np.array([b.ts for b in bars], dtype=np.int64),
        open=np.array([b.open for b in bars], dtype=float),
        high=np.array([b.high for b in bars], dtype=float),
        low=np.array([b.low for b in bars], dtype=float),
        close=np.array([b.close for b in bars], dtype=float),
        volume=np.array([b.volume for b in bars], dtype=float),
    )
