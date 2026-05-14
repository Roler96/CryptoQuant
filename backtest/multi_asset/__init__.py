"""Multi-asset backtesting framework for cross-sectional strategies.

Provides vectorized backtesting for market-neutral multi-factor portfolios,
funding rate arbitrage, and basis trading strategies.
"""

from backtest.multi_asset.engine import MultiAssetBacktestEngine, MultiAssetBacktestConfig, MultiAssetBacktestResult
from backtest.multi_asset.data_loader import MultiAssetDataLoader

__all__ = [
    "MultiAssetBacktestEngine",
    "MultiAssetBacktestConfig",
    "MultiAssetBacktestResult",
    "MultiAssetDataLoader",
]