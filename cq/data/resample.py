"""Derive higher timeframes from the stored 1h base.

Only one granularity is ever fetched, so two timeframes cannot disagree about
the same instant. The cost is that aggregation has to be exact.

Incomplete groups are dropped rather than aggregated. A 4h bar built from
three hourly bars is not a 4h bar: its high and low are understated and its
close belongs to the wrong instant. That matters most at the tail, where an
in-progress period would otherwise become a bar that keeps changing.
"""

from __future__ import annotations

from typing import cast

import pandas as pd

from cq.core.clock import BASE_TIMEFRAME, bars_per, duration_ms

AGGREGATION = {
    "open": "first",
    "high": "max",
    "low": "min",
    "close": "last",
    "volume": "sum",
    "quote_volume": "sum",
}


def resample(
    frame: pd.DataFrame,
    timeframe: str,
    base: str = BASE_TIMEFRAME,
    require_complete: bool = True,
) -> pd.DataFrame:
    """Aggregate `base` bars up to `timeframe`, UTC-anchored.

    With `require_complete` (the default) a period is emitted only when every
    constituent base bar is present, so gaps propagate as missing periods
    instead of quietly distorting one.
    """
    if timeframe == base:
        return frame.copy()

    expected = bars_per(timeframe, base)
    if frame.empty:
        return frame.copy()

    rule = pd.Timedelta(milliseconds=duration_ms(timeframe))
    grouped = frame.resample(rule, label="left", closed="left", origin="epoch")

    columns = {name: how for name, how in AGGREGATION.items() if name in frame.columns}
    aggregated = cast(pd.DataFrame, grouped.agg(columns))
    counts = cast(pd.Series, grouped.size()).to_numpy()

    # `resample` materialises empty periods across gaps; those have no bars at
    # all and must go regardless of the completeness setting.
    keep = counts > 0
    if require_complete:
        keep = keep & (counts == expected)

    return aggregated.loc[keep]
