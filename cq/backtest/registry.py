"""Strategies exposed by the offline backtest CLI."""

from __future__ import annotations

import argparse
from collections.abc import Callable
from dataclasses import dataclass

from cq.engine.loop import Strategy
from cq.strategy.donchian import DonchianTrend


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


REGISTRY: dict[str, StrategyEntry] = {
    "donchian": StrategyEntry(
        name="donchian",
        add_arguments=_add_donchian_arguments,
        build=_build_donchian,
    )
}
