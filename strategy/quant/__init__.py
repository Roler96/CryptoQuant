"""Quantitative strategies for CryptoQuant platform.

This module contains quant strategies:
- Funding rate arbitrage strategy
- Basis momentum/mean reversion strategy
"""

from strategy.quant.funding_rate_arb import FundingRateArbitrageStrategy
from strategy.quant.basis_strategy import BasisMomentumStrategy

__all__ = [
    "FundingRateArbitrageStrategy",
    "BasisMomentumStrategy",
]