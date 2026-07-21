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

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from cq.context import Bar, Context
from cq.core.types import Fill, Side
from cq.data.feed import series_from_bars
from cq.engine.loop import Strategy
from cq.live.broker import LiveBroker, Reconciliation
from cq.live.ids import client_order_id
from cq.live.protocols import AccountEvent, ProtectiveOrder
from cq.live.recovery import RecoveryError, SessionResume


@dataclass(frozen=True)
class PaperEvent:
    """What happened on one closed bar of a paper session."""

    ts: int
    inst_id: str
    timeframe: str
    strategy: str
    close: float
    target: float
    reason: str
    held: float
    cash: float
    equity: float
    fill: Fill | None
    client_order_id: str | None
    rejected: int
    protection: ProtectiveOrder | None
    held_after: float
    cash_after: float
    average_entry: float | None
    strategy_state: dict[str, object] | None
    account_events: tuple[AccountEvent, ...]
    account_event_cursor: int | None


def run_paper(
    strategy: Strategy,
    broker: LiveBroker,
    feed: Iterable[Bar],
    inst_id: str,
    timeframe: str,
    warmup: Iterable[Bar] = (),
    on_event: Callable[[PaperEvent], None] | None = None,
    max_bars: int | None = None,
    resume: SessionResume | None = None,
) -> None:
    """Drive `strategy` against a live `feed`, routing targets to `broker`.

    `warmup` seeds enough closed history for the strategy to be past its warmup
    on the first live bar. `max_bars` bounds the run for tests and finite
    sessions; omit it for a session that runs until interrupted.
    """
    if resume is None:
        reset = getattr(strategy, "reset", None)
        if callable(reset):
            reset()
        average_entry = None
        account_event_cursor = (
            broker.client.milliseconds() if broker.spec.market_type == "swap" else None
        )
    else:
        restore = getattr(strategy, "restore_state", None)
        if not callable(restore):
            raise RecoveryError(
                f"strategy {strategy.name!r} has no restore_state() for checkpoint recovery"
            )
        restore(dict(resume.strategy_state))
        average_entry = resume.average_entry
        account_event_cursor = resume.account_event_cursor
        if broker.spec.market_type == "swap" and account_event_cursor is None:
            account_event_cursor = broker.client.milliseconds()

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
        # Validate persistence before an order can leave the process. A state
        # that cannot be logged is not crash recoverable and must fail closed.
        strategy_state = _snapshot_strategy(strategy)

        account_events: tuple[AccountEvent, ...] = ()
        if account_event_cursor is not None:
            event_end = broker.client.milliseconds()
            if event_end < account_event_cursor:
                raise RecoveryError(
                    "exchange clock moved backwards while reading swap account events"
                )
            if event_end > account_event_cursor:
                account_events = tuple(
                    broker.account_events(account_event_cursor + 1, event_end)
                )
                account_event_cursor = event_end

        state = broker.reconcile()
        if broker.is_effectively_flat(state.held):
            average_entry = None
        equity = state.equity(bar.close)
        delta = broker.quantity_for_target(
            intent.target, bar.close, equity, state.held, state.cash
        )
        target_client_id = client_order_id(
            "target",
            inst_id,
            bar.ts,
            intent.target,
            intent.stop_loss,
            intent.take_profit,
        )
        protection_client_id = client_order_id(
            "protection",
            inst_id,
            bar.ts,
            intent.target,
            intent.stop_loss,
            intent.take_profit,
        )
        before = len(broker.rejections)
        fill = None
        after = state
        if delta != 0:
            # The old exit may cover a different size or race a target close,
            # so remove it before the market order. Reconcile every outcome and
            # restore protection around whatever the exchange actually holds,
            # even when an order was rejected or its result was uncertain.
            previous = broker.active_protection
            broker.cancel_protection()
            try:
                fill = broker.execute(
                    delta,
                    bar.ts,
                    reason=intent.reason,
                    client_order_id=target_client_id,
                )
            except BaseException:
                after = broker.reconcile()
                if previous is not None:
                    broker.sync_protection(
                        after.held,
                        previous.stop_loss,
                        previous.take_profit,
                        client_order_id=client_order_id(
                            "restore",
                            inst_id,
                            bar.ts,
                            intent.target,
                            previous.stop_loss,
                            previous.take_profit,
                        ),
                    )
                else:
                    broker.sync_protection(
                        after.held,
                        intent.stop_loss,
                        intent.take_profit,
                        client_order_id=protection_client_id,
                    )
                raise
            after = broker.reconcile()
            if fill is None and previous is not None:
                # `execute` rejected before sending anything. Keep the old
                # safety net because the intended target was not reached.
                broker.sync_protection(
                    after.held,
                    previous.stop_loss,
                    previous.take_profit,
                    client_order_id=client_order_id(
                        "restore",
                        inst_id,
                        bar.ts,
                        intent.target,
                        previous.stop_loss,
                        previous.take_profit,
                    ),
                )
            elif (
                intent.target == 0
                and not broker.is_effectively_flat(after.held)
                and previous is not None
            ):
                # A partially filled close must protect its residual balance.
                broker.sync_protection(
                    after.held,
                    previous.stop_loss,
                    previous.take_profit,
                    client_order_id=client_order_id(
                        "restore",
                        inst_id,
                        bar.ts,
                        intent.target,
                        previous.stop_loss,
                        previous.take_profit,
                    ),
                )
            else:
                broker.sync_protection(
                    after.held,
                    intent.stop_loss,
                    intent.take_profit,
                    client_order_id=protection_client_id,
                )
        else:
            broker.sync_protection(
                state.held,
                intent.stop_loss,
                intent.take_profit,
                client_order_id=protection_client_id,
            )
        average_entry = _updated_average_entry(
            broker,
            average_entry,
            state,
            after,
            fill,
        )
        rejected = len(broker.rejections) - before

        if on_event is not None:
            on_event(
                PaperEvent(
                    ts=bar.ts,
                    inst_id=inst_id,
                    timeframe=timeframe,
                    strategy=strategy.name,
                    close=bar.close,
                    target=intent.target,
                    reason=intent.reason,
                    held=state.held,
                    cash=state.cash,
                    equity=equity,
                    fill=fill,
                    client_order_id=target_client_id if delta != 0 else None,
                    rejected=rejected,
                    protection=broker.active_protection,
                    held_after=after.held,
                    cash_after=after.cash,
                    average_entry=average_entry,
                    strategy_state=strategy_state,
                    account_events=account_events,
                    account_event_cursor=account_event_cursor,
                )
            )

        seen += 1
        if max_bars is not None and seen >= max_bars:
            return


