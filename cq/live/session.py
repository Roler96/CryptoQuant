"""Paper/live execution through the engine's shared closed-bar loop.

`run_paper` prepares a `LiveEngineFeed` and a live implementation of
`LoopBroker`, then delegates strategy scheduling to `run_event_loop` — the same
function `run_backtest` calls with historical and simulated implementations.
The exchange still owns position and cash, so the live broker reconciles them
instead of applying fills to a simulated portfolio.

Timing, and how it maps to the backtest's fixed order of events:

* the backtest decides on bar t's close and fills at bar t+1's open;
* here, `LiveFeed` yields bar t only once it has closed; the strategy decides on
  it, and a market order goes out immediately, filling at the next tick — the
  opening of t+1. Same decision point, same "never act on an unclosed bar".

Sizing is explicit. REBALANCE re-derives quantity every bar; ON_ENTRY keeps a
durable logical active target and sizes only a target transition. The one
honest difference from the simulator is the sizing price: live uses bar t's
close because t+1's open is not knowable yet. The eventual venue fill can be
better or worse and is reconciled explicitly.

I/O is injected as `on_event`; the CLI passes a callback that prints and appends
to a session log.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable
from dataclasses import dataclass

from cq.context import Bar
from cq.core.types import Fill, Intent, Side, Sizing
from cq.data.feed import LiveEngineFeed
from cq.engine.loop import Strategy, run_event_loop
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
    open: float
    high: float
    low: float
    close: float
    volume: float
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
    sizing: str
    active_target_before: float
    active_target_after: float


class _LiveLoopBroker:
    """OKX-backed implementation of the shared loop broker contract."""

    def __init__(
        self,
        strategy: Strategy,
        broker: LiveBroker,
        inst_id: str,
        timeframe: str,
        average_entry: float | None,
        account_event_cursor: int | None,
        sizing: Sizing,
        active_target: float,
    ):
        self.strategy = strategy
        self.broker = broker
        self.inst_id = inst_id
        self.timeframe = timeframe
        self.average_entry = average_entry
        self.account_event_cursor = account_event_cursor
        self.sizing = sizing
        self.active = Intent(target=active_target)

    def before_bar(self, bar: Bar) -> None:
        """The venue has already applied fills, protection, funding and liq."""

    def after_bar(self, bar: Bar, intent: Intent | None) -> PaperEvent | None:
        if intent is None:
            return None

        # Validate persistence before an order can leave the process. A state
        # that cannot be logged is not crash recoverable and must fail closed.
        strategy_state = _snapshot_strategy(self.strategy)

        account_events: tuple[AccountEvent, ...] = ()
        if self.account_event_cursor is not None:
            event_end = self.broker.client.milliseconds()
            if event_end < self.account_event_cursor:
                raise RecoveryError(
                    "exchange clock moved backwards while reading swap account events"
                )
            if event_end > self.account_event_cursor:
                account_events = tuple(
                    self.broker.account_events(
                        self.account_event_cursor + 1,
                        event_end,
                    )
                )
                self.account_event_cursor = event_end

        state = self.broker.reconcile()
        if self.broker.is_effectively_flat(state.held):
            self.average_entry = None
        equity = state.equity(bar.close)
        active_target_before = self.active.target
        target_changed = intent.target != active_target_before
        should_size = self.sizing is Sizing.REBALANCE or target_changed
        delta = (
            self.broker.quantity_for_target(
                intent.target,
                bar.close,
                equity,
                state.held,
                state.cash,
            )
            if should_size
            else 0.0
        )
        target_client_id = client_order_id(
            "target",
            self.inst_id,
            bar.ts,
            intent.target,
            intent.stop_loss,
            intent.take_profit,
        )
        protection_client_id = client_order_id(
            "protection",
            self.inst_id,
            bar.ts,
            intent.target,
            intent.stop_loss,
            intent.take_profit,
        )
        before = len(self.broker.rejections)
        fill = None
        after = state
        if delta != 0:
            # The old exit may cover a different size or race a target close,
            # so remove it before the market order. Reconcile every outcome and
            # restore protection around whatever the exchange actually holds,
            # even when an order was rejected or its result was uncertain.
            previous = self.broker.active_protection
            self.broker.cancel_protection()
            try:
                fill = self.broker.execute(
                    delta,
                    bar.ts,
                    reason=intent.reason,
                    client_order_id=target_client_id,
                )
            except BaseException:
                after = self.broker.reconcile()
                if previous is not None:
                    self.broker.sync_protection(
                        after.held,
                        previous.stop_loss,
                        previous.take_profit,
                        client_order_id=client_order_id(
                            "restore",
                            self.inst_id,
                            bar.ts,
                            intent.target,
                            previous.stop_loss,
                            previous.take_profit,
                        ),
                    )
                else:
                    self.broker.sync_protection(
                        after.held,
                        intent.stop_loss,
                        intent.take_profit,
                        client_order_id=protection_client_id,
                    )
                raise
            after = self.broker.reconcile()
            if fill is None and previous is not None:
                # `execute` rejected before sending anything. Keep the old
                # safety net because the intended target was not reached.
                self.broker.sync_protection(
                    after.held,
                    previous.stop_loss,
                    previous.take_profit,
                    client_order_id=client_order_id(
                        "restore",
                        self.inst_id,
                        bar.ts,
                        intent.target,
                        previous.stop_loss,
                        previous.take_profit,
                    ),
                )
            elif (
                intent.target == 0
                and not self.broker.is_effectively_flat(after.held)
                and previous is not None
            ):
                # A partially filled close must protect its residual balance.
                self.broker.sync_protection(
                    after.held,
                    previous.stop_loss,
                    previous.take_profit,
                    client_order_id=client_order_id(
                        "restore",
                        self.inst_id,
                        bar.ts,
                        intent.target,
                        previous.stop_loss,
                        previous.take_profit,
                    ),
                )
            else:
                self.broker.sync_protection(
                    after.held,
                    intent.stop_loss,
                    intent.take_profit,
                    client_order_id=protection_client_id,
                )
        else:
            self.broker.sync_protection(
                state.held,
                intent.stop_loss,
                intent.take_profit,
                client_order_id=protection_client_id,
            )
        self.average_entry = _updated_average_entry(
            self.broker,
            self.average_entry,
            state,
            after,
            fill,
        )
        if self.sizing is Sizing.REBALANCE or fill is not None or not target_changed:
            self.active = intent
        rejected = len(self.broker.rejections) - before

        return PaperEvent(
            ts=bar.ts,
            inst_id=self.inst_id,
            timeframe=self.timeframe,
            strategy=self.strategy.name,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            volume=bar.volume,
            target=intent.target,
            reason=intent.reason,
            held=state.held,
            cash=state.cash,
            equity=equity,
            fill=fill,
            client_order_id=target_client_id if delta != 0 else None,
            rejected=rejected,
            protection=self.broker.active_protection,
            held_after=after.held,
            cash_after=after.cash,
            average_entry=self.average_entry,
            strategy_state=strategy_state,
            account_events=account_events,
            account_event_cursor=self.account_event_cursor,
            sizing=self.sizing.value,
            active_target_before=active_target_before,
            active_target_after=self.active.target,
        )


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
    sizing: Sizing = Sizing.REBALANCE,
) -> None:
    """Drive `strategy` against a live `feed`, routing targets to `broker`.

    `warmup` seeds enough closed history for the strategy to be past its warmup
    on the first live bar. `max_bars` bounds the run for tests and finite
    sessions; omit it for a session that runs until interrupted.
    """
    if not isinstance(sizing, Sizing):
        raise TypeError(f"sizing must be a Sizing value, got {sizing!r}")
    if resume is None:
        if sizing is Sizing.ON_ENTRY:
            state = broker.reconcile()
            if not broker.is_effectively_flat(state.held):
                raise RecoveryError("a fresh ON_ENTRY session requires a flat reconciled account")
        average_entry = None
        active_target = 0.0
        account_event_cursor = (
            broker.client.milliseconds() if broker.spec.market_type == "swap" else None
        )
    else:
        if resume.sizing is not sizing:
            raise RecoveryError(
                f"resume sizing {resume.sizing.value!r} does not match requested {sizing.value!r}"
            )
        restore = getattr(strategy, "restore_state", None)
        if not callable(restore):
            raise RecoveryError(
                f"strategy {strategy.name!r} has no restore_state() for checkpoint recovery"
            )
        restore(dict(resume.strategy_state))
        average_entry = resume.average_entry
        active_target = resume.active_target
        account_event_cursor = resume.account_event_cursor
        if broker.spec.market_type == "swap" and account_event_cursor is None:
            account_event_cursor = broker.client.milliseconds()

    engine_feed = LiveEngineFeed(
        feed,
        inst_id,
        timeframe,
        strategy.warmup_bars,
        warmup=warmup,
    )
    loop_broker = _LiveLoopBroker(
        strategy,
        broker,
        inst_id,
        timeframe,
        average_entry,
        account_event_cursor,
        sizing,
        active_target,
    )
    # A fresh run uses the loop's canonical reset. Recovery restored explicit
    # checkpoint state above, so the loop must preserve it.
    run_event_loop(
        strategy,
        engine_feed,
        loop_broker,
        on_event=on_event,
        max_bars=max_bars,
        reset_strategy=resume is None,
    )


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
