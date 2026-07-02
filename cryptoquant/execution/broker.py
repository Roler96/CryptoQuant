"""Exchange broker abstraction — ccxt wrapper with retry logic."""
import functools
import os
import random
import time

import ccxt
from loguru import logger

from cryptoquant.exceptions import (
    ExecutionError,
    InsufficientFundsError,
    OrderRejectedError,
)
from cryptoquant.execution.broker_abc import BrokerABC
from cryptoquant.execution.order import Order, OrderStatus, Position


def _get_proxy_from_env() -> str | None:
    """Get proxy URL from environment variables."""
    return (
        os.environ.get("HTTPS_PROXY")
        or os.environ.get("https_proxy")
        or os.environ.get("HTTP_PROXY")
        or os.environ.get("http_proxy")
    )


def retry_on_network(
    max_retries: int = 3,
    base_delay: float = 1.0,
    max_delay: float = 30.0,
    jitter: float = 0.1,
):
    """Network error retry decorator (exponential backoff + jitter)."""

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_error: BaseException | None = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except (ccxt.NetworkError, ConnectionError, TimeoutError) as e:
                    last_error = e
                    if attempt < max_retries:
                        delay = min(base_delay * (2**attempt), max_delay)
                        delay *= 1 + random.uniform(-jitter, jitter)
                        logger.warning(
                            f"Retry {attempt + 1}/{max_retries} for "
                            f"{func.__name__} in {delay:.1f}s: {e}"
                        )
                        time.sleep(delay)
                    else:
                        logger.error(
                            f"All {max_retries} retries exhausted for "
                            f"{func.__name__}: {e}"
                        )
            if last_error is not None:
                raise last_error
            raise RuntimeError("retry_on_network: unreachable — no error captured")

        return wrapper

    return decorator


