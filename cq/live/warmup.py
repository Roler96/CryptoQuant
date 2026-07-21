"""Seed a strategy's warmup from the local store when one poll is not enough.

`LiveFeed.prime()` returns at most one page (~100 bars). A strategy whose
`warmup_bars` exceeds that — Donchian's 120/60 needs 121 — would otherwise
spend its first ~20 live bars silently building state and emitting nothing.

The shortfall is read from the local OHLCV store (the same `load_series` path
the backtest uses) and placed strictly ahead of the primed backlog, so the seam
is contiguous and the live feed still only ever acts on bars that close from the
primed high-water mark forward.
"""

from __future__ import annotations

from pathlib import Path

from cq.context import Bar
from cq.core.clock import duration_ms, floor_to_bar
from cq.data.feed import HistoricalFeed, load_series
from cq.data.store import Store


def seed_warmup(
    db_path: str | Path,
    backlog: list[Bar],
    inst_id: str,
    timeframe: str,
    warmup_bars: int,
    requested: int = 0,
) -> list[Bar]:
    """Closed bars to seed so a strategy is past its warmup on the first live bar.

    Returns up to ``max(requested, warmup_bars)`` bars ending exactly at the last
    primed bar, filling any shortfall from the store. When the store cannot cover
    the gap the caller simply gets fewer bars (and can warn) rather than an
    exception — an under-warmed strategy decides later, it never decides wrongly.
    """
    needed = max(requested, warmup_bars)
    if needed <= 0 or not backlog or len(backlog) >= needed:
        return backlog[-needed:] if needed > 0 else []

    shortfall = needed - len(backlog)
    oldest = backlog[0].ts
    # Floor to a whole bar so any resampled group is complete; the surplus is
    # dropped by the final slice. `end_ms=oldest` is exclusive, so store bars are
    # strictly older than the backlog and the seam cannot overlap or gap.
    start_ms = floor_to_bar(oldest - (shortfall + 4) * duration_ms(timeframe), timeframe)
    with Store(db_path) as store:
        series = load_series(store, inst_id, timeframe, start_ms=start_ms, end_ms=oldest)
    history = list(HistoricalFeed(series))
    return (history + backlog)[-needed:]
