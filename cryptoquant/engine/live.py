"""Live trading engine — real-time execution loop."""
# pyright: reportAttributeAccessIssue=false

import time
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import Enum

from loguru import logger

from cryptoquant.data.closed_bar import ClosedBarFeed
from cryptoquant.engine.exit_logic import (
    ExitCheck,
    check_signal_flat,
    check_signal_reverse,
    check_stop_loss,
    check_take_profit,
    check_time_exit,
    determine_exit,
)
from cryptoquant.engine.state import EngineState, StateManager
from cryptoquant.exceptions import DataError, OrderRejectedError
from cryptoquant.execution.broker_abc import BrokerABC
from cryptoquant.execution.lifecycle import ExecutionLifecycle
from cryptoquant.execution.order import Order, Position
from cryptoquant.monitor.journal import TradeJournal
from cryptoquant.position.ledger import ManagedPositionLedger
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
    6. Reconcile exchange state on restart (crash recovery)
    """

    def __init__(
        self,
        broker: BrokerABC,
        strategy: Strategy,
        data_feed: ClosedBarFeed,
        risk_manager=None,
        state_dir: str = "state",
        symbol: str = "",
        min_order_usdt: float = 10.0,
        max_order_usdt: float = 1000.0,
        cooldown_bars: int = 0,
        initial_capital: float = 10000.0,
        order_timeout: int = 30,
        stop_loss_pct: float | None = None,
        trailing_stop_pct: float | None = None,
        take_profit_pct: float | None = None,
        max_hold_hours: float | None = None,
        sizer=None,
        reconcile_on_start: bool = True,
        journal: TradeJournal | None = None,
        position_ledger: ManagedPositionLedger | None = None,
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
        if trailing_stop_pct is not None and trailing_stop_pct <= 0:
            raise ValueError("trailing_stop_pct must be positive")
        self.trailing_stop_pct = trailing_stop_pct
        self.take_profit_pct = take_profit_pct
        self.max_hold_hours = max_hold_hours
        self.sizer = sizer
        self.journal = journal
        self.position_ledger = position_ledger
        self._execution = ExecutionLifecycle(
            broker, order_timeout=order_timeout, position_ledger=position_ledger
        )

        self._running = False
        self._cooldown_remaining = 0
        self._trades_count = 0
        self._total_pnl_pct = 0.0
        self._tick_counter: int = 0
        self._position_unknown: bool = False  # True when get_position() failed
        self._trailing_anchor: float = 0.0

        # Restore state if exists
        saved = self.state_mgr.load(strategy.name, symbol)
        if saved:
            logger.info(f"Restored state for {strategy.name} on {symbol}")
            self._trades_count = saved.total_trades
            self._total_pnl_pct = saved.total_pnl_pct
            self._initial_capital = saved.initial_capital
            self._trailing_anchor = saved.trailing_anchor
            if saved.ledger_state and self.position_ledger is not None:
                self.position_ledger.restore(saved.ledger_state)

        # Reconcile exchange state (cancel stale orders, sync positions)
        if reconcile_on_start and self.symbol and getattr(self.broker, "exchange_name", "") != "paper":
            self._reconcile()

    def _reconcile(self) -> None:
        """Reconcile local state with exchange on engine startup.

        Cancel stale open orders, fetch actual positions, and sync risk manager.
        This ensures crash recovery consistency.
        """
        logger.info(f"Reconciling exchange state for {self.strategy.name} on {self.symbol}...")

        # 1. Cancel any stale open orders (they won't fill after restart anyway)
        try:
            stale_count = self.broker.cancel_all_orders(self.symbol)
            if stale_count > 0:
                logger.warning(
                    f"Reconciliation: cancelled {stale_count} stale open orders "
                    f"for {self.symbol}"
                )
        except Exception as e:
            logger.error(f"Reconciliation: failed to cancel stale orders: {e}")

        # 2. Fetch actual exchange position
        try:
            position = self.broker.get_position(self.symbol)
            self._position_unknown = False
        except Exception as e:
            logger.error(
                f"Reconciliation: failed to fetch position: {e} "
                f"— position state UNKNOWN, new entries blocked"
            )
            position = None
            self._position_unknown = True

        # 3. Sync risk manager if we have an active position
        if position is not None and position.amount > 0 and self.risk_manager:
            pos_in_risk = self.symbol in self.risk_manager.get_positions()
            if not pos_in_risk:
                logger.warning(
                    f"Reconciliation: found open position {position.side} "
                    f"{position.amount} on exchange but not in risk manager. "
                    f"Restoring risk state."
                )
                self.risk_manager.record_entry(self.symbol, position.side)

            logger.info(
                f"Reconciliation complete: position={position.side} "
                f"amount={position.amount}"
            )
        elif position is None or position.amount <= 0:
            logger.info("Reconciliation complete: no open position on exchange")

    def tick(self) -> TickResult:
        """Execute one decision loop.

        Returns:
            TickResult describing this tick's outcome.
        """
        self._tick_counter += 1
        corr_id = f"tick-{self._tick_counter}"
        self._last_corr_id = corr_id
        timestamp = int(datetime.now(UTC).timestamp() * 1000)

        # 0. Daily reset check (midnight UTC)
        if self.risk_manager:
            self.risk_manager.check_daily_reset()

        # 1. Cooldown check
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

        # 1. Fetch data (data_feed guarantees the last bar is closed)
        lookback = max(self.strategy.min_bars, 200)
        try:
            df, bar_meta = self.data_feed.fetch(lookback)
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

        # 1.5. Skip signal generation if no new closed bar since last tick.
        #      Still check exits and update risk state every poll.
        is_new_bar = bar_meta.has_new_closed

        # 3. Check current position (broker is source of truth).
        #    P0: Unknown != Flat — if position fetch fails, refuse new entries.
        try:
            position = self.broker.get_position(self.symbol)
            self._position_unknown = False
        except Exception as e:
            logger.error(
                f"Failed to fetch position for {self.symbol}: {e} "
                f"— treating position state as UNKNOWN"
            )
            position = None
            self._position_unknown = True

        has_position = position is not None and position.amount > 0

        if not self._position_unknown and not has_position:
            self._trailing_anchor = 0.0

        signal_is_position = bool(
            getattr(self.strategy, "signal_is_position", False)
        )

        if not is_new_bar:
            signal = 0  # no new signal without a new bar
        else:
            # Generate signal with position context when the strategy supports it.
            try:
                side = position.side if has_position else None
                signals = self.strategy.generate_signal_for_position(df, side)
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

        # 4. Decision
        balance = self._get_balance()
        # Compute total equity including open position value for accurate drawdown
        position_value = self._get_position_value()
        total_equity = balance + position_value
        if self.risk_manager:
            self.risk_manager.update_balance(total_equity, calibrate=True)
        current_positions = 1 if has_position else 0

        if position is not None and position.amount > 0:
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
            trailing_check = self._check_trailing_stop(position, df)
            tp_check = check_take_profit(
                position.side,
                bar_high,
                bar_low,
                take_profit_price,
            )
            time_check = check_time_exit(
                position.timestamp, now_ms, max_hold_ms
            )
            # Signal reverse: exit short on long signal, exit long on short signal
            if position.side == "long":
                signal_check = check_signal_reverse(signal, 1)
            else:
                signal_check = check_signal_reverse(signal, -1)

            # A position-style signal of 0 means "target flat" and must close
            # the position, matching the backtest. Only consult it on a fresh
            # bar: without one `signal` was forced to 0 above, which would
            # otherwise close the position on every poll.
            flat_check = check_signal_flat(
                signal, signal_is_position and is_new_bar
            )

            exit_check = determine_exit(
                sl_check,
                trailing_check,
                tp_check,
                time_check,
                signal_check,
                flat_check,
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
            # P0: Unknown position state — refuse new entries (fail-closed).
            if self._position_unknown:
                logger.warning(
                    "Position state unknown (exchange query failed) "
                    "— refusing new entry"
                )
                return TickResult(
                    action=TickAction.SKIP,
                    signal=signal,
                    reason="position state unknown (exchange query failed)",
                    order=None,
                    balance=balance,
                    timestamp=timestamp,
                )

            # Risk check
            if self.risk_manager:
                allowed, reason = self.risk_manager.can_enter(
                    self.symbol, signal, total_equity, current_positions
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
                "no new bar"
                if not is_new_bar
                else "no signal"
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

            order = self._execution.execute_market(
                self.symbol, "buy" if signal == 1 else "sell", order_amount
            )

            logger.info(f"ENTER {side.upper()}: {order.filled} @ {order.price}")
            if order.filled > 0:
                self._trailing_anchor = float(order.price or price)
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
            order = self._execution.execute_market(
                self.symbol,
                "sell" if position.side == "long" else "buy",
                position.amount,
            )

            self._trades_count += 1
            self._cooldown_remaining = self.cooldown_bars
            self._trailing_anchor = 0.0
            balance_after = self._get_balance()
            self._record_risk_exit(position, order, balance_before, balance_after)

            # Journal the completed trade
            if self.journal:
                exit_price = order.price or position.current_price
                if position.side == "long":
                    pnl_pct = (exit_price / position.entry_price - 1) * 100 if position.entry_price > 0 else 0
                else:
                    pnl_pct = (1 - exit_price / position.entry_price) * 100 if position.entry_price > 0 else 0
                self.journal.record({
                    "symbol": self.symbol,
                    "side": position.side,
                    "entry_price": position.entry_price,
                    "exit_price": exit_price,
                    "amount": position.amount,
                    "pnl_pct": round(pnl_pct, 4),
                    "pnl_abs": round(balance_after - balance_before, 4),
                    "exit_reason": exit_reason,
                    "entry_time": position.timestamp,
                    "exit_time": timestamp,
                    "strategy": self.strategy.name,
                })

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

    def _get_position_value(self) -> float:
        """Get total market value of open positions for accurate equity calc."""
        if getattr(self.broker, "account_type", "spot") == "swap":
            return 0.0
        try:
            pos = self.broker.get_position(self.symbol)
            if pos is not None and pos.amount > 0:
                price = pos.current_price or pos.entry_price
                return pos.amount * price
        except Exception:
            pass
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
        converter = getattr(self.broker, "quote_to_order_amount", None)
        if callable(converter):
            converted = converter(self.symbol, quote_amount, price)
            if isinstance(converted, (int, float)):
                return float(converted)
        return quote_amount / price

    def _check_trailing_stop(self, position: Position, df=None) -> ExitCheck:
        """Update favorable price anchor from ticker and check trailing stop."""
        if self.trailing_stop_pct is None:
            return ExitCheck(False, "")

        price = float(position.current_price or 0)
        try:
            ticker_price = float(
                self.broker.get_ticker(self.symbol).get("last", 0) or 0
            )
            if ticker_price > 0:
                price = ticker_price
        except Exception as e:
            logger.warning(f"Ticker unavailable for trailing stop: {e}")
        if price <= 0 and df is not None and len(df) > 0:
            price = float(df["close"].iloc[-1])
        if price <= 0:
            return ExitCheck(False, "")

        pct = self.trailing_stop_pct / 100
        if position.side == "long":
            self._trailing_anchor = max(
                self._trailing_anchor or position.entry_price, price
            )
            if price <= self._trailing_anchor * (1 - pct):
                return ExitCheck(True, "trailing_stop")
        else:
            self._trailing_anchor = min(
                self._trailing_anchor or position.entry_price, price
            )
            if price >= self._trailing_anchor * (1 + pct):
                return ExitCheck(True, "trailing_stop")
        return ExitCheck(False, "")

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

    def run(self, interval: int = 60, heartbeat_ticks: int = 60):
        """Start live trading loop.

        Args:
            interval: tick interval in seconds (multiple of K-line period).
            heartbeat_ticks: log engine status every N ticks (0 = disabled).
        """
        import signal as os_signal

        self._running = True
        broker_name = getattr(self.broker, "exchange_name", "unknown")
        broker_testnet = getattr(self.broker, "testnet", None)
        broker_account = getattr(self.broker, "account_type", "n/a")
        logger.info(
            f"LiveEngine started: {self.strategy.name} on {self.symbol}, "
            f"interval={interval}s, broker={broker_name}, "
            f"testnet={broker_testnet}, account={broker_account}"
        )

        os_signal.signal(os_signal.SIGINT, self._handle_shutdown)
        os_signal.signal(os_signal.SIGTERM, self._handle_shutdown)

        consecutive_errors = 0
        last_heartbeat_at = 0.0

        try:
            while self._running:
                try:
                    result = self.tick()
                    self._save_state()
                    consecutive_errors = 0

                    # Periodic heartbeat
                    if heartbeat_ticks > 0:
                        now_ts = time.time()
                        if now_ts - last_heartbeat_at >= heartbeat_ticks * interval:
                            self._log_heartbeat()
                            last_heartbeat_at = now_ts

                    if result.action != TickAction.NOOP:
                        logger.info(
                            f"[{self._last_corr_id}] Tick: {result.action.value} | {result.reason}"
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

    def _log_heartbeat(self) -> None:
        """Log structured engine status for monitoring."""
        try:
            balance = self._get_balance()
            position = self.broker.get_position(self.symbol)
            has_pos = position is not None and position.amount > 0

            status = {
                "tick": self._tick_counter,
                "balance": round(balance, 2),
                "has_position": has_pos,
                "position_side": position.side if position is not None and position.amount > 0 else "",
                "trades": self._trades_count,
                "pnl_pct": round(self._total_pnl_pct, 2),
            }

            if self.risk_manager:
                stats = self.risk_manager.get_daily_stats()
                status["daily_trades"] = stats.total_trades
                status["daily_pnl_pct"] = round(stats.total_pnl_pct, 2)
                position_value = self._get_position_value()
                tier = self.risk_manager.current_tier(balance + position_value)
                status["drawdown_tier"] = tier.value

            logger.info(
                f"[HEARTBEAT] tick={status['tick']} "
                f"bal={status['balance']:.2f} "
                f"pos={'Y' if has_pos else 'N'} "
                f"trades={status['trades']} "
                f"pnl={status['pnl_pct']:+.2f}%"
            )
        except Exception as e:
            logger.warning(f"Heartbeat failed: {e}")

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
                ledger_state=(
                    self.position_ledger.to_dict() if self.position_ledger else {}
                ),
                trailing_anchor=self._trailing_anchor,
            )
            self.state_mgr.save(state)
        except Exception as e:
            logger.warning(f"Failed to save state: {e}")
