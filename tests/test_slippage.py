"""Tests for slippage models."""
import pandas as pd
import pytest

from cryptoquant.engine.slippage import ATRSlippage, FixedSlippage


class TestFixedSlippage:
    def test_default_slippage(self):
        model = FixedSlippage()
        bar = pd.Series({"open": 100, "high": 101, "low": 99, "close": 100})
        assert model.calculate(bar, "long") == pytest.approx(0.0005)

    def test_custom_slippage(self):
        model = FixedSlippage(slippage=0.001)
        bar = pd.Series({"open": 100, "high": 101, "low": 99, "close": 100})
        assert model.calculate(bar, "long") == pytest.approx(0.001)


class TestATRSlippage:
    def test_high_volatility_high_slippage(self):
        bar = pd.Series({"open": 100, "high": 105, "low": 95, "close": 100})
        model = ATRSlippage(atr_period=1, multiplier=1.0, max_slippage=0.01)
        # TR = max(10, 5, 5) = 10, ATR_pct = 10/100 = 0.1, slippage = 0.1 * 1 = 0.1 -> clamped to 0.01
        assert model.calculate(bar, "long") == pytest.approx(0.01)

    def test_low_volatility_low_slippage(self):
        bar = pd.Series({"open": 100, "high": 100.1, "low": 99.9, "close": 100})
        model = ATRSlippage(atr_period=1, multiplier=1.0, max_slippage=0.01)
        assert model.calculate(bar, "long") == pytest.approx(0.002)

    def test_clamped_to_max(self):
        bar = pd.Series({"open": 100, "high": 200, "low": 50, "close": 100})
        model = ATRSlippage(atr_period=1, multiplier=1.0, max_slippage=0.005)
        assert model.calculate(bar, "long") == pytest.approx(0.005)

    def test_zero_close_returns_zero(self):
        bar = pd.Series({"open": 0, "high": 0, "low": 0, "close": 0})
        model = ATRSlippage()
        assert model.calculate(bar, "long") == 0.0
