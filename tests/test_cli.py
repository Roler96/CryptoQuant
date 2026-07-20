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
