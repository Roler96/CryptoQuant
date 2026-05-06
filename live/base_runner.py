"""Base trading runner for CryptoQuant platform.

Provides shared functionality between LiveTradingRunner and PaperTradingRunner,
including strategy loading, data fetching, context creation, and position management.
"""

import time
from abc import ABC, abstractmethod
from decimal import Decimal
from typing import Any, Dict, List, Optional

import structlog

from data.manager import OKXClient
from data.models import OHLCVCandle
from risk.position_sizing import PositionSizer
from strategy.base import Signal, StrategyBase, StrategyContext
from strategy.cta.trend_following import TrendFollowingStrategy


logger = structlog.get_logger(__name__)


class BaseTradingRunner(ABC):
    """Abstract base class for trading runners.

    Provides common functionality for both live and paper trading:
    - Strategy loading
    - Data fetching
    - Context creation
    - Quote currency extraction
    - Balance fetching

    Subclasses must implement:
    - _execute_order: Order execution logic
    - _update_position: Position tracking
    - _check_stop_loss: Stop loss handling
    - _check_risk_limits: Risk validation
    """

    def __init__(
        self,
        strategy_name: str,
        pair: str,
        timeframe: str,
        sandbox: bool = True,
        require_confirmation: bool = True,
    ) -> None:
        """Initialize the base trading runner.

        Args:
            strategy_name: Name of strategy to run
            pair: Trading pair symbol
            timeframe: Candle timeframe
            sandbox: Whether to use OKX sandbox
            require_confirmation: Whether to require manual confirmation for first trade
        """
        self.strategy_name = strategy_name
        self.pair = pair
        self.timeframe = timeframe
        self.sandbox = sandbox
        self.require_confirmation = require_confirmation
        self.first_trade_confirmed = not require_confirmation

        self.candles: List[OHLCVCandle] = []
        self.position_sizer: PositionSizer = PositionSizer()

        self.client: Optional[OKXClient] = None
        self.strategy: Optional[StrategyBase] = None

        self.running = False

        self.logger = structlog.get_logger(__name__).bind(
            strategy=strategy_name,
            pair=pair,
            timeframe=timeframe,
            sandbox=sandbox,
        )

        self.logger.info(
            "BaseTradingRunner initialized",
            require_confirmation=require_confirmation,
        )

    def _get_quote_currency(self) -> str:
        """Extract quote currency from trading pair.

        Returns:
            Quote currency (e.g., "USDT")
        """
        if "/" in self.pair:
            return self.pair.split("/")[1]
        return "USDT"

    def _initialize_client(self) -> None:
        """Initialize OKX client."""
        try:
            self.client = OKXClient(sandbox=self.sandbox)
            self.logger.info("OKX client initialized", sandbox=self.sandbox)
        except Exception as e:
            self.logger.error("Failed to initialize OKX client", error=str(e))
            raise

    def _load_strategy(self) -> StrategyBase:
        """Load strategy by name.

        Returns:
            Strategy instance

        Raises:
            ValueError: If strategy name is not recognized
        """
        strategy_name_lower = self.strategy_name.lower()

        if strategy_name_lower in ("cta", "trend_following", "trend"):
            return TrendFollowingStrategy(name=self.strategy_name)
        else:
            raise ValueError(f"Unknown strategy: {self.strategy_name}")

    def _fetch_ohlcv(self, limit: int = 100) -> List[OHLCVCandle]:
        """Fetch OHLCV data from exchange.

        Args:
            limit: Number of candles to fetch

        Returns:
            List of OHLCV candles
        """
        if self.client is None:
            raise RuntimeError("Client not initialized")

        try:
            candles = self.client.fetch_ohlcv(
                symbol=self.pair,
                timeframe=self.timeframe,
                limit=limit,
            )
            self.logger.debug("Fetched OHLCV data", count=len(candles))
            return candles
        except Exception as e:
            self.logger.error("Failed to fetch OHLCV data", error=str(e))
            raise

    def _fetch_balance(self) -> Decimal:
        """Fetch available balance for quote currency.

        Returns:
            Available balance
        """
        if self.client is None:
            raise RuntimeError("Client not initialized")

        try:
            account_balance = self.client.fetch_balance()
            quote = self._get_quote_currency()

            balance = account_balance.balances.get(quote)
            if balance:
                return balance.free
            return Decimal('0')
        except Exception as e:
            self.logger.error("Failed to fetch balance", error=str(e))
            return Decimal('0')

    def _create_context(self, current_price: Decimal, current_time: int) -> StrategyContext:
        """Create strategy context for signal generation.

        Args:
            current_price: Current market price
            current_time: Current timestamp

        Returns:
            StrategyContext instance
        """
        from strategy.base import Position as StrategyPosition

        quote = self._get_quote_currency()
        balance = self._fetch_balance()

        return StrategyContext(
            pair=self.pair,
            timeframe=self.timeframe,
            current_price=current_price,
            positions=self._get_strategy_positions(),
            balances={quote: balance},
            candles=self.candles,
            current_time=current_time,
        )

    @abstractmethod
    def _get_strategy_positions(self) -> Dict[str, Any]:
        """Get positions formatted for StrategyContext.

        Returns:
            Dictionary of positions by pair
        """
        pass

    @abstractmethod
    def _confirm_first_trade(self) -> bool:
        """Confirm first trade execution.

        Returns:
            True if confirmed
        """
        pass

    @abstractmethod
    def _execute_order(self, action: str, price: Decimal, quantity: Decimal) -> bool:
        """Execute an order.

        Args:
            action: Action type
            price: Execution price
            quantity: Position size

        Returns:
            True if successful
        """
        pass

    @abstractmethod
    def _update_position(self, action: str, price: Decimal, quantity: Decimal) -> None:
        """Update position state after trade.

        Args:
            action: Action type
            price: Execution price
            quantity: Position size
        """
        pass

    @abstractmethod
    def _check_stop_loss(self, current_price: Decimal) -> bool:
        """Check and execute stop loss if triggered.

        Args:
            current_price: Current market price

        Returns:
            True if stop loss was triggered
        """
        pass

    @abstractmethod
    def _check_risk_limits(self, signal: Signal) -> bool:
        """Check if trade passes risk management checks.

        Args:
            signal: Trading signal

        Returns:
            True if allowed
        """
        pass

    @abstractmethod
    def _calculate_position_size(self, price: Decimal, signal: Signal) -> Decimal:
        """Calculate position size.

        Args:
            price: Current price
            signal: Trading signal

        Returns:
            Position size
        """
        pass

    @abstractmethod
    def _calculate_stop_loss(self, entry_price: Decimal, side: str) -> Decimal:
        """Calculate stop loss price.

        Args:
            entry_price: Entry price
            side: Position side

        Returns:
            Stop loss price
        """
        pass

    def _process_signal(self, signal: Signal) -> bool:
        """Process trading signal and execute if valid.

        Args:
            signal: Trading signal from strategy

        Returns:
            True if trade was executed
        """
        if signal.is_hold():
            return False

        if not self._check_risk_limits(signal):
            return False

        current_price = signal.price

        if self._check_stop_loss(current_price):
            return False

        action_map = {
            "LONG": "open_long",
            "SHORT": "open_short",
            "CLOSE_LONG": "close_long",
            "CLOSE_SHORT": "close_short",
        }
        action = action_map.get(signal.signal_type.name)

        if action is None:
            self.logger.warning(f"Unknown signal type: {signal.signal_type}")
            return False

        if signal.is_entry():
            quantity = self._calculate_position_size(current_price, signal)
            if quantity <= 0:
                return False

            return self._execute_order(action, current_price, quantity)
        else:
            return self._execute_order(action, current_price, Decimal('0'))

    def run_iteration(self) -> bool:
        """Run a single trading iteration.

        Returns:
            True if a trade was executed
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
            return False

        if not self.candles:
            self.logger.warning("No candle data available")
            return False

        latest_candle = self.candles[-1]
        current_price = latest_candle.close_price
        current_time = latest_candle.timestamp

        self._update_unrealized_pnl(current_price)
        self._check_stop_loss(current_price)

        context = self._create_context(current_price, current_time)

        try:
            signal = self.strategy.on_bar(latest_candle, context)
        except Exception as e:
            self.logger.error("Strategy signal generation failed", error=str(e))
            return False

        return self._process_signal(signal)

    @abstractmethod
    def _update_unrealized_pnl(self, current_price: Decimal) -> None:
        """Update unrealized P&L for open positions.

        Args:
            current_price: Current market price
        """
        pass

    def start(self, interval_seconds: int = 60) -> None:
        """Start the trading loop.

        Args:
            interval_seconds: Seconds between iterations
        """
        self.running = True
        self.logger.info(
            "Starting trading loop",
            interval_seconds=interval_seconds,
            sandbox=self.sandbox,
        )

        try:
            while self.running:
                self.run_iteration()
                time.sleep(interval_seconds)
        except KeyboardInterrupt:
            self.logger.info("Trading loop interrupted by user")
        finally:
            self.stop()

    @abstractmethod
    def stop(self) -> None:
        """Stop the trading loop and cleanup."""
        pass

    @abstractmethod
    def get_summary(self) -> Dict[str, Any]:
        """Get trading summary statistics.

        Returns:
            Dictionary with trading statistics
        """
        pass
