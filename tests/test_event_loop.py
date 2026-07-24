"""The architectural invariant: every runtime uses one closed-bar driver."""

from dataclasses import dataclass, field

import numpy as np

from cq.context import Bar, Context, Series
from cq.core.types import Intent
from cq.data.feed import HistoricalEngineFeed, LiveEngineFeed
from cq.engine.loop import run_event_loop

HOUR = 3_600_000


def series(count: int = 4) -> Series:
    values = np.arange(1, count + 1, dtype=float)
    return Series(
        "DOGE-USDT",
        "1h",
        np.arange(count, dtype=np.int64) * HOUR,
        values,
        values,
        values,
        values,
        np.full(count, 100.0),
    )


@dataclass
class RecordingStrategy:
    log: list[tuple] = field(default_factory=list)
    name = "recording"
    warmup_bars = 2

    def reset(self) -> None:
        self.log.append(("reset",))

    def on_bar(self, ctx: Context) -> Intent:
        self.log.append(("strategy", ctx.index))
        return Intent(target=0.0, reason=str(ctx.index))


@dataclass
class RecordingBroker:
    log: list[tuple]

    def before_bar(self, bar: Bar) -> None:
        self.log.append(("before", bar.ts))

    def after_bar(self, bar: Bar, intent: Intent | None) -> tuple | None:
        target = None if intent is None else intent.target
        self.log.append(("after", bar.ts, target))
        return None if intent is None else ("event", bar.ts)


def test_shared_loop_owns_warmup_order_reset_observation_and_bounds():
    strategy = RecordingStrategy()
    broker = RecordingBroker(strategy.log)
    events = []

    run_event_loop(
        strategy,
        HistoricalEngineFeed(series(), strategy.warmup_bars),
        broker,
        on_event=events.append,
        max_bars=2,
    )

    assert strategy.log == [
        ("reset",),
        ("before", 0),
        ("after", 0, None),
        ("before", HOUR),
        ("strategy", 1),
        ("after", HOUR, 0.0),
        ("before", 2 * HOUR),
        ("strategy", 2),
        ("after", 2 * HOUR, 0.0),
    ]
    assert events == [("event", HOUR), ("event", 2 * HOUR)]


def test_historical_and_live_engine_feeds_expose_identical_causal_contexts():
    primary = series(300)
    historical = HistoricalEngineFeed(primary, warmup_bars=3)
    live = LiveEngineFeed(
        (event.bar for event in HistoricalEngineFeed(primary, warmup_bars=0)),
        primary.inst_id,
        primary.timeframe,
        warmup_bars=3,
    )

    def visible(feed):
        result = []
        for event in feed:
            if event.context is None:
                result.append(None)
                continue
            result.append(
                (
                    event.context.index,
                    event.context.close(3).tolist(),
                )
            )
        return result

    assert visible(live) == visible(historical)


def test_context_offset_preserves_unpositioned_sentinel_and_logical_index():
    context = Context(series(2), index_offset=50)

    assert context.index == -1
    context.seek(0)
    assert context.index == 50
