"""Live trading engine — real-time execution loop."""

import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum

from loguru import logger

from cryptoquant.data.cache import DataCache
from cryptoquant.engine.exit_logic import (
    ExitCheck,
    check_signal_reverse,
    check_stop_loss,
    check_take_profit,
    check_time_exit,
    determine_exit,
)
from cryptoquant.engine.state import EngineState, StateManager
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
        cache: DataCache,
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
        self.cache = cache
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
        timestamp = int(datetime.utcnow().timestamp() * 1000)

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
        df = self.cache.get_ohlcv(
            self.broker.exchange_name,
            self.symbol,
            self.strategy.timeframe,
            lookback=lookback,
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
        current_positions = 1 if has_position else 0

        if has_position:
            current_price = df["close"].iloc[-1]

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

            now_ms = int(datetime.utcnow().timestamp() * 1000)
            max_hold_ms = None
            if self.max_hold_hours is not None:
                max_hold_ms = int(self.max_hold_hours * 3_600_000)

            sl_check = check_stop_loss(
                position.side,
                current_price,
                current_price,
                stop_loss_price,
                use_lows_for_stops=True,
            )
            tp_check = check_take_profit(
                position.side,
                current_price,
                current_price,
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

        order_amount = self._calculate_position_size(balance, df)

        # Hard limit: max order size
        if order_amount > self.max_order_usdt:
            logger.warning(
                f"Order {order_amount:.1f} USDT exceeds max "
                f"{self.max_order_usdt}, clamped to max"
            )
            order_amount = self.max_order_usdt

        if order_amount < self.min_order_usdt:
            return TickResult(
                action=TickAction.SKIP,
                signal=signal,
                reason=(
                    f"order amount {order_amount:.1f} < "
                    f"min {self.min_order_usdt}"
                ),
                order=None,
                balance=balance,
                timestamp=timestamp,
            )

        try:
            if signal == 1:
                order = self.broker.market_buy(self.symbol, order_amount)
            else:
                order = self.broker.market_sell(self.symbol, order_amount)

            # Wait for fill
            if order.is_open or order.is_partially_filled:
                order = self._wait_and_handle_fill(order)

            logger.info(f"ENTER {side.upper()}: {order.filled} @ {order.price}")

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
        """Calculate order amount in USDT."""
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
                timestamp=int(datetime.utcnow().timestamp() * 1000),
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
                last_tick_time=int(datetime.utcnow().timestamp() * 1000),
            )
            self.state_mgr.save(state)
        except Exception as e:
            logger.warning(f"Failed to save state: {e}")
