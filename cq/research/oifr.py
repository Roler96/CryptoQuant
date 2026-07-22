"""Forward-only observer for DOGE open-interest flush reversals.

The study is deliberately unlike a backtest. It captures only the decision
slot that is current when the function runs, persists the exact derived state
once, and refuses to revise or catch up an older slot. Historical rows may be
used as a causal warm-up, but never become historical strategy observations.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from hashlib import sha256
from typing import Any, cast

import numpy as np
import pandas as pd

from cq.data.store import ForwardRecord, Store

STUDY = "DOGE_OIFR_V1"
CAPTURE = "capture"
OUTCOME = "outcome"

HOUR_MS = 3_600_000
DAY_MS = 24 * HOUR_MS
MINUTE_MS = 60_000
FORWARD_START_DECISION = 1_784_714_400_000  # 2026-07-22 10:00:00 UTC
CAPTURE_EARLIEST_LAG_MS = 10 * MINUTE_MS
CAPTURE_LATEST_LAG_MS = 30 * MINUTE_MS
OI_LAG_HOURS = 6
BASELINE_CHANGES = 720
FUNDING_MAX_AGE_MS = 8 * HOUR_MS
MIN_SIGNAL_SPACING_MS = 61 * HOUR_MS
ENTRY_DELAY_HOURS = 1
HOLD_HOURS = 12
TARGET_RETURN = 0.10
POSITION_WEIGHT = 0.10
BASE_COST_BPS = 15.0
STRESS_COST_BPS = 25.0
OUTCOME_FINALIZATION_LAG_MS = 2 * HOUR_MS
MIN_FORWARD_DAYS = 365
MIN_SETTLED_EPISODES = 60
MIN_CAPTURE_RATE = 0.98
MIN_VALID_CAPTURE_RATE = 0.95
MIN_SIGNAL_QUARTERS = 3
BOOTSTRAP_SAMPLES = 10_000
BOOTSTRAP_BLOCK_SIZE = 4
BOOTSTRAP_SEED = 20_260_722


@dataclass(frozen=True)
class CaptureResult:
    """Result of attempting the one decision slot current at ``observed_at``."""

    decision_time: int
    status: str
    inserted: bool
    payload: dict[str, Any]


@dataclass(frozen=True)
class SettlementResult:
    """An accepted signal whose paper outcome was newly frozen."""

    decision_time: int
    inserted: bool
    payload: dict[str, Any]


@dataclass(frozen=True)
class LedgerSummary:
    captures: int
    valid_captures: int
    unavailable_captures: int
    missed_late: int
    accepted_signals: int
    settled_outcomes: int
    first_decision: int | None
    last_decision: int | None
    status: str


@dataclass(frozen=True)
class Adjudication:
    """Frozen maturity state and, only when mature, the one-shot verdict."""

    status: str
    mature: bool
    maturity_failures: tuple[str, ...]
    gates: dict[str, bool]
    metrics: dict[str, float | int]


class InputUnavailable(ValueError):
    """A causal input for the current decision slot is absent or invalid."""


def capture_latest(store: Store, observed_at: int) -> CaptureResult:
    """Capture only the current hourly decision slot, never historical slots."""
    decision_time = observed_at // HOUR_MS * HOUR_MS
    if decision_time < FORWARD_START_DECISION:
        return CaptureResult(
            decision_time=decision_time,
            status="not_started",
            inserted=False,
            payload={"status": "not_started", "forward_start": FORWARD_START_DECISION},
        )

    existing = _record_for(store, CAPTURE, decision_time)
    if existing is not None:
        payload = _decode(existing)
        return CaptureResult(decision_time, str(payload["status"]), False, payload)

    lag_ms = observed_at - decision_time
    if lag_ms < CAPTURE_EARLIEST_LAG_MS:
        return CaptureResult(
            decision_time=decision_time,
            status="too_early",
            inserted=False,
            payload={
                "status": "too_early",
                "decision_time": decision_time,
                "retry_at": decision_time + CAPTURE_EARLIEST_LAG_MS,
            },
        )
    if lag_ms > CAPTURE_LATEST_LAG_MS:
        payload = {
            "schema_version": 1,
            "status": "missed_late",
            "decision_time": decision_time,
            "capture_lag_ms": lag_ms,
            "latest_allowed_lag_ms": CAPTURE_LATEST_LAG_MS,
        }
        inserted = _append(store, CAPTURE, decision_time, observed_at, payload)
        return CaptureResult(decision_time, "missed_late", inserted, payload)

    try:
        inputs = _decision_inputs(store, decision_time, observed_at)
    except InputUnavailable as exc:
        payload = {
            "schema_version": 1,
            "status": "data_unavailable",
            "decision_time": decision_time,
            "capture_lag_ms": lag_ms,
            "reason": str(exc),
        }
        inserted = _append(store, CAPTURE, decision_time, observed_at, payload)
        return CaptureResult(decision_time, "data_unavailable", inserted, payload)

    criteria = {
        "oi_flush": inputs["oi_change_6h"] < inputs["oi_q05"],
        "spot_down_6h": inputs["spot_return_6h"] < 0.0,
        "positive_realized_funding": inputs["realized_funding"] > 0.0,
        "spot_reversal_1h": inputs["spot_return_1h"] > 0.0,
    }
    raw_event = all(criteria.values())
    last_accepted = _last_accepted_decision(store, decision_time)
    cooldown_until = (
        last_accepted + MIN_SIGNAL_SPACING_MS if last_accepted is not None else None
    )
    cooldown_clear = cooldown_until is None or decision_time >= cooldown_until
    accepted = raw_event and cooldown_clear

    payload = {
        "schema_version": 1,
        "status": "valid",
        "decision_time": decision_time,
        "bar_open": decision_time - HOUR_MS,
        "features": {
            key: inputs[key]
            for key in (
                "oi_change_6h",
                "oi_q05",
                "spot_return_6h",
                "spot_return_1h",
                "realized_funding",
                "funding_time",
            )
        },
        "criteria": criteria,
        "raw_event": raw_event,
        "cooldown_clear": cooldown_clear,
        "previous_accepted_decision": last_accepted,
        "cooldown_until": cooldown_until,
        "accepted": accepted,
        "paper_plan": _paper_plan(decision_time) if accepted else None,
        "source": inputs["source"],
        "input_sha256": inputs["input_sha256"],
    }
    inserted = _append(store, CAPTURE, decision_time, observed_at, payload)
    return CaptureResult(decision_time, "valid", inserted, payload)


def settle_matured(store: Store, observed_at: int) -> list[SettlementResult]:
    """Append immutable paper outcomes for accepted signals that have matured."""
    outcomes = {record.decision_time for record in store.load_forward_records(STUDY, OUTCOME)}
    settled: list[SettlementResult] = []
    for record in store.load_forward_records(STUDY, CAPTURE):
        if record.decision_time in outcomes:
            continue
        capture = _decode(record)
        if capture.get("status") != "valid" or not capture.get("accepted"):
            continue
        plan = capture["paper_plan"]
        exit_ts = int(plan["scheduled_exit_ts"])
        if observed_at < exit_ts + OUTCOME_FINALIZATION_LAG_MS:
            continue
        try:
            payload = _paper_outcome(store, record.decision_time, observed_at)
        except InputUnavailable:
            # Outcomes may be settled later: unlike a signal, filling a missing
            # old price cannot change which trade was selected.
            continue
        inserted = _append(store, OUTCOME, record.decision_time, observed_at, payload)
        settled.append(SettlementResult(record.decision_time, inserted, payload))
    return settled


def summarize_ledger(store: Store) -> LedgerSummary:
    """Small operational summary; statistical adjudication waits for maturity."""
    captures = store.load_forward_records(STUDY, CAPTURE)
    outcomes = store.load_forward_records(STUDY, OUTCOME)
    payloads = [_decode(record) for record in captures]
    valid = sum(payload.get("status") == "valid" for payload in payloads)
    unavailable = sum(payload.get("status") == "data_unavailable" for payload in payloads)
    late = sum(payload.get("status") == "missed_late" for payload in payloads)
    accepted = sum(bool(payload.get("accepted")) for payload in payloads)
    times = [record.decision_time for record in captures]
    return LedgerSummary(
        captures=len(captures),
        valid_captures=valid,
        unavailable_captures=unavailable,
        missed_late=late,
        accepted_signals=accepted,
        settled_outcomes=len(outcomes),
        first_decision=min(times) if times else None,
        last_decision=max(times) if times else None,
        status="FORWARD_INCONCLUSIVE",
    )


def adjudicate_ledger(store: Store, as_of: int) -> Adjudication:
    """Apply the protocol's frozen maturity and shadow-candidate gates."""
    capture_records = store.load_forward_records(STUDY, CAPTURE)
    outcome_records = store.load_forward_records(STUDY, OUTCOME)
    captures = [_decode(record) for record in capture_records]
    outcomes = [_decode(record) for record in outcome_records]

    expected_slots = _expected_capture_slots(as_of)
    capture_rate = len(captures) / expected_slots if expected_slots else 0.0
    valid_count = sum(payload.get("status") == "valid" for payload in captures)
    valid_rate = valid_count / len(captures) if captures else 0.0
    accepted_times = [
        record.decision_time
        for record, payload in zip(capture_records, captures, strict=True)
        if bool(payload.get("accepted"))
    ]
    signal_quarters = len({_utc_quarter(timestamp) for timestamp in accepted_times})
    elapsed_days = max(0.0, (as_of - FORWARD_START_DECISION) / DAY_MS)

    maturity_checks = {
        "365_calendar_days": elapsed_days >= MIN_FORWARD_DAYS,
        "60_settled_episodes": len(outcomes) >= MIN_SETTLED_EPISODES,
        "98pct_capture_rate": capture_rate >= MIN_CAPTURE_RATE,
        "95pct_valid_capture_rate": valid_rate >= MIN_VALID_CAPTURE_RATE,
        "three_signal_quarters": signal_quarters >= MIN_SIGNAL_QUARTERS,
        "outcomes_belong_to_accepted_signals": all(
            record.decision_time in accepted_times for record in outcome_records
        ),
    }
    maturity_failures = tuple(name for name, passed in maturity_checks.items() if not passed)
    base_returns = np.asarray(
        [float(payload["base_account_return"]) for payload in outcomes], dtype=float
    )
    stress_returns = np.asarray(
        [float(payload["stress_account_return"]) for payload in outcomes], dtype=float
    )
    episode_returns = np.asarray(
        [float(payload["base_episode_return"]) for payload in outcomes], dtype=float
    )
    metrics: dict[str, float | int] = {
        "elapsed_days": elapsed_days,
        "expected_capture_slots": expected_slots,
        "capture_count": len(captures),
        "capture_rate": capture_rate,
        "valid_capture_count": valid_count,
        "valid_capture_rate": valid_rate,
        "accepted_signals": len(accepted_times),
        "settled_outcomes": len(outcomes),
        "signal_quarters": signal_quarters,
    }
    if maturity_failures:
        return Adjudication(
            status="FORWARD_INCONCLUSIVE",
            mature=False,
            maturity_failures=maturity_failures,
            gates={},
            metrics=metrics,
        )

    base_total = _compound(base_returns)
    stress_total = _compound(stress_returns)
    less_best = _compound(np.delete(base_returns, int(np.argmax(base_returns))))
    bootstrap_p05 = _circular_block_mean_p05(episode_returns)
    positive_quarter_concentration = _positive_quarter_concentration(
        outcome_records, outcomes
    )
    gates = {
        "base_total_positive": base_total > 0.0,
        "mean_episode_positive": float(np.mean(episode_returns)) > 0.0,
        "stress_total_positive": stress_total > 0.0,
        "less_best_positive": less_best > 0.0,
        "block_bootstrap_mean_p05_positive": bootstrap_p05 > 0.0,
        "positive_quarter_concentration_le_50pct": positive_quarter_concentration <= 0.50,
        "ledger_alignment": len(outcomes) <= len(accepted_times),
    }
    metrics.update(
        {
            "base_total_return": base_total,
            "mean_base_episode_return": float(np.mean(episode_returns)),
            "stress_total_return": stress_total,
            "less_best_total_return": less_best,
            "block_bootstrap_mean_p05": bootstrap_p05,
            "positive_quarter_concentration": positive_quarter_concentration,
        }
    )
    passed = all(gates.values())
    return Adjudication(
        status="SHADOW_PAPER_CANDIDATE" if passed else "REJECTED",
        mature=True,
        maturity_failures=(),
        gates=gates,
        metrics=metrics,
    )


