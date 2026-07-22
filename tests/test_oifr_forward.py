"""Strict as-of behavior for the OIFR forward observer."""

from __future__ import annotations

import json

import pytest

from cq.data.store import Store
from cq.research.oifr import (
    BASE_COST_BPS,
    BASELINE_CHANGES,
    CAPTURE,
    FORWARD_START_DECISION,
    HOLD_HOURS,
    HOUR_MS,
    OI_LAG_HOURS,
    OUTCOME,
    STUDY,
    adjudicate_ledger,
    capture_latest,
    settle_matured,
    summarize_ledger,
)


@pytest.fixture
def store(tmp_path):
    with Store(tmp_path / "oifr.db") as value:
        yield value


def _ohlcv(inst_id: str, ts: int, close: float, high: float | None = None) -> tuple:
    high = close if high is None else high
    return (inst_id, "1h", ts, close, high, close, close, 100.0, 100.0 * close)


def _seed_signal_inputs(
    store: Store,
    decision: int,
    *,
    missing_oi_position: int | None = None,
) -> int:
    observed_at = decision + 15 * 60_000
    bar_ts = decision - HOUR_MS
    source_start = bar_ts - (BASELINE_CHANGES + OI_LAG_HOURS) * HOUR_MS

    oi_rows = []
    swap_rows = []
    for position in range(BASELINE_CHANGES + OI_LAG_HOURS + 1):
        if position == missing_oi_position:
            continue
        ts = source_start + position * HOUR_MS
        normalized_oi = 50.0 if ts == bar_ts else 100.0
        swap_close = 0.2
        oi_rows.append(("DOGE", ts, normalized_oi * swap_close, 1_000.0, decision + 5 * 60_000))
        swap_rows.append(_ohlcv("DOGE-USDT-SWAP", ts, swap_close))
    store.upsert_open_interest(oi_rows)
    store.upsert_ohlcv(swap_rows)

    spot_start = bar_ts - OI_LAG_HOURS * HOUR_MS
    spot_closes = [1.0, 1.0, 1.0, 1.0, 1.0, 0.8, 0.9]
    store.upsert_ohlcv(
        [
            _ohlcv("DOGE-USDT", spot_start + position * HOUR_MS, close)
            for position, close in enumerate(spot_closes)
        ]
    )
    store.upsert_funding(
        [
            (
                "DOGE-USDT-SWAP",
                decision - 2 * HOUR_MS,
                0.0001,
                0.0001,
                decision + 5 * 60_000,
            )
        ]
    )
    return observed_at


def test_observer_does_nothing_before_the_frozen_forward_start(store):
    result = capture_latest(store, FORWARD_START_DECISION - 45 * 60_000)

    assert result.status == "not_started"
    assert store.load_forward_records(STUDY) == []
    adjudication = adjudicate_ledger(store, FORWARD_START_DECISION - 45 * 60_000)
    assert adjudication.status == "FORWARD_INCONCLUSIVE"
    assert adjudication.metrics["expected_capture_slots"] == 0


def test_current_tail_flush_is_captured_once_as_an_accepted_signal(store):
    decision = FORWARD_START_DECISION + 100 * HOUR_MS
    observed_at = _seed_signal_inputs(store, decision)

    result = capture_latest(store, observed_at)

    assert result.status == "valid"
    assert result.inserted
    assert result.payload["criteria"] == {
        "oi_flush": True,
        "positive_realized_funding": True,
        "spot_down_6h": True,
        "spot_reversal_1h": True,
    }
    assert result.payload["accepted"] is True
    assert result.payload["features"]["oi_q05"] == pytest.approx(0.0)
    assert result.payload["features"]["oi_change_6h"] == pytest.approx(-0.69314718056)
    assert len(result.payload["input_sha256"]) == 64

    adjudication = adjudicate_ledger(store, observed_at)
    assert adjudication.status == "FORWARD_INCONCLUSIVE"
    assert adjudication.metrics["capture_rate"] == pytest.approx(1 / 101)
    assert "base_total_return" not in adjudication.metrics

    # Even if OKX later revises the current OI, a retry returns the frozen
    # record rather than recomputing it from hindsight.
    bar_ts = decision - HOUR_MS
    store.upsert_open_interest([("DOGE", bar_ts, 1000.0, 1_000.0, observed_at + 1)])
    replay = capture_latest(store, decision + 20 * 60_000)
    assert not replay.inserted
    assert replay.payload == result.payload
    assert len(store.load_forward_records(STUDY, CAPTURE)) == 1


