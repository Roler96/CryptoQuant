#!/usr/bin/env python
"""One paper (demo) session, wired for a standalone run — the live twin of backtest.py.

Same idea as `backtest.py`: everything a run needs is a plain constant in the
CONFIG block below, so the file runs the moment you launch it and you edit a
value rather than a launch profile. It drives the *same* `run_paper` the tests
build and reuses `cq/live/` unchanged, so nothing here diverges from the live
package — this file adds the Donchian paper run without touching the `cq paper`
CLI, exactly as `backtest.py` adds a Donchian backtest without touching the
`cq backtest` path.

What it does, one closed bar at a time:

    LiveFeed closed bar -> DonchianTrend.on_bar -> LiveBroker market order on OKX
    demo -> reconcile against the exchange -> append a versioned JSONL checkpoint.

Scope, stated so it is not mistaken for more: this collects forward paper data
through the same scheduling loop used by backtests. Spot is the only order path
proven against demo, and the strategy starts flat: the first real demo order
fires on the first breakout. Set MAX_BARS to a small number for a shakeout
before a long unattended run.
"""

from __future__ import annotations

import datetime as dt
import json
import os
from typing import cast

from cq.data.feed import FeedStalledError, LiveFeed
from cq.data.okx import OkxPublicClient
from cq.live.broker import LiveBroker, min_base_amount_of, spec_from_market
from cq.live.client import OkxTradeClient, TradeError, base_currency, is_swap, to_symbol

# _event_row is the single source of truth for the durable, recovery-critical
# JSONL schema; reusing it (rather than re-serialising here) keeps this session's
# checkpoints readable by the same restart recovery the CLI relies on.
from cq.live.commands import PAPER_LOG_DIR, _event_row
from cq.live.config import OkxCredentials
from cq.live.protocols import MarginMode
from cq.live.recovery import RecoveryError, load_latest_checkpoint, reconcile_restart
from cq.live.session import PaperEvent, run_paper
from cq.live.warmup import seed_warmup
from cq.strategy.donchian import DonchianTrend

# ======================================================================
# CONFIG — the whole run lives here. Edit and re-launch; no CLI needed.
# ======================================================================

DB_PATH = "data/cq.db"

# DEMO=True routes to the OKX_SANDBOX_* keys and demo endpoint. DEMO=False uses
# the live keys and SPENDS REAL MONEY — leave it True unless that is the intent.
DEMO = True

# Spot BASE-QUOTE, or a linear swap BASE-QUOTE-SWAP. On spot DonchianTrend is
# forced long-only below (a spot market refuses a short outright); a swap runs
# the symmetric candidate unless LONG_ONLY is set.
INSTRUMENT = "DOGE-USDT"
TIMEFRAME = "1h"

# DonchianTrend parameters — the candidate carried since 2026-07.
ENTRY_LOOKBACK = 120
EXIT_LOOKBACK = 60
SIZE = 1.0  # target weight of equity per position
LONG_ONLY = True  # honoured on swap; always forced True on spot

# Swap only; ignored on spot.
LEVERAGE = 1.0
MARGIN_MODE = "cross"  # or "isolated"

# Feed and session controls.
POLL_SECONDS = 5.0
STALL_GRACE_SECONDS = 120.0
WARMUP = 8  # seed floor; raised to the strategy's warmup_bars when larger
MAX_BARS: int | None = None  # set a small int for a shakeout; None runs until stopped


# ======================================================================


def build_strategy(swap: bool) -> DonchianTrend:
    """DonchianTrend from the CONFIG block; spot is forced long-only."""
    long_only = True if not swap else LONG_ONLY
    return DonchianTrend(ENTRY_LOOKBACK, EXIT_LOOKBACK, SIZE, long_only=long_only)