def _decision_inputs(store: Store, decision_time: int, observed_at: int) -> dict[str, Any]:
    bar_ts = decision_time - HOUR_MS
    source_start = bar_ts - (BASELINE_CHANGES + OI_LAG_HOURS) * HOUR_MS
    source_end = decision_time

    oi = store.load_open_interest("DOGE", source_start, source_end)
    swap = store.load_ohlcv("DOGE-USDT-SWAP", "1h", source_start, source_end)
    spot_start = bar_ts - OI_LAG_HOURS * HOUR_MS
    spot = store.load_ohlcv("DOGE-USDT", "1h", spot_start, source_end)

    expected_long = pd.date_range(
        pd.to_datetime(source_start, unit="ms", utc=True),
        pd.to_datetime(bar_ts, unit="ms", utc=True),
        freq="1h",
    )
    expected_spot = pd.date_range(
        pd.to_datetime(spot_start, unit="ms", utc=True),
        pd.to_datetime(bar_ts, unit="ms", utc=True),
        freq="1h",
    )
    _require_index(oi, expected_long, "open_interest")
    _require_index(swap, expected_long, "swap_ohlcv")
    _require_index(spot, expected_spot, "spot_ohlcv")

    oi_usd = _positive_array(oi["oi_usd"], "oi_usd")
    swap_close = _positive_array(swap["close"], "swap_close")
    spot_close = _positive_array(spot["close"], "spot_close")
    fetched = _finite_array(oi["fetched_at"], "oi_fetched_at")
    if np.any(fetched > observed_at):
        raise InputUnavailable("open_interest_fetched_after_observation")

    normalized_oi = oi_usd / swap_close
    changes = np.log(normalized_oi[OI_LAG_HOURS:] / normalized_oi[:-OI_LAG_HOURS])
    if len(changes) != BASELINE_CHANGES + 1:
        raise InputUnavailable("open_interest_change_window_wrong_length")
    baseline = changes[:-1]
    current_change = float(changes[-1])
    q05 = float(np.quantile(baseline, 0.05, method="linear"))

    funding = store.load_funding_frame(
        "DOGE-USDT-SWAP", end_ms=decision_time + 1
    )
    funding = funding[funding["realized_rate"].notna()]
    if funding.empty:
        raise InputUnavailable("no_realized_funding")
    latest = funding.iloc[-1]
    funding_index = cast(pd.DatetimeIndex, funding.index)
    funding_time = int(funding_index.asi8[-1]) // 1_000_000
    funding_age = decision_time - funding_time
    if funding_age < 0 or funding_age > FUNDING_MAX_AGE_MS:
        raise InputUnavailable("realized_funding_stale")
    realized_funding = float(latest["realized_rate"])
    funding_fetched_at = int(latest["fetched_at"])
    if not math.isfinite(realized_funding):
        raise InputUnavailable("realized_funding_non_finite")
    if funding_fetched_at > observed_at:
        raise InputUnavailable("funding_fetched_after_observation")

    input_digest = _digest(
        {
            "timestamps": _index_milliseconds(expected_long),
            "oi_usd": oi_usd.tolist(),
            "swap_close": swap_close.tolist(),
            "spot_timestamps": _index_milliseconds(expected_spot),
            "spot_close": spot_close.tolist(),
            "funding_time": funding_time,
            "realized_funding": realized_funding,
            "funding_fetched_at": funding_fetched_at,
        }
    )
    return {
        "oi_change_6h": current_change,
        "oi_q05": q05,
        "spot_return_6h": float(math.log(spot_close[-1] / spot_close[0])),
        "spot_return_1h": float(math.log(spot_close[-1] / spot_close[-2])),
        "realized_funding": realized_funding,
        "funding_time": funding_time,
        "source": {
            "window_start": source_start,
            "window_end_exclusive": source_end,
            "oi_rows": len(oi),
            "swap_rows": len(swap),
            "spot_rows": len(spot),
            "oi_fetched_at_min": int(fetched.min()),
            "oi_fetched_at_max": int(fetched.max()),
            "funding_fetched_at": funding_fetched_at,
        },
        "input_sha256": input_digest,
    }


