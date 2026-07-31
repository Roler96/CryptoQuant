"""CLI wiring for offline backtests."""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path
from typing import cast

from cq.backtest.benchmark import BuyAndHold
from cq.backtest.registry import REGISTRY
from cq.backtest.report import (
    SegmentResult,
    build_payload,
    new_run_identity,
    render_text,
    summary_payload,
    utc_iso,
    write_bundle,
)
from cq.context import Series
from cq.core.clock import BASE_TIMEFRAME, duration_ms
from cq.core.types import (
    DEFAULT_FEE_BPS,
    DEFAULT_SLIPPAGE_BPS,
    CostModel,
    Intent,
    MarketSpec,
    Sizing,
    TradingError,
)
from cq.data.feed import load_series
from cq.data.store import DEFAULT_DB_PATH, Store
from cq.engine.funding import (
    AssumedFunding,
    MissingFundingError,
    NoFunding,
    load_actual_funding,
)
from cq.engine.loop import run_backtest
from cq.live.client import is_swap

FUNDING_CHOICES = ("off", "actual", "assumed")


def register(subparsers: argparse._SubParsersAction) -> None:
    """Attach one ``cq backtest`` subcommand per registered strategy."""
    for name, entry in REGISTRY.items():
        parser = subparsers.add_parser(name, help=f"run the {name} strategy")
        _add_common_arguments(parser)
        entry.add_arguments(parser)
        parser.set_defaults(handler=cmd_run, strategy_name=name)


def _add_common_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite path")
    parser.add_argument("--inst", required=True, help="OKX-native instrument id")
    parser.add_argument("--tf", default=BASE_TIMEFRAME, help="bar timeframe")
    parser.add_argument("--start", default=None, help="UTC date, inclusive")
    parser.add_argument("--end", default=None, help="UTC date, exclusive")
    parser.add_argument(
        "--split",
        type=float,
        default=0.7,
        help="fraction of bars assigned to historical evaluation (default: 0.7)",
    )
    parser.add_argument("--initial-cash", type=float, default=10_000.0)
    parser.add_argument("--fee-bps", type=float, default=DEFAULT_FEE_BPS)
    parser.add_argument("--slippage-bps", type=float, default=DEFAULT_SLIPPAGE_BPS)
    parser.add_argument(
        "--sizing",
        choices=[sizing.value for sizing in Sizing],
        default=Sizing.ON_ENTRY.value,
    )
    parser.add_argument("--leverage", type=float, default=1.0, help="swap only")
    parser.add_argument(
        "--funding",
        choices=FUNDING_CHOICES,
        default="actual",
        help="swap funding model",
    )
    parser.add_argument(
        "--funding-rate",
        type=float,
        default=None,
        help="assumed funding in bps per settlement (swap only)",
    )
    parser.add_argument(
        "--format",
        dest="output_format",
        choices=("text", "json"),
        default="text",
        help="stdout report format",
    )
    parser.add_argument(
        "--output-dir",
        default="reports/backtests",
        help="parent directory for the per-run result bundle",
    )
    parser.add_argument(
        "--show-trades",
        type=int,
        default=0,
        help="show the last N transaction attempts in text output",
    )


