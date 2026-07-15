"""Tests for strategy name resolution.

live_runner and run_doge_backtest share this, so that a config naming a
strategy and a backtest naming the same strategy cannot land on different
classes.
"""
import sys
import types
from pathlib import Path

import pytest

from cryptoquant.exceptions import StrategyError
from cryptoquant.strategy.base import Strategy
from cryptoquant.strategy.resolve import resolve_strategy, resolve_strategy_class


class TestResolveShippedStrategies:
    @pytest.mark.parametrize(
        "name, expected",
        [
            ("doge_donchian_trend", "DogeDonchianTrend"),
        ],
    )
    def test_resolves_to_expected_class(self, name, expected):
        assert resolve_strategy_class(name).__name__ == expected

    def test_returns_an_instance(self):
        assert isinstance(resolve_strategy("doge_donchian_trend"), Strategy)

    def test_every_shipped_strategy_resolves(self):
        """Catches a strategy module that resolution cannot reach — and keeps
        the parametrize list above honest as strategies come and go."""
        modules = sorted(
            p.stem
            for p in (Path(__file__).resolve().parent.parent / "strategies").glob("*.py")
            if p.stem != "__init__"
        )
        assert modules, "no strategies found — this guard would be vacuous"
        for name in modules:
            assert issubclass(resolve_strategy_class(name), Strategy)


class TestResolveErrors:
    def test_unknown_strategy_raises(self):
        with pytest.raises(StrategyError, match="not found"):
            resolve_strategy_class("no_such_strategy")

    def test_empty_name_raises(self):
        with pytest.raises(StrategyError, match="No strategy specified"):
            resolve_strategy_class("")


class TestImportedClassesDoNotWin:
    """dir() is alphabetical, so a Strategy merely imported into a module
    could out-sort the one actually defined there. Only definitions count.
    """

    @pytest.fixture
    def fake_module(self, request):
        name = "strategies._resolve_fixture"
        module = types.ModuleType(name)
        module.__name__ = name
        sys.modules[name] = module
        request.addfinalizer(lambda: sys.modules.pop(name, None))
        return module, name.split(".", 1)[1]

    def test_imported_strategy_is_ignored(self, fake_module):
        module, short = fake_module

        class AaaImported(Strategy):
            """Sorts before the real one and is not defined here."""
            DEFAULT_PARAMS = {}

            @property
            def name(self) -> str:
                return "AaaImported"

            def generate_signal(self, df):
                raise NotImplementedError

        class ZzzDefined(Strategy):
            DEFAULT_PARAMS = {}

            @property
            def name(self) -> str:
                return "ZzzDefined"

            def generate_signal(self, df):
                raise NotImplementedError

        AaaImported.__module__ = "strategies.somewhere_else"
        ZzzDefined.__module__ = module.__name__
        module.AaaImported = AaaImported
        module.ZzzDefined = ZzzDefined

        assert resolve_strategy_class(short) is ZzzDefined

    def test_module_without_a_strategy_raises(self, fake_module):
        module, short = fake_module
        module.something = 42

        with pytest.raises(StrategyError, match="defines no Strategy subclass"):
            resolve_strategy_class(short)

    def test_ambiguous_module_raises(self, fake_module):
        module, short = fake_module

        class First(Strategy):
            DEFAULT_PARAMS = {}

            @property
            def name(self) -> str:
                return "First"

            def generate_signal(self, df):
                raise NotImplementedError

        class Second(Strategy):
            DEFAULT_PARAMS = {}

            @property
            def name(self) -> str:
                return "Second"

            def generate_signal(self, df):
                raise NotImplementedError

        First.__module__ = module.__name__
        Second.__module__ = module.__name__
        module.First = First
        module.Second = Second

        with pytest.raises(StrategyError, match="more than one strategy"):
            resolve_strategy_class(short)
