"""Smoke tests for the CLI skeleton."""

import pytest

from cq import __version__
from cq.cli import build_parser, main


def test_version_flag_reports_package_version(capsys):
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0
    assert __version__ in capsys.readouterr().out


def test_parser_requires_a_command():
    parser = build_parser()
    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_paper_run_exposes_feed_stall_grace():
    args = build_parser().parse_args(["paper", "run", "--stall-grace", "45"])

    assert args.stall_grace == 45.0


def test_paper_run_exposes_the_frozen_calibration_sequence():
    args = build_parser().parse_args(
        [
            "paper",
            "run",
            "--strategy",
            "calibration-sequence",
            "--new-session",
        ]
    )

    assert args.strategy == "calibration-sequence"
    assert args.new_session


def test_paper_run_exposes_explicit_swap_account_settings():
    args = build_parser().parse_args(
        [
            "paper",
            "run",
            "--inst",
            "DOGE-USDT-SWAP",
            "--leverage",
            "3",
            "--margin-mode",
            "isolated",
        ]
    )

    assert args.inst == "DOGE-USDT-SWAP"
    assert args.leverage == 3.0
    assert args.margin_mode == "isolated"


def test_calibration_status_is_capability_scoped():
    args = build_parser().parse_args(
        [
            "calibration",
            "status",
            "--capability",
            "swap",
            "--sizing",
            "on_entry",
            "--artifact",
            "gate.json",
        ]
    )

    assert args.capability == "swap"
    assert args.sizing == "on_entry"
    assert args.artifact == "gate.json"


def test_forward_observer_accepts_a_spot_gate_artifact():
    args = build_parser().parse_args(
        [
            "research",
            "observe-oifr",
            "--calibration-artifact",
            "reports/calibration/spot.json",
        ]
    )

    assert args.calibration_artifact == "reports/calibration/spot.json"