def _paper_plan(decision_time: int) -> dict[str, int | float]:
    entry_ts = decision_time + ENTRY_DELAY_HOURS * HOUR_MS
    exit_ts = entry_ts + HOLD_HOURS * HOUR_MS
    return {
        "entry_ts": entry_ts,
        "scheduled_exit_ts": exit_ts,
        "hold_hours": HOLD_HOURS,
        "target_return": TARGET_RETURN,
        "position_weight": POSITION_WEIGHT,
        "base_cost_bps_per_side": BASE_COST_BPS,
        "stress_cost_bps_per_side": STRESS_COST_BPS,
    }


def _paper_outcome(store: Store, decision_time: int, observed_at: int) -> dict[str, Any]:
    plan = _paper_plan(decision_time)
    entry_ts = int(plan["entry_ts"])
    exit_ts = int(plan["scheduled_exit_ts"])
    spot = store.load_ohlcv("DOGE-USDT", "1h", entry_ts, exit_ts + 1)
    expected = pd.date_range(
        pd.to_datetime(entry_ts, unit="ms", utc=True),
        pd.to_datetime(exit_ts, unit="ms", utc=True),
        freq="1h",
    )
    _require_index(spot, expected, "outcome_spot_ohlcv")
    opens = _positive_array(spot["open"], "outcome_open")
    highs = _positive_array(spot["high"], "outcome_high")
    entry_price = float(opens[0])
    target_price = entry_price * (1.0 + TARGET_RETURN)
    held_highs = highs[:HOLD_HOURS]
    hits = np.flatnonzero(held_highs >= target_price)
    if len(hits):
        hit = int(hits[0])
        exit_price = target_price
        actual_exit_ts = entry_ts + hit * HOUR_MS
        exit_reason = "target"
    else:
        exit_price = float(opens[-1])
        actual_exit_ts = exit_ts
        exit_reason = "time"

    gross_return = exit_price / entry_price - 1.0
    base_return = _round_trip_return(entry_price, exit_price, BASE_COST_BPS)
    stress_return = _round_trip_return(entry_price, exit_price, STRESS_COST_BPS)
    source_digest = _digest(
        {
            "timestamps": _index_milliseconds(expected),
            "open": opens.tolist(),
            "high": highs.tolist(),
        }
    )
    return {
        "schema_version": 1,
        "status": "settled",
        "decision_time": decision_time,
        "entry_ts": entry_ts,
        "entry_price": entry_price,
        "scheduled_exit_ts": exit_ts,
        "actual_exit_ts": actual_exit_ts,
        "exit_price": exit_price,
        "exit_reason": exit_reason,
        "gross_episode_return": gross_return,
        "base_episode_return": base_return,
        "stress_episode_return": stress_return,
        "base_account_return": POSITION_WEIGHT * base_return,
        "stress_account_return": POSITION_WEIGHT * stress_return,
        "settled_from_data_at": observed_at,
        "input_sha256": source_digest,
    }