def test_missing_hour_is_frozen_as_unavailable_not_backfilled(store):
    decision = FORWARD_START_DECISION + 120 * HOUR_MS
    observed_at = _seed_signal_inputs(store, decision, missing_oi_position=20)

    result = capture_latest(store, observed_at)

    assert result.status == "data_unavailable"
    assert result.payload["reason"] == "open_interest_missing_or_non_hourly"
    assert result.inserted

    # Filling the old gap afterwards cannot turn the slot into a signal.
    source_start = (
        decision
        - HOUR_MS
        - (BASELINE_CHANGES + OI_LAG_HOURS) * HOUR_MS
    )
    missing_ts = source_start + 20 * HOUR_MS
    store.upsert_open_interest([("DOGE", missing_ts, 20.0, 1_000.0, observed_at + 1)])
    replay = capture_latest(store, decision + 20 * 60_000)
    assert replay.payload["status"] == "data_unavailable"


def test_late_invocation_records_a_missed_slot_without_reading_inputs(store):
    decision = FORWARD_START_DECISION + 140 * HOUR_MS

    result = capture_latest(store, decision + 31 * 60_000)

    assert result.status == "missed_late"
    assert result.inserted
    assert result.payload["capture_lag_ms"] == 31 * 60_000


def test_raw_event_inside_cooldown_is_not_accepted(store):
    decision = FORWARD_START_DECISION + 200 * HOUR_MS
    previous = decision - HOUR_MS
    store.append_forward_record(
        STUDY,
        CAPTURE,
        previous,
        previous + 15 * 60_000,
        json.dumps({"accepted": True, "status": "valid"}, sort_keys=True),
    )
    observed_at = _seed_signal_inputs(store, decision)

    result = capture_latest(store, observed_at)

    assert result.payload["raw_event"] is True
    assert result.payload["cooldown_clear"] is False
    assert result.payload["accepted"] is False


def test_matured_target_outcome_is_appended_once(store):
    decision = FORWARD_START_DECISION + 300 * HOUR_MS
    observed_at = _seed_signal_inputs(store, decision)
    capture = capture_latest(store, observed_at)
    assert capture.payload["accepted"] is True

    entry_ts = decision + HOUR_MS
    exit_ts = entry_ts + HOLD_HOURS * HOUR_MS
    rows = []
    for position in range(HOLD_HOURS + 1):
        ts = entry_ts + position * HOUR_MS
        high = 1.11 if position == 2 else 1.05
        rows.append(_ohlcv("DOGE-USDT", ts, 1.0, high=high))
    store.upsert_ohlcv(rows)

    settled = settle_matured(store, exit_ts + 2 * HOUR_MS)

    assert len(settled) == 1
    payload = settled[0].payload
    assert payload["exit_reason"] == "target"
    assert payload["actual_exit_ts"] == entry_ts + 2 * HOUR_MS
    expected = 1.1 * (1 - BASE_COST_BPS / 10_000) / (1 + BASE_COST_BPS / 10_000) - 1
    assert payload["base_episode_return"] == pytest.approx(expected)
    assert len(store.load_forward_records(STUDY, OUTCOME)) == 1

    assert settle_matured(store, exit_ts + 3 * HOUR_MS) == []
    summary = summarize_ledger(store)
    assert summary.accepted_signals == 1
    assert summary.settled_outcomes == 1
    assert summary.status == "FORWARD_INCONCLUSIVE"
