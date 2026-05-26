"""Backtrader strategy adapter.

Bridges StrategyBase to Backtrader's bt.Strategy, handling signal processing,
position management, and trade recording.
"""

from decimal import Decimal
from typing import Any, Dict, List, Optional

import backtrader as bt
import structlog

from data.models import OHLCVCandle
from strategy.base import Signal, SignalType, StrategyContext


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
        self.candles: List[OHLCVCandle] = []
        self.trades: List[Dict[str, Any]] = []
        self.equity_curve: List[float] = []
        self.equity_timestamps: List[int] = []
        self.position_state = None
        self.entry_price: Optional[Decimal] = None
        self.entry_time: Optional[int] = None

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

    def _create_candle(self, data) -> OHLCVCandle:
        """Create OHLCVCandle from Backtrader data."""
        return OHLCVCandle(
            timestamp=int(data.datetime.datetime(0).timestamp() * 1000),
            open=Decimal(str(data.open[0])),
            high=Decimal(str(data.high[0])),
            low=Decimal(str(data.low[0])),
            close=Decimal(str(data.close[0])),
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
                self.logger.debug("long_position_opened", size=size, price=str(current_price))

        elif signal.signal_type == SignalType.SHORT:
            if self.position and self.position.size > 0:
                # Reverse long → short: close long first
                self.close()
                self._record_trade(current_price, current_time, "long")
            if not self.position:
                self.sell(size=size)
                self.entry_price = current_price
                self.entry_time = current_time
                self.logger.debug("short_position_opened", size=size, price=str(current_price))

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
            "pnl": float(pnl),
        }

        self.trades.append(trade)
        self.logger.debug(
            "trade_recorded",
            side=side,
            entry_price=str(entry_price),
            exit_price=str(exit_price),
            pnl=float(pnl),
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