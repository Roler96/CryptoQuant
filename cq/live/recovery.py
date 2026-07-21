"""Crash-safe reconstruction of a paper session from JSONL and OKX.

The exchange owns the current balance and resting orders. The log owns the
pieces a spot balance cannot express: strategy state and average entry cost.
Recovery only proceeds when those two views agree; an unexplained position or
algo is an error, never something the runner guesses around.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from cq.core.types import Side
from cq.live.broker import LiveBroker
from cq.live.protocols import ProtectiveOrder

CHECKPOINT_VERSION = 1


class RecoveryError(RuntimeError):
    """The exchange and durable checkpoint cannot be reconciled safely."""


@dataclass(frozen=True)
class PaperCheckpoint:
    """The durable state captured after one paper decision."""

    ts: int
    inst_id: str
    timeframe: str
    strategy: str
    target: float
    held: float
    cash: float
    average_entry: float | None
    strategy_state: dict[str, object]
    protection: ProtectiveOrder | None
    source: Path


@dataclass(frozen=True)
class SessionResume:
    """State already reconciled against the exchange and safe to restore."""

    checkpoint_ts: int
    average_entry: float | None
    strategy_state: dict[str, object]
    source: Path


def load_latest_checkpoint(
    log_dir: Path,
    inst_id: str,
    timeframe: str,
) -> PaperCheckpoint | None:
    """Load the newest complete versioned event for an instrument/timeframe.

    Empty files and a torn final JSON line are expected after a crash. A legacy
    row predating checkpoints returns ``None``; it is not silently interpreted
    as state it never recorded.
    """
    pattern = f"{inst_id}_{timeframe}_*.jsonl"
    for path in sorted(log_dir.glob(pattern), reverse=True):
        row = _last_complete_row(path)
        if row is None:
            continue
        if "checkpoint_version" not in row:
            return None
        return _checkpoint_from_row(row, path, inst_id, timeframe)
    return None


def reconcile_restart(
    strategy_name: str,
    broker: LiveBroker,
    checkpoint: PaperCheckpoint | None,
) -> SessionResume | None:
    """Validate durable state against OKX and adopt/rebuild its protection."""
    account = broker.reconcile()
    pending = broker.client.pending_protective_orders(broker.spec.inst_id)
    for order in pending:
        if order.side is not Side.SELL:
            raise RecoveryError(
                f"{broker.spec.inst_id}: unexpected pending {order.side.value} algo "
                f"{order.algo_id}"
            )

    actual_flat = broker.is_effectively_flat(account.held)
    if checkpoint is None:
        if not actual_flat:
            raise RecoveryError(
                f"{broker.spec.inst_id}: exchange holds {account.held} but no resumable "
                "checkpoint exists"
            )
        if pending:
            raise RecoveryError(
                f"{broker.spec.inst_id}: exchange has pending algo(s) but no resumable "
                "checkpoint exists"
            )
        return None

    if checkpoint.strategy != strategy_name:
        raise RecoveryError(
            f"latest checkpoint belongs to strategy {checkpoint.strategy!r}, "
            f"not {strategy_name!r}"
        )
    if checkpoint.inst_id != broker.spec.inst_id:
        raise RecoveryError(
            f"checkpoint instrument {checkpoint.inst_id!r} does not match "
            f"{broker.spec.inst_id!r}"
        )

    if actual_flat:
        if pending:
            ids = ", ".join(order.algo_id for order in pending)
            raise RecoveryError(
                f"{broker.spec.inst_id}: account is flat but protective algo(s) remain: {ids}"
            )
        return SessionResume(
            checkpoint_ts=checkpoint.ts,
            average_entry=None,
            strategy_state=dict(checkpoint.strategy_state),
            source=checkpoint.source,
        )

    if broker.is_effectively_flat(checkpoint.held) or not _quantity_matches(
        broker, account.held, checkpoint.held
    ):
        raise RecoveryError(
            f"{broker.spec.inst_id}: exchange holding {account.held} does not match "
            f"checkpoint holding {checkpoint.held}"
        )
    if checkpoint.average_entry is None:
        raise RecoveryError(
            f"{broker.spec.inst_id}: non-flat checkpoint has no recoverable average entry"
        )

    logged = checkpoint.protection
    if logged is not None and not _quantity_matches(broker, logged.quantity, account.held):
        raise RecoveryError(
            f"{broker.spec.inst_id}: checkpoint protection quantity {logged.quantity} "
            f"does not cover exchange holding {account.held}"
        )
    if len(pending) > 1:
        ids = ", ".join(order.algo_id for order in pending)
        raise RecoveryError(f"{broker.spec.inst_id}: multiple protective algos are pending: {ids}")
    if logged is None and pending:
        raise RecoveryError(
            f"{broker.spec.inst_id}: pending algo {pending[0].algo_id} is absent from checkpoint"
        )
    if logged is not None and pending:
        venue = pending[0]
        if not _protection_matches(broker, venue, logged):
            raise RecoveryError(
                f"{broker.spec.inst_id}: pending algo {venue.algo_id} does not match checkpoint "
                f"algo {logged.algo_id}"
            )
        broker.adopt_protection(venue)
    elif logged is not None:
        state = broker.client.protective_order_state(broker.spec.inst_id, logged.algo_id)
        if state in ("canceled", "order_failed"):
            # The process may have died after canceling the old order but
            # before logging its replacement. Rebuild from durable levels
            # around the exchange's actual holding.
            broker.sync_protection(account.held, logged.stop_loss, logged.take_profit)
        else:
            raise RecoveryError(
                f"{broker.spec.inst_id}: checkpoint algo {logged.algo_id} is {state!r} "
                "but absent from pending orders"
            )

    return SessionResume(
        checkpoint_ts=checkpoint.ts,
        average_entry=checkpoint.average_entry,
        strategy_state=dict(checkpoint.strategy_state),
        source=checkpoint.source,
    )


def _last_complete_row(path: Path) -> dict[str, Any] | None:
    """Newest decodable object in a JSONL file, tolerating a torn last line."""
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except OSError as exc:
        raise RecoveryError(f"could not read paper log {path}: {exc}") from exc
    for line in reversed(lines):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(row, dict):
            return row
    return None


def _checkpoint_from_row(
    row: dict[str, Any],
    source: Path,
    expected_inst_id: str,
    expected_timeframe: str,
) -> PaperCheckpoint:
    """Validate an untrusted JSON object before it can control live state."""
    if row.get("checkpoint_version") != CHECKPOINT_VERSION:
        raise RecoveryError(
            f"{source}: unsupported checkpoint version {row.get('checkpoint_version')!r}"
        )
    try:
        inst_id = str(row["inst_id"])
        timeframe = str(row["timeframe"])
        strategy = str(row["strategy"])
        ts = int(row["ts"])
        target = _finite_float(row["target"], "target")
        held = _finite_float(row["held_after"], "held_after")
        cash = _finite_float(row["cash_after"], "cash_after")
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise RecoveryError(f"{source}: malformed paper checkpoint: {exc}") from exc
    if inst_id != expected_inst_id or timeframe != expected_timeframe:
        raise RecoveryError(
            f"{source}: checkpoint key {(inst_id, timeframe)!r} does not match "
            f"{(expected_inst_id, expected_timeframe)!r}"
        )
    raw_state = row.get("strategy_state")
    if not isinstance(raw_state, dict):
        raise RecoveryError(f"{source}: checkpoint has no restorable strategy_state")
    average_entry = _optional_positive(row.get("average_entry"), "average_entry")
    protection = _protection_from_row(row.get("protection"), source)
    if held < 0 or cash < 0:
        raise RecoveryError(f"{source}: spot checkpoint balances must be non-negative")
    return PaperCheckpoint(
        ts=ts,
        inst_id=inst_id,
        timeframe=timeframe,
        strategy=strategy,
        target=target,
        held=held,
        cash=cash,
        average_entry=average_entry,
        strategy_state=dict(raw_state),
        protection=protection,
        source=source,
    )


def _protection_from_row(value: Any, source: Path) -> ProtectiveOrder | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise RecoveryError(f"{source}: malformed protection checkpoint")
    try:
        algo_id = str(value["algo_id"])
        quantity = _finite_float(value["quantity"], "protection.quantity")
        side = Side(str(value.get("side", "sell")))
    except (KeyError, TypeError, ValueError, OverflowError) as exc:
        raise RecoveryError(f"{source}: malformed protection checkpoint: {exc}") from exc
    stop_loss = _optional_positive(value.get("stop_loss"), "protection.stop_loss")
    take_profit = _optional_positive(value.get("take_profit"), "protection.take_profit")
    if not algo_id or quantity <= 0 or (stop_loss is None and take_profit is None):
        raise RecoveryError(f"{source}: malformed protection checkpoint")
    return ProtectiveOrder(algo_id, quantity, stop_loss, take_profit, side)


def _finite_float(value: Any, name: str) -> float:
    if isinstance(value, bool):
        raise ValueError(f"{name} must be numeric, not boolean")
    number = float(value)
    if not math.isfinite(number):
        raise ValueError(f"{name} must be finite")
    return number


def _optional_positive(value: Any, name: str) -> float | None:
    if value is None:
        return None
    try:
        number = _finite_float(value, name)
    except (TypeError, ValueError, OverflowError) as exc:
        raise RecoveryError(f"{name} must be a finite positive number") from exc
    if number <= 0:
        raise RecoveryError(f"{name} must be positive")
    return number


def _quantity_matches(broker: LiveBroker, left: float, right: float) -> bool:
    tolerance = max(broker.spec.lot_size * 1e-6, 1e-9)
    return math.isclose(left, right, rel_tol=1e-9, abs_tol=tolerance)


def _level_matches(left: float | None, right: float | None) -> bool:
    if left is None or right is None:
        return left is right
    return math.isclose(left, right, rel_tol=1e-12, abs_tol=1e-12)


def _protection_matches(
    broker: LiveBroker,
    venue: ProtectiveOrder,
    logged: ProtectiveOrder,
) -> bool:
    return (
        venue.algo_id == logged.algo_id
        and venue.side is logged.side
        and _quantity_matches(broker, venue.quantity, logged.quantity)
        and _level_matches(venue.stop_loss, logged.stop_loss)
        and _level_matches(venue.take_profit, logged.take_profit)
    )
