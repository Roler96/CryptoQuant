"""Resolve a strategy name to its class.

Shared by live_runner and the backtest scripts on purpose: if the two
resolved names differently, live could run a different class than the one
the backtest signed off on.
"""
import importlib

from cryptoquant.exceptions import StrategyError
from cryptoquant.strategy.base import Strategy


def resolve_strategy_class(name: str) -> type[Strategy]:
    """Return the Strategy subclass defined in strategies/<name>.py.

    Raises StrategyError if the module is missing or defines no strategy.
    """
    if not name:
        raise StrategyError("No strategy specified")

    try:
        module = importlib.import_module(f"strategies.{name}")
    except ImportError as e:
        raise StrategyError(f"Strategy '{name}' not found in strategies/") from e

    # Only classes *defined* in the module count. Matching on any Strategy
    # subclass in the namespace would also match ones merely imported there,
    # and dir() is alphabetical, so the import could win.
    candidates = [
        obj
        for attr in dir(module)
        if isinstance(obj := getattr(module, attr), type)
        and issubclass(obj, Strategy)
        and obj is not Strategy
        and obj.__module__ == module.__name__
    ]

    if not candidates:
        raise StrategyError(f"Module strategies/{name}.py defines no Strategy subclass")
    if len(candidates) > 1:
        names = ", ".join(sorted(c.__name__ for c in candidates))
        raise StrategyError(
            f"strategies/{name}.py defines more than one strategy ({names}); "
            f"resolution would be arbitrary"
        )
    return candidates[0]


def resolve_strategy(name: str) -> Strategy:
    """Instantiate the strategy defined in strategies/<name>.py."""
    return resolve_strategy_class(name)()
