#!/usr/bin/env python
"""One backtest, wired for the debugger.

Open this file and press F5 (VS Code's "uv Debug" configuration already runs
the open file with the project venv, the repo root as cwd, and PYTHONPATH set).
There are no command-line arguments to configure: everything a run needs is a
plain constant in the CONFIG block below, so the file runs the moment you hit
"Debug" and you edit a value rather than a launch profile.

This drives the same `run_backtest` used by the test suite, so nothing here can
be more optimistic than live.
`scripts/debug_backtest.py` is the argparse version with the exhaustive per-bar
tables and a pdb hook; reach for it when you want those. This file is for the
IDE loop: set a breakpoint, run, step.

Where to put breakpoints
------------------------
* one bar's decision  — in `cq/strategy/donchian.py`, `DonchianTrend.on_bar`.
  For a specific bar, make it a *conditional* breakpoint: `ctx.index == 200`.
* every fill / the event ordering — in `cq/engine/loop.py`, `run_backtest`
  (the numbered steps 1-6 inside the `for i in range(len(primary))` loop).
* this file's `run()` call below — step *into* it to walk the whole loop.
"""

from __future__ import annotations

from cq.core.clock import duration_ms
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
from cq.research.metrics import compute_metrics, trades_from_fills
from cq.research.split import from_ms, to_ms
from cq.strategy.donchian import DonchianTrend

# ======================================================================
# CONFIG — the whole run lives here. Edit and re-launch; no CLI needed.
# ======================================================================

DB_PATH = "data/cq.db"

# An id ending in -SWAP is a perpetual (shorts allowed, funding applies);
# anything else is spot (long-only, no funding, no leverage). DonchianTrend is
# long/short, so it needs a swap — a spot market rejects its first short rather
# than silently running it long-only.
INSTRUMENT = "BTC-USDT"
TIMEFRAME = "1h"

# Half-open window [START, END). END is exclusive. The store holds DOGE/BTC
# from 2021-01-01; the 2026-07-20 freeze is where genuine out-of-sample begins.
START = "2026-01-01"
END = "2026-07-12"

# ON_ENTRY sizes once when the target changes and then holds that quantity
# (what a trend follower means by "1x"); REBALANCE re-derives it every bar to
# hold the weight constant. Different strategies — an order of magnitude apart.
SIZING = Sizing.ON_ENTRY

INITIAL_CASH = 10_000.0
FEE_BPS = 10.0
SLIPPAGE_BPS = 5.0

# Swap only. Spot is forced to 1.0 / 0.0 below. maintenance_margin_rate = 0.0
# means liquidation at bankruptcy; set the venue's tier rate to model the
# margin call that actually arrives first.
MAX_LEVERAGE = 1.0
MAINT_MARGIN = 0.0

# DonchianTrend parameters — the candidate carried since 2026-07.
ENTRY_LOOKBACK = 120
EXIT_LOOKBACK = 60
SIZE = 1.0
# Skip the short side, so the strategy never asks to hold a negative target.
# Required to run on spot (a spot market refuses a short outright); the name
# then records "-long" so it is not confused with the long/short run.
LONG_ONLY = True

# "none"    — funding omitted (a cost dropped, in whichever direction it ran).
#             Comparable to every prior study, which was computed this way.
# "actual"  — measured rates from the archive; raises on any gap. Swap only,
#             and the archive is ~3 months deep — narrow START/END to match.
# "assumed" — a constant rate per settlement, for sensitivity analysis.
FUNDING = "none"
ASSUMED_BPS = 1.0  # rate per settlement, "assumed" mode only

# Output. Set SHOW_BARS_TAIL to N to print the last N per-bar rows (0 = off).
SHOW_FILLS = True
SHOW_TRADES = True  # round-trip trades with per-trade P&L and account value
SHOW_FUNDING = False
SHOW_REJECTIONS = True
SHOW_BARS_TAIL = 0


# ======================================================================


def build_funding(store: Store, is_swap: bool) -> FundingModel:
    """The funding model named by FUNDING, or a clear exit explaining why not."""
    if FUNDING == "none":
        return NoFunding()
    if FUNDING == "assumed":
        return AssumedFunding(rate=ASSUMED_BPS / 10_000)
    if FUNDING == "actual":
        if not is_swap:
            raise SystemExit("FUNDING='actual' needs a swap; spot has no funding")
        model = load_actual_funding(store, INSTRUMENT)
        if model.covered_range is None:
            raise SystemExit(
                f"no archived funding for {INSTRUMENT}; run `uv run cq data archive`"
            )
        return model
    raise SystemExit(f"unknown FUNDING {FUNDING!r}; use none|assumed|actual")


