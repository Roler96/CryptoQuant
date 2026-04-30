"""Live trading module for CryptoQuant platform.

Provides real trading execution using OKXClient with integrated risk management,
kill switch, stop loss, and position sizing controls.
"""

import time
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional

import structlog

from data.manager import OKXClient
from data.models import OHLCVCandle
from live.kill_switch import KillSwitch, KillSwitchReason
from live.order_manager import OrderManager, OrderSide
from logs.audit import audit_risk_event
from risk.position_sizing import PositionSizer
from risk.stop_loss import StopLossManager, StopLossResult
from strategy.base import Signal, StrategyBase, StrategyContext
from strategy.cta.trend_following import TrendFollowingStrategy


logger = structlog.get_logger(__name__)


@dataclass
class LiveTrade:
    """Record of a live trade execution.

    Attributes:
        trade_id: Unique trade identifier
        timestamp: Unix timestamp in milliseconds
        pair: Trading pair symbol
        side: Trade side ("buy" or "sell")
        action: Action type ("open_long", "close_long", "open_short", "close_short")
        price: Execution price
        quantity: Position size
        value: Total trade value
        order_id: Associated order ID from OrderManager
        pnl: Realized P&L (for closing trades)
    """
    trade_id: str
    timestamp: int
    pair: str
    side: str
    action: str
    price: Decimal
    quantity: Decimal
    value: Decimal
    order_id: str
    pnl: Decimal = Decimal('0')


@dataclass
class LivePosition:
    """Live position state.

    Attributes:
        pair: Trading pair symbol
        side: Position side ("long" or "short")
        size: Position size
        entry_price: Average entry price
        entry_time: Unix timestamp when position was opened
        unrealized_pnl: Current unrealized P&L
        realized_pnl: Total realized P&L
        stop_loss: Stop loss price
        stop_loss_result: StopLossResult for tracking
    """
    pair: str
    side: str
    size: Decimal
    entry_price: Decimal
    entry_time: int
    unrealized_pnl: Decimal = Decimal('0')
    realized_pnl: Decimal = Decimal('0')
    stop_loss: Optional[Decimal] = None
    stop_loss_result: Optional[StopLossResult] = None

    @property
    def is_long(self) -> bool:
        return self.side == "long"

    @property
    def is_short(self) -> bool:
        return self.side == "short"

    @property
    def is_flat(self) -> bool:
        return self.size == 0

    def update_unrealized_pnl(self, current_price: Decimal) -> None:
        if self.is_flat:
            self.unrealized_pnl = Decimal('0')
            return

        if self.is_long:
            self.unrealized_pnl = (current_price - self.entry_price) * self.size
        else:
            self.unrealized_pnl = (self.entry_price - current_price) * self.size


