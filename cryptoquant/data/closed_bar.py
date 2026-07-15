"""Closed-bar data feed — guarantees the last OHLCV bar is fully closed.

Phase 2 module. Wraps LiveDataFeed and strips the current (still-forming)
bar so the engine never generates signals from incomplete candles.

See review 2.1: "实盘用尚未闭合的 K 线生成信号"
"""

import time as _time
from typing import cast

import pandas as pd

from cryptoquant.data.live_feed import LiveDataFeed
from cryptoquant.utils import timeframe_to_seconds


class ClosedBarFeed:
    """Wraps a LiveDataFeed and guarantees the last bar is closed.

    The wrapped feed returns whatever the exchange gives, including the
    current (unclosed) candle. ClosedBarFeed strips that bar and only
    returns fully-formed candle data.

    Usage:
        raw_feed = LiveDataFeed(fetcher, store, ...)
        feed = ClosedBarFeed(raw_feed)

        df, meta = feed.fetch(lookback=200)
        # df never contains incomplete candles
        # meta.has_new_closed_bar → True when a new bar closed since last fetch
    """

    def __init__(self, live_feed: LiveDataFeed):
        self._feed = live_feed
        self._last_closed_ts: int = 0  # Unix ms of last closed bar we returned

    def fetch(self, lookback: int) -> tuple[pd.DataFrame, "BarFetchMeta"]:
        """Fetch bars and strip any unclosed candle.

        Returns:
            df: DataFrame containing only closed bars (may be empty).
            meta: Metadata about what happened in this fetch.
        """
        df = self._feed.fetch(lookback)

        if df.empty:
            return df, BarFetchMeta(has_new_closed=False, stripped=0)

        tf_ms = timeframe_to_seconds(self._feed.timeframe) * 1000
        now_ms = int(_time.time() * 1000)

        # A bar at timestamp T closes at T + tf_ms.
        # If now < T + tf_ms, the bar is still forming.
        stripped = 0
        execution_price: float | None = None
        while len(df) > 0:
            last_bar_open = cast(pd.Timestamp, df.index[-1])
            last_bar_open_ms = int(last_bar_open.value // 1_000_000)
            last_bar_close_ms = last_bar_open_ms + tf_ms

            if now_ms < last_bar_close_ms:
                # This bar hasn't closed yet — strip it from signal inputs.
                # Its latest trade is nevertheless a causal paper-fill proxy.
                # Immediately after the boundary this is approximately the
                # backtest's next-bar open; if context arrives late it updates
                # toward the actually executable market instead of replaying
                # a stale closed-candle price.
                execution_price = float(df["close"].iloc[-1])
                df = df.iloc[:-1]
                stripped += 1
            else:
                break

        # Determine if we have a NEW closed bar since last fetch
        has_new = False
        latest_ts = 0
        if len(df) > 0:
            latest = cast(pd.Timestamp, df.index[-1])
            latest_ts = int(latest.value // 1_000_000)
            if latest_ts != self._last_closed_ts:
                has_new = True
                self._last_closed_ts = latest_ts

        return df, BarFetchMeta(
            has_new_closed=has_new,
            stripped=stripped,
            common_bar_ts=latest_ts,
            decision_ready=len(df) > 0,
            execution_price=execution_price,
        )

    @property
    def last_fetch_ts(self) -> int:
        return self._feed.last_fetch_ts

    @property
    def last_quality_report(self):
        return self._feed.last_quality_report

    @property
    def symbol(self) -> str:
        return self._feed.symbol

    @property
    def timeframe(self) -> str:
        return self._feed.timeframe

    def stats(self) -> dict:
        stats = self._feed.stats()
        stats["last_closed_ts"] = self._last_closed_ts
        return stats


class BarFetchMeta:
    """Metadata returned alongside bars from ClosedBarFeed.fetch()."""

    def __init__(
        self,
        has_new_closed: bool = False,
        stripped: int = 0,
        common_bar_ts: int = 0,
        decision_ready: bool = True,
        issues: tuple[str, ...] = (),
        execution_price: float | None = None,
    ):
        self.has_new_closed = has_new_closed
        self.stripped = stripped  # number of unclosed bars stripped
        self.common_bar_ts = common_bar_ts
        self.decision_ready = decision_ready
        self.issues = issues
        self.execution_price = execution_price
