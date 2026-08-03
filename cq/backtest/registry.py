"""Strategies exposed by the offline backtest CLI."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass

from cq.engine.loop import Strategy
from cq.strategy.donchian import DonchianTrend
from cq.strategy.turtle import TurtleTrend


@dataclass(frozen=True)
class StrategyEntry:
    """CLI argument and construction hooks for one strategy."""

    name: str
    add_arguments: Callable[[argparse.ArgumentParser], None]
    build: Callable[[argparse.Namespace], Strategy]


def _add_donchian_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--lookback", type=int, default=20, help="channel lookback in bars")


def _build_donchian(args: argparse.Namespace) -> Strategy:
    return DonchianTrend(lookback=args.lookback)


def _add_turtle_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--entry-lookback", type=int, default=20)
    parser.add_argument("--exit-lookback", type=int, default=10)
    parser.add_argument("--atr-lookback", type=int, default=20)
    parser.add_argument("--stop-atr", type=float, default=2.0)
    parser.add_argument("--target", type=float, default=1.0, help="absolute target weight")
    parser.add_argument(
        "--long-only",
        action="store_true",
        help="disable short entries (required for spot instruments)",
    )


def _build_turtle(args: argparse.Namespace) -> Strategy:
    return TurtleTrend(
        entry_lookback=args.entry_lookback,
        exit_lookback=args.exit_lookback,
        atr_lookback=args.atr_lookback,
        stop_atr=args.stop_atr,
        target=args.target,
        allow_short=not args.long_only,
    )


REGISTRY: dict[str, StrategyEntry] = {
    "donchian": StrategyEntry(
        name="donchian",
        add_arguments=_add_donchian_arguments,
        build=_build_donchian,
    ),
    "turtle": StrategyEntry(
        name="turtle",
        add_arguments=_add_turtle_arguments,
        build=_build_turtle,
    ),
}