def guard_funding_coverage(model: FundingModel, ts, bar_ms: int) -> None:
    """Fail before the run if the window outruns the funding archive.

    The engine would raise MissingFundingError mid-loop anyway; catching it here
    turns a stack trace into the covered range and a copy-pasteable fix. The
    window is never silently shrunk — that quiet change is what this project
    treats as a defect.
    """
    covered = getattr(model, "covered_range", None)
    if covered is None or len(ts) == 0:
        return
    interval = getattr(model, "interval_ms", bar_ms)
    lo, hi = covered
    want_lo, want_hi = int(ts[0]), int(ts[-1]) + bar_ms
    if want_lo < lo or want_hi > hi + interval:
        raise SystemExit(
            "requested window is outside archived funding coverage.\n"
            f"  archive covers : {from_ms(lo)} .. {from_ms(hi + interval)}\n"
            f"  window needs   : {from_ms(want_lo)} .. {from_ms(want_hi)}\n"
            "  narrow START/END into the covered range, or set FUNDING='none'."
        )


def equity_by_ts(timestamps, equity) -> dict[int, float]:
    """Account value (marked to close) indexed by bar open time.

    A fill executes at a bar's open, so that bar's closing equity is the
    account value carried out of the trade. It is read straight from the
    engine's own per-bar equity — funding and all — not re-derived here.
    """
    return {int(ts): float(equity[i]) for i, ts in enumerate(timestamps)}


def _acct(ts: int, equity_at: dict[int, float]) -> str:
    value = equity_at.get(int(ts))
    return f"{value:>14.2f}" if value is not None else f"{'—':>14}"


def print_fills(fills, equity_at) -> None:
    if not fills:
        print("\nfills: none")
        return
    print(f"\nfills ({len(fills)}):")
    print(
        f"  {'when':<12}{'side':<5}{'qty':>14}{'price':>12}"
        f"{'fee':>10}{'account':>14}  reason"
    )
    for f in fills:
        print(
            f"  {from_ms(f.ts):<12}{f.side.value:<5}{f.quantity:>14.6g}"
            f"{f.price:>12.6g}{f.fee:>10.4g}{_acct(f.ts, equity_at)}  {f.reason}"
        )


def print_trades(trades, equity_at) -> None:
    """Round-trip trades: realised P&L and the account value at each close.

    Trades are paired from the fill ledger exactly as the metrics layer pairs
    them — entry to exit, a flip closing one and opening the next — so this P&L
    is the same number the summary's win rate and profit factor are built from,
    not a second definition. `pnl` is gross of fees; `net` is after them and is
    the realised profit or loss the trade actually booked. `account` is the
    engine's equity at the bar the trade closed on.
    """
    if not trades:
        print("\ntrades: none")
        return
    net_total = sum(t.net_pnl for t in trades)
    print(f"\ntrades ({len(trades)}, net P&L {net_total:+,.2f}):")
    print(
        f"  {'entry':<12}{'exit':<12}{'side':<6}{'qty':>13}{'entry':>11}{'exit':>11}"
        f"{'pnl':>12}{'fees':>9}{'net':>12}{'ret%':>8}{'account':>14}"
    )
    for t in trades:
        print(
            f"  {from_ms(t.entry_ts):<12}{from_ms(t.exit_ts):<12}{t.side:<6}"
            f"{t.quantity:>13.6g}{t.entry_price:>11.6g}{t.exit_price:>11.6g}"
            f"{t.pnl:>+12.2f}{t.fees:>9.2f}{t.net_pnl:>+12.2f}"
            f"{t.return_pct * 100:>+7.1f}%{_acct(t.exit_ts, equity_at)}"
        )


def print_open_position(portfolio, mark_price: float) -> None:
    """The position still open when the run ended, with its unrealised P&L.

    The trades table is closed round trips only, so a run that ends holding has
    one position whose result is not in it. Marked at the final close, this is
    that result — and it is what makes the account reconcile: closed net P&L
    plus this unrealised figure is the whole change in equity.
    """
    if portfolio.is_flat:
        return
    side = "long" if portfolio.quantity > 0 else "short"
    print(
        f"\nopen at end: {side} {abs(portfolio.quantity):.6g} @ {portfolio.avg_entry:.6g}"
        f"   mark {mark_price:.6g}   unrealised {portfolio.unrealized_pnl(mark_price):+,.2f}"
    )


