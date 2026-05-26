"""Backtest data models.

Contains configuration and result dataclasses for backtest execution.
These models define the input parameters and output structure for all backtests.
"""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger(__name__)


@dataclass
class BacktestConfig:
    """Configuration for backtest execution.

    Controls simulation parameters including capital, fees, and output options.
    All monetary values are in USDT.

    Attributes:
        initial_cash: Starting portfolio value in USDT (default: 10000)
        commission: Per-trade fee rate as decimal (default: 0.001 = 0.1% for OKX spot)
        slippage: Execution price penalty as decimal (default: 0.0005 = 0.05%)
        plot_results: Whether to generate equity curve PNG (default: True)
        log_path: Directory for saving plots and logs (default: "logs")

    Example:
        >>> config = BacktestConfig(
        ...     initial_cash=50000,
        ...     commission=0.0005,  # 0.05% for OKX futures
        ...     slippage=0.0002,
        ...     plot_results=False,
        ... )
    """

    initial_cash: float = 10000.0  # Starting capital in USDT
    commission: float = 0.001      # Fee rate: 0.1% (OKX spot), 0.05% (OKX futures)
    slippage: float = 0.0005       # Execution slippage: 0.05%
    plot_results: bool = True      # Generate equity curve visualization
    log_path: str = "logs"         # Output directory for plots

    @classmethod
    def with_real_commission(
        cls,
        symbol: str = "BTC/USDT",
        market_type: str = "spot",
        use_taker: bool = True,
        sandbox: bool = True,
        initial_cash: float = 10000.0,
        slippage: float = 0.0005,
        plot_results: bool = True,
        log_path: str = "logs",
    ) -> "BacktestConfig":
        """Create config with real commission from OKX API.

        Fetches actual trading fee rates from OKX exchange via API.
        Falls back to default rates if API fails.

        Args:
            symbol: Trading pair for fee lookup (default: "BTC/USDT")
            market_type: "spot" or "swap" (futures/perpetual)
            use_taker: True for taker fee (market orders, default),
                       False for maker fee (limit orders)
            sandbox: Use sandbox mode (default: True)
            initial_cash: Starting capital (default: 10000)
            slippage: Execution slippage (default: 0.0005)
            plot_results: Generate equity plot (default: True)
            log_path: Output directory (default: "logs")

        Returns:
            BacktestConfig with real commission rate

        Example:
            >>> # Get real taker fee for BTC/USDT spot
            >>> config = BacktestConfig.with_real_commission("BTC/USDT")
            >>> print(f"Commission: {config.commission:.4%}")  # ~0.10%

            >>> # Get maker fee for futures
            >>> config = BacktestConfig.with_real_commission(
            ...     symbol="BTC/USDT",
            ...     market_type="swap",
            ...     use_taker=False,  # Maker fee
            ... )
            >>> print(f"Commission: {config.commission:.4%}")  # ~0.02%
        """
        try:
            from data.manager import OKXClient

            with OKXClient(sandbox=sandbox) as client:
                commission = client.get_effective_commission(
                    symbol=symbol,
                    market_type=market_type,
                    use_taker=use_taker,
                )

            logger.info(
                "real_commission_fetched",
                symbol=symbol,
                market_type=market_type,
                use_taker=use_taker,
                commission=commission,
            )

        except Exception as e:
            # Fallback to default OKX fees if API fails
            # OKX fee structure:
            # - Spot: maker 0.08%, taker 0.10%
            # - Swap (perpetual): maker 0.02%, taker 0.05%
            default_fees = {
                ("spot", True): 0.001,      # Spot taker: 0.10%
                ("spot", False): 0.0008,    # Spot maker: 0.08%
                ("swap", True): 0.0005,     # Swap taker: 0.05%
                ("swap", False): 0.0002,    # Swap maker: 0.02%
            }
            commission = default_fees.get((market_type, use_taker), 0.001)

            logger.warning(
                "real_commission_fallback",
                symbol=symbol,
                market_type=market_type,
                use_taker=use_taker,
                commission=commission,
                error=str(e),
            )

        return cls(
            initial_cash=initial_cash,
            commission=commission,
            slippage=slippage,
            plot_results=plot_results,
            log_path=log_path,
        )


