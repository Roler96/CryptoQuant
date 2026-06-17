"""Tests for CVaRCalculator."""
import numpy as np

from cryptoquant.risk.cvar import CVaRCalculator


class TestCVaRCalculator:
    def test_empty_returns(self):
        result = CVaRCalculator.calculate(np.array([]))
        assert result == 0.0

    def test_single_return(self):
        result = CVaRCalculator.calculate(np.array([1.0]))
        assert result == 0.0

    def test_all_positive_returns(self):
        returns = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
        result = CVaRCalculator.calculate(returns, confidence=0.95)
        assert result <= 1.0

    def test_all_negative_returns(self):
        returns = np.array([-1.0, -2.0, -3.0, -4.0, -5.0])
        result = CVaRCalculator.calculate(returns, confidence=0.95)
        assert result < 0

    def test_mixed_returns(self):
        returns = np.array([5.0, -2.0, 3.0, -8.0, 1.0, -4.0, 2.0])
        result = CVaRCalculator.calculate(returns, confidence=0.95)
        assert result < 0

    def test_95_confidence(self):
        np.random.seed(42)
        returns = np.random.normal(0, 2, 1000)
        result = CVaRCalculator.calculate(returns, confidence=0.95)
        assert result < 0

    def test_99_confidence_more_negative(self):
        np.random.seed(42)
        returns = np.random.normal(0, 2, 1000)
        cvar_95 = CVaRCalculator.calculate(returns, confidence=0.95)
        cvar_99 = CVaRCalculator.calculate(returns, confidence=0.99)
        assert cvar_99 <= cvar_95

    def test_with_nan_values(self):
        returns = np.array([1.0, -2.0, np.nan, 3.0, -4.0])
        result = CVaRCalculator.calculate(returns, confidence=0.95)
        assert result < 0

    def test_known_distribution(self):
        returns = np.array([-10.0, -8.0, -6.0, 0.0, 5.0, 10.0])
        result = CVaRCalculator.calculate(returns, confidence=0.80)
        assert result < 0

    def test_cvar_worse_than_var(self):
        np.random.seed(42)
        returns = np.random.normal(0, 3, 500)
        var_95 = np.percentile(returns, 5)
        cvar_95 = CVaRCalculator.calculate(returns, confidence=0.95)
        assert cvar_95 <= var_95