def _round_trip_return(entry: float, exit_: float, cost_bps: float) -> float:
    cost = cost_bps / 10_000.0
    return exit_ * (1.0 - cost) / (entry * (1.0 + cost)) - 1.0


def _expected_capture_slots(as_of: int) -> int:
    if as_of < FORWARD_START_DECISION + CAPTURE_EARLIEST_LAG_MS:
        return 0
    current_decision = as_of // HOUR_MS * HOUR_MS
    if as_of - current_decision < CAPTURE_EARLIEST_LAG_MS:
        current_decision -= HOUR_MS
    if current_decision < FORWARD_START_DECISION:
        return 0
    return (current_decision - FORWARD_START_DECISION) // HOUR_MS + 1


def _compound(returns: np.ndarray) -> float:
    return float(np.prod(1.0 + returns) - 1.0)


def _circular_block_mean_p05(returns: np.ndarray) -> float:
    blocks = math.ceil(len(returns) / BOOTSTRAP_BLOCK_SIZE)
    rng = np.random.default_rng(BOOTSTRAP_SEED)
    starts = rng.integers(0, len(returns), size=(BOOTSTRAP_SAMPLES, blocks))
    offsets = np.arange(BOOTSTRAP_BLOCK_SIZE)
    indexes = ((starts[:, :, None] + offsets) % len(returns)).reshape(
        BOOTSTRAP_SAMPLES, -1
    )
    draws = returns[indexes[:, : len(returns)]]
    return float(np.percentile(np.mean(draws, axis=1), 5))