@dataclass
class BacktestResult:
    """Result of a backtest execution.

    Contains all performance data including trades, equity curve, and risk metrics.
    Immutable record of a single backtest run.

    Attributes:
        strategy_name: Identifier of the strategy that was tested
        pair: Trading pair (e.g., "BTC/USDT")
        timeframe: Candle interval (e.g., "1h", "4h", "1d")
        initial_value: Portfolio value at start (USDT)
        final_value: Portfolio value at end (USDT)
        total_return: Total return as decimal (e.g., 0.15 = 15% gain)
        trades: List of completed trades, each with entry_time, exit_time,
                entry_price, exit_price, side, pnl
        equity_curve: Portfolio values over time (USDT)
        equity_timestamps: Corresponding timestamps in milliseconds
        sharpe_ratio: Annualized risk-adjusted return (higher = better)
        max_drawdown: Maximum peak-to-trough decline as decimal (e.g., 0.20 = 20%)
        config: Configuration used for this backtest
        plot_path: Path to saved equity curve PNG (if generated)
        error: Error message if backtest failed (None if successful)

    Example:
        >>> result = engine.run_backtest(strategy, "BTC/USDT", "1h", days=90)
        >>> if result.error:
        ...     print(f"Failed: {result.error}")
        ... else:
        ...     print(f"Return: {result.total_return:.2%}")
        ...     print(f"Sharpe: {result.sharpe_ratio:.4f}")
    """

    # Required fields (no defaults)
    strategy_name: str             # Strategy identifier
    pair: str                      # Trading pair (e.g., "BTC/USDT")
    timeframe: str                 # Candle interval (e.g., "1h")
    initial_value: float           # Starting portfolio value (USDT)
    final_value: float             # Ending portfolio value (USDT)
    total_return: float            # Total return as decimal (0.15 = +15%)

    # Optional fields with defaults
    trades: List[Dict[str, Any]] = field(default_factory=list)  # Completed trades
    equity_curve: List[float] = field(default_factory=list)     # Portfolio values over time
    equity_timestamps: List[int] = field(default_factory=list)  # Timestamps in milliseconds
    sharpe_ratio: Optional[float] = None    # Annualized Sharpe ratio
    max_drawdown: Optional[float] = None    # Max drawdown as decimal (0.20 = 20%)
    config: Optional[BacktestConfig] = None # Configuration used
    plot_path: Optional[str] = None         # Path to equity curve PNG
    error: Optional[str] = None             # Error message if failed

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary for JSON serialization.

        Returns:
            Dict with all key metrics, suitable for API responses or file storage.
            Note: Full trades list and equity_curve are excluded; use total_trades count.

        Example:
            >>> result.to_dict()
            {
                "strategy_name": "cta",
                "pair": "BTC/USDT",
                "timeframe": "1h",
                "initial_value": 10000.0,
                "final_value": 11500.0,
                "total_return": 0.15,
                "total_trades": 25,
                "sharpe_ratio": 1.2,
                "max_drawdown": 0.08,
                "plot_path": "logs/equity_cta_BTC_USDT_1h_20240101.png",
                "error": None,
            }
        """
        return {
            "strategy_name": self.strategy_name,
            "pair": self.pair,
            "timeframe": self.timeframe,
            "initial_value": self.initial_value,
            "final_value": self.final_value,
            "total_return": self.total_return,
            "total_trades": len(self.trades),
            "sharpe_ratio": self.sharpe_ratio,
            "max_drawdown": self.max_drawdown,
            "plot_path": self.plot_path,
            "error": self.error,
        }