class LiveTradingRunner:
    """Live trading runner for real execution on OKX exchange.

    Executes trading strategies with real capital, integrating risk management
    controls including kill switch, stop loss, and position sizing.

    Attributes:
        strategy_name: Name of strategy to run
        pair: Trading pair symbol
        timeframe: Candle timeframe
        sandbox: Whether to use OKX sandbox
        require_confirmation: Whether to require manual confirmation for first trade
        running: Whether trading loop is active
    """

    def __init__(
        self,
        strategy_name: str,
        pair: str,
        timeframe: str,
        sandbox: bool = False,
        require_confirmation: bool = True,
        max_drawdown_pct: Decimal = Decimal('10'),
        risk_per_trade_pct: Decimal = Decimal('0.02'),
    ) -> None:
        self.strategy_name = strategy_name
        self.pair = pair
        self.timeframe = timeframe
        self.sandbox = sandbox
        self.require_confirmation = require_confirmation
        self.risk_per_trade_pct = risk_per_trade_pct
        self.running = False
        self.first_trade_confirmed = not require_confirmation

        self.positions: Dict[str, LivePosition] = {}
        self.trades: List[LiveTrade] = []
        self.candles: List[OHLCVCandle] = []

        self.client: Optional[OKXClient] = None
        self.order_manager: Optional[OrderManager] = None
        self.strategy: Optional[StrategyBase] = None
        self.kill_switch: KillSwitch = KillSwitch(max_drawdown_pct=max_drawdown_pct)
        self.stop_loss_manager: StopLossManager = StopLossManager()
        self.position_sizer: PositionSizer = PositionSizer()

        self.logger = structlog.get_logger(__name__).bind(
            strategy=strategy_name,
            pair=pair,
            timeframe=timeframe,
            sandbox=sandbox,
        )

        self.logger.info(
            "LiveTradingRunner initialized",
            require_confirmation=require_confirmation,
            max_drawdown_pct=str(max_drawdown_pct),
            risk_per_trade_pct=str(risk_per_trade_pct),
        )

    def _initialize_client(self) -> None:
        try:
            self.client = OKXClient(sandbox=self.sandbox)
            self.order_manager = OrderManager(client=self.client)
            self.logger.info("OKX client initialized", sandbox=self.sandbox)
        except Exception as e:
            self.logger.error("Failed to initialize OKX client", error=str(e))
            raise

    def _load_strategy(self) -> StrategyBase:
        strategy_name_lower = self.strategy_name.lower()

        if strategy_name_lower in ("cta", "trend_following", "trend"):
            return TrendFollowingStrategy(name=self.strategy_name)
        else:
            raise ValueError(f"Unknown strategy: {self.strategy_name}")

    def _fetch_ohlcv(self, limit: int = 100) -> List[OHLCVCandle]:
        if self.client is None:
            raise RuntimeError("Client not initialized")

        try:
            candles = self.client.fetch_ohlcv(
                symbol=self.pair,
                timeframe=self.timeframe,
                limit=limit,
            )
            self.logger.debug(
                "Fetched OHLCV data",
                count=len(candles),
            )
            return candles
        except Exception as e:
            self.logger.error("Failed to fetch OHLCV data", error=str(e))
            self.kill_switch.trigger_api_error(str(e))
            raise

    def _fetch_balance(self) -> Decimal:
        if self.client is None:
            raise RuntimeError("Client not initialized")

        try:
            account_balance = self.client.fetch_balance()

            if "/" in self.pair:
                quote = self.pair.split("/")[1]
            else:
                quote = "USDT"

            balance = account_balance.balances.get(quote)
            if balance:
                return balance.free
            return Decimal('0')
        except Exception as e:
            self.logger.error("Failed to fetch balance", error=str(e))
            return Decimal('0')

    def _create_context(self, current_price: Decimal, current_time: int) -> StrategyContext:
        from strategy.base import Position as StrategyPosition

        context_positions = {}
        for pair, pos in self.positions.items():
            context_positions[pair] = StrategyPosition(
                pair=pair,
                side=pos.side,
                size=pos.size,
                entry_price=pos.entry_price,
                entry_time=pos.entry_time,
                unrealized_pnl=pos.unrealized_pnl,
            )

        if "/" in self.pair:
            quote = self.pair.split("/")[1]
        else:
            quote = "USDT"

        balance = self._fetch_balance()

        return StrategyContext(
            pair=self.pair,
            timeframe=self.timeframe,
            current_price=current_price,
            positions=context_positions,
            balances={quote: balance},
            candles=self.candles,
            current_time=current_time,
        )

    def _confirm_first_trade(self) -> bool:
        if self.first_trade_confirmed:
            return True

        self.logger.warning("FIRST TRADE REQUIRES MANUAL CONFIRMATION")
        self.logger.warning(f"Strategy: {self.strategy_name}")
        self.logger.warning(f"Pair: {self.pair}")
        self.logger.warning("Waiting for confirmation...")

        try:
            response = input(
                f"\n*** FIRST TRADE CONFIRMATION ***\n"
                f"Strategy: {self.strategy_name}\n"
                f"Pair: {self.pair}\n"
                f"Sandbox: {self.sandbox}\n\n"
                f"Type 'YES' to confirm first trade execution: "
            ).strip().upper()

            if response == "YES":
                self.first_trade_confirmed = True
                self.logger.info("First trade confirmed by user")
                audit_risk_event(
                    event_type="first_trade_confirmed",
                    severity="info",
                    message="User confirmed first trade execution",
                    metadata={
                        "strategy": self.strategy_name,
                        "pair": self.pair,
                        "sandbox": self.sandbox,
                    },
                )
                return True
            else:
                self.logger.warning("First trade NOT confirmed - trade will be skipped")
                return False
        except EOFError:
            self.logger.warning("Non-interactive mode - skipping first trade")
            return False

    def execute_order(
        self,
        action: str,
        price: Decimal,
        quantity: Decimal,
        stop_loss_price: Optional[Decimal] = None,
    ) -> Optional[LiveTrade]:
        """Execute a live order.

        Args:
            action: Action type ("open_long", "close_long", "open_short", "close_short")
            price: Execution price
            quantity: Position size
            stop_loss_price: Optional stop loss price

        Returns:
            LiveTrade if successful, None otherwise
        """
        if self.order_manager is None:
            self.logger.error("Order manager not initialized")
            return None

        if self.kill_switch.is_safe_mode():
            self.logger.warning("Kill switch active - order blocked")
            return None

        if action not in ("open_long", "close_long", "open_short", "close_short"):
            self.logger.error(f"Invalid action: {action}")
            return None

        is_entry = action in ("open_long", "open_short")

        if is_entry and not self.first_trade_confirmed and self.require_confirmation:
            if not self._confirm_first_trade():
                return None

        side = OrderSide.BUY if action in ("open_long", "close_short") else OrderSide.SELL

        try:
            self.logger.info(
                "Executing order",
                action=action,
                side=side.name,
                price=str(price),
                quantity=str(quantity),
            )

            result = self.order_manager.place_market_order(
                pair=self.pair,
                side=side,
                amount=quantity,
                metadata={
                    "strategy": self.strategy_name,
                    "action": action,
                    "stop_loss": str(stop_loss_price) if stop_loss_price else None,
                }
            )

            if not result.success or result.order is None:
                self.logger.error(
                    "Order execution failed",
                    error=result.error_message,
                )
                return None

            order = result.order

            trade = LiveTrade(
                trade_id=order.order_id,
                timestamp=order.created_at,
                pair=self.pair,
                side="buy" if side == OrderSide.BUY else "sell",
                action=action,
                price=order.average or price,
                quantity=order.filled,
                value=order.cost,
                order_id=order.order_id,
            )

            self.trades.append(trade)

            self._update_position(action, trade.price, trade.quantity, stop_loss_price)

            self.logger.info(
                "Order executed successfully",
                trade_id=trade.trade_id,
                order_id=order.order_id,
                filled=str(order.filled),
                cost=str(order.cost),
            )

            return trade

        except Exception as e:
            self.logger.error("Order execution error", error=str(e))
            return None

    def _update_position(
        self,
        action: str,
        price: Decimal,
        quantity: Decimal,
        stop_loss_price: Optional[Decimal] = None,
    ) -> None:
        current_position = self.positions.get(self.pair)

        if action == "open_long":
            if current_position and current_position.is_long:
                total_value = (current_position.size * current_position.entry_price) + (quantity * price)
                total_size = current_position.size + quantity
                new_entry = total_value / total_size

                current_position.size = total_size
                current_position.entry_price = new_entry
                if stop_loss_price:
                    current_position.stop_loss = stop_loss_price
            else:
                self.positions[self.pair] = LivePosition(
                    pair=self.pair,
                    side="long",
                    size=quantity,
                    entry_price=price,
                    entry_time=int(time.time() * 1000),
                    stop_loss=stop_loss_price,
                )

                if stop_loss_price:
                    self.stop_loss_manager.initialize_trailing_state(
                        position_id=self.pair,
                        entry_price=price,
                        trail_pct=Decimal('0.05'),
                        side="long"
                    )

        elif action == "open_short":
            if current_position and current_position.is_short:
                total_value = (current_position.size * current_position.entry_price) + (quantity * price)
                total_size = current_position.size + quantity
                new_entry = total_value / total_size

                current_position.size = total_size
                current_position.entry_price = new_entry
                if stop_loss_price:
                    current_position.stop_loss = stop_loss_price
            else:
                self.positions[self.pair] = LivePosition(
                    pair=self.pair,
                    side="short",
                    size=quantity,
                    entry_price=price,
                    entry_time=int(time.time() * 1000),
                    stop_loss=stop_loss_price,
                )

                if stop_loss_price:
                    self.stop_loss_manager.initialize_trailing_state(
                        position_id=self.pair,
                        entry_price=price,
                        trail_pct=Decimal('0.05'),
                        side="short"
                    )

        elif action in ("close_long", "close_short"):
            if current_position:
                if action == "close_long":
                    pnl = (price - current_position.entry_price) * quantity
                else:
                    pnl = (current_position.entry_price - price) * quantity

                current_position.realized_pnl += pnl
                remaining_size = current_position.size - quantity

                if remaining_size <= 0:
                    current_position.size = Decimal('0')
                    self.stop_loss_manager.remove_trailing_state(self.pair)
                    self.logger.info(
                        "Position closed",
                        pair=self.pair,
                        realized_pnl=str(current_position.realized_pnl),
                    )
                else:
                    current_position.size = remaining_size
                    self.logger.info(
                        "Position partially closed",
                        pair=self.pair,
                        remaining_size=str(remaining_size),
                        realized_pnl=str(current_position.realized_pnl),
                    )

    def _check_stop_loss(self, current_price: Decimal) -> bool:
        """Check and execute stop loss if triggered.

        Returns:
            True if stop loss was triggered and executed
        """
        position = self.positions.get(self.pair)
        if not position or position.is_flat:
            return False

        if position.stop_loss:
            if position.is_long and current_price <= position.stop_loss:
                self.logger.warning(
                    "Stop loss triggered for long position",
                    stop_price=str(position.stop_loss),
                    current_price=str(current_price),
                )
                self.execute_order(
                    action="close_long",
                    price=current_price,
                    quantity=position.size,
                )
                return True

            if position.is_short and current_price >= position.stop_loss:
                self.logger.warning(
                    "Stop loss triggered for short position",
                    stop_price=str(position.stop_loss),
                    current_price=str(current_price),
                )
                self.execute_order(
                    action="close_short",
                    price=current_price,
                    quantity=position.size,
                )
                return True

        trailing_state = self.stop_loss_manager.get_trailing_state(self.pair)
        if trailing_state:
            self.stop_loss_manager.update_trailing_state(
                position_id=self.pair,
                current_price=current_price,
                trail_pct=Decimal('0.05')
            )

            result = self.stop_loss_manager.trailing_stop(
                current_price=current_price,
                highest_price=trailing_state.highest_price,
                trail_pct=Decimal('0.05'),
                side=position.side
            )

            if result.is_triggered:
                self.logger.warning(
                    "Trailing stop triggered",
                    stop_price=str(result.stop_price),
                    current_price=str(current_price),
                )
                action = "close_long" if position.is_long else "close_short"
                self.execute_order(
                    action=action,
                    price=current_price,
                    quantity=position.size,
                )
                return True

        return False

    def _check_risk_limits(self, signal: Signal) -> bool:
        """Check if trade passes risk management checks.

        Args:
            signal: Trading signal to validate

        Returns:
            True if trade is allowed, False otherwise
        """
        if self.kill_switch.is_safe_mode():
            self.logger.warning("Risk check failed: Kill switch is active")
            return False

        current_position = self.positions.get(self.pair)

        if signal.is_entry() and current_position and not current_position.is_flat:
            self.logger.warning(
                "Risk check failed: Already in position",
                signal=signal.signal_type.name,
                current_side=current_position.side,
            )
            return False

        if signal.is_exit() and (not current_position or current_position.is_flat):
            self.logger.warning(
                "Risk check failed: No position to exit",
                signal=signal.signal_type.name,
            )
            return False

        balance = self._fetch_balance()
        if signal.is_entry() and balance <= 0:
            self.logger.warning("Risk check failed: Insufficient balance")
            return False

        total_pnl = sum(pos.realized_pnl + pos.unrealized_pnl for pos in self.positions.values())
        if balance > 0:
            drawdown_pct = abs(total_pnl) / balance * 100
            if self.kill_switch.trigger_max_loss(drawdown_pct=drawdown_pct):
                self.logger.critical(
                    "Risk check failed: Maximum drawdown exceeded",
                    drawdown_pct=str(drawdown_pct),
                )
                return False

        return True

    def _calculate_position_size(self, price: Decimal, signal: Signal) -> Decimal:
        """Calculate position size using position sizer.

        Args:
            price: Current price
            signal: Trading signal

        Returns:
            Position size in base currency
        """
        balance = self._fetch_balance()

        result = self.position_sizer.fixed_pct(
            portfolio_value=balance,
            risk_pct=self.risk_per_trade_pct,
            price=price,
        )

        if not result.is_valid:
            self.logger.warning(
                "Position sizing failed",
                errors=result.validation_errors,
            )
            return Decimal('0')

        self.logger.debug(
            "Position size calculated",
            size=str(result.size),
            risk_amount=str(result.risk_amount),
        )

        return result.size

    def _calculate_stop_loss(self, entry_price: Decimal, side: str) -> Decimal:
        """Calculate stop loss price.

        Args:
            entry_price: Entry price
            side: Position side ("long" or "short")

        Returns:
            Stop loss price
        """
        stop_pct = Decimal('0.05')
        return self.stop_loss_manager.percentage_stop(entry_price, stop_pct, side)

    def _process_signal(self, signal: Signal) -> Optional[LiveTrade]:
        """Process trading signal and execute if valid.

        Args:
            signal: Trading signal from strategy

        Returns:
            LiveTrade if executed, None otherwise
        """
        if signal.is_hold():
            return None

        if not self._check_risk_limits(signal):
            return None

        current_price = signal.price

        if self._check_stop_loss(current_price):
            return None

        action_map = {
            "LONG": "open_long",
            "SHORT": "open_short",
            "CLOSE_LONG": "close_long",
            "CLOSE_SHORT": "close_short",
        }
        action = action_map.get(signal.signal_type.name)

        if action is None:
            self.logger.warning(f"Unknown signal type: {signal.signal_type}")
            return None

        if signal.is_entry():
            quantity = self._calculate_position_size(current_price, signal)
            if quantity <= 0:
                return None

            side = "long" if action == "open_long" else "short"
            stop_loss_price = self._calculate_stop_loss(current_price, side)

            return self.execute_order(action, current_price, quantity, stop_loss_price)
        else:
            position = self.positions.get(self.pair)
            if position:
                return self.execute_order(action, current_price, position.size)

        return None

    def run_iteration(self) -> Optional[LiveTrade]:
        """Run a single trading iteration.

        Returns:
            LiveTrade if a trade was executed, None otherwise
        """
        if self.client is None:
            self._initialize_client()

        if self.strategy is None:
            self.strategy = self._load_strategy()
            self.strategy.initialize()

        try:
            new_candles = self._fetch_ohlcv(limit=100)
            if new_candles:
                self.candles = new_candles
        except Exception as e:
            self.logger.error("Failed to fetch OHLCV", error=str(e))
            return None

        if not self.candles:
            self.logger.warning("No candle data available")
            return None

        latest_candle = self.candles[-1]
        current_price = latest_candle.close_price
        current_time = latest_candle.timestamp

        if self.pair in self.positions:
            self.positions[self.pair].update_unrealized_pnl(current_price)

        self._check_stop_loss(current_price)

        if self.kill_switch.is_safe_mode():
            self.logger.debug("Skipping signal generation - kill switch active")
            return None

        context = self._create_context(current_price, current_time)

        try:
            signal = self.strategy.on_bar(latest_candle, context)
        except Exception as e:
            self.logger.error("Strategy signal generation failed", error=str(e))
            return None

        return self._process_signal(signal)

    def start(self, interval_seconds: int = 60) -> None:
        """Start the live trading loop.

        Args:
            interval_seconds: Seconds between iterations
        """
        self.running = True
        self.logger.info(
            "Starting live trading loop",
            interval_seconds=interval_seconds,
            sandbox=self.sandbox,
            require_confirmation=self.require_confirmation,
        )

        try:
            while self.running:
                self.run_iteration()
                time.sleep(interval_seconds)
        except KeyboardInterrupt:
            self.logger.info("Trading loop interrupted by user")
        finally:
            self.stop()

    def stop(self) -> None:
        """Stop the trading loop and cleanup."""
        self.running = False
        self.logger.info(
            "Live trading stopped",
            total_trades=len(self.trades),
        )

        if self.order_manager:
            self.order_manager.cancel_all_orders(self.pair)

        if self.client:
            self.client.close()

    def trigger_kill_switch(
        self,
        reason: KillSwitchReason = KillSwitchReason.MANUAL,
        confirmed: bool = False,
    ) -> bool:
        """Manually trigger the kill switch.

        Args:
            reason: Reason for triggering
            confirmed: Confirmation flag

        Returns:
            True if kill switch was triggered
        """
        if reason == KillSwitchReason.MANUAL:
            return self.kill_switch.trigger_manual(confirmed=confirmed)
        return False

    def reset_kill_switch(self, confirmed: bool = False) -> bool:
        """Reset the kill switch to resume trading.

        Args:
            confirmed: Confirmation flag

        Returns:
            True if reset was successful
        """
        return self.kill_switch.reset_safe_mode(confirmed=confirmed)

    def get_kill_switch_status(self) -> Dict[str, Any]:
        """Get current kill switch status.

        Returns:
            Dictionary with kill switch status
        """
        return self.kill_switch.get_status()

    def get_positions(self) -> Dict[str, LivePosition]:
        """Get current positions.

        Returns:
            Dictionary of positions by trading pair
        """
        return self.positions.copy()

    def get_trades(self) -> List[LiveTrade]:
        """Get trade history.

        Returns:
            List of all executed trades
        """
        return self.trades.copy()

    def get_summary(self) -> Dict[str, Any]:
        """Get trading summary statistics.

        Returns:
            Dictionary with trading statistics
        """
        total_trades = len(self.trades)
        buy_trades = sum(1 for t in self.trades if t.side == "buy")
        sell_trades = sum(1 for t in self.trades if t.side == "sell")

        total_realized_pnl = sum(
            pos.realized_pnl for pos in self.positions.values()
        )
        total_unrealized_pnl = sum(
            pos.unrealized_pnl for pos in self.positions.values()
        )

        return {
            "strategy": self.strategy_name,
            "pair": self.pair,
            "timeframe": self.timeframe,
            "sandbox": self.sandbox,
            "total_trades": total_trades,
            "buy_trades": buy_trades,
            "sell_trades": sell_trades,
            "realized_pnl": str(total_realized_pnl),
            "unrealized_pnl": str(total_unrealized_pnl),
            "open_positions": len([p for p in self.positions.values() if not p.is_flat]),
            "kill_switch_active": self.kill_switch.is_safe_mode(),
        }
