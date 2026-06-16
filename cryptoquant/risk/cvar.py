"""Conditional Value at Risk (CVaR) tail risk calculator."""
import numpy as np


class CVaRCalculator:
    """Calculates CVaR (Expected Shortfall) from a returns distribution.

    CVaR is the average of returns that fall below the VaR threshold.
    """

    @staticmethod
    def calculate(returns: np.ndarray, confidence: float = 0.95) -> float:
        """Calculate CVaR for a given returns array.

        Args:
            returns: Array of percentage returns (e.g., [1.5, -2.0, 0.5, ...]).
            confidence: Confidence level (default 0.95 for 95% CVaR).

        Returns:
            CVaR value as a percentage. Negative means loss.
            Returns 0.0 if returns array is empty or has insufficient data.
        """
        if len(returns) == 0:
            return 0.0

        if not np.isfinite(returns).all():
            returns = returns[np.isfinite(returns)]

        if len(returns) < 2:
            return 0.0

        var_threshold = np.percentile(returns, (1 - confidence) * 100)
        tail_returns = returns[returns <= var_threshold]

        if len(tail_returns) == 0:
            return 0.0

        cvar = float(np.mean(tail_returns))
        return cvar
