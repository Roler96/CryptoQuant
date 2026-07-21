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