def _updated_average_entry(
    broker: LiveBroker,
    previous: float | None,
    before: Reconciliation,
    after: Reconciliation,
    fill: Fill | None,
) -> float | None:
    """Average quote cost of spot, or the venue's swap entry price.

    Cash movement, rather than the normalized fee field, captures whether OKX
    charged a buy fee in base or quote currency. Sells leave the average of the
    remaining units unchanged.
    """
    if broker.is_effectively_flat(after.held):
        return None
    if broker.spec.market_type == "swap":
        return after.average_entry
    if fill is None or fill.side is Side.SELL:
        return previous

    if broker.is_effectively_flat(before.held):
        old_cost = 0.0
    elif previous is not None:
        old_cost = before.held * previous
    else:
        return None
    cash_spent = before.cash - after.cash
    if cash_spent <= 0:
        return None
    return (old_cost + cash_spent) / after.held


def _snapshot_strategy(strategy: Strategy) -> dict[str, object] | None:
    """Copy a JSON-serialisable strategy checkpoint, if it exposes one."""
    snapshot = getattr(strategy, "snapshot_state", None)
    if not callable(snapshot):
        return None
    state = snapshot()
    if not isinstance(state, dict):
        raise TypeError(f"strategy {strategy.name!r} snapshot_state() must return a dict")
    copied = dict(state)
    try:
        json.dumps(copied, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise TypeError(f"strategy {strategy.name!r} returned non-JSON checkpoint state") from exc
    return copied
