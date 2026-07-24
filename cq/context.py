"""The strategy's only window onto the market.

A strategy never receives a DataFrame. It receives a `Context` holding a
cursor, and every accessor slices to that cursor. Reading a future bar is not
something the type system discourages — it is something there is no method
for.

This is the layer the previous system got wrong twice, both times by leaving
"is this higher-timeframe value knowable yet?" to the strategy author. Here it
is decided once, in `_asof_index`, and there is no way around it.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass

import numpy as np

from cq.core.clock import duration_ms


class LookaheadError(LookupError):
    """Raised when data that was not knowable at the cursor is requested."""


@dataclass(frozen=True)
class Bar:
    """One closed bar."""

    ts: int
    open: float
    high: float
    low: float
    close: float
    volume: float


@dataclass(frozen=True)
class Series:
    """An instrument's closed bars at one timeframe, ascending by open time."""

    inst_id: str
    timeframe: str
    ts: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    volume: np.ndarray

    def __post_init__(self) -> None:
        # frozen=True stops the attributes being rebound but not the arrays'
        # contents being written in place: `series.close[0] = 999` would still
        # mutate a run's data underneath the fingerprint that is supposed to
        # pin it. Each column is replaced with a private, read-only copy, so the
        # data a Series carries is immutable in fact and not merely by
        # convention — which is what lets a fingerprint taken of it stay true.
        for name in ("ts", "open", "high", "low", "close", "volume"):
            column = np.array(getattr(self, name), copy=True)
            column.setflags(write=False)
            object.__setattr__(self, name, column)

        lengths = {
            len(self.ts),
            len(self.open),
            len(self.high),
            len(self.low),
            len(self.close),
            len(self.volume),
        }
        if len(lengths) > 1:
            raise ValueError(f"{self.key}: column lengths disagree: {sorted(lengths)}")
        if len(self.ts) > 1 and not bool(np.all(np.diff(self.ts) > 0)):
            raise ValueError(f"{self.key}: timestamps must be strictly ascending")

    @property
    def key(self) -> tuple[str, str]:
        return (self.inst_id, self.timeframe)

    @property
    def close_times(self) -> np.ndarray:
        """Exclusive end of each bar — the instant its values became final."""
        return self.ts + duration_ms(self.timeframe)

    def __len__(self) -> int:
        return len(self.ts)


def series_fingerprint(series: Series) -> str:
    """SHA-256 (truncated) of the exact bars a series holds.

    Identifies the data content, not merely its shape: a re-sync that fills a
    gap, a corrected candle, or a single edited price all change it. Computed
    at run time and pinned into the run's manifest, it is what lets a report
    prove it describes the data the result actually came from — a check that
    instrument, timeframe, length and first timestamp together cannot make,
    because a doctored copy can match all four.
    """
    digest = hashlib.sha256()
    digest.update(series.inst_id.encode())
    digest.update(series.timeframe.encode())
    for column in (series.ts, series.open, series.high, series.low, series.close, series.volume):
        digest.update(np.ascontiguousarray(column).tobytes())
    return digest.hexdigest()[:16]


class MarketView:
    """A read-only window into one series, truncated at a cursor.

    `cursor` is the index of the newest visible bar, or -1 when nothing in
    this series has closed yet.
    """

    def __init__(self, series: Series, cursor: int):
        self._series = series
        self._cursor = cursor

    @property
    def available(self) -> bool:
        return self._cursor >= 0

    @property
    def inst_id(self) -> str:
        return self._series.inst_id

    @property
    def timeframe(self) -> str:
        return self._series.timeframe

    @property
    def bar(self) -> Bar:
        self._require_available()
        i = self._cursor
        s = self._series
        return Bar(
            ts=int(s.ts[i]),
            open=float(s.open[i]),
            high=float(s.high[i]),
            low=float(s.low[i]),
            close=float(s.close[i]),
            volume=float(s.volume[i]),
        )

    def open(self, n: int = 1) -> np.ndarray:
        return self._window(self._series.open, n)

    def high(self, n: int = 1) -> np.ndarray:
        return self._window(self._series.high, n)

    def low(self, n: int = 1) -> np.ndarray:
        return self._window(self._series.low, n)

    def close(self, n: int = 1) -> np.ndarray:
        return self._window(self._series.close, n)

    def volume(self, n: int = 1) -> np.ndarray:
        return self._window(self._series.volume, n)

    def timestamps(self, n: int = 1) -> np.ndarray:
        return self._window(self._series.ts, n)

    def _require_available(self) -> None:
        if self._cursor < 0:
            raise LookaheadError(
                f"{self._series.key} has no closed bar at this point in time"
            )

    def _window(self, column: np.ndarray, n: int) -> np.ndarray:
        if n <= 0:
            raise ValueError(f"window size must be positive, got {n}")
        self._require_available()
        available = self._cursor + 1
        if n > available:
            raise LookaheadError(
                f"{self._series.key}: asked for {n} bars but only {available} have "
                f"closed; padding would hide a short warmup"
            )
        # A copy, not a slice: a numpy view would expose the whole array —
        # future included — through `.base`.
        window = np.array(column[available - n : available])
        window.setflags(write=False)
        return window


