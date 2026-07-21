"""CLI wiring for the `cq paper ...` subcommands."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path
from typing import cast

from cq.core.clock import BASE_TIMEFRAME
from cq.core.types import Side
from cq.data.feed import FeedStalledError, LiveFeed
from cq.data.okx import OkxPublicClient
from cq.live.broker import LiveBroker, min_base_amount_of, spec_from_market
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

DEFAULT_INSTRUMENT = "DOGE-USDT"
PAPER_LOG_DIR = Path("logs/paper")


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
        "--strategy", default="probe", choices=("probe",), help="only the plumbing probe for now"
    )
    run.add_argument("--weight", type=float, default=0.02, help="probe target weight")
    run.add_argument("--period", type=int, default=1, help="probe flip cadence in bars")
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
    print(f"  start balance: {client.free_balance(quote):.4f} {quote}, "
          f"{client.base_holding(inst):.6f} {base}")

    price = client.last_price(inst)
    quantity = client.round_amount(inst, args.notional / price)
    if quantity <= 0:
        print(
            f"  notional {args.notional} {quote} at {price} rounds below one lot; "
            f"raise --notional"
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
        f"  SELL filled {sell.quantity} {base} @ {sell.price} {quote}, "
        f"fee {sell.fee:.6f} {quote}"
    )

    print(f"  end balance:   {client.free_balance(quote):.4f} {quote}, "
          f"{client.base_holding(inst):.6f} {base}")
    print("  round trip complete — order path is live")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    """Run a strategy against live closed bars, trading on OKX demo by default."""
    inst, tf = args.inst, args.tf
    swap = is_swap(inst)
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
    broker = LiveBroker(
        client=trade,
        spec=spec,
        min_base_amount=min_base_amount_of(market),
    )
    strategy = HeartbeatProbe(weight=args.weight, period=args.period)
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
        resume = reconcile_restart(strategy.name, broker, checkpoint)
    except RecoveryError as exc:
        print(f"refusing to start unreconciled paper session: {exc}")
        return 1
    warmup = backlog[-args.warmup :] if args.warmup > 0 else []

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
            _print_event(event)
            log.write(json.dumps(_event_row(event), allow_nan=False) + "\n")
            log.flush()
            os.fsync(log.fileno())

        try:
            run_paper(
                strategy, broker, feed, inst, tf,
                warmup=warmup, on_event=on_event, max_bars=args.max_bars, resume=resume,
            )
        except KeyboardInterrupt:
            print("\n  stopped")
        except FeedStalledError as exc:
            print(f"\n  stopped stalled paper feed: {exc}")
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
        "close": event.close,
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
        f"  {when}  close {event.close:<12.6g} target {event.target:<5} "
        f"equity {event.equity:,.2f}"
    )
    if event.fill is not None:
        f = event.fill
        line += f"  {f.side.value.upper()} {f.quantity:g} @ {f.price:g}"
    elif event.rejected:
        line += "  (rejected)"
    if event.account_events:
        changes = ", ".join(
            f"{item.kind} {item.amount:+g} {item.currency}"
            for item in event.account_events
        )
        line += f"  [{changes}]"
    print(line)
