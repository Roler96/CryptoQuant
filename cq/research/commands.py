"""CLI wiring for research studies."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from cq.data.store import DEFAULT_DB_PATH, Store
from cq.research.bar_sequence.runner import run_study

DEFAULT_OUT_PATH = Path("reports/research/doge_bar_sequence_gbm.json")


def _run_bar_sequence_gbm(args: argparse.Namespace) -> int:
    db_path = Path(args.db) if args.db else DEFAULT_DB_PATH
    out_path = Path(args.out) if args.out else DEFAULT_OUT_PATH
    out_path.parent.mkdir(parents=True, exist_ok=True)

    with Store(db_path) as store:
        report = run_study(store)

    out_path.write_text(json.dumps(report, indent=2, default=str))
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