def _announce(event: PaperEvent) -> None:
    when = dt.datetime.fromtimestamp(event.ts / 1000, dt.UTC).strftime("%m-%d %H:%M")
    line = (
        f"  {when}  close {event.close:<12.6g} target {event.target:<8.4g} "
        f"equity {event.equity:,.2f}"
    )
    if event.fill is not None:
        f = event.fill
        line += f"  {f.side.value.upper()} {f.quantity:g} @ {f.price:g}"
    elif event.rejected:
        line += "  (rejected)"
    print(line)


def main() -> int:
    inst, tf = INSTRUMENT, TIMEFRAME
    swap = is_swap(inst)
    demo = DEMO
    trade = OkxTradeClient(OkxCredentials.from_env(demo=demo))
    public = OkxPublicClient()

    try:
        market = trade.exchange.market(to_symbol(inst))
        spec = spec_from_market(market, inst, max_leverage=LEVERAGE if swap else None)
        if swap:
            trade.configure_swap(inst, LEVERAGE, cast(MarginMode, MARGIN_MODE))
    except (TradeError, ValueError) as exc:
        print(f"refusing unsupported paper market/account configuration: {exc}")
        return 1

    broker = LiveBroker(client=trade, spec=spec, min_base_amount=min_base_amount_of(market))
    strategy = build_strategy(swap)
    checkpoint = load_latest_checkpoint(PAPER_LOG_DIR, inst, tf)
    feed = LiveFeed(
        public, inst, tf, poll_seconds=POLL_SECONDS, stall_grace_seconds=STALL_GRACE_SECONDS
    )

    # One successful priming poll returns the recent closed backlog and arms the
    # feed's high-water mark: the session then only ever acts on bars that close
    # from here forward, never replaying old history as if it were a live signal.
    try:
        backlog = feed.prime()
    except FeedStalledError as exc:
        print(f"refusing to start with a stalled paper feed: {exc}")
        return 1

    if checkpoint is not None:
        missed = [bar for bar in backlog if bar.ts > checkpoint.ts]
        if missed:
            print(
                "refusing to resume across unprocessed closed bars: "
                f"checkpoint {checkpoint.ts}, newest primed bar {missed[-1].ts}"
            )
            return 1

    try:
        resume = reconcile_restart(strategy.name, broker, checkpoint)
    except RecoveryError as exc:
        print(f"refusing to start unreconciled paper session: {exc}")
        return 1

    warmup = seed_warmup(DB_PATH, backlog, inst, tf, strategy.warmup_bars, WARMUP)
    if len(warmup) < strategy.warmup_bars:
        print(
            f"  warning: only {len(warmup)} of {strategy.warmup_bars} warmup bars available; "
            f"{strategy.name} will not decide until it accumulates the rest — "
            f"backfill history with `uv run cq data sync --instruments {inst}`"
        )

    mode = "DEMO" if demo else "LIVE — REAL MONEY"
    print(
        f"paper run [{mode}]  {strategy.name} on {inst} {tf}  "
        f"(warmup {len(warmup)} bars, min order {broker.min_base_amount} {base_currency(inst)})"
    )
    if resume is not None:
        resumed_at = dt.datetime.fromtimestamp(resume.checkpoint_ts / 1000, dt.UTC).isoformat()
        print(f"  resumed checkpoint {resumed_at} from {resume.source}")

    PAPER_LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    log_path = PAPER_LOG_DIR / f"{inst}_{tf}_{stamp}.jsonl"
    print(f"  logging to {log_path}")

    with log_path.open("a", encoding="utf-8") as log:

        def on_event(event: PaperEvent) -> None:
            _announce(event)
            log.write(json.dumps(_event_row(event), allow_nan=False) + "\n")
            log.flush()
            os.fsync(log.fileno())

        try:
            run_paper(
                strategy, broker, feed, inst, tf,
                warmup=warmup, on_event=on_event, max_bars=MAX_BARS, resume=resume,
            )
        except KeyboardInterrupt:
            print("\n  stopped")
        except FeedStalledError as exc:
            print(f"\n  stopped stalled paper feed: {exc}")
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
