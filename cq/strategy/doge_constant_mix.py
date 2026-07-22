"""Frozen DOGE spot constant-mix rebalancing policy.

This is not a return strategy and is not approved for real capital as one. The
2026-07-22 volatility-harvest study found the rebalancing premium does *not*
show up as excess return on DOGE — trimming into its pumps costs more than the
harvest earns, so a band rebalancer's total return trails a static allocation
of the same weight. What it does deliver, and what static weighting cannot at
any level, is a *bounded* risk exposure: a 100x pump balloons any static DOGE
weight to near-full and then eats the crash (~90% drawdown at every weight),
while rebalancing dials the drawdown down with the weight. Its honest role is a
bounded-risk layer-1 allocation policy, and a clean engine-calibration
instrument — its equity is a path integral, insensitive to the exit/sizing
semantics the Donchian calibration gate still disputes.

The policy is the pair ``(weight, band)``. ``on_bar`` only needs the weight; the
band is the no-trade threshold applied by whoever runs it — ``dust_fraction``
under ``Sizing.REBALANCE`` in the backtest, and the ``LiveBroker`` dust fraction
in paper, which sizes every bar and so is REBALANCE by construction. Carrying
the band here keeps the two halves of the policy from being set apart and
drifting: a runner reads ``config.band`` rather than guessing it.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from cq.context import Context
from cq.core.types import Intent


@dataclass(frozen=True)
class DogeConstantMixConfig:
    """The frozen main configuration from the volatility-harvest study."""

    weight: float = 0.30
    band: float = 0.10

    def __post_init__(self) -> None:
        if not 0.0 < self.weight <= 1.0:
            raise ValueError("weight must be in (0, 1]")
        if not 0.0 < self.band < 1.0:
            raise ValueError("band must be in (0, 1)")


class DogeConstantMix:
    """Hold a constant target weight of DOGE; the band decides when to trade.

    Reads no history and forecasts nothing: every bar names the same target
    weight. Whether that weight has drifted far enough to rebalance is the
    engine's ``dust_fraction`` decision under ``Sizing.REBALANCE`` — which,
    because the sized delta's notional is ``|weight - current| * equity`` to
    first order, is exactly a weight-drift band. Under ``Sizing.ON_ENTRY`` the
    same target sizes once and then drifts, the static benchmark the rebalancing
    action is measured against.
    """

    def __init__(self, config: DogeConstantMixConfig | None = None):
        self.config = config or DogeConstantMixConfig()

    @property
    def name(self) -> str:
        c = self.config
        return f"doge-cmix-w{c.weight:g}-b{c.band:g}"

    @property
    def weight(self) -> float:
        return self.config.weight

    @property
    def band(self) -> float:
        """The no-trade band a runner must apply as the broker's dust fraction."""
        return self.config.band

    @property
    def warmup_bars(self) -> int:
        return 1

    def reset(self) -> None:  # stateless, but the loop resets every strategy
        return None

    def snapshot_state(self) -> dict[str, object]:
        return {"config": asdict(self.config)}

    def restore_state(self, state: dict[str, object]) -> None:
        if state.get("config") != asdict(self.config):
            raise ValueError("DOGE constant-mix checkpoint configuration does not match")

    def on_bar(self, ctx: Context) -> Intent:
        return Intent(target=self.config.weight, reason=self.name)