def print_funding(payments) -> None:
    if not payments:
        print("\nfunding payments: none")
        return
    total = sum(p.amount for p in payments)
    print(f"\nfunding payments ({len(payments)}, net paid {total:+.2f}):")


def print_rejections(rejections) -> None:
    if not rejections:
        print("\nrejections: none")
        return
    print(f"\nrejections ({len(rejections)}):")
    for r in rejections:
        print(f"  {from_ms(r.ts):<12}wanted {r.wanted_quantity:>+14.6g}   {r.reason}")


def print_bars(timestamps, equity, closes, fills, tail: int) -> None:
    """Per-bar table: close, equity, and a '*' on bars that traded."""
    fill_ts = {f.ts for f in fills}
    n = len(equity)
    start = max(0, n - tail)
    print(f"\nbars ({start}..{n - 1} of {n}):")
    print(f"  {'#':>6}  {'when':<12}{'close':>12}{'equity':>16}  trade")
    for i in range(start, n):
        mark = "*" if int(timestamps[i]) in fill_ts else ""
        print(
            f"  {i:>6}  {from_ms(int(timestamps[i])):<12}"
            f"{float(closes[i]):>12.6g}{float(equity[i]):>16.2f}  {mark}"
        )


def main() -> int:
    is_swap = INSTRUMENT.upper().endswith("-SWAP")
    market_type = "swap" if is_swap else "spot"

    with Store(DB_PATH) as store:
        series = load_series(
            store, INSTRUMENT, TIMEFRAME, start_ms=to_ms(START), end_ms=to_ms(END)
        )
        if len(series) == 0:
            print("no data in this window: run `uv run cq data sync` or widen START/END")
            return 1

        if is_swap:
            spec = MarketSpec(
                INSTRUMENT,
                "swap",
                max_leverage=MAX_LEVERAGE,
                maintenance_margin_rate=MAINT_MARGIN,
            )
        else:
            spec = MarketSpec(INSTRUMENT, "spot")  # forces leverage 1.0, no liquidation

        funding = build_funding(store, is_swap)
        if is_swap and FUNDING == "actual":
            guard_funding_coverage(funding, series.ts, duration_ms(series.timeframe))

        costs = CostModel(fee_bps=FEE_BPS, slippage_bps=SLIPPAGE_BPS)
        strategy = DonchianTrend(ENTRY_LOOKBACK, EXIT_LOOKBACK, SIZE, long_only=LONG_ONLY)

        print(
            f"{INSTRUMENT}  {TIMEFRAME}  {market_type}  "
            f"{from_ms(int(series.ts[0]))}..{from_ms(int(series.ts[-1]))}  {len(series)} bars"
        )
        print(f"strategy {strategy.name}  (warmup {strategy.warmup_bars} bars)")
        print(f"sizing {SIZING.value}   costs {FEE_BPS:g}+{SLIPPAGE_BPS:g} bps/side")
        print(f"funding {funding.label}")

        # Step *into* this call in the debugger to walk the engine loop, or set
        # a breakpoint in DonchianTrend.on_bar / run_backtest first, then run.
        try:
            result = run_backtest(
                strategy,
                series,
                spec,
                INITIAL_CASH,
                costs=costs,
                funding=funding,
                sizing=SIZING,
            )
        except MissingFundingError as exc:
            raise SystemExit(f"funding archive incomplete for this window:\n  {exc}") from exc
        except TradingError as exc:
            # A long/short strategy on a spot market lands here the first time it
            # tries to short: the engine refusing to run long-only, not a bug.
            raise SystemExit(
                f"the market rejected a target:\n  {exc}\n"
                "  tip: DonchianTrend is long/short here — either use a *-SWAP\n"
                "  instrument, or set LONG_ONLY=True to run it on spot."
            ) from exc

    print("\n" + "=" * 66)
    print(result.summary())
    metrics = compute_metrics(
        result.timestamps, result.equity, result.fills, result.initial_cash
    )
    print(metrics.summary())

    equity_at = equity_by_ts(result.timestamps, result.equity)
    if SHOW_FILLS:
        print_fills(result.fills, equity_at)
    if SHOW_TRADES:
        print_trades(trades_from_fills(result.fills), equity_at)
        print_open_position(result.portfolio, float(series.close[-1]))
    if SHOW_FUNDING:
        print_funding(result.funding_payments)
    if SHOW_REJECTIONS:
        print_rejections(result.rejections)
    if SHOW_BARS_TAIL:
        print_bars(result.timestamps, result.equity, series.close, result.fills, SHOW_BARS_TAIL)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
