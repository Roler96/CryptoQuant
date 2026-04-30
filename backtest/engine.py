"""Backtest engine integrating Backtrader framework.

Provides a comprehensive backtesting solution with:
- Backtrader Cerebro integration
- Custom PandasData feed from Parquet files
- Strategy loading by name
- Configurable backtest parameters (cash, commission, slippage)
- Trade tracking and equity curve generation
- Performance visualization with matplotlib
"""

import os
from dataclasses import dataclass, field
from decimal import Decimal
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Type

import backtrader as bt
import matplotlib
import pandas as pd
import structlog
from matplotlib import pyplot as plt

from data.storage import load_historical_data
from strategy.base import Signal, SignalType, StrategyBase, StrategyContext
from strategy.cta.trend_following import TrendFollowingStrategy

logger = structlog.get_logger(__name__)

matplotlib.use("Agg")


@dataclass
class BacktestConfig:
    """Configuration for backtest execution."""

    initial_cash: float = 10000.0
    commission: float = 0.001
    slippage: float = 0.0005
    plot_results: bool = True
    log_path: str = "logs"


@dataclass
class BacktestResult:
    """Result of a backtest execution."""

    strategy_name: str
    pair: str
    timeframe: str
    initial_value: float
    final_value: float
    total_return: float
    trades: List[Dict[str, Any]] = field(default_factory=list)
    equity_curve: List[float] = field(default_factory=list)
    equity_timestamps: List[int] = field(default_factory=list)
    sharpe_ratio: Optional[float] = None
    max_drawdown: Optional[float] = None
    config: Optional[BacktestConfig] = None
    plot_path: Optional[str] = None
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary."""
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


class PandasDataFeed(bt.feeds.PandasData):
    """Custom Backtrader data feed for our Parquet DataFrame format.

    Maps our standard columns (timestamp, open, high, low, close, volume)
    to Backtrader's expected format.
    """

    params = (
        ("datetime", 0),
        ("open", 1),
        ("high", 2),
        ("low", 3),
        ("close", 4),
        ("volume", 5),
        ("openinterest", -1),
    )

    def __init__(self, dataframe: pd.DataFrame, **kwargs):
        """Initialize with pandas DataFrame.

        Args:
            dataframe: DataFrame with columns: timestamp, open, high, low, close, volume
            **kwargs: Additional Backtrader feed parameters
        """
        processed_df = self._prepare_dataframe(dataframe)
        super().__init__(dataname=processed_df, **kwargs)

    def _prepare_dataframe(self, df: pd.DataFrame) -> pd.DataFrame:
        """Prepare DataFrame for Backtrader.

        Converts timestamp to datetime and ensures proper column order.
        """
        df = df.copy()

        if "timestamp" in df.columns:
            df["datetime"] = pd.to_datetime(df["timestamp"], unit="ms")
            df = df.set_index("datetime")
        else:
            raise ValueError("DataFrame must have 'timestamp' column")

        required_cols = ["open", "high", "low", "close", "volume"]
        for col in required_cols:
            if col not in df.columns:
                raise ValueError(f"DataFrame missing required column: {col}")

        return df[["open", "high", "low", "close", "volume"]]


class BacktraderStrategyAdapter(bt.Strategy):
    """Backtrader strategy adapter that wraps our StrategyBase classes.

    This adapter bridges our strategy framework with Backtrader's Cerebro engine.
    """

    params = (
        ("strategy_instance", None),
        ("pair", ""),
        ("timeframe", ""),
    )

    def __init__(self):
        """Initialize the adapter strategy."""
        self.strategy = self.params.strategy_instance
        self.pair = self.params.pair
        self.timeframe = self.params.timeframe
        self.candles: List[Any] = []
        self.trades: List[Dict[str, Any]] = []
        self.equity_curve: List[float] = []
        self.equity_timestamps: List[int] = []
        self.position_state = None
        self.entry_price = None
        self.entry_time = None

        self.logger = structlog.get_logger(__name__).bind(
            strategy=self.strategy.name if self.strategy else "unknown",
            pair=self.pair,
        )

    def log(self, txt: str, dt: Optional[Any] = None):
        """Log message with datetime."""
        dt = dt or self.datas[0].datetime.datetime(0)
        self.logger.info(txt, datetime=str(dt))

    def next(self):
        """Called for each new bar."""
        data = self.datas[0]

        candle = self._create_candle(data)
        self.candles.append(candle)

        current_price = Decimal(str(data.close[0]))
        current_time = int(data.datetime.datetime(0).timestamp() * 1000)

        context = self._create_context(current_price, current_time)

        try:
            signal = self.strategy.on_bar(candle, context)
            self._process_signal(signal, current_price, current_time)
        except Exception as e:
            self.logger.error("signal_processing_error", error=str(e))

        self.equity_curve.append(self.broker.getvalue())
        self.equity_timestamps.append(current_time)

    def _create_candle(self, data) -> Any:
        """Create OHLCVCandle from Backtrader data."""
        from data.models import OHLCVCandle

        return OHLCVCandle(
            timestamp=int(data.datetime.datetime(0).timestamp() * 1000),
            open_price=Decimal(str(data.open[0])),
            high_price=Decimal(str(data.high[0])),
            low_price=Decimal(str(data.low[0])),
            close_price=Decimal(str(data.close[0])),
            volume=Decimal(str(data.volume[0])),
            pair=self.pair,
            timeframe=self.timeframe,
        )

    def _create_context(self, current_price: Decimal, current_time: int) -> StrategyContext:
        """Create strategy context."""
        return StrategyContext(
            pair=self.pair,
            timeframe=self.timeframe,
            current_price=current_price,
            candles=self.candles,
            current_time=current_time,
        )

    def _process_signal(self, signal: Signal, current_price: Decimal, current_time: int):
        """Process trading signal and execute orders."""
        if signal.signal_type == SignalType.HOLD:
            return

        size = self._calculate_position_size(signal, current_price)

        if signal.signal_type == SignalType.LONG:
            if not self.position:
                self.buy(size=size)
                self.entry_price = float(current_price)
                self.entry_time = current_time
                self.logger.debug("long_position_opened", size=size, price=float(current_price))

        elif signal.signal_type == SignalType.SHORT:
            if not self.position:
                self.sell(size=size)
                self.entry_price = float(current_price)
                self.entry_time = current_time
                self.logger.debug("short_position_opened", size=size, price=float(current_price))

        elif signal.signal_type == SignalType.CLOSE_LONG:
            if self.position and self.position.size > 0:
                self.close()
                self._record_trade(current_price, current_time, "long")

        elif signal.signal_type == SignalType.CLOSE_SHORT:
            if self.position and self.position.size < 0:
                self.close()
                self._record_trade(current_price, current_time, "short")

    def _calculate_position_size(self, signal: Signal, current_price: Decimal) -> float:
        """Calculate position size based on signal and available cash."""
        cash = self.broker.getcash()
        max_position_value = cash * 0.95
        size = max_position_value / float(current_price)
        return max(size, 0.001)

    def _record_trade(self, exit_price: Decimal, exit_time: int, side: str):
        """Record completed trade."""
        if self.entry_price is None or self.entry_time is None:
            return

        entry_price = self.entry_price
        exit_price_float = float(exit_price)

        if side == "long":
            pnl = (exit_price_float - entry_price) / entry_price
        else:
            pnl = (entry_price - exit_price_float) / entry_price

        trade = {
            "entry_time": self.entry_time,
            "exit_time": exit_time,
            "entry_price": entry_price,
            "exit_price": exit_price_float,
            "side": side,
            "pnl": pnl,
        }

        self.trades.append(trade)
        self.logger.debug(
            "trade_recorded",
            side=side,
            entry_price=entry_price,
            exit_price=exit_price_float,
            pnl=pnl,
        )

        self.entry_price = None
        self.entry_time = None

    def notify_order(self, order):
        """Called when order status changes."""
        if order.status in [order.Completed]:
            if order.isbuy():
                self.logger.debug(
                    "buy_executed",
                    price=order.executed.price,
                    size=order.executed.size,
                    cost=order.executed.value,
                    commission=order.executed.comm,
                )
            else:
                self.logger.debug(
                    "sell_executed",
                    price=order.executed.price,
                    size=order.executed.size,
                    cost=order.executed.value,
                    commission=order.executed.comm,
                )

    def stop(self):
        """Called when backtest ends."""
        final_value = self.broker.getvalue()
        total_return = (final_value - self.broker.startingcash) / self.broker.startingcash

        self.logger.info(
            "backtest_completed",
            initial_value=self.broker.startingcash,
            final_value=final_value,
            total_return=total_return,
            total_trades=len(self.trades),
        )


class BacktestEngine:
    """Backtest engine that integrates Backtrader Cerebro.

    Provides a high-level interface for running backtests with:
    - Strategy loading by name
    - Custom data feeds from Parquet files
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
    ) -> PandasDataFeed:
        """Create data feed from historical data.

        Args:
            pair: Trading pair (e.g., "BTC/USDT")
            timeframe: Candle timeframe (e.g., "1h", "1d")
            days: Optional limit on number of days to load

        Returns:
            PandasDataFeed ready for Backtrader

        Raises:
            FileNotFoundError: If historical data not found
        """
        df = load_historical_data(pair, timeframe)

        if days is not None:
            cutoff_timestamp = (pd.Timestamp.now() - pd.Timedelta(days=days)).timestamp() * 1000
            df = df[df["timestamp"] >= cutoff_timestamp]

        self.logger.info(
            "data_feed_created",
            pair=pair,
            timeframe=timeframe,
            rows=len(df),
            days=days,
        )

        return PandasDataFeed(df)

    def run_backtest(
        self,
        strategy: StrategyBase,
        pair: str,
        timeframe: str,
        days: Optional[int] = None,
        config: Optional[BacktestConfig] = None,
    ) -> BacktestResult:
        """Execute backtest with given strategy and parameters.

        Args:
            strategy: Strategy instance to backtest
            pair: Trading pair to backtest on
            timeframe: Candle timeframe
            days: Optional limit on backtest period
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

            data_feed = self.create_data_feed(pair, timeframe, days)
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
