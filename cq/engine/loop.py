"""The matching loop.

One loop drives backtest, paper and live: only the broker and the feed
differ. That is the structural reason a backtest here cannot be more
optimistic than live — there is no second implementation to drift from.

Order of events within a bar, fixed and singular:

1. funding settled up to and including this bar's open, against the position
   carried in, priced at the open;
2. the target decided on the *previous* bar, filled at this bar's open;
3. protective exits and liquidation, triggered from this bar's high and low;
4. funding settled strictly inside the bar, against the position now held,
   priced at the close;
5. the strategy sees the closed bar and names a target for the next one;
6. equity is marked at the close.

Step 5 comes after steps 2-3 by construction, so a strategy cannot act on a
bar before that bar has finished.

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

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Protocol

from cq.context import Context, Series
from cq.core.clock import duration_ms
from cq.core.types import CostModel, Fill, Intent, MarketSpec, Sizing
from cq.engine.funding import FundingModel, NoFunding
from cq.engine.portfolio import FundingPayment, Portfolio
from cq.engine.sim import Rejection, SimBroker


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


@dataclass
class RunResult:
    """Everything a run produced, with the assumptions that produced it."""

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


def run_backtest(
    strategy: Strategy,
    primary: Series,
    spec: MarketSpec,
    initial_cash: float = 10_000.0,
    costs: CostModel | None = None,
    funding: FundingModel | None = None,
    aux: Iterable[Series] = (),
    sizing: Sizing = Sizing.ON_ENTRY,
) -> RunResult:
    """Replay `primary` through `strategy`, one bar at a time."""
    costs = costs or CostModel()
    funding = funding or NoFunding()
    broker = SimBroker(spec, costs)
    portfolio = Portfolio(spec, initial_cash)
    aux = list(aux)
    ctx = Context(primary, aux=aux)
    bar_ms = duration_ms(primary.timeframe)

    # A strategy instance carries state — DonchianTrend remembers its target —
    # and instances get reused across splits and parameter sweeps. Without
    # this, run two picks up mid-position from run one and prints a trade that
    # belongs to neither.
    reset = getattr(strategy, "reset", None)
    if callable(reset):
        reset()

    result = RunResult(
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

    pending: Intent | None = None
    active = Intent()
    is_swap = spec.market_type == "swap"
    # Funding is charged over elapsed time, not per bar, so the window starts
    # where the last one ended. On the first bar there is nothing before it.
    settled_through = int(primary.ts[0]) if len(primary) else 0

    for i in range(len(primary)):
        ctx.seek(i)
        bar = ctx.bar

        # 1. Funding settled since the last bar closed, up to and including
        #    this bar's open, on the position carried in. The `+ 1` makes a
        #    settlement falling exactly on the open belong to this window:
        #    it is paid by whoever held through it, before any order fills.
        if is_swap:
            for ts, rate in funding.settlements(settled_through, bar.ts + 1):
                if not portfolio.is_flat:
                    result.funding_payments.append(
                        portfolio.apply_funding(ts, rate, bar.open)
                    )

        # 2. Last bar's decision fills at this bar's open.
        if pending is not None:
            target_changed = pending.target != active.target
            if sizing is Sizing.REBALANCE or target_changed:
                delta = broker.quantity_for_target(
                    pending.target,
                    bar.open,
                    portfolio.equity(bar.open),
                    portfolio.quantity,
                    portfolio.cash,
                )
                fill = broker.execute(portfolio, bar, delta, reason=pending.reason)
                if fill is not None:
                    result.fills.append(fill)
                    active = pending
                    pending = None
            else:
                # ON_ENTRY: an unchanged target holds its quantity. Re-deriving
                # it every bar would trim the position as it moves in favour.
                active = pending
                pending = None

        # 3. Protective exits and liquidation, from this bar's range.
        exit_now = broker.triggered_exit(portfolio, bar, active.stop_loss, active.take_profit)
        if exit_now is not None:
            price, reason = exit_now
            fill = broker.execute(
                portfolio, bar, -portfolio.quantity, reason=reason, reference_price=price
            )
            if fill is not None:
                result.fills.append(fill)
                active = Intent()
                pending = None

        # 4. Funding settled strictly inside the bar, on the position actually
        #    held after this bar's trading, marked at the last price known.
        if is_swap:
            for ts, rate in funding.settlements(bar.ts + 1, bar.ts + bar_ms):
                if not portfolio.is_flat:
                    result.funding_payments.append(
                        portfolio.apply_funding(ts, rate, bar.close)
                    )
        settled_through = bar.ts + bar_ms

        # 5. Only now may the strategy see this bar.
        if i + 1 >= strategy.warmup_bars:
            pending = strategy.on_bar(ctx)

        # 6. Mark to close.
        result.timestamps.append(bar.ts)
        result.equity.append(portfolio.equity(bar.close))

    result.rejections = broker.rejections
    return result
