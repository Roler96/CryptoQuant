#!/usr/bin/env python
"""Drive one backtest and lay its internals bare.

A debugging harness, not a study. Its only job is to make a single
`run_backtest` call inspectable: which bar filled at what price, every funding
settlement, every rejection, the per-bar equity, and — with `--pdb-bar` — a
live debugger stopped at the strategy's decision on a chosen bar.

Nothing here decides anything the engine does not already decide. It selects
the same run the calibration script and the tests build and prints what the
RunResult already carries. `scripts/calibrate_donchian.py` is the
research-gate version of the same wiring; read it for the numbers that matter.

Examples
--------
  # default DOGE swap, 4h, on_entry, no funding
  uv run python scripts/debug_backtest.py

  # rebalance sizing, print the per-bar table (last 40 rows)
  uv run python scripts/debug_backtest.py --sizing rebalance --show bars --tail 40

  # stop in pdb at the strategy's decision on bar 200
  uv run python scripts/debug_backtest.py --pdb-bar 200

  # real archived funding (swap only, ~3 months of coverage — narrow the window)
  uv run python scripts/debug_backtest.py --funding actual \
      --start 2026-04-14 --end 2026-07-12
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from collections.abc import Sequence

import numpy as np

from cq.context import Context
from cq.core.types import CostModel, MarketSpec, Sizing, TradingError
from cq.data.feed import load_series
from cq.data.store import Store
from cq.engine.funding import (
    AssumedFunding,
    FundingModel,
    MissingFundingError,
    NoFunding,
    load_actual_funding,
)
from cq.engine.loop import run_backtest
from cq.research.metrics import compute_metrics
from cq.research.split import from_ms, to_ms
from cq.strategy.donchian import DonchianTrend

SHOW_CHOICES = ("fills", "funding", "rejections", "bars")


def fmt_ts(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, dt.UTC).strftime("%Y-%m-%d %H:%M")


def _channel(ctx: Context, lookback: int) -> tuple[float, float]:
    """Highest high and lowest low of the `lookback` bars before this one.

    A copy of DonchianTrend._channel so the debugger can show the levels the
    strategy is about to compare against without reaching into the strategy.
    """
    highs = ctx.high(lookback + 1)[:-1]
    lows = ctx.low(lookback + 1)[:-1]
    return float(np.max(highs)), float(np.min(lows))


def _decision_note(ctx: Context, inner) -> str:
    """One-line (or two) picture of what the strategy sees on this bar."""
    close = float(ctx.close(1)[-1])
    lines = [f"bar {ctx.index} @ {fmt_ts(ctx.now)}   close={close:g}"]
    entry = getattr(inner, "entry_lookback", None)
    exit_lb = getattr(inner, "exit_lookback", None)
    if entry and exit_lb and ctx.index >= max(entry, exit_lb):
        eh, el = _channel(ctx, entry)
        xh, xl = _channel(ctx, exit_lb)
        lines.append(f"  entry[{entry}] {el:g}..{eh:g}    exit[{exit_lb}] {xl:g}..{xh:g}")
        lines.append(f"  target currently held = {getattr(inner, '_target', '?')}")
    return "\n".join(lines)


class BreakAt:
    """Wraps a strategy and drops into pdb at one bar's decision.

    Transparent to the engine: name, warmup and reset all delegate, so the run
    is byte-for-byte the run without the wrapper — the only difference is that
    `on_bar` pauses once, at `bar`, with `ctx` and `inner` in scope.
    """

    def __init__(self, inner, bar: int):
        self.inner = inner
        self.bar = bar

    @property
    def name(self) -> str:
        return self.inner.name

    @property
    def warmup_bars(self) -> int:
        return self.inner.warmup_bars

    def reset(self) -> None:
        reset = getattr(self.inner, "reset", None)
        if callable(reset):
            reset()

    def on_bar(self, ctx: Context):
        if ctx.index == self.bar:
            inner = self.inner  # bound so the debugger frame can see it
            print("\n--- pdb: strategy decision point ---")
            print(_decision_note(ctx, inner))
            print("inspect: ctx.close(5), ctx.high(10), _channel(ctx, N), inner.__dict__")
            breakpoint()
        return self.inner.on_bar(ctx)


def build_funding(
    kind: str, assumed_bps: float, store: Store, inst: str, is_swap: bool
) -> FundingModel:
    if kind == "none":
        return NoFunding()
    if kind == "assumed":
        return AssumedFunding(rate=assumed_bps / 10_000)
    if kind == "actual":
        if not is_swap:
            sys.exit("actual funding only applies to swaps; spot has none")
        model = load_actual_funding(store, inst)
        if model.covered_range is None:
            sys.exit(f"no archived funding for {inst}: run `uv run cq data archive` first")
        return model
    raise ValueError(kind)  # argparse restricts this


def guard_funding_coverage(model: FundingModel, ts: np.ndarray, bar_ms: int) -> None:
    """Fail loudly, before the run, if the window outruns the funding archive.

    The engine would raise MissingFundingError mid-run anyway; catching it here
    turns a stack trace into the covered range and a copy-pasteable fix. We do
    not clamp the window — silently shrinking the run is exactly the kind of
    quiet change this project treats as a defect.
    """
    covered = getattr(model, "covered_range", None)
    if covered is None or len(ts) == 0:
        return
    interval = getattr(model, "interval_ms", bar_ms)
    lo, hi = covered
    want_lo, want_hi = int(ts[0]), int(ts[-1]) + bar_ms
    if want_lo < lo or want_hi > hi + interval:
        sys.exit(
            "requested window is outside archived funding coverage.\n"
            f"  archive covers : {fmt_ts(lo)} .. {fmt_ts(hi + interval)}\n"
            f"  window needs   : {fmt_ts(want_lo)} .. {fmt_ts(want_hi)}\n"
            "  narrow --start/--end into the covered range, "
            "or use --funding none|assumed."
        )


def print_fills(fills) -> None:
    if not fills:
        print("\nfills: none")
        return
    print(f"\nfills ({len(fills)}):")
    print(f"  {'when':<17}{'side':<5}{'qty':>14}{'price':>12}{'fee':>10}  reason")
    for f in fills:
        print(
            f"  {fmt_ts(f.ts):<17}{f.side.value:<5}{f.quantity:>14.6g}"
            f"{f.price:>12.6g}{f.fee:>10.4g}  {f.reason}"
        )


def print_funding(payments) -> None:
    if not payments:
        print("\nfunding payments: none")
        return
    total = sum(p.amount for p in payments)
    print(f"\nfunding payments ({len(payments)}, net paid {total:+.2f}):")
    print(f"  {'when':<17}{'rate(bps)':>11}{'mark':>12}{'amount':>12}")
    for p in payments:
        print(
            f"  {fmt_ts(p.ts):<17}{p.rate * 10_000:>11.4f}"
            f"{p.mark_price:>12.6g}{p.amount:>+12.4f}"
        )


def print_rejections(rejections) -> None:
    if not rejections:
        print("\nrejections: none")
        return
    print(f"\nrejections ({len(rejections)}):")
    for r in rejections:
        print(f"  {fmt_ts(r.ts):<17}wanted {r.wanted_quantity:>+14.6g}   {r.reason}")


def print_bars(timestamps, equity, closes, fills, tail: int) -> None:
    """Per-bar table: close, equity, and a '*' on bars that traded."""
    fill_ts = {f.ts for f in fills}
    n = len(equity)
    start = max(0, n - tail) if tail else 0
    print(f"\nbars ({start}..{n - 1} of {n}):")
    print(f"  {'#':>6}  {'when':<17}{'close':>12}{'equity':>16}  trade")
    for i in range(start, n):
        mark = "*" if int(timestamps[i]) in fill_ts else ""
        print(
            f"  {i:>6}  {fmt_ts(int(timestamps[i])):<17}"
            f"{float(closes[i]):>12.6g}{float(equity[i]):>16.2f}  {mark}"
        )


def main(argv: Sequence[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    p.add_argument("--db", default="data/cq.db")
    p.add_argument("--inst", default="DOGE-USDT-SWAP", help="instrument id; *-SWAP means swap")
    p.add_argument("-t", "--timeframe", default="4h")
    p.add_argument("--start", default="2021-01-01")
    p.add_argument("--end", default="2026-07-12", help="exclusive")
    p.add_argument("--sizing", choices=[s.value for s in Sizing], default=Sizing.ON_ENTRY.value)
    p.add_argument("--cash", type=float, default=10_000.0)
    p.add_argument("--fee-bps", type=float, default=10.0)
    p.add_argument("--slippage-bps", type=float, default=5.0)
    p.add_argument("--max-leverage", type=float, default=1.0, help="swap only; spot forced to 1.0")
    p.add_argument("--maint-margin", type=float, default=0.0, help="maint margin rate, swap only")
    p.add_argument("--entry", type=int, default=120, help="Donchian entry lookback")
    p.add_argument("--exit", type=int, default=60, help="Donchian exit lookback")
    p.add_argument("--size", type=float, default=1.0)
    p.add_argument("--funding", choices=["none", "assumed", "actual"], default="none")
    p.add_argument("--assumed-bps", type=float, default=1.0, help="rate/settlement, assumed mode")
    p.add_argument("--show", default="fills,rejections", help=f"comma list of {SHOW_CHOICES}")
    p.add_argument("--tail", type=int, default=0, help="limit bars table to last N rows (0=all)")
    p.add_argument("--pdb-bar", type=int, default=None, help="drop into pdb at this bar's decision")
    p.add_argument("--coverage", action="store_true", help="print coverage for --inst and exit")
    args = p.parse_args(argv)

    show = {s.strip() for s in args.show.split(",") if s.strip()}
    bad = show - set(SHOW_CHOICES)
    if bad:
        p.error(f"unknown --show value(s): {', '.join(sorted(bad))}")

    is_swap = args.inst.upper().endswith("-SWAP")
    market_type = "swap" if is_swap else "spot"

    with Store(args.db) as store:
        if args.coverage:
            n, lo, hi = store.ohlcv_coverage(args.inst, "1h")
            print(f"{args.inst}  1h base: {n} bars", end="")
            print(f"  {fmt_ts(lo)} .. {fmt_ts(hi)}" if n else "  (none)")
            fn, flo, fhi = store.funding_coverage(args.inst)
            print(f"{args.inst}  funding: {fn} settlements", end="")
            print(f"  {fmt_ts(flo)} .. {fmt_ts(fhi)}" if fn else "  (none)")
            return 0

        series = load_series(
            store, args.inst, args.timeframe, start_ms=to_ms(args.start), end_ms=to_ms(args.end)
        )
        if len(series) == 0:
            print("no data in this window: run `uv run cq data sync` or widen --start/--end")
            return 1

        if is_swap:
            spec = MarketSpec(
                args.inst, "swap", max_leverage=args.max_leverage,
                maintenance_margin_rate=args.maint_margin,
            )
        else:
            if args.max_leverage != 1.0:
                print("note: spot cannot be leveraged; forcing max_leverage=1.0")
            spec = MarketSpec(args.inst, "spot")

        funding = build_funding(args.funding, args.assumed_bps, store, args.inst, is_swap)
        if is_swap and args.funding == "actual":
            from cq.core.clock import duration_ms

            guard_funding_coverage(funding, series.ts, duration_ms(series.timeframe))

        costs = CostModel(fee_bps=args.fee_bps, slippage_bps=args.slippage_bps)
        sizing = Sizing(args.sizing)
        strategy = DonchianTrend(args.entry, args.exit, args.size)

        print(f"{args.inst}  {args.timeframe}  {market_type}  "
              f"{from_ms(int(series.ts[0]))}..{from_ms(int(series.ts[-1]))}  {len(series)} bars")
        print(f"strategy {strategy.name}  (warmup {strategy.warmup_bars} bars)")
        print(f"sizing {sizing.value}   costs {costs.fee_bps:g}+{costs.slippage_bps:g} bps/side")
        print(f"funding {funding.label}")

        run_strategy = strategy
        if args.pdb_bar is not None:
            first_traded = strategy.warmup_bars - 1
            if args.pdb_bar < first_traded:
                print(f"note: bar {args.pdb_bar} is inside warmup; the strategy is first "
                      f"consulted on bar {first_traded}, so pdb will not fire before then")
            run_strategy = BreakAt(strategy, args.pdb_bar)

        try:
            result = run_backtest(
                run_strategy, series, spec, args.cash,
                costs=costs, funding=funding, sizing=sizing,
            )
        except MissingFundingError as exc:
            sys.exit(f"funding archive incomplete for this window:\n  {exc}")
        except TradingError as exc:
            # A long/short strategy on a spot market hits this the first time it
            # tries to short. It is the engine refusing to silently run as
            # long-only, not a bug in the run — point at the fix.
            sys.exit(f"the market rejected a target:\n  {exc}\n"
                     f"  tip: this strategy is long/short; use a *-SWAP instrument for it.")

    print("\n" + "=" * 66)
    print(result.summary())
    metrics = compute_metrics(result.timestamps, result.equity, result.fills, result.initial_cash)
    print(metrics.summary())

    if "fills" in show:
        print_fills(result.fills)
    if "funding" in show:
        print_funding(result.funding_payments)
    if "rejections" in show:
        print_rejections(result.rejections)
    if "bars" in show:
        print_bars(result.timestamps, result.equity, series.close, result.fills, args.tail)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
