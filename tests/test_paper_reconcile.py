"""The paper calibration reconciler requires independent parity and coverage."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "reconcile_paper.py"
FIVE_MINUTES_MS = 300_000


@pytest.fixture(scope="module")
def reconcile():
    spec = importlib.util.spec_from_file_location("reconcile_paper", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def row(reconcile, position: int, *, fill=None, rejected: int = 0, **changes):
    values = {
        "ts": position * FIVE_MINUTES_MS,
        "open": 1.0,
        "high": 1.01,
        "low": 0.99,
        "close": 1.0,
        "volume": 100.0,
        "target": 0.3,
        "held": 300.0,
        "cash": 700.0,
        "equity": 1_000.0,
        "held_after": 300.0,
        "cash_after": 700.0,
        "fill": fill,
        "weight": 0.3,
        "band": 0.01,
        "rejected": rejected,
        "account_events": (),
        "strategy_state": None,
        "has_full_ohlcv": True,
        "runtime_engine_fingerprint": "runtime-fingerprint",
    }
    values.update(changes)
    return reconcile.Row(**values)


def test_runtime_provenance_requires_every_row_to_match_current_source(reconcile, monkeypatch):
    monkeypatch.setattr(reconcile, "engine_fingerprint", lambda: "current")
    matching = row(
        reconcile,
        0,
        runtime_engine_fingerprint="current",
    )
    missing = row(
        reconcile,
        1,
        runtime_engine_fingerprint=None,
    )
    stale = row(
        reconcile,
        2,
        runtime_engine_fingerprint="stale",
    )

    passed = reconcile._runtime_provenance([matching])
    assert passed["passed"]
    assert passed["missing_rows"] == 0

    assert not reconcile._runtime_provenance([matching, missing])["passed"]
    assert not reconcile._runtime_provenance([matching, stale])["passed"]


def test_independent_formula_catches_a_shared_sizing_false_agreement(
    reconcile, monkeypatch
):
    live_fill = {"side": "buy", "quantity": 250.0, "price": 1.0, "fee": 0.25}
    sample = row(reconcile, 0, fill=live_fill, held=0.0, held_after=249.75)
    monkeypatch.setattr(reconcile, "target_delta", lambda *args: 250.0)

    result = reconcile._decision_parity([sample])

    assert not result["passed"]
    assert [item["source"] for item in result["mismatches"]] == [
        "independent_formula"
    ]


def test_accounting_accepts_explicit_base_and_quote_fee_conventions(reconcile):
    base_fill = {"side": "buy", "quantity": 300.0, "price": 1.0, "fee": 0.3}
    quote_fill = {"side": "sell", "quantity": 10.0, "price": 1.0, "fee": 0.01}
    first = row(
        reconcile,
        0,
        fill=base_fill,
        held=0.0,
        cash=1_000.0,
        equity=1_000.0,
        held_after=299.7,
        cash_after=700.0,
    )
    second = row(
        reconcile,
        1,
        fill=quote_fill,
        held=299.7,
        cash=700.0,
        equity=999.7,
        held_after=289.7,
        cash_after=709.99,
    )

    result = reconcile._accounting([first, second])

    assert result["passed"]
    assert result["fee_in_base_bars"] == 1
    assert result["fee_in_quote_bars"] == 1


def test_accounting_rejects_broken_state_continuity(reconcile):
    first = row(reconcile, 0)
    second = row(reconcile, 1, held=299.0, equity=999.0)

    result = reconcile._accounting([first, second])

    assert not result["passed"]
    assert any("continue" in item["why"] for item in result["breaks"])


def test_frozen_event_coverage_requires_bars_both_directions_and_no_rejections(
    reconcile,
):
    rows = []
    for position in range(reconcile.MIN_BARS):
        fill = None
        if position <= reconcile.MIN_POST_INITIAL_FILLS:
            side = "buy" if position % 2 == 0 else "sell"
            fill = {"side": side, "quantity": 1.0, "price": 1.0, "fee": 0.001}
        rows.append(row(reconcile, position, fill=fill))
    band = {
        "holds_inside_band": 1,
        "post_initial_trades_outside_band": reconcile.MIN_POST_INITIAL_FILLS,
    }

    result = reconcile._coverage(rows, "5m", band)

    assert result["passed"]
    assert result["post_initial_fills"] == reconcile.MIN_POST_INITIAL_FILLS
    assert result["post_initial_buys"] >= reconcile.MIN_POST_INITIAL_BUYS
    assert result["post_initial_sells"] >= reconcile.MIN_POST_INITIAL_SELLS

    rows[-1].rejected = 1
    assert not reconcile._coverage(rows, "5m", band)["passed"]


def test_a_timestamp_gap_fails_coverage(reconcile):
    rows = [row(reconcile, position) for position in range(reconcile.MIN_BARS)]
    rows[-1].ts += FIVE_MINUTES_MS
    band = {"holds_inside_band": 1, "post_initial_trades_outside_band": 1}

    result = reconcile._coverage(rows, "5m", band)

    assert not result["checks"]["consecutive_bars"]


def test_only_the_frozen_sequence_is_artifact_eligible(reconcile):
    probe = reconcile.SpotCalibrationSequence()
    rows = []
    for position in range(reconcile.MIN_BARS):
        target = probe.on_bar(None).target
        rows.append(
            row(
                reconcile,
                position,
                target=target,
                strategy_state=probe.snapshot_state(),
            )
        )

    result = reconcile._frozen_sequence(rows, probe.name)

    assert result["passed"]
    assert not reconcile._frozen_sequence(rows, "doge-cmix-w0.3-b0.1")["passed"]


def test_equity_parity_replays_logged_five_minute_ohlcv_without_the_store(reconcile):
    rows = [
        row(reconcile, position, target=0.0)
        for position in range(len(reconcile.CALIBRATION_TARGETS))
    ]

    result = reconcile._equity_parity(rows, "5m")

    assert result["available"]
    assert result["complete"]
    assert result["bars_compared"] == len(rows)
    assert result["bar_series_fingerprint"]


def test_equity_parity_fails_closed_for_legacy_close_only_logs(reconcile):
    legacy = row(reconcile, 0, has_full_ohlcv=False)

    result = reconcile._equity_parity([legacy], "5m")

    assert not result["available"]
    assert "full OHLCV" in result["reason"]
