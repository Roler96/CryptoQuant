"""Tests for commission models."""
import pytest

from cryptoquant.engine.commission import FlatCommission, TieredCommission


class TestFlatCommission:
    def test_default_rate(self):
        model = FlatCommission()
        assert model.calculate(100.0, 1.0, "buy") == pytest.approx(0.1)

    def test_custom_rate(self):
        model = FlatCommission(commission=0.002)
        assert model.calculate(100.0, 1.0, "buy") == pytest.approx(0.2)

    def test_ignores_maker_flag(self):
        model = FlatCommission()
        assert model.calculate(100.0, 1.0, "buy", is_maker=True) == pytest.approx(0.1)


class TestTieredCommission:
    def test_taker_default(self):
        model = TieredCommission()
        assert model.calculate(100.0, 1.0, "buy", is_maker=False) == pytest.approx(0.05)

    def test_maker_default(self):
        model = TieredCommission()
        assert model.calculate(100.0, 1.0, "buy", is_maker=True) == pytest.approx(0.03)

    def test_vip_taker(self):
        model = TieredCommission(vip=True)
        assert model.calculate(100.0, 1.0, "buy", is_maker=False) == pytest.approx(0.03)

    def test_vip_maker(self):
        model = TieredCommission(vip=True)
        assert model.calculate(100.0, 1.0, "buy", is_maker=True) == pytest.approx(0.01)

    def test_custom_tiers(self):
        model = TieredCommission(tiers={"taker": 0.001, "maker": 0.0005})
        assert model.calculate(100.0, 1.0, "buy", is_maker=False) == pytest.approx(0.1)
        assert model.calculate(100.0, 1.0, "buy", is_maker=True) == pytest.approx(0.05)

    def test_maker_uses_default_when_not_overridden(self):
        model = TieredCommission(tiers={"taker": 0.002})
        # maker still uses default 0.0003 because it was not overridden
        assert model.calculate(100.0, 1.0, "buy", is_maker=True) == pytest.approx(0.03)
