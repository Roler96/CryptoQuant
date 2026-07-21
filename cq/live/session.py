"""The paper trading session — the live counterpart of `run_backtest`.

It shares the pieces that must not diverge from the backtest: the strategy sees
a `Context` over closed bars only, and the target it names is sized by the same
`target_delta`. What is genuinely different lives in `LiveBroker` — the exchange
holds the position and the cash, so each bar reconciles against it rather than
against a simulated portfolio.

Timing, and how it maps to the backtest's fixed order of events:

* the backtest decides on bar t's close and fills at bar t+1's open;
* here, `LiveFeed` yields bar t only once it has closed; the strategy decides on
  it, and a market order goes out immediately, filling at the next tick — the
  opening of t+1. Same decision point, same "never act on an unclosed bar".

The one honest difference: sizing uses bar t's close as the price, because t+1's
open is not knowable yet. That is the last price available at the decision, and
it makes live no more optimistic than the backtest — if anything the fill can
be a touch worse, never better.

I/O is injected as `on_event` so the loop itself stays pure and testable; the
CLI passes a callback that prints and appends to a session log.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from cq.context import Bar, Context
from cq.core.types import Fill
from cq.data.feed import series_from_bars
from cq.engine.loop import Strategy
from cq.live.broker import LiveBroker


@dataclass(frozen=True)
class PaperEvent:
    """What happened on one closed bar of a paper session."""

    ts: int
    close: float
    target: float
    reason: str
    held: float
    cash: float
    equity: float
    fill: Fill | None
    rejected: int


def run_paper(
    strategy: Strategy,
    broker: LiveBroker,
    feed: Iterable[Bar],
    inst_id: str,
    timeframe: str,
    warmup: Iterable[Bar] = (),
    on_event: Callable[[PaperEvent], None] | None = None,
    max_bars: int | None = None,
) -> None:
    """Drive `strategy` against a live `feed`, routing targets to `broker`.

    `warmup` seeds enough closed history for the strategy to be past its warmup
    on the first live bar. `max_bars` bounds the run for tests and finite
    sessions; omit it for a session that runs until interrupted.
    """
    reset = getattr(strategy, "reset", None)
    if callable(reset):
        reset()

    bars: list[Bar] = list(warmup)
    # Keep the rolling window bounded but always longer than the strategy can
    # look back, so a long session does not grow without limit.
    keep = max(strategy.warmup_bars * 4, 256)
    seen = 0

    for bar in feed:
        bars.append(bar)
        if len(bars) > keep:
            del bars[: len(bars) - keep]
        if len(bars) < strategy.warmup_bars:
            continue

        series = series_from_bars(inst_id, timeframe, bars)
        ctx = Context(series)
        ctx.seek(len(bars) - 1)
        intent = strategy.on_bar(ctx)

        state = broker.reconcile()
        equity = state.equity(bar.close)
        delta = broker.quantity_for_target(
            intent.target, bar.close, equity, state.held, state.cash
        )
        before = len(broker.rejections)
        fill = broker.execute(delta, bar.ts, reason=intent.reason) if delta != 0 else None
        rejected = len(broker.rejections) - before

        if on_event is not None:
            on_event(
                PaperEvent(
                    ts=bar.ts,
                    close=bar.close,
                    target=intent.target,
                    reason=intent.reason,
                    held=state.held,
                    cash=state.cash,
                    equity=equity,
                    fill=fill,
                    rejected=rejected,
                )
            )

        seen += 1
        if max_bars is not None and seen >= max_bars:
            return
