"""The matching loop.

One loop drives backtest, paper and live: only the broker and the feed
differ. That is the structural reason a backtest here cannot be more
optimistic than live — there is no second implementation to drift from.

Order of events within a bar, fixed and singular:

1. funding settlements that fall inside the bar, against the position carried in;
2. the target decided on the *previous* bar, filled at this bar's open;
3. protective exits, triggered from this bar's high and low;
4. the strategy sees the closed bar and names a target for the next one;
5. equity is marked at the close.

Step 4 comes after steps 2-3 by construction, so a strategy cannot act on a
bar before that bar has finished.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Protocol

from cq.context import Context, Series
from cq.core.clock import duration_ms
from cq.core.types import CostModel, Fill, Intent, MarketSpec
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


@dataclass
class RunResult:
    """Everything a run produced, with the assumptions that produced it."""

    strategy: str
    inst_id: str
    timeframe: str
    market_type: str
    funding_label: str
    cost_label: str
    initial_cash: float
    portfolio: Portfolio
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
            f"  funding {self.funding_label}"
        )


def run_backtest(
    strategy: Strategy,
    primary: Series,
    spec: MarketSpec,
    initial_cash: float = 10_000.0,
    costs: CostModel | None = None,
    funding: FundingModel | None = None,
    aux: Iterable[Series] = (),
) -> RunResult:
    """Replay `primary` through `strategy`, one bar at a time."""
    costs = costs or CostModel()
    funding = funding or NoFunding()
    broker = SimBroker(spec, costs)
    portfolio = Portfolio(spec, initial_cash)
    ctx = Context(primary, aux=aux)
    bar_ms = duration_ms(primary.timeframe)

    result = RunResult(
        strategy=strategy.name,
        inst_id=spec.inst_id,
        timeframe=primary.timeframe,
        market_type=spec.market_type,
        funding_label=funding.label,
        cost_label=f"{costs.fee_bps:.1f} bps fee + {costs.slippage_bps:.1f} bps slippage per side",
        initial_cash=initial_cash,
        portfolio=portfolio,
    )

    pending: Intent | None = None
    active = Intent()

    for i in range(len(primary)):
        ctx.seek(i)
        bar = ctx.bar

        # 1. Funding accrues on the position carried into this bar.
        if spec.market_type == "swap":
            for ts, rate in funding.settlements(bar.ts, bar.ts + bar_ms):
                if not portfolio.is_flat:
                    result.funding_payments.append(
                        portfolio.apply_funding(ts, rate, bar.open)
                    )

        # 2. Last bar's decision fills at this bar's open.
        if pending is not None:
            delta = broker.quantity_for_target(
                pending.target, bar.open, portfolio.equity(bar.open), portfolio.quantity
            )
            fill = broker.execute(portfolio, bar, delta, reason=pending.reason)
            if fill is not None:
                result.fills.append(fill)
                active = pending
                pending = None
            # A rejected order stays pending only if it never traded at all;
            # the next bar's decision supersedes it anyway.

        # 3. Protective exits from this bar's range.
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

        # 4. Only now may the strategy see this bar.
        if i + 1 >= strategy.warmup_bars:
            pending = strategy.on_bar(ctx)

        # 5. Mark to close.
        result.timestamps.append(bar.ts)
        result.equity.append(portfolio.equity(bar.close))

    result.rejections = broker.rejections
    return result
