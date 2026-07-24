"""Capability-scoped calibration artifacts fail closed."""

from __future__ import annotations

import json

import pytest

from cq.calibration import (
    SPOT_REBALANCE_CHECKS,
    CalibrationClosed,
    build_gate_artifact,
    calibration_status,
    require_calibration,
    write_gate_artifact,
)

SOURCE_SHA = "a" * 64


def passing_payload():
    return build_gate_artifact(
        "spot",
        "rebalance",
        checks=dict.fromkeys(SPOT_REBALANCE_CHECKS, True),
        evidence={"bars": 200},
        source_sha256=SOURCE_SHA,
    )


def test_missing_artifact_is_closed(tmp_path):
    status = calibration_status("spot", "rebalance", tmp_path / "missing.json")

    assert not status.is_open
    assert "missing artifact" in status.reason
    with pytest.raises(CalibrationClosed, match="CLOSED"):
        require_calibration("spot", "rebalance", tmp_path / "missing.json")


def test_current_passing_artifact_opens_only_its_capability(tmp_path):
    path = write_gate_artifact(passing_payload(), tmp_path / "spot.json")

    assert calibration_status("spot", "rebalance", path).is_open
    swap = calibration_status("swap", "rebalance", path)
    assert not swap.is_open
    assert "no calibration protocol" in swap.reason

    on_entry = calibration_status("spot", "on_entry", path)
    assert not on_entry.is_open
    assert "no calibration protocol" in on_entry.reason


def test_a_false_check_can_never_be_written_as_pass(tmp_path):
    payload = build_gate_artifact(
        "spot",
        "rebalance",
        checks={"decision_parity": True, "event_coverage": False},
        evidence={},
        source_sha256=SOURCE_SHA,
    )
    path = write_gate_artifact(payload, tmp_path / "spot.json")

    assert payload["status"] == "FAILED"
    assert not calibration_status("spot", "rebalance", path).is_open


def test_engine_fingerprint_mismatch_closes_a_previously_passing_artifact(tmp_path):
    payload = passing_payload()
    payload["engine_fingerprint"] = "0" * 64
    path = write_gate_artifact(payload, tmp_path / "spot.json")

    status = calibration_status("spot", "rebalance", path)

    assert not status.is_open
    assert "sources changed" in status.reason


def test_malformed_or_incomplete_artifact_is_closed(tmp_path):
    malformed = tmp_path / "malformed.json"
    malformed.write_text("{", encoding="utf-8")
    assert not calibration_status("spot", "rebalance", malformed).is_open

    incomplete = tmp_path / "incomplete.json"
    incomplete.write_text(json.dumps({"status": "PASS"}), encoding="utf-8")
    assert not calibration_status("spot", "rebalance", incomplete).is_open


def test_a_handwritten_pass_cannot_omit_frozen_checks(tmp_path):
    payload = passing_payload()
    payload["checks"] = {"decision_parity": True}
    path = write_gate_artifact(payload, tmp_path / "spot.json")

    status = calibration_status("spot", "rebalance", path)

    assert not status.is_open
    assert "omits required checks" in status.reason