class Broker(BrokerABC):
    """Exchange abstraction layer.

    Wraps ccxt with unified interface, error handling, and retry logic.
    """

    def __init__(
        self,
        exchange: str = "okx",
        api_key: str = "",
        secret: str = "",
        password: str = "",
        testnet: bool = True,
        account_type: str = "spot",
        proxy: str | None = None,
    ):
        exchange_class = getattr(ccxt, exchange)
        self.exchange = exchange_class(
            {
                "apiKey": api_key,
                "secret": secret,
                "password": password,
                "enableRateLimit": True,
                "options": {"defaultType": account_type},
            }
        )
        self.exchange_name = exchange
        self.testnet = testnet
        self.account_type = account_type

        if testnet:
            self.exchange.set_sandbox_mode(True)
            logger.info(f"Broker initialized: {exchange} TESTNET ({account_type})")
        else:
            logger.warning(f"Broker initialized: {exchange} LIVE ({account_type})")

        # Configure proxy - ccxt sets trust_env=False, so we must set proxies manually
        proxy_url = proxy or _get_proxy_from_env()
        if proxy_url:
            self.exchange.session.proxies = {
                "http": proxy_url,
                "https": proxy_url,
            }
            logger.debug(f"Broker using proxy: {proxy_url}")

    @property
    def can_short(self) -> bool:
        return self.account_type == "swap"

    def _handle_ccxt_error(self, e: Exception, context: str) -> None:
        if isinstance(e, ccxt.NetworkError):
            logger.error(f"[{context}] Network error: {e}")
            raise ExecutionError(f"Exchange network error: {e}") from e
        elif isinstance(e, ccxt.AuthenticationError):
            logger.error(f"[{context}] Auth error — check API keys")
            raise ExecutionError("Exchange authentication failed") from e
        elif isinstance(e, ccxt.InsufficientFunds):
            logger.error(f"[{context}] Insufficient funds")
            raise InsufficientFundsError("Insufficient funds") from e
        elif isinstance(e, ccxt.InvalidOrder):
            logger.error(f"[{context}] Invalid order: {e}")
            raise OrderRejectedError(f"Invalid order: {e}") from e
        else:
            logger.error(f"[{context}] Unknown error: {e}")
            raise

    @retry_on_network(max_retries=3, base_delay=1.0)
    def get_balance(self, quote: str = "USDT") -> float:
        try:
            balance = self.exchange.fetch_balance()
            free = balance.get(quote, {}).get("free", 0)
            if free is None:
                free = 0.0
            return float(free)
        except Exception as e:
            self._handle_ccxt_error(e, "get_balance")
            raise

    @retry_on_network(max_retries=3, base_delay=1.0)
    def get_ticker(self, symbol: str) -> dict:
        try:
            ticker = self.exchange.fetch_ticker(symbol)
            return {
                "bid": ticker.get("bid", 0),
                "ask": ticker.get("ask", 0),
                "last": ticker.get("last", 0),
                "timestamp": ticker.get("timestamp", 0),
            }
        except Exception as e:
            self._handle_ccxt_error(e, f"get_ticker({symbol})")
            raise

    def normalize_order_amount(
        self, symbol: str, amount: float, price: float | None = None
    ) -> float:
        """Apply exchange precision and minimum amount/cost checks."""
        if amount <= 0:
            raise OrderRejectedError(f"Invalid order amount: {amount}")

        try:
            precise_amount = float(self.exchange.amount_to_precision(symbol, amount))
        except Exception:
            precise_amount = amount

        if precise_amount <= 0:
            raise OrderRejectedError(
                f"Order amount {amount} rounded to zero by exchange precision"
            )

        market = self._get_market(symbol)
        limits = market.get("limits", {}) if market else {}
        amount_limits = limits.get("amount", {}) or {}
        cost_limits = limits.get("cost", {}) or {}

        min_amount = amount_limits.get("min")
        if min_amount is not None and precise_amount < float(min_amount):
            raise OrderRejectedError(
                f"Order amount {precise_amount} below exchange min {min_amount}"
            )

        min_cost = cost_limits.get("min")
        if min_cost is not None and price is not None:
            notional = precise_amount * price
            if notional < float(min_cost):
                raise OrderRejectedError(
                    f"Order notional {notional:.8f} below exchange min cost {min_cost}"
                )

        return precise_amount

    def _get_market(self, symbol: str) -> dict:
        try:
            market = self.exchange.market(symbol)
            if market:
                return market
        except Exception:
            pass

        try:
            self.exchange.load_markets()
            market = self.exchange.market(symbol)
            return market or {}
        except Exception:
            logger.warning(f"Could not load market metadata for {symbol}")
            return {}

    @retry_on_network(max_retries=3, base_delay=1.0)
    def market_buy(self, symbol: str, amount: float) -> Order:
        logger.info(f"MARKET BUY {symbol}: amount={amount}")
        try:
            raw = self.exchange.create_market_buy_order(symbol, amount)
            return Order.from_ccxt(raw, exchange=self.exchange_name)
        except Exception as e:
            self._handle_ccxt_error(e, f"market_buy({symbol})")
            raise

    @retry_on_network(max_retries=3, base_delay=1.0)
    def market_sell(self, symbol: str, amount: float) -> Order:
        logger.info(f"MARKET SELL {symbol}: amount={amount}")
        try:
            raw = self.exchange.create_market_sell_order(symbol, amount)
            return Order.from_ccxt(raw, exchange=self.exchange_name)
        except Exception as e:
            self._handle_ccxt_error(e, f"market_sell({symbol})")
            raise

    @retry_on_network(max_retries=3, base_delay=1.0)
    def limit_buy(self, symbol: str, amount: float, price: float) -> Order:
        logger.info(f"LIMIT BUY {symbol}: amount={amount}, price={price}")
        try:
            raw = self.exchange.create_limit_buy_order(symbol, amount, price)
            return Order.from_ccxt(raw, exchange=self.exchange_name)
        except Exception as e:
            self._handle_ccxt_error(e, f"limit_buy({symbol})")
            raise

    @retry_on_network(max_retries=3, base_delay=1.0)
    def limit_sell(self, symbol: str, amount: float, price: float) -> Order:
        logger.info(f"LIMIT SELL {symbol}: amount={amount}, price={price}")
        try:
            raw = self.exchange.create_limit_sell_order(symbol, amount, price)
            return Order.from_ccxt(raw, exchange=self.exchange_name)
        except Exception as e:
            self._handle_ccxt_error(e, f"limit_sell({symbol})")
            raise

    @retry_on_network(max_retries=2, base_delay=0.5)
    def cancel_order(self, order_id: str, symbol: str) -> bool:
        try:
            self.exchange.cancel_order(order_id, symbol)
            return True
        except Exception as e:
            self._handle_ccxt_error(e, f"cancel_order({order_id})")
            return False

    @retry_on_network(max_retries=2, base_delay=0.5)
    def cancel_all_orders(self, symbol: str) -> int:
        try:
            orders = self.exchange.fetch_open_orders(symbol)
            count = 0
            for o in orders:
                try:
                    self.exchange.cancel_order(o["id"], symbol)
                    count += 1
                except Exception:
                    pass
            return count
        except Exception as e:
            self._handle_ccxt_error(e, f"cancel_all_orders({symbol})")
            return 0

    @retry_on_network(max_retries=3, base_delay=1.0)
    def get_open_orders(self, symbol: str) -> list[Order]:
        try:
            raw_orders = self.exchange.fetch_open_orders(symbol)
            return [Order.from_ccxt(o, exchange=self.exchange_name) for o in raw_orders]
        except Exception as e:
            self._handle_ccxt_error(e, f"get_open_orders({symbol})")
            return []

    @retry_on_network(max_retries=3, base_delay=1.0)
    def get_position(self, symbol: str) -> Position | None:
        try:
            if self.account_type == "spot":
                return self._get_spot_position(symbol)
            else:
                return self._get_swap_position(symbol)
        except Exception as e:
            self._handle_ccxt_error(e, f"get_position({symbol})")
            return None

    def _get_spot_position(self, symbol: str) -> Position | None:
        base = symbol.split("/")[0]
        balance = self.exchange.fetch_balance()
        free = float(balance.get(base, {}).get("free", 0) or 0)

        if free <= 0:
            return None

        ticker = self.exchange.fetch_ticker(symbol)
        current_price = float(ticker.get("last", 0))

        return Position(
            symbol=symbol,
            side="long",
            amount=free,
            entry_price=0.0,
            current_price=current_price,
            unrealized_pnl=0.0,
            unrealized_pnl_abs=0.0,
            timestamp=int(ticker.get("timestamp", 0) or 0),
        )

    def _get_swap_position(self, symbol: str) -> Position | None:
        try:
            positions = self.exchange.fetch_positions([symbol])
            for pos in positions:
                amount = float(pos.get("contracts", 0) or 0)
                if amount > 0:
                    return Position.from_ccxt(pos)
        except Exception:
            pass
        return None

    @retry_on_network(max_retries=3, base_delay=1.0)
    def wait_for_fill(self, order_id: str, symbol: str, timeout: int = 30) -> Order:
        start = time.time()
        while time.time() - start < timeout:
            order = self.fetch_order(order_id, symbol)
            if order.is_filled:
                return order
            if order.status in (
                OrderStatus.CANCELED,
                OrderStatus.REJECTED,
                OrderStatus.EXPIRED,
            ):
                raise OrderRejectedError(f"Order {order_id} {order.status.value}")
            time.sleep(1)
        raise ExecutionError(f"Order {order_id} not filled within {timeout}s")

    @retry_on_network(max_retries=3, base_delay=1.0)
    def fetch_order(self, order_id: str, symbol: str) -> Order:
        try:
            raw = self.exchange.fetch_order(order_id, symbol)
            return Order.from_ccxt(raw, exchange=self.exchange_name)
        except Exception as e:
            self._handle_ccxt_error(e, f"fetch_order({order_id})")
            raise

    def reconnect(self) -> None:
        logger.warning(f"Reconnecting to {self.exchange_name}...")
        try:
            self.exchange.load_markets(reload=True)
            logger.info(f"Reconnected to {self.exchange_name}")
        except Exception as e:
            logger.error(f"Reconnect failed: {e}")
            raise ExecutionError(f"Reconnect failed: {e}") from e
