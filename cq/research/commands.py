"""CLI wiring for research studies."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from cq.data.store import DEFAULT_DB_PATH, Store
from cq.research.bar_sequence.runner import run_study
from cq.research.crdr.runner import run_study as run_crdr_study

BAR_SEQUENCE_OUT_PATH = Path("reports/research/doge_bar_sequence_gbm.json")
CRDR_OUT_PATH = Path("reports/research/crdr_v1.json")


def _run_bar_sequence_gbm(args: argparse.Namespace) -> int:
    db_path = Path(args.db) if args.db else DEFAULT_DB_PATH
    out_path = Path(args.out) if args.out else BAR_SEQUENCE_OUT_PATH
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with Store(db_path) as store:
        report = run_study(store)

    out_path.write_text(json.dumps(report, indent=2, default=str))
    print(f"wrote {out_path}")
    return 0


def _run_crdr(args: argparse.Namespace) -> int:
    db_path = Path(args.db) if args.db else DEFAULT_DB_PATH
    out_path = Path(args.out) if args.out else CRDR_OUT_PATH
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with Store(db_path) as store:
        report = run_crdr_study(store)

    out_path.write_text(json.dumps(report, indent=2, default=str) + "\n")
    print(f"wrote {out_path}")
    return 0


def register(subparsers: argparse._SubParsersAction) -> None:
    bar_sequence_gbm = subparsers.add_parser(
        "bar-sequence-gbm", help="doge-bar-sequence-gbm-v1: bar-return-sequence GBM study"
    )
    bar_sequence_sub = bar_sequence_gbm.add_subparsers(
        dest="bar_sequence_command", required=True
    )

    run_parser = bar_sequence_sub.add_parser("run", help="run the frozen protocol end to end")
    run_parser.add_argument(
        "--out", help="output JSON path (default: reports/research/doge_bar_sequence_gbm.json)"
    )
    run_parser.add_argument("--db", help="sqlite db path (default: data/cq.db)")
    run_parser.set_defaults(handler=_run_bar_sequence_gbm)

    crdr = subparsers.add_parser(
        "crdr", help="crypto-cross-sectional-residual-dispersion-reversion-v1"
    )
    crdr_sub = crdr.add_subparsers(dest="crdr_command", required=True)
    crdr_run = crdr_sub.add_parser("run", help="run the frozen CRDR protocol end to end")
    crdr_run.add_argument(
        "--out", help="output JSON path (default: reports/research/crdr_v1.json)"
    )
    crdr_run.add_argument("--db", help="sqlite db path (default: data/cq.db)")
    crdr_run.set_defaults(handler=_run_crdr)
