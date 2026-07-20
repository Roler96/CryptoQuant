#!/usr/bin/env python
"""Reproduce the engine calibration gate.

This is an engine check, not a study. It compares the rebuilt engine against
the one external number available from before the rebuild. See
docs/engine_calibration_gate.md for the result and what it does and does not
establish.
"""

from __future__ import annotations

from cq.core.types import CostModel, MarketSpec, Sizing
from cq.data.feed import load_series
from cq.data.store import Store
from cq.engine.funding import NoFunding
from cq.engine.loop import run_backtest
from cq.research.metrics import compute_metrics
from cq.research.split import to_ms
from cq.strategy.donchian import DonchianTrend

# Recorded before the rebuild, funding not included.
BASELINE = {
    "return": 17.47,
    "sharpe": 0.69,
    "max_drawdown": 0.778,
    "trades": 54,
}

START, END = "2021-01-01", "2026-07-12"
INSTRUMENT = "DOGE-USDT-SWAP"


def main() -> int:
    with Store("data/cq.db") as store:
        series = load_series(
            store, INSTRUMENT, "4h", start_ms=to_ms(START), end_ms=to_ms(END)
        )
        if len(series) == 0:
            print("no data: run `uv run cq data sync` first")
            return 1

        spec = MarketSpec(INSTRUMENT, "swap", max_leverage=1.0)
        print(f"{INSTRUMENT} 4h  {START}..{END}  {len(series)} bars")
        print(f"{'sizing':<12}{'return':>12}{'Sharpe':>9}{'MaxDD':>9}{'trades':>9}{'ex-best':>12}")
        print("-" * 63)

        for mode in (Sizing.ON_ENTRY, Sizing.REBALANCE):
            result = run_backtest(
                DonchianTrend(120, 60),
                series,
                spec,
                10_000.0,
                costs=CostModel(fee_bps=10, slippage_bps=5),
                funding=NoFunding(),
                sizing=mode,
            )
            m = compute_metrics(
                result.timestamps, result.equity, result.fills, result.initial_cash
            )
            print(
                f"{mode.value:<12}{m.total_return * 100:>11,.1f}%{m.sharpe:>9.2f}"
                f"{m.max_drawdown * 100:>8.1f}%{m.trades:>9d}"
                f"{m.return_excluding_best_trade * 100:>11,.1f}%"
            )

        print(
            f"{'baseline':<12}{BASELINE['return'] * 100:>11,.1f}%"
            f"{BASELINE['sharpe']:>9.2f}{BASELINE['max_drawdown'] * 100:>8.1f}%"
            f"{BASELINE['trades']:>9d}{330.0:>11,.1f}%"
        )
        print()
        print("GATE: FAILED — return differs by ~1.6x; see docs/engine_calibration_gate.md")
        print("No research conclusions are produced while the gate is closed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
