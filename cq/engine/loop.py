"""The single closed-bar event loop.

`run_event_loop` drives backtest, paper and live. Only its `EngineFeed` and
`LoopBroker` implementations differ, so warmup, strategy timing, lifecycle,
observer dispatch and finite-run behavior cannot drift into separate runtime
implementations.

For the simulated broker, the fixed within-bar sequence is:

1. funding settled up to and including this bar's open, against the position
   carried in, priced at the open;
2. the target decided on the *previous* bar, filled at this bar's open;
3. protective exits and liquidation, triggered from this bar's high and low;
4. funding settled strictly inside the bar, against the position now held,
   priced at the close;
5. the shared loop lets the strategy see the closed bar and name a target;
6. the broker marks equity at the close.

The live broker observes the same two loop phases, but the venue has already
applied funding, protective exits and liquidation to the reconciled account.
The target named after the close is submitted immediately for the next market
tick instead of being filled from a historical next-open value.

Splitting funding across steps 1 and 4 is what makes it land on the position
that actually existed at each settlement. Charging every settlement in a bar
before the bar's own order — the earlier arrangement here — meant that on
daily bars an entry at 00:00 escaped the 08:00 and 16:00 settlements it held
through, while an exit at 00:00 was charged for settlements it had already
left. Step 1 also reaches back to the previous bar's close rather than to
this bar's open, so settlements inside a data gap are still charged instead
of vanishing with the missing bars.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from typing import Protocol, TypeVar

from cq.context import Bar, Context, Series, series_fingerprint
from cq.core.clock import duration_ms
from cq.core.types import CostModel, Fill, Intent, MarketSpec, Sizing
from cq.data.feed import EngineFeed, HistoricalEngineFeed
from cq.engine.funding import FundingModel, NoFunding
from cq.engine.portfolio import FundingPayment, Portfolio
from cq.engine.sim import Rejection, SimBroker

# Bumped whenever a change alters the numbers a run produces from identical
# inputs. Pinned into every RunManifest so a result carries the engine that
# made it, and two runs computed by different engines are never mistaken for
# reproductions of each other.
ENGINE_VERSION = "cq-engine/1"


class Strategy(Protocol):
    """Sees only a Context, returns only a target."""

    @property
    def name(self) -> str: ...

    @property
    def warmup_bars(self) -> int: ...

    def on_bar(self, ctx: Context) -> Intent: ...


class Resettable(Protocol):
    """A strategy that carries state between bars and can clear it."""

    def reset(self) -> None: ...


class Checkpointable(Protocol):
    """A live strategy whose mutable state can survive a process restart."""

    def snapshot_state(self) -> dict[str, object]: ...

    def restore_state(self, state: dict[str, object]) -> None: ...


EventT_co = TypeVar("EventT_co", covariant=True)
EventT = TypeVar("EventT")


class LoopBroker(Protocol[EventT_co]):
    """Execution boundary used by the one shared closed-bar event loop.

    `before_bar` handles everything that happened before the strategy may see
    this closed bar: a simulated next-open fill and intrabar exits in a
    backtest, or exchange reconciliation hooks in live trading.

    `after_bar` accepts the target decided from that closed bar. A simulated
    broker queues it for the next historical open; a live broker routes it to
    the venue immediately after the close so it reaches the next market tick.
    """

    def before_bar(self, bar: Bar) -> None: ...

    def after_bar(self, bar: Bar, intent: Intent | None) -> EventT_co | None: ...


def run_event_loop(
    strategy: Strategy,
    feed: EngineFeed,
    broker: LoopBroker[EventT],
    *,
    on_event: Callable[[EventT], None] | None = None,
    max_bars: int | None = None,
    reset_strategy: bool = True,
) -> None:
    """Drive backtest, paper and live through one fixed event sequence.

    Feed implementations own only causal context construction. Broker
    implementations own only execution/account state. Strategy scheduling,
    warmup enforcement, lifecycle reset, observer dispatch and finite-run
    bounds live here once.
    """
    if reset_strategy:
        reset = getattr(strategy, "reset", None)
        if callable(reset):
            reset()

    decisions = 0
    for item in feed:
        broker.before_bar(item.bar)
        intent = (
            strategy.on_bar(item.context)
            if item.context is not None
            else None
        )
        event = broker.after_bar(item.bar, intent)
        if intent is None:
            continue
        if event is not None and on_event is not None:
            on_event(event)
        decisions += 1
        if max_bars is not None and decisions >= max_bars:
            return


@dataclass(frozen=True)
class RunManifest:
    """The fingerprinted inputs a run consumed, captured as it ran.

    The point of provenance is to bind a result to the data and configuration
    that produced it. The earlier design left the data unbound: the report
    fingerprinted whatever series the caller later handed it, and its match
    check only compared instrument, timeframe, bar count and first timestamp.
    Any doctored copy agreeing on those four could be reported, in the report's
    own words, as the data behind a result it never touched — run on data A,
    edit a price, hand the reporter data B, and the report would swear the
    figures came from B.

    Frozen, and computed here rather than in the reporter, so it is the one
    authority on what the run saw. `primary_fingerprint` covers the full
    content of every bar; the reporter verifies any series it is shown against
    this rather than deciding for itself what the run consumed.
    """

    primary_fingerprint: str
    # (inst_id, timeframe, fingerprint) per auxiliary market, in the order the
    # run received them. A run that read a second series cannot be reproduced
    # from the primary alone, so the aux data is pinned too.
    aux_fingerprints: tuple[tuple[str, str, str], ...]
    market_spec_fingerprint: str
    funding_fingerprint: str
    cost_fingerprint: str
    sizing: str
    initial_cash: float
    engine_version: str = ENGINE_VERSION


def _spec_fingerprint(spec: MarketSpec) -> str:
    """Hash of the exchange rules a run was sized and liquidated under.

    Bound because the same strategy on the same bars is a different backtest
    under a different lot size, minimum notional, leverage cap or maintenance
    margin — and reporting one under the other's spec would misdescribe how the
    result could ever be reproduced.
    """
    payload = "|".join(
        repr(value)
        for value in (
            spec.inst_id,
            spec.market_type,
            spec.lot_size,
            spec.min_notional,
            spec.max_leverage,
            spec.maintenance_margin_rate,
        )
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def _cost_fingerprint(costs: CostModel) -> str:
    """Hash of the fee and slippage a run was charged."""
    payload = f"{costs.fee_bps!r}|{costs.slippage_bps!r}"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


@dataclass
class RunResult:
    """Everything a run produced, with the assumptions that produced it."""

    # The authoritative, frozen record of what this run consumed. A report reads
    # its provenance from here rather than re-deriving it from a series a caller
    # passes after the fact.
    manifest: RunManifest
    strategy: str
    inst_id: str
    timeframe: str
    market_type: str
    funding_label: str
    funding_fingerprint: str
    cost_label: str
    sizing: str
    initial_cash: float
    portfolio: Portfolio
    # Auxiliary markets the strategy could read. Recorded because a run that
    # consumed a second series cannot be reproduced from the primary alone.
    aux_keys: tuple[tuple[str, str], ...] = ()
    timestamps: list[int] = field(default_factory=list)
    equity: list[float] = field(default_factory=list)
    fills: list[Fill] = field(default_factory=list)
    funding_payments: list[FundingPayment] = field(default_factory=list)
    rejections: list[Rejection] = field(default_factory=list)

    @property
    def final_equity(self) -> float:
        return self.equity[-1] if self.equity else self.initial_cash

    @property
    def total_return(self) -> float:
        return self.final_equity / self.initial_cash - 1.0

    @property
    def bars(self) -> int:
        return len(self.equity)

    def summary(self) -> str:
        return (
            f"{self.strategy} on {self.inst_id} {self.timeframe} ({self.market_type})\n"
            f"  bars {self.bars}, fills {len(self.fills)}, "
            f"rejected {len(self.rejections)}\n"
            f"  return {self.total_return * 100:+.2f}%  "
            f"final equity {self.final_equity:,.2f}\n"
            f"  costs {self.cost_label}\n"
            f"  funding {self.funding_label}\n"
            f"  sizing {self.sizing}"
        )


class _BacktestLoopBroker:
    """Simulated implementation of the shared loop broker contract."""

    def __init__(
        self,
        *,
        broker: SimBroker,
        portfolio: Portfolio,
        result: RunResult,
        funding: FundingModel,
        sizing: Sizing,
        bar_ms: int,
        first_ts: int,
    ):
        self.broker = broker
        self.portfolio = portfolio
        self.result = result
        self.funding = funding
        self.sizing = sizing
        self.bar_ms = bar_ms
        self.pending: Intent | None = None
        self.active = Intent()
        self.is_swap = broker.spec.market_type == "swap"
        self.settled_through = first_ts

    def before_bar(self, bar: Bar) -> None:
        """Apply the pre-decision half of the canonical bar sequence."""
        if self.is_swap:
            for ts, rate in self.funding.settlements(
                self.settled_through, bar.ts + 1
            ):
                if not self.portfolio.is_flat:
                    self.result.funding_payments.append(
                        self.portfolio.apply_funding(ts, rate, bar.open)
                    )

        if self.pending is not None:
            target_changed = self.pending.target != self.active.target
            if self.sizing is Sizing.REBALANCE or target_changed:
                delta = self.broker.quantity_for_target(
                    self.pending.target,
                    bar.open,
                    self.portfolio.equity(bar.open),
                    self.portfolio.quantity,
                    self.portfolio.cash,
                )
                fill = self.broker.execute(
                    self.portfolio,
                    bar,
                    delta,
                    reason=self.pending.reason,
                )
                if fill is not None:
                    self.result.fills.append(fill)
                    self.active = self.pending
                    self.pending = None
            else:
                self.active = self.pending
                self.pending = None

        exit_now = self.broker.triggered_exit(
            self.portfolio,
            bar,
            self.active.stop_loss,
            self.active.take_profit,
        )
        if exit_now is not None:
            price, reason = exit_now
            fill = self.broker.execute(
                self.portfolio,
                bar,
                -self.portfolio.quantity,
                reason=reason,
                reference_price=price,
            )
            if fill is not None:
                self.result.fills.append(fill)
                self.active = Intent()
                self.pending = None

        if self.is_swap:
            for ts, rate in self.funding.settlements(
                bar.ts + 1, bar.ts + self.bar_ms
            ):
                if not self.portfolio.is_flat:
                    self.result.funding_payments.append(
                        self.portfolio.apply_funding(ts, rate, bar.close)
                    )
        self.settled_through = bar.ts + self.bar_ms

    def after_bar(self, bar: Bar, intent: Intent | None) -> None:
        """Queue this close's decision and mark the simulated account."""
        if intent is not None:
            self.pending = intent
        self.result.timestamps.append(bar.ts)
        self.result.equity.append(self.portfolio.equity(bar.close))


