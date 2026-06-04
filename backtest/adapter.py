"""Backtrader strategy adapter.

Bridges StrategyBase to Backtrader's bt.Strategy, handling signal processing,
position management, and trade recording.

Optimized for backtest speed:
- Uses float arrays instead of OHLCVCandle list (avoids Decimal overhead)
- Trims data window to prevent O(n²) growth
- Skips per-bar OHLCVCandle creation
- Initializes strategy once at startup
"""

from decimal import Decimal
from typing import Any, Dict, List, Optional

import backtrader as bt
import structlog

from strategy.base import Signal, SignalType, StrategyContext


class BacktraderStrategyAdapter(bt.Strategy):
    """Backtrader strategy adapter that wraps our StrategyBase classes.

    This adapter bridges our strategy framework with Backtrader's Cerebro engine.
    Optimized for speed: uses float arrays, trims data window, skips candle creation.
    """

    params = (
        ("strategy_instance", None),
        ("pair", ""),
        ("timeframe", ""),
        ("max_window", 500),  # Max bars to keep in float arrays (increased for long MAs)
    )

    def __init__(self):
        """Initialize the adapter strategy."""
        self.strategy = self.params.strategy_instance
        self.pair = self.params.pair
        self.timeframe = self.params.timeframe
        self.max_window = self.params.max_window

        # Fast float arrays (main performance optimization)
        self.closes_f: List[float] = []
        self.opens_f: List[float] = []
        self.highs_f: List[float] = []
        self.lows_f: List[float] = []
        self.volumes_f: List[float] = []

        self.trades: List[Dict[str, Any]] = []
        self.equity_curve: List[float] = []
        self.equity_timestamps: List[int] = []
        self.position_state = None
        self.entry_price: Optional[Decimal] = None
        self.entry_time: Optional[int] = None
        self.position_size: Decimal = Decimal('0')

        # Initialize strategy once at startup (instead of per-bar in on_bar)
        if self.strategy:
            self.strategy.initialize()
            self.strategy._initialized = True

        self.logger = structlog.get_logger(__name__).bind(
            strategy=self.strategy.name if self.strategy else "unknown",
            pair=self.pair,
        )

    def log(self, txt: str, dt: Optional[Any] = None):
        """Log message with datetime."""
        dt = dt or self.datas[0].datetime.datetime(0)
        self.logger.info(txt, datetime=str(dt))

    def next(self):
        """Called for each new bar — optimized hot path."""
        data = self.datas[0]

        # Append to float arrays (fast — no Decimal/dataclass overhead)
        self.opens_f.append(float(data.open[0]))
        self.highs_f.append(float(data.high[0]))
        self.lows_f.append(float(data.low[0]))
        self.closes_f.append(float(data.close[0]))
        self.volumes_f.append(float(data.volume[0]))

        # Trim arrays to max window (prevents O(n²) in indicator calculations)
        if len(self.closes_f) > self.max_window:
            trim = len(self.closes_f) - self.max_window
            self.closes_f = self.closes_f[trim:]
            self.opens_f = self.opens_f[trim:]
            self.highs_f = self.highs_f[trim:]
            self.lows_f = self.lows_f[trim:]
            self.volumes_f = self.volumes_f[trim:]

        current_price = Decimal(str(data.close[0]))
        current_time = int(data.datetime.datetime(0).timestamp() * 1000)

        # Create context with fast float arrays
        context = StrategyContext(
            pair=self.pair,
            timeframe=self.timeframe,
            current_price=current_price,
            candles=[],  # Empty — strategy uses float arrays via has_fast_data
            current_time=current_time,
            closes_f=self.closes_f,
            opens_f=self.opens_f,
            highs_f=self.highs_f,
            lows_f=self.lows_f,
            volumes_f=self.volumes_f,
        )

        try:
            # Call generate_signal directly (skip on_bar overhead)
            signal = self.strategy.generate_signal(context)
            self._process_signal(signal, current_price, current_time)
        except Exception as e:
            self.logger.error("signal_processing_error", error=str(e))

        self.equity_curve.append(self.broker.getvalue())
        self.equity_timestamps.append(current_time)

    def _process_signal(self, signal: Signal, current_price: Decimal, current_time: int):
        """Process trading signal and execute orders.

        Handles position reversal: if a LONG signal comes while in a short
        position (or vice versa), closes the current position first before
        opening the new one.
        """
        if signal.signal_type == SignalType.HOLD:
            return

        size = self._calculate_position_size(signal, current_price)

        if signal.signal_type == SignalType.LONG:
            if self.position and self.position.size < 0:
                # Reverse short → long: close short first
                self.close()
                self._record_trade(current_price, current_time, "short")
            if not self.position:
                self.buy(size=size)
                self.entry_price = current_price
                self.entry_time = current_time
                self.position_size = Decimal(str(size))

        elif signal.signal_type == SignalType.SHORT:
            if self.position and self.position.size > 0:
                # Reverse long → short: close long first
                self.close()
                self._record_trade(current_price, current_time, "long")
            if not self.position:
                self.sell(size=size)
                self.entry_price = current_price
                self.entry_time = current_time
                self.position_size = Decimal(str(size))

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
        cash = Decimal(str(self.broker.getcash()))
        max_position_value = cash * Decimal('0.95')
        size = max_position_value / current_price
        return float(max(size, Decimal('0.001')))

    def _record_trade(self, exit_price: Decimal, exit_time: int, side: str):
        """Record completed trade."""
        if self.entry_price is None or self.entry_time is None:
            return

        entry_price = self.entry_price

        if side == "long":
            pnl = (exit_price - entry_price) / entry_price
        else:
            pnl = (entry_price - exit_price) / entry_price

        trade = {
            "entry_time": self.entry_time,
            "exit_time": exit_time,
            "entry_price": str(entry_price),
            "exit_price": str(exit_price),
            "side": side,
            "pnl": float(pnl),  # percentage return
            "position_size": float(self.position_size) if self.position_size else 0,
            "entry_value": float(entry_price * self.position_size) if self.position_size else 0,
        }

        self.trades.append(trade)

        self.entry_price = None
        self.entry_time = None
        self.position_size = Decimal('0')

    def notify_order(self, order):
        """Called when order status changes."""
        if order.status in [order.Completed]:
            dt = self.datas[0].datetime.datetime(0)
            portfolio_value = self.broker.getvalue()
            side = "buy" if order.isbuy() else "sell"
            self.logger.debug(
                f"{side}_executed",
                datetime=str(dt),
                price=order.executed.price,
                size=order.executed.size,
                cost=order.executed.value,
                commission=order.executed.comm,
                portfolio_value=portfolio_value,
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