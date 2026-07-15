"""Exchange broker abstraction — ccxt wrapper with retry logic."""
import time
import uuid
from collections.abc import Callable
from typing import NoReturn, TypeVar

import ccxt
from loguru import logger

from cryptoquant.exceptions import (
    ExecutionError,
    InsufficientFundsError,
    OrderRejectedError,
)
from cryptoquant.execution.broker_abc import BrokerABC
from cryptoquant.execution.order import Order, OrderStatus, Position
from cryptoquant.position.ledger import ManagedPositionLedger
from cryptoquant.utils import get_proxy_from_env, retry_on_network

T = TypeVar("T")


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
        position_ledger: ManagedPositionLedger | None = None,
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

        # Strategy-owned position tracking (see ManagedPositionLedger).
        # Spot _get_spot_position used to return ALL free balance as "our position".
        # Now we track only what this strategy actually bought/sold.
        self.position_ledger = position_ledger or ManagedPositionLedger()

        if testnet:
            self.exchange.set_sandbox_mode(True)
            logger.info(f"Broker initialized: {exchange} TESTNET ({account_type})")
        else:
            logger.warning(f"Broker initialized: {exchange} LIVE ({account_type})")

        # Configure proxy - ccxt sets trust_env=False, so we must set proxies manually
        proxy_url = proxy or get_proxy_from_env()
        if proxy_url:
            self.exchange.session.proxies = {
                "http": proxy_url,
                "https": proxy_url,
            }
            logger.debug(f"Broker using proxy: {proxy_url}")

    @property
    def can_short(self) -> bool:
        return self.account_type == "swap"

    def _handle_ccxt_error(self, e: Exception, context: str) -> NoReturn:
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

    def _call_with_retry(
        self,
        call: Callable[[], T],
        context: str,
        max_retries: int = 3,
        base_delay: float = 1.0,
    ) -> T:
        """Run a read-only or idempotent ccxt call, retrying network failures.

        The retry must wrap the ccxt call itself: retry_on_network only
        recognizes ccxt's own network types, so _handle_ccxt_error's
        conversion to ExecutionError has to happen out here, once the
        retries are spent. Permanent failures (AuthenticationError,
        InvalidOrder) are not network types and so convert on the first
        attempt without burning the backoff budget.

        Order placement is NOT idempotent — see _place_order.
        """

        @retry_on_network(max_retries=max_retries, base_delay=base_delay)
        def attempt() -> T:
            return call()

        try:
            return attempt()
        except Exception as e:
            self._handle_ccxt_error(e, context)

    def _new_client_order_id(self) -> str:
        """Mint an idempotency key. Alphanumeric and 22 chars to satisfy
        the tightest exchange limit we target (OKX clOrdId, 32)."""
        return f"cq{uuid.uuid4().hex[:20]}"

    @retry_on_network(max_retries=3, base_delay=1.0)
    def _find_order_by_client_id(
        self, symbol: str, client_order_id: str
    ) -> Order | None:
        """Return the order carrying our key, or None if the exchange has none.

        Raises rather than returning None when the exchange cannot be
        reached: "could not check" must never be read as "never placed",
        or the caller would re-send an order that is already live.
        """
        try:
            raw = self.exchange.fetch_order(
                client_order_id, symbol, {"clientOrderId": client_order_id}
            )
            if raw:
                return Order.from_ccxt(raw, exchange=self.exchange_name)
        except ccxt.OrderNotFound:
            return None
        except (ccxt.NetworkError, ConnectionError, TimeoutError):
            raise
        except Exception:
            pass  # exchange can't look up by key — fall back to listing orders

        scanned = False
        for fetch in (self.exchange.fetch_open_orders, self.exchange.fetch_closed_orders):
            try:
                candidates = fetch(symbol)
            except (ccxt.NetworkError, ConnectionError, TimeoutError):
                raise
            except Exception:
                continue
            scanned = True
            for candidate in candidates:
                if candidate.get("clientOrderId") == client_order_id:
                    return Order.from_ccxt(candidate, exchange=self.exchange_name)

        if not scanned:
            raise ExecutionError(
                f"Cannot confirm whether order {client_order_id} on {symbol} "
                f"was placed: {self.exchange_name} supports no lookup by "
                f"clientOrderId. Refusing to re-send."
            )
        return None

    def _place_order(
        self,
        symbol: str,
        context: str,
        place: Callable[[str], dict],
        max_retries: int = 3,
        base_delay: float = 1.0,
    ) -> Order:
        """Place an order, retrying network failures under an idempotency key.

        A lost response is ambiguous — the order may already be live on the
        exchange. Before every re-send we look the key up and adopt the
        order if it landed, so a timeout can never open a second position.
        """
        client_order_id = self._new_client_order_id()
        sent = False

        @retry_on_network(max_retries=max_retries, base_delay=base_delay)
        def attempt() -> Order:
            nonlocal sent
            if sent:
                existing = self._find_order_by_client_id(symbol, client_order_id)
                if existing is not None:
                    logger.warning(
                        f"[{context}] Response was lost but order "
                        f"{client_order_id} did land — adopting it instead "
                        f"of re-sending."
                    )
                    return existing
            sent = True
            raw = place(client_order_id)
            return Order.from_ccxt(raw, exchange=self.exchange_name)

        try:
            return attempt()
        except Exception as e:
            self._handle_ccxt_error(e, context)

    def get_balance(self, quote: str = "USDT") -> float:
        balance = self._call_with_retry(self.exchange.fetch_balance, "get_balance")
        free = balance.get(quote, {}).get("free", 0)
        if free is None:
            free = 0.0
        return float(free)

    def get_ticker(self, symbol: str) -> dict:
        ticker = self._call_with_retry(
            lambda: self.exchange.fetch_ticker(symbol), f"get_ticker({symbol})"
        )
        return {
            "bid": ticker.get("bid", 0),
            "ask": ticker.get("ask", 0),
            "last": ticker.get("last", 0),
            "timestamp": ticker.get("timestamp", 0),
        }

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
            contract_size = float(market.get("contractSize", 1) or 1)
            notional = precise_amount * contract_size * price
            if notional < float(min_cost):
                raise OrderRejectedError(
                    f"Order notional {notional:.8f} below exchange min cost {min_cost}"
                )

        return precise_amount

    def quote_to_order_amount(
        self, symbol: str, quote_amount: float, price: float
    ) -> float:
        """Convert USDT notional to base units or derivative contracts."""
        if quote_amount <= 0 or price <= 0:
            return 0.0
        if self.account_type != "swap":
            return quote_amount / price
        market = self._get_market(symbol)
        contract_size = float(market.get("contractSize", 1) or 1)
        return quote_amount / (price * contract_size)

    def order_amount_to_quote(
        self, symbol: str, amount: float, price: float
    ) -> float:
        """Convert spot base units or derivative contracts to quote notional."""
        if amount <= 0 or price <= 0:
            return 0.0
        if self.account_type != "swap":
            return amount * price
        market = self._get_market(symbol)
        contract_size = float(market.get("contractSize", 1) or 1)
        return amount * contract_size * price

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

    def market_buy(self, symbol: str, amount: float) -> Order:
        logger.info(f"MARKET BUY {symbol}: amount={amount}")
        return self._place_order(
            symbol,
            f"market_buy({symbol})",
            lambda coid: self.exchange.create_market_buy_order(
                symbol, amount, {"clientOrderId": coid}
            ),
        )

    def market_sell(self, symbol: str, amount: float) -> Order:
        logger.info(f"MARKET SELL {symbol}: amount={amount}")
        return self._place_order(
            symbol,
            f"market_sell({symbol})",
            lambda coid: self.exchange.create_market_sell_order(
                symbol, amount, {"clientOrderId": coid}
            ),
        )

    def limit_buy(self, symbol: str, amount: float, price: float) -> Order:
        logger.info(f"LIMIT BUY {symbol}: amount={amount}, price={price}")
        return self._place_order(
            symbol,
            f"limit_buy({symbol})",
            lambda coid: self.exchange.create_limit_buy_order(
                symbol, amount, price, {"clientOrderId": coid}
            ),
        )

    def limit_sell(self, symbol: str, amount: float, price: float) -> Order:
        logger.info(f"LIMIT SELL {symbol}: amount={amount}, price={price}")
        return self._place_order(
            symbol,
            f"limit_sell({symbol})",
            lambda coid: self.exchange.create_limit_sell_order(
                symbol, amount, price, {"clientOrderId": coid}
            ),
        )

    def cancel_order(self, order_id: str, symbol: str) -> bool:
        self._call_with_retry(
            lambda: self.exchange.cancel_order(order_id, symbol),
            f"cancel_order({order_id})",
            max_retries=2,
            base_delay=0.5,
        )
        return True

    def cancel_all_orders(self, symbol: str) -> int:
        orders = self._call_with_retry(
            lambda: self.exchange.fetch_open_orders(symbol),
            f"cancel_all_orders({symbol})",
            max_retries=2,
            base_delay=0.5,
        )
        count = 0
        for o in orders:
            try:
                self.cancel_order(o["id"], symbol)
                count += 1
            except Exception:
                pass
        return count

    def get_open_orders(self, symbol: str) -> list[Order]:
        raw_orders = self._call_with_retry(
            lambda: self.exchange.fetch_open_orders(symbol),
            f"get_open_orders({symbol})",
        )
        return [Order.from_ccxt(o, exchange=self.exchange_name) for o in raw_orders]

    def get_position(self, symbol: str) -> Position | None:
        if self.account_type == "spot":
            return self._get_spot_position(symbol)
        return self._get_swap_position(symbol)

    def _get_spot_position(self, symbol: str) -> Position | None:
        """Return strategy-owned spot position only.

        P0 fix: Previously returned ALL free balance as "our position",
        which could sell coins bought manually, by other strategies, or
        received via transfer/airdrop. Now only reports positions the
        strategy actually bought through this Broker instance.

        On restart, LiveEngine restores position_ledger from persisted state
        before this is queried.
        """
        snapshot = self.position_ledger.get_position(symbol)
        if snapshot is None:
            return None

        try:
            current_price = float(self.get_ticker(symbol)["last"])
        except Exception:
            current_price = snapshot.avg_entry_price

        return Position(
            symbol=symbol,
            side=snapshot.side,
            amount=snapshot.amount,
            entry_price=snapshot.avg_entry_price,
            current_price=current_price,
            unrealized_pnl=0.0,
            unrealized_pnl_abs=0.0,
            # Preserve the strategy's actual entry time. Replacing this with
            # "now" on every query prevents max_hold_hours from ever expiring.
            timestamp=snapshot.timestamp,
        )

    def _get_swap_position(self, symbol: str) -> Position | None:
        """Return the open swap position, or None if genuinely flat.

        Failures propagate: swallowing them here would report an
        unreachable exchange as "no position" and invite a double entry.
        """
        positions = self._call_with_retry(
            lambda: self.exchange.fetch_positions([symbol]),
            f"get_position({symbol})",
        )
        for pos in positions:
            amount = float(pos.get("contracts", 0) or 0)
            if amount > 0:
                return Position.from_ccxt(pos)
        return None

    def wait_for_fill(self, order_id: str, symbol: str, timeout: int = 30) -> Order:
        """Poll until the order fills. fetch_order retries network blips
        internally, so retrying out here would only restart the clock."""
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

    def fetch_order(self, order_id: str, symbol: str) -> Order:
        raw = self._call_with_retry(
            lambda: self.exchange.fetch_order(order_id, symbol),
            f"fetch_order({order_id})",
        )
        return Order.from_ccxt(raw, exchange=self.exchange_name)

    def reconnect(self) -> None:
        logger.warning(f"Reconnecting to {self.exchange_name}...")
        try:
            self.exchange.load_markets(reload=True)
            logger.info(f"Reconnected to {self.exchange_name}")
        except Exception as e:
            logger.error(f"Reconnect failed: {e}")
            raise ExecutionError(f"Reconnect failed: {e}") from e
