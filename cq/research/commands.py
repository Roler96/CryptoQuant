"""CLI wiring for immutable forward research observers."""

from __future__ import annotations

import argparse
import datetime as dt

from cq.calibration import calibration_status
from cq.data.store import DEFAULT_DB_PATH, Store
from cq.research.oifr import (
    adjudicate_ledger,
    capture_latest,
    settle_matured,
    summarize_ledger,
)


def register(subparsers: argparse._SubParsersAction) -> None:
    observe = subparsers.add_parser(
        "observe-oifr", help="capture the current forward-only DOGE OIFR decision slot"
    )
    observe.add_argument("--db", default=str(DEFAULT_DB_PATH), help="SQLite path")
    observe.add_argument(
        "--calibration-artifact",
        help="spot gate artifact; capture continues when absent, adjudication does not",
    )
    observe.set_defaults(handler=cmd_observe_oifr)


def cmd_observe_oifr(args: argparse.Namespace) -> int:
    observed_at = int(dt.datetime.now(dt.UTC).timestamp() * 1000)
    # OIFR is a directional entry/exit observer, not a constant-weight
    # rebalancer. A spot/rebalance artifact cannot authorize its adjudication.
    gate = calibration_status("spot", "on_entry", args.calibration_artifact)
    with Store(args.db) as store:
        capture = capture_latest(store, observed_at)
        settlements = settle_matured(store, observed_at)
        summary = summarize_ledger(store)
        adjudication = adjudicate_ledger(store, observed_at) if gate.is_open else None

    timestamp = _fmt(capture.decision_time)
    details = ""
    if capture.status == "valid" and gate.is_open:
        details = (
            f" raw_event={capture.payload['raw_event']}"
            f" accepted={capture.payload['accepted']}"
        )
    elif capture.status in {"data_unavailable", "missed_late"}:
        details = f" reason={capture.payload.get('reason', capture.status)}"
    print(
        f"OIFR decision={timestamp} status={capture.status} inserted={capture.inserted}"
        f"{details}"
    )
    print(
        "ledger: "
        f"captures={summary.captures} valid={summary.valid_captures} "
        f"unavailable={summary.unavailable_captures} late={summary.missed_late} "
        f"signals={summary.accepted_signals} outcomes={summary.settled_outcomes} "
        f"stage={adjudication.status if adjudication is not None else 'GATE-BLOCKED'} "
        f"newly_settled={len(settlements)}"
    )
    if adjudication is None:
        print(f"adjudication blocked: spot calibration gate is CLOSED — {gate.reason}")
    else:
        print(
            "maturity: "
            f"expected={int(adjudication.metrics['expected_capture_slots'])} "
            f"capture_rate={float(adjudication.metrics['capture_rate']):.4f} "
            f"valid_rate={float(adjudication.metrics['valid_capture_rate']):.4f} "
            f"failures={','.join(adjudication.maturity_failures)}"
        )
    return 1 if capture.status in {"data_unavailable", "missed_late"} else 0


def _fmt(ms: int) -> str:
    return dt.datetime.fromtimestamp(ms / 1000, dt.UTC).strftime("%Y-%m-%d %H:%M UTC")
