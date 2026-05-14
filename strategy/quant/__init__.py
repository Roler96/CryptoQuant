"""Quantitative strategies for CryptoQuant platform.

This module contains advanced quantitative strategies:
- Cross-sectional multi-factor strategy
- Funding rate arbitrage strategy
- Basis momentum/mean reversion strategy
"""

from strategy.quant.cross_sectional import CrossSectionalMultiFactorStrategy
from strategy.quant.funding_rate_arb import FundingRateArbitrageStrategy
from strategy.quant.basis_strategy import BasisMomentumStrategy

__all__ = [
    "CrossSectionalMultiFactorStrategy",
    "FundingRateArbitrageStrategy",
    "BasisMomentumStrategy",
]