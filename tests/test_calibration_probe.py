"""The calibration target sequence is deterministic and demo-only."""

from __future__ import annotations

from typing import cast

import pytest

from cq.cli import main
from cq.context import Context
from cq.live.calibration_probe import (
    CALIBRATION_BAND,
    CALIBRATION_BARS,
    CALIBRATION_TARGETS,
    SpotCalibrationSequence,
)


def _next_target(probe: SpotCalibrationSequence) -> float:
    return probe.on_bar(cast(Context, object())).target


def test_sequence_repeats_frozen_targets_and_snapshots_its_phase():
    probe = SpotCalibrationSequence()

    observed = [_next_target(probe) for _ in range(len(CALIBRATION_TARGETS) * 2)]

    assert observed == list(CALIBRATION_TARGETS) * 2
    assert CALIBRATION_BARS % len(CALIBRATION_TARGETS) == 0
    assert CALIBRATION_TARGETS[-1] == 0.0
    assert probe.band == CALIBRATION_BAND
    state = probe.snapshot_state()
    assert state["count"] == len(observed)
    assert state["config"] == {
        "version": 1,
        "band": CALIBRATION_BAND,
        "targets": list(CALIBRATION_TARGETS),
    }


def test_checkpoint_round_trip_preserves_phase():
    first = SpotCalibrationSequence()
    for _ in range(5):
        _next_target(first)

    resumed = SpotCalibrationSequence()
    resumed.restore_state(first.snapshot_state())

    assert _next_target(resumed) == CALIBRATION_TARGETS[5]


def test_checkpoint_rejects_a_changed_protocol():
    probe = SpotCalibrationSequence()
    state = probe.snapshot_state()
    state["config"] = {"version": 999}

    with pytest.raises(ValueError, match="configuration"):
        probe.restore_state(state)


def test_calibration_sequence_refuses_real_money_before_loading_credentials(capsys):
    code = main(
        [
            "paper",
            "run",
            "--strategy",
            "calibration-sequence",
            "--new-session",
            "--live",
        ]
    )

    assert code == 1
    assert "demo-only" in capsys.readouterr().out


def test_calibration_sequence_requires_a_fresh_flat_session(capsys):
    code = main(
        ["paper", "run", "--strategy", "calibration-sequence", "--tf", "5m"]
    )

    assert code == 1
    assert "--new-session" in capsys.readouterr().out
