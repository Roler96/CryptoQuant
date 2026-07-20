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

# What "matching the baseline" means, decided here rather than by eye. The
# return tolerance is wide because the pre-rebuild number carries assumptions
# that were never written down; it is still nowhere near wide enough to admit
# the 1,053%-vs-390% spread the gate is currently reporting.
TOLERANCE = {
    "return": 0.25,  # relative
    "sharpe": 0.15,  # absolute
    "max_drawdown": 0.10,  # absolute
    "trades": 0.30,  # relative
}


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

        measured = {}
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
            measured[mode] = m
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

        # The gate passes only if some sizing mode reproduces the baseline.
        # Which one it is matters — ON_ENTRY and REBALANCE are different
        # strategies — but the gate's question is narrower: can this engine
        # reproduce the one external number at all?
        failures = {mode: _deviations(m) for mode, m in measured.items()}
        passed = [mode for mode, bad in failures.items() if not bad]

        for mode, bad in failures.items():
            for line in bad:
                print(f"  {mode.value:<12}{line}")

        if passed:
            print()
            print(f"GATE: PASSED — {', '.join(m.value for m in passed)} matches the baseline")
            return 0

        print()
        print("GATE: FAILED — no sizing mode reproduces the baseline within tolerance.")
        print("See docs/engine_calibration_gate.md.")
        print("No research conclusions are produced while the gate is closed.")
    return 1


def _deviations(m) -> list[str]:
    """Every baseline figure this run misses, with the size of the miss."""
    checks = [
        ("return", m.total_return, BASELINE["return"], TOLERANCE["return"], True),
        ("sharpe", m.sharpe, BASELINE["sharpe"], TOLERANCE["sharpe"], False),
        (
            "max_drawdown",
            m.max_drawdown,
            BASELINE["max_drawdown"],
            TOLERANCE["max_drawdown"],
            False,
        ),
        ("trades", float(m.trades), float(BASELINE["trades"]), TOLERANCE["trades"], True),
    ]
    out = []
    for name, actual, expected, tolerance, relative in checks:
        limit = abs(expected) * tolerance if relative else tolerance
        miss = abs(actual - expected)
        if miss > limit:
            kind = "relative" if relative else "absolute"
            out.append(
                f"{name}: {actual:,.4f} vs baseline {expected:,.4f} "
                f"(off by {miss:,.4f}, {kind} tolerance {limit:,.4f})"
            )
    return out


if __name__ == "__main__":
    raise SystemExit(main())
