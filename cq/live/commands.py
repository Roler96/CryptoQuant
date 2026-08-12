"""CLI wiring for the `cq paper ...` subcommands."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from itertools import pairwise
from pathlib import Path
from typing import cast

from cq.core.clock import BASE_TIMEFRAME
from cq.core.types import Side, Sizing
from cq.data.feed import FeedStalledError, LiveFeed, WarmupError, recent_closed_bars
from cq.data.okx import OkxPublicClient
from cq.engine.loop import Strategy
from cq.live.broker import (
    DEFAULT_DUST_FRACTION,
    LiveBroker,
    min_base_amount_of,
    spec_from_market,
)
from cq.live.client import (
    OkxTradeClient,
    TradeError,
    base_currency,
    is_swap,
    quote_currency,
    to_symbol,
)
from cq.live.config import OkxCredentials
from cq.live.probe import HeartbeatProbe
from cq.live.protocols import MarginMode
from cq.live.recovery import (
    CHECKPOINT_VERSION,
    RecoveryError,
    load_latest_checkpoint,
    reconcile_restart,
)
from cq.live.session import PaperEvent, run_paper
from cq.research.downside_recovery import DownsideRecoveryStrategy

DEFAULT_INSTRUMENT = "DOGE-USDT"
PAPER_LOG_DIR = Path("logs/paper")
DSPR_LOG_DIR = PAPER_LOG_DIR / "dspr-v1"
DSPR_INSTRUMENT = "DOGE-USDT-SWAP"
DSPR_TIMEFRAME = "5m"


def register(subparsers: argparse._SubParsersAction) -> None:
    """Attach every `cq paper ...` subcommand to the parser."""
    smoke = subparsers.add_parser(
        "smoke",
        help="place a tiny round-trip on OKX demo to prove the order path works",
    )
    smoke.add_argument("--inst", default=DEFAULT_INSTRUMENT, help="spot instrument, BASE-QUOTE")
    smoke.add_argument(
        "--notional", type=float, default=5.0, help="quote-currency size of the test buy"
    )
    smoke.add_argument(
        "--live",
        action="store_true",
        help="use the LIVE keys instead of demo — this spends real money",
    )
    smoke.set_defaults(handler=cmd_smoke)

    run = subparsers.add_parser(
        "run",
        help="drive a strategy against live closed bars, trading on OKX demo",
    )
    run.add_argument(
        "--inst",
        default=DEFAULT_INSTRUMENT,
        help="spot BASE-QUOTE or linear swap BASE-QUOTE-SWAP",
    )
    run.add_argument("--tf", default=BASE_TIMEFRAME, help="bar timeframe, e.g. 1m or 1h")
    run.add_argument(
        "--weight", type=float, default=0.02, help="probe target weight"
    )
    run.add_argument("--period", type=int, default=1, help="probe flip cadence in bars")
    run.add_argument(
        "--sizing",
        choices=tuple(mode.value for mode in Sizing),
        default=Sizing.REBALANCE.value,
        help="rebalance every bar or size only when the target changes",
    )
    run.add_argument(
        "--leverage",
        type=float,
        default=1.0,
        help="explicit swap leverage (1-125)",
    )
    run.add_argument(
        "--margin-mode",
        choices=("cross", "isolated"),
        default="cross",
        help="explicit swap margin mode",
    )
    run.add_argument("--warmup", type=int, default=8, help="recent closed bars to seed as warmup")
    run.add_argument("--poll", type=float, default=5.0, help="feed poll interval, seconds")
    run.add_argument(
        "--stall-grace",
        type=float,
        default=120.0,
        help="seconds past an expected bar close before the feed fails as stalled",
    )
    run.add_argument("--max-bars", type=int, default=None, help="stop after this many live bars")
    run.add_argument(
        "--live",
        action="store_true",
        help="use the LIVE keys instead of demo — this spends real money",
    )
    run.set_defaults(handler=cmd_run)

    dspr = subparsers.add_parser(
        "dspr",
        help="run frozen DSPR v1 on OKX demo (real-money mode is intentionally unavailable)",
    )
    dspr.add_argument("--poll", type=float, default=5.0, help="feed poll interval, seconds")
    dspr.add_argument(
        "--stall-grace",
        type=float,
        default=120.0,
        help="seconds past an expected bar close before the feed fails as stalled",
    )
    dspr.add_argument("--max-bars", type=int, default=None, help="stop after this many live bars")
    dspr.add_argument(
        "--preflight-only",
        action="store_true",
        help="verify demo account, flat state and warmup without starting the session",
    )
    dspr.set_defaults(handler=cmd_dspr)


def cmd_smoke(args: argparse.Namespace) -> int:
    """Buy a tiny notional and sell it straight back, reporting each fill.

    A deliberately loud, self-contained check of credentials, sandbox routing
    and the create/fill/read-back loop, run before any strategy is wired in.
    """
    if is_swap(args.inst):
        print("paper smoke is a spot round trip; use `paper run` for linear swaps")
        return 1
    demo = not args.live
    creds = OkxCredentials.from_env(demo=demo)
    client = OkxTradeClient(creds)
    inst = args.inst
    base, quote = base_currency(inst), quote_currency(inst)

    mode = "DEMO" if demo else "LIVE — REAL MONEY"
    print(f"OKX paper smoke [{mode}]  {inst}")
    print(
        f"  start balance: {client.free_balance(quote):.4f} {quote}, "
        f"{client.base_holding(inst):.6f} {base}"
    )

    price = client.last_price(inst)
    quantity = client.round_amount(inst, args.notional / price)
    if quantity <= 0:
        print(
            f"  notional {args.notional} {quote} at {price} rounds below one lot; raise --notional"
        )
        return 1
    print(f"  last price {price} {quote}; buying {quantity} {base} (~{args.notional} {quote})")

    base_before = client.base_holding(inst)
    buy = client.market_order(inst, Side.BUY, quantity, reason="smoke-buy")
    print(f"  BUY  filled {buy.quantity} {base} @ {buy.price} {quote}, fee {buy.fee:.6f} {quote}")

    received = client.round_amount(inst, client.base_holding(inst) - base_before)
    if received <= 0:
        print("  nothing received to sell back; check the fill above")
        return 1
    sell = client.market_order(inst, Side.SELL, received, reason="smoke-sell")
    print(
        f"  SELL filled {sell.quantity} {base} @ {sell.price} {quote}, fee {sell.fee:.6f} {quote}"
    )

    print(
        f"  end balance:   {client.free_balance(quote):.4f} {quote}, "
        f"{client.base_holding(inst):.6f} {base}"
    )
    print("  round trip complete — order path is live")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """Run the heartbeat probe against live closed bars, trading on OKX demo by default."""
    inst, tf = args.inst, args.tf
    swap = is_swap(inst)
    sizing = Sizing(args.sizing)
    if not swap and (args.leverage != 1.0 or args.margin_mode != "cross"):
        print("--leverage and --margin-mode only apply to swap instruments")
        return 1
    demo = not args.live
    trade = OkxTradeClient(OkxCredentials.from_env(demo=demo))
    public = OkxPublicClient()

    try:
        market = trade.exchange.market(to_symbol(inst))
        spec = spec_from_market(
            market,
            inst,
            max_leverage=args.leverage if swap else None,
        )
        if swap:
            trade.configure_swap(
                inst,
                args.leverage,
                cast(MarginMode, args.margin_mode),
            )
    except (TradeError, ValueError) as exc:
        print(f"refusing unsupported paper market/account configuration: {exc}")
        return 1
    strategy: Strategy = HeartbeatProbe(weight=args.weight, period=args.period)
    dust = DEFAULT_DUST_FRACTION
    broker = LiveBroker(
        client=trade,
        spec=spec,
        min_base_amount=min_base_amount_of(market),
        dust_fraction=dust,
    )
    checkpoint = load_latest_checkpoint(PAPER_LOG_DIR, inst, tf)
    feed = LiveFeed(
        public,
        inst,
        tf,
        poll_seconds=args.poll,
        stall_grace_seconds=args.stall_grace,
    )
    # One successful priming poll returns the recent closed backlog and,
    # crucially, arms the feed's high-water mark: the session then only ever
    # acts on bars that close from here forward, never replaying old history as
    # if it were a live signal. Transient failures retry inside prime().
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
        resume = reconcile_restart(strategy.name, broker, checkpoint, sizing)
    except RecoveryError as exc:
        print(f"refusing to start unreconciled paper session: {exc}")
        return 1
    warmup = backlog[-args.warmup :] if args.warmup > 0 else []

    mode = "DEMO" if demo else "LIVE — REAL MONEY"
    print(
        f"paper run [{mode}]  {strategy.name} on {inst} {tf}  "
        f"(sizing {sizing.value}, warmup {len(warmup)} bars, "
        f"min order {broker.min_base_amount} {base_currency(inst)})"
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
            _print_event(event)
            log.write(json.dumps(_event_row(event), allow_nan=False) + "\n")
            log.flush()
            os.fsync(log.fileno())

        try:
            run_paper(
                strategy,
                broker,
                feed,
                inst,
                tf,
                warmup=warmup,
                on_event=on_event,
                max_bars=args.max_bars,
                resume=resume,
                sizing=sizing,
            )
        except KeyboardInterrupt:
            print("\n  stopped")
        except FeedStalledError as exc:
            print(f"\n  stopped stalled paper feed: {exc}")
            return 1
    return 0


def cmd_dspr(args: argparse.Namespace) -> int:
    """Run the exact DSPR v1 research strategy against OKX demo only."""
    if args.max_bars is not None and args.max_bars <= 0:
        print("--max-bars must be positive")
        return 1
    inst, tf = DSPR_INSTRUMENT, DSPR_TIMEFRAME
    sizing = Sizing.ON_ENTRY
    strategy: Strategy = DownsideRecoveryStrategy()
    trade = OkxTradeClient(OkxCredentials.from_env(demo=True))
    public = OkxPublicClient()

    try:
        market = trade.exchange.market(to_symbol(inst))
        spec = spec_from_market(market, inst, max_leverage=1.0)
        trade.configure_swap(inst, 1.0, "isolated")
    except (TradeError, ValueError) as exc:
        print(f"refusing unsupported DSPR demo market/account configuration: {exc}")
        return 1

    broker = LiveBroker(
        client=trade,
        spec=spec,
        min_base_amount=min_base_amount_of(market),
        dust_fraction=DEFAULT_DUST_FRACTION,
    )
    checkpoint = load_latest_checkpoint(DSPR_LOG_DIR, inst, tf)
    feed = LiveFeed(
        public,
        inst,
        tf,
        poll_seconds=args.poll,
        stall_grace_seconds=args.stall_grace,
    )
    try:
        warmup = recent_closed_bars(public, inst, tf, strategy.warmup_bars)
        primed = feed.prime()
    except (FeedStalledError, WarmupError) as exc:
        print(f"refusing to start DSPR demo with invalid public feed: {exc}")
        return 1

    # A bar may close between the paged warmup and the priming call. Include it
    # in context, but never replay it as a live decision.
    merged = {bar.ts: bar for bar in warmup}
    merged.update((bar.ts, bar) for bar in primed)
    warmup = [merged[ts] for ts in sorted(merged)][-strategy.warmup_bars :]
    if len(warmup) != strategy.warmup_bars or any(
        right.ts - left.ts != 300_000
        for left, right in pairwise(warmup)
    ):
        print("refusing to start DSPR demo: merged warmup is incomplete or non-contiguous")
        return 1

    if checkpoint is not None:
        missed = [bar for bar in warmup if bar.ts > checkpoint.ts]
        if missed:
            print(
                "refusing to resume DSPR across unprocessed closed bars: "
                f"checkpoint {checkpoint.ts}, newest warmup bar {missed[-1].ts}"
            )
            return 1
    try:
        resume = reconcile_restart(strategy.name, broker, checkpoint, sizing)
    except RecoveryError as exc:
        print(f"refusing to start unreconciled DSPR demo session: {exc}")
        return 1

    state = broker.reconcile()
    newest = dt.datetime.fromtimestamp(warmup[-1].ts / 1000, dt.UTC).isoformat()
    print(
        f"DSPR v1 demo preflight OK  {inst} {tf}  "
        f"(1x isolated, {sizing.value}, target 25%, warmup {len(warmup)} bars)"
    )
    print(
        f"  newest closed warmup {newest}; demo equity {state.equity(warmup[-1].close):,.2f} USDT; "
        f"position {state.held:g} DOGE"
    )
    print("  no protective stop: this preserves the frozen one-hour time-exit specification")
    if args.preflight_only:
        print("  preflight only — no strategy session started and no order was placed")
        return 0

    if resume is not None:
        resumed_at = dt.datetime.fromtimestamp(resume.checkpoint_ts / 1000, dt.UTC).isoformat()
        print(f"  resumed checkpoint {resumed_at} from {resume.source}")
    DSPR_LOG_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    log_path = DSPR_LOG_DIR / f"{inst}_{tf}_{stamp}.jsonl"
    print(f"  starting DEMO session; logging to {log_path}")

    with log_path.open("a", encoding="utf-8") as log:

        def on_event(event: PaperEvent) -> None:
            _print_event(event)
            log.write(json.dumps(_event_row(event), allow_nan=False) + "\n")
            log.flush()
            os.fsync(log.fileno())

        try:
            run_paper(
                strategy,
                broker,
                feed,
                inst,
                tf,
                warmup=warmup,
                on_event=on_event,
                max_bars=args.max_bars,
                resume=resume,
                sizing=sizing,
            )
        except KeyboardInterrupt:
            print("\n  stopped")
        except FeedStalledError as exc:
            print(f"\n  stopped stalled DSPR demo feed: {exc}")
            return 1
    return 0


def _event_row(event: PaperEvent) -> dict:
    """A PaperEvent as a JSON-serialisable dict for the session log."""
    fill = event.fill
    return {
        "checkpoint_version": CHECKPOINT_VERSION,
        "ts": event.ts,
        "time": dt.datetime.fromtimestamp(event.ts / 1000, dt.UTC).isoformat(),
        "inst_id": event.inst_id,
        "timeframe": event.timeframe,
        "strategy": event.strategy,
        "open": event.open,
        "high": event.high,
        "low": event.low,
        "close": event.close,
        "volume": event.volume,
        "target": event.target,
        "reason": event.reason,
        "held": event.held,
        "cash": event.cash,
        "equity": event.equity,
        "held_after": event.held_after,
        "cash_after": event.cash_after,
        "average_entry": event.average_entry,
        "strategy_state": event.strategy_state,
        "account_event_cursor": event.account_event_cursor,
        "sizing": event.sizing,
        "active_target_before": event.active_target_before,
        "active_target_after": event.active_target_after,
        "account_events": [
            {
                "bill_id": item.bill_id,
                "ts": item.ts,
                "kind": item.kind,
                "amount": item.amount,
                "currency": item.currency,
                "price": item.price,
                "quantity": item.quantity,
                "subtype": item.subtype,
            }
            for item in event.account_events
        ],
        "rejected": event.rejected,
        "client_order_id": event.client_order_id,
        "protection": None
        if event.protection is None
        else {
            "algo_id": event.protection.algo_id,
            "quantity": event.protection.quantity,
            "stop_loss": event.protection.stop_loss,
            "take_profit": event.protection.take_profit,
            "side": event.protection.side.value,
            "client_order_id": event.protection.client_order_id,
        },
        "fill": None
        if fill is None
        else {
            "side": fill.side.value,
            "quantity": fill.quantity,
            "price": fill.price,
            "fee": fill.fee,
        },
    }


def _print_event(event: PaperEvent) -> None:
    when = dt.datetime.fromtimestamp(event.ts / 1000, dt.UTC).strftime("%m-%d %H:%M")
    line = (
        f"  {when}  close {event.close:<12.6g} target {event.target:<5} equity {event.equity:,.2f}"
    )
    if event.fill is not None:
        f = event.fill
        line += f"  {f.side.value.upper()} {f.quantity:g} @ {f.price:g}"
    elif event.rejected:
        line += "  (rejected)"
    if event.account_events:
        changes = ", ".join(
            f"{item.kind} {item.amount:+g} {item.currency}" for item in event.account_events
        )
        line += f"  [{changes}]"
    print(line)
