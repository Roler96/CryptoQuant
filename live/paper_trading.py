"""Paper trading module for CryptoQuant platform.

Simulates live trading execution without real capital at risk.
Provides a realistic trading environment for strategy validation
before deploying to live markets.
"""

import time
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any, Dict, List, Optional

import structlog

from data.manager import OKXClient
from data.models import OHLCVCandle
from logs.audit import audit_trade
from risk.position_sizing import PositionSizer
from strategy.base import Signal, StrategyBase, StrategyContext
from strategy.cta.trend_following import TrendFollowingStrategy


logger = structlog.get_logger(__name__)


@dataclass
class SimulatedTrade:
    """Record of a simulated trade execution.

    Attributes:
        trade_id: Unique trade identifier
        timestamp: Unix timestamp in milliseconds
        pair: Trading pair symbol
        side: Trade side ("buy" or "sell")
        action: Action type ("open_long", "close_long", "open_short", "close_short")
        price: Execution price
        quantity: Position size
        value: Total trade value in quote currency
        balance_before: Balance before trade
        balance_after: Balance after trade
    """
    trade_id: str
    timestamp: int
    pair: str
    side: str
    action: str
    price: Decimal
    quantity: Decimal
    value: Decimal
    balance_before: Decimal
    balance_after: Decimal


@dataclass
class SimulatedPosition:
    """Simulated position state.

    Attributes:
        pair: Trading pair symbol
        side: Position side ("long" or "short")
        size: Position size in base currency
        entry_price: Average entry price
        entry_time: Unix timestamp when position was opened
        unrealized_pnl: Current unrealized P&L
        realized_pnl: Total realized P&L from this position
    """
    pair: str
    side: str
    size: Decimal
    entry_price: Decimal
    entry_time: int
    unrealized_pnl: Decimal = Decimal('0')
    realized_pnl: Decimal = Decimal('0')

    @property
    def is_long(self) -> bool:
        """Check if position is long."""
        return self.side == "long"

    @property
    def is_short(self) -> bool:
        """Check if position is short."""
        return self.side == "short"

    @property
    def is_flat(self) -> bool:
        """Check if position is flat (no position)."""
        return self.size == 0

    def update_unrealized_pnl(self, current_price: Decimal) -> None:
        """Update unrealized P&L based on current price.

        Args:
            current_price: Current market price
        """
        if self.is_flat:
            self.unrealized_pnl = Decimal('0')
            return

        if self.is_long:
            self.unrealized_pnl = (current_price - self.entry_price) * self.size
        else:
            self.unrealized_pnl = (self.entry_price - current_price) * self.size