def _positive_quarter_concentration(
    records: list[ForwardRecord], outcomes: list[dict[str, Any]]
) -> float:
    by_quarter: dict[str, float] = {}
    for record, outcome in zip(records, outcomes, strict=True):
        quarter = _utc_quarter(record.decision_time)
        gross = POSITION_WEIGHT * float(outcome["gross_episode_return"])
        by_quarter[quarter] = by_quarter.get(quarter, 0.0) + gross
    positive = [value for value in by_quarter.values() if value > 0.0]
    return max(positive) / sum(positive) if positive else 1.0


def _utc_quarter(timestamp_ms: int) -> str:
    timestamp = pd.Timestamp(timestamp_ms, unit="ms", tz="UTC")
    return f"{timestamp.year}Q{(timestamp.month - 1) // 3 + 1}"


def _require_index(frame: pd.DataFrame, expected: pd.DatetimeIndex, name: str) -> None:
    if len(frame) != len(expected) or not frame.index.equals(expected):
        raise InputUnavailable(f"{name}_missing_or_non_hourly")


def _finite_array(series: Any, name: str) -> np.ndarray:
    values = np.asarray(series, dtype=float).reshape(-1)
    if not np.all(np.isfinite(values)):
        raise InputUnavailable(f"{name}_non_finite")
    return values