def run_backtest(
    strategy: Strategy,
    primary: Series,
    spec: MarketSpec,
    initial_cash: float = 10_000.0,
    costs: CostModel | None = None,
    funding: FundingModel | None = None,
    aux: Iterable[Series] = (),
    sizing: Sizing = Sizing.ON_ENTRY,
    dust_fraction: float | None = None,
) -> RunResult:
    """Replay `primary` through `strategy`, one bar at a time.

    `dust_fraction` is the smallest position adjustment the broker will act on,
    as a fraction of equity; a delta whose notional is below it is dropped. Its
    default is a float-noise floor that keeps a held position from re-trading on
    rounding crumbs. Under `Sizing.REBALANCE`, where the quantity is re-derived
    every bar, raising it turns that floor into an explicit no-trade band: a
    constant-weight target then only rebalances once its weight has drifted by
    more than `dust_fraction`, because the delta's notional is
    `|target - current| * equity` to first order. That is the one knob that
    separates a band rebalancer from a continuous one, so it is a caller choice
    rather than a fixed constant.
    """
    costs = costs or CostModel()
    funding = funding or NoFunding()
    broker = (
        SimBroker(spec, costs)
        if dust_fraction is None
        else SimBroker(spec, costs, dust_fraction)
    )
    portfolio = Portfolio(spec, initial_cash)
    aux = list(aux)
    # Fingerprint the inputs before the loop touches them. The Series columns
    # are read-only, so what is hashed here is exactly what the run replays.
    manifest = RunManifest(
        primary_fingerprint=series_fingerprint(primary),
        aux_fingerprints=tuple(
            (s.inst_id, s.timeframe, series_fingerprint(s)) for s in aux
        ),
        market_spec_fingerprint=_spec_fingerprint(spec),
        funding_fingerprint=getattr(funding, "fingerprint", "unidentified"),
        cost_fingerprint=_cost_fingerprint(costs),
        sizing=sizing.value,
        initial_cash=initial_cash,
    )

    result = RunResult(
        manifest=manifest,
        strategy=strategy.name,
        inst_id=spec.inst_id,
        timeframe=primary.timeframe,
        market_type=spec.market_type,
        funding_label=funding.label,
        funding_fingerprint=getattr(funding, "fingerprint", "unidentified"),
        cost_label=f"{costs.fee_bps:.1f} bps fee + {costs.slippage_bps:.1f} bps slippage per side",
        sizing=sizing.value,
        initial_cash=initial_cash,
        portfolio=portfolio,
        aux_keys=tuple(series.key for series in aux),
    )

    loop_broker = _BacktestLoopBroker(
        broker=broker,
        portfolio=portfolio,
        result=result,
        funding=funding,
        sizing=sizing,
        bar_ms=duration_ms(primary.timeframe),
        first_ts=int(primary.ts[0]) if len(primary) else 0,
    )
    feed = HistoricalEngineFeed(primary, strategy.warmup_bars, aux=aux)
    run_event_loop(strategy, feed, loop_broker)

    result.rejections = broker.rejections
    return result
