"""Command line entry point.

Subcommands are registered by their owning module so that the CLI does not
become a second place where behaviour is defined.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from cq import __version__


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="cq", description="CQuant research platform")
    parser.add_argument("--version", action="version", version=f"cq {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    data = subparsers.add_parser("data", help="market data management")
    data_sub = data.add_subparsers(dest="data_command", required=True)
    _register_data_commands(data_sub)

    backtest = subparsers.add_parser("backtest", help="run strategies on stored data")
    backtest_sub = backtest.add_subparsers(dest="backtest_strategy", required=True)
    _register_backtest_commands(backtest_sub)

    paper = subparsers.add_parser("paper", help="paper (demo) trading against OKX")
    paper_sub = paper.add_subparsers(dest="paper_command", required=True)
    _register_paper_commands(paper_sub)

    research = subparsers.add_parser("research", help="run pre-registered research studies")
    research_sub = research.add_subparsers(dest="research_study", required=True)
    _register_research_commands(research_sub)

    return parser


def _register_data_commands(subparsers: argparse._SubParsersAction) -> None:
    from cq.data import commands

    commands.register(subparsers)


def _register_backtest_commands(subparsers: argparse._SubParsersAction) -> None:
    from cq.backtest import commands

    commands.register(subparsers)


def _register_paper_commands(subparsers: argparse._SubParsersAction) -> None:
    from cq.live import commands

    commands.register(subparsers)


def _register_research_commands(subparsers: argparse._SubParsersAction) -> None:
    from cq.research import commands

    commands.register(subparsers)


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    handler = getattr(args, "handler", None)
    if handler is None:
        parser.error("no handler bound to this command")
    return handler(args)


if __name__ == "__main__":
    sys.exit(main())