class PaperTradingRunner:
    """Paper trading runner for simulated live trading.

    Simulates trading execution with real market data but without
    risking actual capital. Tracks positions, balance, and trades
    locally while providing realistic execution simulation.

    Attributes:
        strategy_name: Name of the strategy to run
        pair: Trading pair symbol (e.g., "BTC/USDT")
        timeframe: Candle timeframe (e.g., "1h", "15m")
        initial_balance: Starting balance in quote currency
        sandbox: Whether to use OKX sandbox environment
        running: Whether the trading loop is currently running
    """

    def __init__(
        self,
        strategy_name: str,
        pair: str,
        timeframe: str,
        initial_balance: Decimal,
        sandbox: bool = True,
    ) -> None:
        """Initialize paper trading runner.

        Args:
            strategy_name: Strategy identifier name
            pair: Trading pair symbol (e.g., "BTC/USDT")
            timeframe: Candle timeframe (e.g., "1h", "15m")
            initial_balance: Starting balance in quote currency
            sandbox: Use OKX sandbox environment (default: True)
        """
        self.strategy_name = strategy_name
        self.pair = pair
        self.timeframe = timeframe
        self.initial_balance = initial_balance
        self.sandbox = sandbox
        self.running = False

        self.balance: Decimal = initial_balance
        self.positions: Dict[str, SimulatedPosition] = {}
        self.trades: List[SimulatedTrade] = []
        self.candles: List[OHLCVCandle] = []

        self.client: Optional[OKXClient] = None
        self.strategy: Optional[StrategyBase] = None
        self.position_sizer: PositionSizer = PositionSizer()

        self.logger = structlog.get_logger(__name__).bind(
            strategy=strategy_name,
            pair=pair,
            timeframe=timeframe,
            sandbox=sandbox,
        )

        self.logger.info(
            "PaperTradingRunner initialized",
            initial_balance=str(initial_balance),
        )

    def _initialize_client(self) -> None:
        """Initialize OKX API client."""
        try:
            self.client = OKXClient(sandbox=self.sandbox)
            self.logger.info("OKX client initialized", sandbox=self.sandbox)
        except Exception as e:
            self.logger.error("Failed to initialize OKX client", error=str(e))
            raise

    def _load_strategy(self) -> StrategyBase:
        """Load strategy instance by name.

        Returns:
            StrategyBase instance

        Raises:
            ValueError: If strategy name is not recognized
        """
        strategy_name_lower = self.strategy_name.lower()

        if strategy_name_lower in ("cta", "trend_following", "trend"):
            return TrendFollowingStrategy(name=self.strategy_name)
        else:
            raise ValueError(f"Unknown strategy: {self.strategy_name}")

    def _fetch_ohlcv(self, limit: int = 100) -> List[OHLCVCandle]:
        """Fetch OHLCV data from OKX.

        Args:
            limit: Number of candles to fetch

        Returns:
            List of OHLCVCandle objects
        """
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
                pair=self.pair,
                timeframe=self.timeframe,
            )
            return candles
        except Exception as e:
            self.logger.error("Failed to fetch OHLCV data", error=str(e))
            raise

    def _create_context(self, current_price: Decimal, current_time: int) -> StrategyContext:
        """Create strategy context for signal generation.

        Args:
            current_price: Current market price
            current_time: Current timestamp in milliseconds

        Returns:
            StrategyContext instance
        """
        from strategy.base import Position

        context_positions = {}
        for pair, pos in self.positions.items():
            context_positions[pair] = Position(
                pair=pair,
                side=pos.side,
                size=pos.size,
                entry_price=pos.entry_price,
                entry_time=pos.entry_time,
                unrealized_pnl=pos.unrealized_pnl,
            )

        if "/" in self.pair:
            _, quote = self.pair.split("/")
        else:
            quote = "USDT"

        return StrategyContext(
            pair=self.pair,
            timeframe=self.timeframe,
            current_price=current_price,
            positions=context_positions,
            balances={quote: self.balance},
            candles=self.candles,
            current_time=current_time,
        )

    def _check_risk_limits(self, signal: Signal) -> bool:
        """Check if trade passes risk management checks.

        Args:
            signal: Trading signal to validate

        Returns:
            True if trade is allowed, False otherwise
        """
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

        if signal.is_entry() and self.balance <= 0:
            self.logger.warning("Risk check failed: Insufficient balance")
            return False

        return True

    def simulate_order(
        self,
        action: str,
        price: Decimal,
        quantity: Decimal,
    ) -> SimulatedTrade:
        """Simulate order execution.

        Args:
            action: Action type ("open_long", "close_long", "open_short", "close_short")
            price: Execution price
            quantity: Position size

        Returns:
            SimulatedTrade record

        Raises:
            ValueError: If action is invalid
        """
        if action not in ("open_long", "close_long", "open_short", "close_short"):
            raise ValueError(f"Invalid action: {action}")

        trade_id = f"paper_{uuid.uuid4().hex[:12]}"
        timestamp = int(time.time() * 1000)

        if action in ("open_long", "close_short"):
            side = "buy"
        else:
            side = "sell"

        value = price * quantity
        balance_before = self.balance

        if action in ("open_long", "open_short"):
            if value > self.balance:
                raise ValueError(f"Insufficient balance: {self.balance} < {value}")
            self.balance -= value
        else:
            current_position = self.positions.get(self.pair)
            if current_position:
                if action == "close_long":
                    pnl = (price - current_position.entry_price) * quantity
                else:
                    pnl = (current_position.entry_price - price) * quantity
                self.balance += value + pnl
            else:
                self.balance += value

        balance_after = self.balance

        trade = SimulatedTrade(
            trade_id=trade_id,
            timestamp=timestamp,
            pair=self.pair,
            side=side,
            action=action,
            price=price,
            quantity=quantity,
            value=value,
            balance_before=balance_before,
            balance_after=balance_after,
        )
        self.trades.append(trade)

        self._update_position(action, price, quantity)

        audit_trade(
            trade_id=trade_id,
            strategy=self.strategy_name,
            pair=self.pair,
            side=side,
            size=quantity,
            entry_price=price,
            status="open" if action in ("open_long", "open_short") else "closed",
        )

        self.logger.info(
            "Trade simulated",
            trade_id=trade_id,
            action=action,
            side=side,
            price=str(price),
            quantity=str(quantity),
            value=str(value),
            balance_before=str(balance_before),
            balance_after=str(balance_after),
        )

        return trade

    def _update_position(self, action: str, price: Decimal, quantity: Decimal) -> None:
        """Update position state after trade.

        Args:
            action: Trade action
            price: Execution price
            quantity: Position size
        """
        current_position = self.positions.get(self.pair)

        if action == "open_long":
            if current_position and current_position.is_long:
                total_value = (current_position.size * current_position.entry_price) + (quantity * price)
                total_size = current_position.size + quantity
                new_entry = total_value / total_size
                self.positions[self.pair] = SimulatedPosition(
                    pair=self.pair,
                    side="long",
                    size=total_size,
                    entry_price=new_entry,
                    entry_time=current_position.entry_time,
                    realized_pnl=current_position.realized_pnl,
                )
            else:
                self.positions[self.pair] = SimulatedPosition(
                    pair=self.pair,
                    side="long",
                    size=quantity,
                    entry_price=price,
                    entry_time=int(time.time() * 1000),
                )

        elif action == "open_short":
            if current_position and current_position.is_short:
                total_value = (current_position.size * current_position.entry_price) + (quantity * price)
                total_size = current_position.size + quantity
                new_entry = total_value / total_size
                self.positions[self.pair] = SimulatedPosition(
                    pair=self.pair,
                    side="short",
                    size=total_size,
                    entry_price=new_entry,
                    entry_time=current_position.entry_time,
                    realized_pnl=current_position.realized_pnl,
                )
            else:
                self.positions[self.pair] = SimulatedPosition(
                    pair=self.pair,
                    side="short",
                    size=quantity,
                    entry_price=price,
                    entry_time=int(time.time() * 1000),
                )

        elif action in ("close_long", "close_short"):
            if current_position:
                if action == "close_long":
                    pnl = (price - current_position.entry_price) * quantity
                else:
                    pnl = (current_position.entry_price - price) * quantity

                remaining_size = current_position.size - quantity

                if remaining_size <= 0:
                    current_position.realized_pnl += pnl
                    current_position.size = Decimal('0')
                    self.logger.info(
                        "Position closed",
                        pair=self.pair,
                        side=current_position.side,
                        realized_pnl=str(current_position.realized_pnl),
                    )
                else:
                    current_position.realized_pnl += pnl
                    current_position.size = remaining_size
                    self.logger.info(
                        "Position partially closed",
                        pair=self.pair,
                        side=current_position.side,
                        remaining_size=str(remaining_size),
                        realized_pnl=str(current_position.realized_pnl),
                    )

    def _process_signal(self, signal: Signal) -> Optional[SimulatedTrade]:
        """Process trading signal and execute if valid.

        Args:
            signal: Trading signal from strategy

        Returns:
            SimulatedTrade if executed, None otherwise
        """
        if signal.is_hold():
            return None

        if not self._check_risk_limits(signal):
            return None

        current_price = signal.price
        risk_pct = Decimal('0.95')
        position_value = self.balance * risk_pct
        quantity = position_value / current_price

        result = self.position_sizer.validate_position(
            position_size=quantity,
            portfolio_value=self.balance,
        )
        if not result[0]:
            self.logger.warning(
                "Position validation failed",
                errors=result[1],
            )
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

        try:
            trade = self.simulate_order(action, current_price, quantity)
            return trade
        except Exception as e:
            self.logger.error("Failed to simulate order", error=str(e))
            return None

    def run_iteration(self) -> Optional[SimulatedTrade]:
        """Run a single trading iteration.

        Fetches latest data, generates signal, checks risk,
        and simulates execution if valid.

        Returns:
            SimulatedTrade if a trade was executed, None otherwise
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

        context = self._create_context(current_price, current_time)

        try:
            signal = self.strategy.on_bar(latest_candle, context)
        except Exception as e:
            self.logger.error("Strategy signal generation failed", error=str(e))
            return None

        return self._process_signal(signal)

    def start(self, interval_seconds: int = 60) -> None:
        """Start the trading loop.

        Args:
            interval_seconds: Seconds between iterations (default: 60)
        """
        self.running = True
        self.logger.info(
            "Starting paper trading loop",
            interval_seconds=interval_seconds,
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
        """Stop the trading loop."""
        self.running = False
        self.logger.info(
            "Paper trading stopped",
            total_trades=len(self.trades),
            final_balance=str(self.balance),
        )

        if self.client:
            self.client.close()

    def get_balance(self) -> Decimal:
        """Get current balance.

        Returns:
            Current balance in quote currency
        """
        return self.balance

    def get_positions(self) -> Dict[str, SimulatedPosition]:
        """Get current positions.

        Returns:
            Dictionary of positions by trading pair
        """
        return self.positions.copy()

    def get_trades(self) -> List[SimulatedTrade]:
        """Get trade history.

        Returns:
            List of all simulated trades
        """
        return self.trades.copy()

    def validate_balance(self) -> bool:
        """Validate that balance has not gone negative.

        Returns:
            True if balance is valid (non-negative), False otherwise
        """
        is_valid = self.balance >= 0
        if not is_valid:
            self.logger.error(
                "Balance validation failed",
                balance=str(self.balance),
            )
        return is_valid

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
            "initial_balance": str(self.initial_balance),
            "current_balance": str(self.balance),
            "total_return": str(self.balance - self.initial_balance),
            "total_return_pct": str(
                ((self.balance - self.initial_balance) / self.initial_balance * 100)
                if self.initial_balance > 0 else Decimal('0')
            ),
            "total_trades": total_trades,
            "buy_trades": buy_trades,
            "sell_trades": sell_trades,
            "realized_pnl": str(total_realized_pnl),
            "unrealized_pnl": str(total_unrealized_pnl),
            "open_positions": len([p for p in self.positions.values() if not p.is_flat]),
        }