def cmd_run(args: argparse.Namespace) -> int:
    """Run a registered strategy against locally stored OHLCV data."""
    swap = is_swap(args.inst)
    if not swap and (
        args.leverage != 1.0 or args.funding != "actual" or args.funding_rate is not None
    ):
        print("--leverage, --funding and --funding-rate only apply to swap instruments")
        return 1
    if args.funding == "assumed" and args.funding_rate is None:
        print("--funding-rate is required when --funding assumed")
        return 1
    if args.funding != "assumed" and args.funding_rate is not None:
        print("--funding-rate only applies when --funding assumed")
        return 1
    if not 0 < args.split < 1:
        print("--split must be greater than 0 and less than 1")
        return 1
    if args.show_trades < 0:
        print("--show-trades must be non-negative")
        return 1

    try:
        start_ms = _parse_utc_date(args.start) if args.start else None
        end_ms = _parse_utc_date(args.end) if args.end else None
        spec = MarketSpec(
            inst_id=args.inst,
            market_type="swap" if swap else "spot",
            lot_size=0.0,
            min_notional=0.0,
            max_leverage=args.leverage if swap else 1.0,
            maintenance_margin_rate=0.0,
            contract_size=1.0,
        )
        costs = CostModel(fee_bps=args.fee_bps, slippage_bps=args.slippage_bps)
        with Store(args.db) as store:
            series = load_series(store, args.inst, args.tf, start_ms, end_ms)
            if len(series) < 2:
                print(
                    f"cannot split {len(series)} stored bar(s); at least 2 are required"
                )
                return 1
            cut_index = int(len(series) * args.split)
            if cut_index <= 0 or cut_index >= len(series):
                print(
                    f"--split {args.split} leaves an empty segment for "
                    f"{len(series)} stored bars"
                )
                return 1

            historical_series = _slice_series(series, 0, cut_index)
            recent_evaluation = _slice_series(series, cut_index, len(series))

            historical_strategy = REGISTRY[args.strategy_name].build(args)
            historical_result = run_backtest(
                historical_strategy,
                historical_series,
                spec,
                initial_cash=args.initial_cash,
                costs=costs,
                funding=_funding_model(store, args, swap),
                sizing=Sizing(args.sizing),
            )

            recent_strategy = REGISTRY[args.strategy_name].build(args)
            warmup_start = max(0, cut_index - recent_strategy.warmup_bars)
            recent_input = _slice_series(series, warmup_start, len(series))
            recent_result = run_backtest(
                recent_strategy,
                recent_input,
                spec,
                initial_cash=args.initial_cash,
                costs=costs,
                funding=_funding_model(store, args, swap),
                sizing=Sizing(args.sizing),
                evaluation_start_ms=int(series.ts[cut_index]),
            )

            historical_benchmark_strategy = BuyAndHold()
            historical_benchmark_result = run_backtest(
                historical_benchmark_strategy,
                historical_series,
                spec,
                initial_cash=args.initial_cash,
                costs=costs,
                funding=_funding_model(store, args, swap),
                sizing=Sizing(args.sizing),
                initial_intent=Intent(target=1.0, reason="buy-and-hold"),
            )
            recent_benchmark_strategy = BuyAndHold()
            recent_benchmark_result = run_backtest(
                recent_benchmark_strategy,
                recent_evaluation,
                spec,
                initial_cash=args.initial_cash,
                costs=costs,
                funding=_funding_model(store, args, swap),
                sizing=Sizing(args.sizing),
                initial_intent=Intent(target=1.0, reason="buy-and-hold"),
            )
            full_strategy = REGISTRY[args.strategy_name].build(args)
            full_result = run_backtest(
                full_strategy,
                series,
                spec,
                initial_cash=args.initial_cash,
                costs=costs,
                funding=_funding_model(store, args, swap),
                sizing=Sizing(args.sizing),
            )
            full_benchmark_strategy = BuyAndHold()
            full_benchmark_result = run_backtest(
                full_benchmark_strategy,
                series,
                spec,
                initial_cash=args.initial_cash,
                costs=costs,
                funding=_funding_model(store, args, swap),
                sizing=Sizing(args.sizing),
                initial_intent=Intent(target=1.0, reason="buy-and-hold"),
            )
    except (MissingFundingError, TradingError, ValueError) as exc:
        print(exc)
        return 1

    historical = SegmentResult(
        "historical",
        historical_result,
        historical_series,
        warmup_bars=0,
    )
    recent = SegmentResult(
        "recent",
        recent_result,
        recent_evaluation,
        warmup_bars=cut_index - warmup_start,
    )
    historical_benchmark = SegmentResult(
        "historical",
        historical_benchmark_result,
        historical_series,
        warmup_bars=0,
    )
    recent_benchmark = SegmentResult(
        "recent",
        recent_benchmark_result,
        recent_evaluation,
        warmup_bars=0,
    )
    full = SegmentResult(
        "full",
        full_result,
        series,
        warmup_bars=0,
    )
    full_benchmark = SegmentResult(
        "full",
        full_benchmark_result,
        series,
        warmup_bars=0,
    )
    output_root = Path(args.output_dir)
    run_id, created_at, artifact_dir = new_run_identity(
        historical_result.strategy,
        args.inst,
        output_root,
    )
    payload = build_payload(
        run_id=run_id,
        created_at=created_at,
        artifact_dir=artifact_dir,
        config={
            "strategy": historical_result.strategy,
            "strategy_registry_name": args.strategy_name,
            "inst_id": args.inst,
            "market_type": spec.market_type,
            "timeframe": args.tf,
            "data_start": utc_iso(int(series.ts[0])),
            "data_end": utc_iso(int(series.ts[-1]) + duration_ms(args.tf)),
            "initial_cash": args.initial_cash,
            "fee_bps": args.fee_bps,
            "slippage_bps": args.slippage_bps,
            "costs": historical_result.cost_label,
            "sizing": args.sizing,
            "leverage": args.leverage if swap else 1.0,
            "funding_mode": args.funding if swap else "off",
            "funding_rate_bps": args.funding_rate,
            "funding": historical_result.funding_label,
            "database": str(args.db),
            "requested_start": args.start,
            "requested_end": args.end,
        },
        full_series=series,
        split=args.split,
        cut_index=cut_index,
        historical=historical,
        recent=recent,
        historical_benchmark=historical_benchmark,
        recent_benchmark=recent_benchmark,
        full=full,
        full_benchmark=full_benchmark,
    )
    write_bundle(payload, artifact_dir)
    if args.output_format == "json":
        print(
            json.dumps(
                summary_payload(payload),
                ensure_ascii=False,
                indent=2,
                allow_nan=False,
            )
        )
    else:
        print(render_text(payload, show_trades=args.show_trades))
    return 0


def _parse_utc_date(text: str) -> int:
    parsed = dt.datetime.strptime(text, "%Y-%m-%d").replace(tzinfo=dt.UTC)
    return int(parsed.timestamp() * 1000)


def _funding_model(store: Store, args: argparse.Namespace, swap: bool):
    if not swap or args.funding == "off":
        return NoFunding()
    if args.funding == "actual":
        return load_actual_funding(store, args.inst)
    rate = cast(float, args.funding_rate)
    return AssumedFunding(rate=rate / 10_000)


def _slice_series(series: Series, start: int, end: int) -> Series:
    return Series(
        inst_id=series.inst_id,
        timeframe=series.timeframe,
        ts=series.ts[start:end],
        open=series.open[start:end],
        high=series.high[start:end],
        low=series.low[start:end],
        close=series.close[start:end],
        volume=series.volume[start:end],
    )
