"""Backtest engine integrating Backtrader framework.

Provides a high-level interface for running backtests with:
- Strategy loading by name
- Custom data feeds from SQLite repository
- Configurable simulation parameters
- Result collection and visualization
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Type

import backtrader as bt
import matplotlib
import pandas as pd
import structlog
from matplotlib import pyplot as plt

from backtest.adapter import BacktraderStrategyAdapter
from backtest.data_feed import PandasDataFeed
from backtest.models import BacktestConfig, BacktestResult
from data.repository import get_repository
from strategy.base import StrategyBase
from strategy.cta.trend_following import TrendFollowingStrategy

logger = structlog.get_logger(__name__)

matplotlib.use("Agg")


class BacktestEngine:
    """Backtest engine that integrates Backtrader Cerebro.

    Provides a high-level interface for running backtests with:
    - Strategy loading by name
    - Custom data feeds from SQLite repository
    - Configurable simulation parameters
    - Result collection and visualization
    """

    def __init__(self, config: Optional[BacktestConfig] = None):
        """Initialize the backtest engine.

        Args:
            config: Backtest configuration (uses defaults if None)
        """
        self.config = config or BacktestConfig()
        self.cerebro: Optional[bt.Cerebro] = None
        self.logger = structlog.get_logger(__name__)

        self._strategy_map: Dict[str, Type[StrategyBase]] = {
            "cta": TrendFollowingStrategy,
            "trend_following": TrendFollowingStrategy,
            "trend": TrendFollowingStrategy,
        }

    def load_strategy(self, strategy_name: str, params: Optional[Dict[str, Any]] = None) -> StrategyBase:
        """Load strategy by name.

        Args:
            strategy_name: Strategy identifier ('cta', 'trend_following', etc.)
            params: Optional strategy parameters

        Returns:
            Strategy instance

        Raises:
            ValueError: If strategy name is not recognized
        """
        strategy_name_lower = strategy_name.lower()

        if strategy_name_lower not in self._strategy_map:
            available = ", ".join(self._strategy_map.keys())
            raise ValueError(f"Unknown strategy '{strategy_name}'. Available: {available}")

        strategy_class = self._strategy_map[strategy_name_lower]
        strategy = strategy_class(name=strategy_name, params=params)

        self.logger.info(
            "strategy_loaded",
            name=strategy_name,
            class_name=strategy_class.__name__,
        )

        return strategy

    def create_data_feed(
        self,
        pair: str,
        timeframe: str,
        days: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
    ) -> PandasDataFeed:
        """Create data feed from SQLite repository.

        Args:
            pair: Trading pair (e.g., "BTC/USDT")
            timeframe: Candle timeframe (e.g., "1h", "1d")
            days: Optional limit on number of days to load (from now)
            start_date: Optional start date (e.g., "2024-01-01")
            end_date: Optional end date (e.g., "2024-12-31")

        Returns:
            PandasDataFeed ready for Backtrader

        Raises:
            FileNotFoundError: If no data found for pair/timeframe
        """
        repo = get_repository()

        since = None
        until = None

        if start_date:
            since = int(pd.Timestamp(start_date).timestamp() * 1000)
        elif days is not None:
            cutoff_dt = pd.Timestamp.now() - pd.Timedelta(days=days)
            since = int(cutoff_dt.timestamp() * 1000)

        if end_date:
            until = int(pd.Timestamp(end_date).timestamp() * 1000)

        df = repo.load_as_dataframe(pair, timeframe, since=since, until=until)

        if df.empty:
            raise FileNotFoundError(
                f"No historical data found for {pair} {timeframe}. "
                f"Run: python -m data.downloader --pair {pair} --timeframe {timeframe}"
            )

        self.logger.info(
            "data_feed_created",
            pair=pair,
            timeframe=timeframe,
            rows=len(df),
            days=days,
        )

        return PandasDataFeed.from_dataframe(df)

    def run_backtest(
        self,
        strategy: StrategyBase,
        pair: str,
        timeframe: str,
        days: Optional[int] = None,
        start_date: Optional[str] = None,
        end_date: Optional[str] = None,
        config: Optional[BacktestConfig] = None,
    ) -> BacktestResult:
        """Execute backtest with given strategy and parameters.

        Args:
            strategy: Strategy instance to backtest
            pair: Trading pair to backtest on
            timeframe: Candle timeframe
            days: Optional limit on backtest period (from now)
            start_date: Optional start date (e.g., "2024-01-01")
            end_date: Optional end date (e.g., "2024-12-31")
            config: Optional override for backtest config

        Returns:
            BacktestResult with all metrics and data
        """
        run_config = config or self.config

        self.logger.info(
            "starting_backtest",
            strategy=strategy.name,
            pair=pair,
            timeframe=timeframe,
            initial_cash=run_config.initial_cash,
        )

        try:
            self.cerebro = bt.Cerebro()

            self.cerebro.broker.setcash(run_config.initial_cash)
            self.cerebro.broker.setcommission(commission=run_config.commission)

            data_feed = self.create_data_feed(pair, timeframe, days, start_date, end_date)
            self.cerebro.adddata(data_feed)

            self.cerebro.addstrategy(
                BacktraderStrategyAdapter,
                strategy_instance=strategy,
                pair=pair,
                timeframe=timeframe,
            )

            self.cerebro.addanalyzer(bt.analyzers.SharpeRatio, _name="sharpe", timeframe=bt.TimeFrame.Days)
            self.cerebro.addanalyzer(bt.analyzers.DrawDown, _name="drawdown")

            initial_value = self.cerebro.broker.getvalue()

            results = self.cerebro.run()

            if not results:
                return BacktestResult(
                    strategy_name=strategy.name,
                    pair=pair,
                    timeframe=timeframe,
                    initial_value=run_config.initial_cash,
                    final_value=run_config.initial_cash,
                    total_return=0.0,
                    error="Backtest returned no results",
                )

            bt_strategy = results[0]

            final_value = self.cerebro.broker.getvalue()
            total_return = (final_value - initial_value) / initial_value if initial_value > 0 else 0.0

            sharpe_ratio = None
            max_drawdown = None

            if hasattr(bt_strategy, "analyzers"):
                sharpe_analyzer = bt_strategy.analyzers.sharpe
                if sharpe_analyzer:
                    try:
                        sharpe_ratio = sharpe_analyzer.get_analysis().get("sharperatio")
                    except Exception:
                        pass

                drawdown_analyzer = bt_strategy.analyzers.drawdown
                if drawdown_analyzer:
                    try:
                        max_drawdown = drawdown_analyzer.get_analysis().get("max", {}).get("drawdown")
                        if max_drawdown:
                            max_drawdown = max_drawdown / 100
                    except Exception:
                        pass

            plot_path = None
            if run_config.plot_results:
                plot_path = self._save_equity_plot(
                    bt_strategy.equity_curve,
                    bt_strategy.equity_timestamps,
                    pair,
                    timeframe,
                    strategy.name,
                )

            result = BacktestResult(
                strategy_name=strategy.name,
                pair=pair,
                timeframe=timeframe,
                initial_value=initial_value,
                final_value=final_value,
                total_return=total_return,
                trades=bt_strategy.trades,
                equity_curve=bt_strategy.equity_curve,
                equity_timestamps=bt_strategy.equity_timestamps,
                sharpe_ratio=sharpe_ratio,
                max_drawdown=max_drawdown,
                config=run_config,
                plot_path=plot_path,
            )

            self.logger.info(
                "backtest_completed",
                strategy=strategy.name,
                pair=pair,
                initial_value=initial_value,
                final_value=final_value,
                total_return=total_return,
                total_trades=len(bt_strategy.trades),
                sharpe_ratio=sharpe_ratio,
                max_drawdown=max_drawdown,
            )

            return result

        except FileNotFoundError as e:
            error_msg = f"Historical data not found: {e}"
            self.logger.error(error_msg)
            return BacktestResult(
                strategy_name=strategy.name,
                pair=pair,
                timeframe=timeframe,
                initial_value=run_config.initial_cash,
                final_value=run_config.initial_cash,
                total_return=0.0,
                error=error_msg,
            )

        except Exception as e:
            error_msg = f"Backtest failed: {str(e)}"
            self.logger.error(error_msg)
            return BacktestResult(
                strategy_name=strategy.name,
                pair=pair,
                timeframe=timeframe,
                initial_value=run_config.initial_cash,
                final_value=run_config.initial_cash,
                total_return=0.0,
                error=error_msg,
            )

    def _save_equity_plot(
        self,
        equity_curve: List[float],
        timestamps: List[int],
        pair: str,
        timeframe: str,
        strategy_name: str,
    ) -> Optional[str]:
        """Save equity curve plot to file.

        Args:
            equity_curve: List of portfolio values
            timestamps: List of timestamps
            pair: Trading pair
            timeframe: Timeframe
            strategy_name: Strategy name

        Returns:
            Path to saved plot file
        """
        if not equity_curve:
            return None

        try:
            log_dir = Path(self.config.log_path)
            log_dir.mkdir(parents=True, exist_ok=True)

            timestamp_str = pd.Timestamp.now().strftime("%Y%m%d_%H%M%S")
            filename = f"equity_{strategy_name}_{pair.replace('/', '_')}_{timeframe}_{timestamp_str}.png"
            plot_path = log_dir / filename

            fig, ax = plt.subplots(figsize=(12, 6))

            dates = pd.to_datetime([ts / 1000 for ts in timestamps], unit="s")
            ax.plot(dates, equity_curve, label="Portfolio Value", linewidth=1.5)

            initial_value = equity_curve[0] if equity_curve else 0
            ax.axhline(y=initial_value, color="gray", linestyle="--", alpha=0.5, label="Initial Value")

            ax.set_title(f"Backtest Equity Curve - {strategy_name} on {pair} ({timeframe})")
            ax.set_xlabel("Date")
            ax.set_ylabel("Portfolio Value (USDT)")
            ax.legend()
            ax.grid(True, alpha=0.3)

            plt.tight_layout()
            plt.savefig(plot_path, dpi=150)
            plt.close(fig)

            self.logger.info("equity_plot_saved", path=str(plot_path))
            return str(plot_path)

        except Exception as e:
            self.logger.error("equity_plot_save_failed", error=str(e))
            return None

    def get_available_strategies(self) -> List[str]:
        """Get list of available strategy names.

        Returns:
            List of strategy identifiers
        """
        return list(self._strategy_map.keys())

    def register_strategy(self, name: str, strategy_class: Type[StrategyBase]):
        """Register a new strategy for use in backtests.

        Args:
            name: Strategy identifier
            strategy_class: Strategy class (must inherit from StrategyBase)
        """
        self._strategy_map[name.lower()] = strategy_class
        self.logger.info("strategy_registered", name=name, class_name=strategy_class.__name__)