class Context:
    """What a strategy may know at one instant.

    The primary series drives the cursor. Auxiliary markets — other
    instruments, other timeframes — are aligned to it by close time.
    """

    def __init__(
        self,
        primary: Series,
        aux: Iterable[Series] = (),
        *,
        index_offset: int = 0,
    ):
        if index_offset < 0:
            raise ValueError(f"index_offset must be non-negative, got {index_offset}")
        self._primary = primary
        # Live contexts retain only a bounded lookback window. The offset keeps
        # `index` on the same logical bar ordinal a historical context exposes,
        # even after older in-memory bars have been discarded.
        self._index_offset = index_offset
        self._aux: dict[tuple[str, str], Series] = {}
        for series in aux:
            if series.key in self._aux:
                raise ValueError(f"duplicate auxiliary market {series.key}")
            self._aux[series.key] = series
        self._cursor = -1
        self._aux_cursors: dict[tuple[str, str], int] = dict.fromkeys(self._aux, -1)

    # ---- cursor -------------------------------------------------------

    def seek(self, index: int) -> None:
        """Move to bar `index` of the primary series."""
        if index < 0 or index >= len(self._primary):
            raise LookaheadError(
                f"bar {index} is outside the primary series of {len(self._primary)} bars"
            )
        self._cursor = index
        decision_time = int(self._primary.close_times[index])
        for key, series in self._aux.items():
            self._aux_cursors[key] = _asof_index(series, decision_time)

    @property
    def index(self) -> int:
        if self._cursor < 0:
            return -1
        return self._index_offset + self._cursor

    @property
    def now(self) -> int:
        """Open time of the current bar."""
        self._require_seeked()
        return int(self._primary.ts[self._cursor])

    @property
    def decision_time(self) -> int:
        """When this bar's values became final — when the strategy decides."""
        self._require_seeked()
        return int(self._primary.close_times[self._cursor])

    @property
    def bar(self) -> Bar:
        return self.primary.bar

    @property
    def primary(self) -> MarketView:
        self._require_seeked()
        return MarketView(self._primary, self._cursor)

    # ---- primary shortcuts --------------------------------------------

    def open(self, n: int = 1) -> np.ndarray:
        return self.primary.open(n)

    def high(self, n: int = 1) -> np.ndarray:
        return self.primary.high(n)

    def low(self, n: int = 1) -> np.ndarray:
        return self.primary.low(n)

    def close(self, n: int = 1) -> np.ndarray:
        return self.primary.close(n)

    def volume(self, n: int = 1) -> np.ndarray:
        return self.primary.volume(n)

    # ---- auxiliary markets --------------------------------------------

    def market(self, inst_id: str, timeframe: str) -> MarketView:
        """An auxiliary market, aligned so nothing unknowable is visible."""
        self._require_seeked()
        key = (inst_id, timeframe)
        if key not in self._aux:
            raise KeyError(
                f"{key} is not an auxiliary market of this context; "
                f"declared: {sorted(self._aux)}"
            )
        return MarketView(self._aux[key], self._aux_cursors[key])

    @property
    def markets(self) -> Sequence[tuple[str, str]]:
        return sorted(self._aux)

    def _require_seeked(self) -> None:
        if self._cursor < 0:
            raise LookaheadError("context has not been positioned on a bar yet")


def _asof_index(series: Series, decision_time: int) -> int:
    """Index of the newest bar in `series` that had closed by `decision_time`.

    Returns -1 when none had. The comparison is against the *close* time, and
    inclusive: a bar that ends at the very instant of the decision is final,
    so it is knowable. Using the primary bar's open time instead would be
    safe but wrong in a different direction — it would lag every same-
    timeframe auxiliary market by a full bar.
    """
    return int(np.searchsorted(series.close_times, decision_time, side="right")) - 1
