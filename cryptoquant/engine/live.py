"""Live trading engine — real-time execution loop."""

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

from loguru import logger

from cryptoquant.data.live_feed import LiveDataFeed
from cryptoquant.engine.exit_logic import (
    ExitCheck,
    check_signal_reverse,
    check_stop_loss,
    check_take_profit,
    check_time_exit,
    determine_exit,
)
from cryptoquant.engine.state import EngineState, StateManager
from cryptoquant.exceptions import DataError, OrderRejectedError
from cryptoquant.execution.broker import Broker
from cryptoquant.execution.order import Order, OrderStatus, Position
from cryptoquant.strategy.base import Strategy


class TickAction(str, Enum):
    NOOP = "noop"
    ENTRY_LONG = "entry_long"
    ENTRY_SHORT = "entry_short"
    EXIT = "exit"
    SKIP = "skip"


@dataclass
class TickResult:
    action: TickAction
    signal: int
    reason: str
    order: Order | None
    balance: float
    timestamp: int


class LiveEngine:
    """Live trading engine.

    Responsibilities:
    1. Periodically fetch latest OHLCV data
    2. Call strategy to generate signal
    3. Check risk management
    4. Execute orders via Broker
    5. Persist state
    """

    def __init__(
        self,
        broker: Broker,
        strategy: Strategy,
        data_feed: LiveDataFeed,
        risk_manager=None,
        state_dir: str = "state",
        symbol: str = "",
        min_order_usdt: float = 10.0,
        max_order_usdt: float = 1000.0,
        cooldown_bars: int = 0,
        initial_capital: float = 10000.0,
        order_timeout: int = 30,
        stop_loss_pct: float | None = None,
        take_profit_pct: float | None = None,
        max_hold_hours: float | None = None,
        sizer=None,
    ):
        self.broker = broker
        self.strategy = strategy
        self.data_feed = data_feed
        self.risk_manager = risk_manager
        self.state_mgr = StateManager(state_dir)
        self.symbol = symbol
        self.min_order_usdt = min_order_usdt
        self.max_order_usdt = max_order_usdt
        self.cooldown_bars = cooldown_bars
        self._initial_capital = initial_capital
        self.order_timeout = order_timeout
        self.stop_loss_pct = stop_loss_pct
        self.take_profit_pct = take_profit_pct
        self.max_hold_hours = max_hold_hours
        self.sizer = sizer

        self._running = False
        self._cooldown_remaining = 0
        self._trades_count = 0
        self._total_pnl_pct = 0.0

        # Restore state if exists
        saved = self.state_mgr.load(strategy.name, symbol)
        if saved:
            logger.info(f"Restored state for {strategy.name} on {symbol}")
            self._trades_count = saved.total_trades
            self._total_pnl_pct = saved.total_pnl_pct
            self._initial_capital = saved.initial_capital

    def tick(self) -> TickResult:
        """Execute one decision loop.

        Returns:
            TickResult describing this tick's outcome.
        """
        timestamp = int(datetime.now(UTC).timestamp() * 1000)

        # 0. Cooldown check
        if self._cooldown_remaining > 0:
            self._cooldown_remaining -= 1
            return TickResult(
                action=TickAction.SKIP,
                signal=0,
                reason=f"cooldown ({self._cooldown_remaining} bars remaining)",
                order=None,
                balance=self._get_balance(),
                timestamp=timestamp,
            )

        # 1. Fetch data
        lookback = max(self.strategy.min_bars, 200)
        try:
            df = self.data_feed.fetch(lookback)
        except DataError as e:
            logger.error(f"Live data fetch/validation failed: {e}")
            return TickResult(
                action=TickAction.SKIP,
                signal=0,
                reason=f"data error: {e}",
                order=None,
                balance=self._get_balance(),
                timestamp=timestamp,
            )

        if len(df) < self.strategy.min_bars:
            logger.warning(
                f"Insufficient data: {len(df)} < {self.strategy.min_bars}"
            )
            return TickResult(
                action=TickAction.SKIP,
                signal=0,
                reason="insufficient data",
                order=None,
                balance=self._get_balance(),
                timestamp=timestamp,
            )

        quality_report = getattr(self.data_feed, "last_quality_report", None)
        if quality_report is not None and not quality_report.is_healthy:
            return TickResult(
                action=TickAction.SKIP,
                signal=0,
                reason="data quality unhealthy",
                order=None,
                balance=self._get_balance(),
                timestamp=timestamp,
            )

        self._update_simulated_price(df)

        # 2. Generate signal
        try:
            signals = self.strategy.generate_signal(df)
            signal = int(signals.iloc[-1])
        except Exception as e:
            logger.error(f"Signal generation failed: {e}")
            return TickResult(
                action=TickAction.SKIP,
                signal=0,
                reason=f"signal error: {e}",
                order=None,
                balance=self._get_balance(),
                timestamp=timestamp,
            )

        # 3. Check current position (broker is source of truth)
        try:
            position = self.broker.get_position(self.symbol)
        except Exception:
            position = None

        has_position = position is not None and position.amount > 0

        # 4. Decision
        balance = self._get_balance()
        if self.risk_manager:
            self.risk_manager.update_balance(balance, calibrate=True)
        current_positions = 1 if has_position else 0

        if has_position:
            bar_high = float(df["high"].iloc[-1])
            bar_low = float(df["low"].iloc[-1])

            stop_loss_price = None
            if self.stop_loss_pct is not None:
                if position.side == "long":
                    stop_loss_price = position.entry_price * (
                        1 - self.stop_loss_pct / 100
                    )
                else:
                    stop_loss_price = position.entry_price * (
                        1 + self.stop_loss_pct / 100
                    )

            take_profit_price = None
            if self.take_profit_pct is not None:
                if position.side == "long":
                    take_profit_price = position.entry_price * (
                        1 + self.take_profit_pct / 100
                    )
                else:
                    take_profit_price = position.entry_price * (
                        1 - self.take_profit_pct / 100
                    )

            now_ms = int(datetime.now(UTC).timestamp() * 1000)
            max_hold_ms = None
            if self.max_hold_hours is not None:
                max_hold_ms = int(self.max_hold_hours * 3_600_000)

            sl_check = check_stop_loss(
                position.side,
                bar_high,
                bar_low,
                stop_loss_price,
                use_lows_for_stops=True,
            )
            tp_check = check_take_profit(
                position.side,
                bar_high,
                bar_low,
                take_profit_price,
            )
            time_check = check_time_exit(
                position.timestamp, now_ms, max_hold_ms
            )
            # Preserve original behavior: only check signal reverse for longs
            if position.side == "long":
                signal_check = check_signal_reverse(signal, 1)
            else:
                signal_check = ExitCheck(False, "")

            exit_check = determine_exit(
                sl_check, tp_check, time_check, signal_check
            )
            if exit_check.should_exit:
                return self._exit_position(
                    position, signal, timestamp, exit_reason=exit_check.reason
                )

            return TickResult(
                action=TickAction.NOOP,
                signal=signal,
                reason=f"holding {position.side}",
                order=None,
                balance=balance,
                timestamp=timestamp,
            )

        # Entry condition
        if signal in (1, -1) and (signal == 1 or self.broker.can_short):
            # Risk check
            if self.risk_manager:
                allowed, reason = self.risk_manager.can_enter(
                    self.symbol, signal, balance, current_positions
                )
                if not allowed:
                    logger.warning(
                        f"Entry blocked by risk manager: {reason}"
                    )
                    return TickResult(
                        action=TickAction.SKIP,
                        signal=signal,
                        reason=f"risk: {reason}",
                        order=None,
                        balance=balance,
                        timestamp=timestamp,
                    )
            return self._enter_position(signal, timestamp, df)

        return TickResult(
            action=TickAction.NOOP,
            signal=signal if signal == -1 else 0,
            reason=(
                "no signal"
                if signal == 0
                else "short not allowed in spot"
            ),
            order=None,
            balance=balance,
            timestamp=timestamp,
        )

    def _enter_position(
        self, signal: int, timestamp: int, df=None
    ) -> TickResult:
        """Open position."""
        side = "long" if signal == 1 else "short"
        balance = self._get_balance()

        order_value_usdt = self._calculate_position_size(balance, df)

        # Hard limit: max order size
        if order_value_usdt > self.max_order_usdt:
            logger.warning(
                f"Order {order_value_usdt:.1f} USDT exceeds max "
                f"{self.max_order_usdt}, clamped to max"
            )
            order_value_usdt = self.max_order_usdt

        if order_value_usdt < self.min_order_usdt:
            return TickResult(
                action=TickAction.SKIP,
                signal=signal,
                reason=(
                    f"order amount {order_value_usdt:.1f} < "
                    f"min {self.min_order_usdt}"
                ),
                order=None,
                balance=balance,
                timestamp=timestamp,
            )

        try:
            price = self._current_price(df)
            order_amount = self._quote_to_base_amount(order_value_usdt, price)
            if order_amount <= 0:
                return TickResult(
                    action=TickAction.SKIP,
                    signal=signal,
                    reason=f"invalid order amount from price {price}",
                    order=None,
                    balance=balance,
                    timestamp=timestamp,
                )
            try:
                order_amount = self.broker.normalize_order_amount(
                    self.symbol, order_amount, price
                )
            except OrderRejectedError as e:
                logger.warning(f"Order rejected before submit: {e}")
                return TickResult(
                    action=TickAction.SKIP,
                    signal=signal,
                    reason=f"order rejected: {e}",
                    order=None,
                    balance=balance,
                    timestamp=timestamp,
                )

            if signal == 1:
                order = self.broker.market_buy(self.symbol, order_amount)
            else:
                order = self.broker.market_sell(self.symbol, order_amount)

            # Wait for fill
            if order.is_open or order.is_partially_filled:
                order = self._wait_and_handle_fill(order)

            logger.info(f"ENTER {side.upper()}: {order.filled} @ {order.price}")
            if self.risk_manager and order.filled > 0:
                self.risk_manager.record_entry(self.symbol, side)
                self.risk_manager.update_balance(self._get_balance(), calibrate=True)

            return TickResult(
                action=(
                    TickAction.ENTRY_LONG
                    if signal == 1
                    else TickAction.ENTRY_SHORT
                ),
                signal=signal,
                reason=f"entry {side}",
                order=order,
                balance=self._get_balance(),
                timestamp=timestamp,
            )
        except Exception as e:
            logger.error(f"Entry failed: {e}")
            return TickResult(
                action=TickAction.SKIP,
                signal=signal,
                reason=f"entry error: {e}",
                order=None,
                balance=balance,
                timestamp=timestamp,
            )

    def _wait_and_handle_fill(self, order: Order) -> Order:
        """Wait for order fill, handle partial fills and timeout."""
        try:
            order = self.broker.wait_for_fill(
                order.id, self.symbol, timeout=self.order_timeout
            )
        except Exception:
            logger.warning(
                f"Order {order.id} timeout after "
                f"{self.order_timeout}s, cancelling"
            )
            self.broker.cancel_order(order.id, self.symbol)
            raise

        # Handle partial fill
        if order.is_partially_filled:
            order = self._handle_partial_fill(order)

        return order

    def _handle_partial_fill(self, order: Order) -> Order:
        """Handle partial fill.

        >=90% filled: treat as complete.
        <90% filled: cancel remaining.
        """
        if order.fill_pct >= 90:
            logger.info(
                f"Order {order.id} {order.fill_pct:.1f}% filled, "
                f"treating as complete"
            )
            order.status = OrderStatus.CLOSED
            order.amount = order.filled
        else:
            logger.warning(
                f"Order {order.id} {order.fill_pct:.1f}% filled, "
                f"cancelling remaining {order.remaining}"
            )
            self.broker.cancel_order(order.id, order.symbol)
            order.amount = order.filled
        return order

    def _exit_position(
        self,
        position: Position,
        signal: int,
        timestamp: int,
        exit_reason: str = "signal_reverse",
    ) -> TickResult:
        """Close position."""
        logger.info(f"EXIT {position.side.upper()}: {exit_reason}")
        balance_before = self._get_balance()

        try:
            if position.side == "long":
                order = self.broker.market_sell(
                    self.symbol, position.amount
                )
            else:
                order = self.broker.market_buy(
                    self.symbol, position.amount
                )

            # Wait for fill
            if order.is_open or order.is_partially_filled:
                order = self._wait_and_handle_fill(order)

            self._trades_count += 1
            self._cooldown_remaining = self.cooldown_bars
            balance_after = self._get_balance()
            self._record_risk_exit(position, order, balance_before, balance_after)

            return TickResult(
                action=TickAction.EXIT,
                signal=signal,
                reason=f"exit {position.side} ({exit_reason})",
                order=order,
                balance=self._get_balance(),
                timestamp=timestamp,
            )
        except Exception as e:
            logger.error(f"Exit failed: {e}")
            return TickResult(
                action=TickAction.SKIP,
                signal=signal,
                reason=f"exit error: {e}",
                order=None,
                balance=self._get_balance(),
                timestamp=timestamp,
            )

    def _get_balance(self) -> float:
        """Safely get balance."""
        try:
            return self.broker.get_balance("USDT")
        except Exception:
            return 0.0

    def _calculate_position_size(
        self, balance: float, df=None
    ) -> float:
        """Calculate target order value in USDT."""
        if self.sizer:
            amount = self.sizer.calculate(
                balance,
                df["close"].iloc[-1] if df is not None else 0,
                df=df,
            )
        elif self.risk_manager:
            amount = self.risk_manager.position_size(
                balance,
                df["close"].iloc[-1] if df is not None else 0,
                df=df,
            )
        else:
            amount = balance * 0.50

        return min(amount, self.max_order_usdt)

    def _current_price(self, df=None) -> float:
        if df is not None and len(df) > 0:
            return float(df["close"].iloc[-1])
        ticker = self.broker.get_ticker(self.symbol)
        return float(ticker.get("last", 0) or 0)

    def _quote_to_base_amount(self, quote_amount: float, price: float) -> float:
        if quote_amount <= 0 or price <= 0:
            return 0.0
        return quote_amount / price

    def _update_simulated_price(self, df) -> None:
        update_price = getattr(self.broker, "update_price", None)
        if callable(update_price):
            update_price(self.symbol, self._current_price(df))

    def _record_risk_exit(
        self,
        position: Position,
        order: Order,
        balance_before: float,
        balance_after: float,
    ) -> None:
        if not self.risk_manager:
            return

        exit_price = order.price or position.current_price
        if position.entry_price > 0 and exit_price:
            if position.side == "long":
                pnl_pct = (exit_price / position.entry_price - 1) * 100
            else:
                pnl_pct = (1 - exit_price / position.entry_price) * 100
        else:
            pnl_pct = 0.0

        pnl_abs = balance_after - balance_before
        self._total_pnl_pct += pnl_pct
        self.risk_manager.record_exit(self.symbol, pnl_pct, pnl_abs)
        self.risk_manager.update_balance(balance_after, calibrate=True)

    def run(self, interval: int = 60):
        """Start live trading loop.

        Args:
            interval: tick interval in seconds (multiple of K-line period).
        """
        import signal as os_signal

        self._running = True
        logger.info(
            f"LiveEngine started: {self.strategy.name} on {self.symbol}, "
            f"interval={interval}s, testnet={self.broker.testnet}, "
            f"account={self.broker.account_type}"
        )

        os_signal.signal(os_signal.SIGINT, self._handle_shutdown)
        os_signal.signal(os_signal.SIGTERM, self._handle_shutdown)

        consecutive_errors = 0

        try:
            while self._running:
                try:
                    result = self.tick()
                    self._save_state()
                    consecutive_errors = 0

                    if result.action != TickAction.NOOP:
                        logger.info(
                            f"Tick: {result.action.value} | {result.reason}"
                        )

                except Exception as e:
                    consecutive_errors += 1
                    logger.error(
                        f"Tick failed ({consecutive_errors}x): {e}"
                    )

                    if consecutive_errors >= 3:
                        logger.warning(
                            "Multiple consecutive errors, "
                            "attempting reconnect..."
                        )
                        try:
                            self.broker.reconnect()
                            consecutive_errors = 0
                        except Exception:
                            pass

                time.sleep(interval)

        finally:
            self._save_state()
            logger.info("LiveEngine stopped")

    def _handle_shutdown(self, signum, frame):
        """Handle SIGINT/SIGTERM for graceful shutdown."""
        logger.info(f"Received signal {signum}, shutting down...")
        self._running = False

    def stop(self):
        """Manually stop the engine."""
        self._running = False

    def _save_state(self):
        """Save current state to file."""
        try:
            balance = self._get_balance()
            position = self.broker.get_position(self.symbol)

            state = EngineState(
                timestamp=int(datetime.now(UTC).timestamp() * 1000),
                strategy_name=self.strategy.name,
                symbol=self.symbol,
                balance=balance,
                initial_capital=self._initial_capital,
                has_position=(
                    position is not None and position.amount > 0
                ),
                position_side=position.side if position else "",
                position_entry_price=(
                    position.entry_price if position else 0
                ),
                position_amount=(
                    position.amount if position else 0
                ),
                position_entry_time=(
                    position.timestamp if position else 0
                ),
                active_order_ids=[],
                total_trades=self._trades_count,
                total_pnl_pct=self._total_pnl_pct,
                last_signal=0,
                last_tick_time=int(datetime.now(UTC).timestamp() * 1000),
            )
            self.state_mgr.save(state)
        except Exception as e:
            logger.warning(f"Failed to save state: {e}")