def _positive_array(series: Any, name: str) -> np.ndarray:
    values = _finite_array(series, name)
    if np.any(values <= 0.0):
        raise InputUnavailable(f"{name}_non_positive")
    return values


def _index_milliseconds(index: pd.DatetimeIndex) -> list[int]:
    return [int(value) // 1_000_000 for value in index.asi8]


def _last_accepted_decision(store: Store, before: int) -> int | None:
    accepted = [
        record.decision_time
        for record in store.load_forward_records(STUDY, CAPTURE)
        if record.decision_time < before and bool(_decode(record).get("accepted"))
    ]
    return max(accepted) if accepted else None


def _record_for(store: Store, record_type: str, decision_time: int) -> ForwardRecord | None:
    return next(
        (
            record
            for record in store.load_forward_records(STUDY, record_type)
            if record.decision_time == decision_time
        ),
        None,
    )


def _append(
    store: Store,
    record_type: str,
    decision_time: int,
    recorded_at: int,
    payload: dict[str, Any],
) -> bool:
    return store.append_forward_record(
        STUDY,
        record_type,
        decision_time,
        recorded_at,
        _canonical_json(payload),
    )


def _decode(record: ForwardRecord) -> dict[str, Any]:
    if sha256(record.payload_json.encode("utf-8")).hexdigest() != record.payload_sha256:
        raise ValueError(
            f"forward ledger digest mismatch for {record.study}/"
            f"{record.record_type}/{record.decision_time}"
        )
    payload = json.loads(record.payload_json)
    if not isinstance(payload, dict):
        raise ValueError("forward ledger payload must be a JSON object")
    return payload


def _digest(value: Any) -> str:
    return sha256(_canonical_json(value).encode("utf-8")).hexdigest()


def _canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
