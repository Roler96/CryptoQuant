"""Authenticated OKX client for the trade endpoints.

The counterpart to `cq.data.okx.OkxPublicClient`: this one holds credentials and
can place orders, so it lives in `cq.live` and nowhere near the public-data path.
Point it at demo trading with ``demo=True`` (the default), which sets OKX's
``x-simulated-trading`` header through ccxt's sandbox mode — the same code then
talks to the live venue only when explicitly told to.

Order semantics that bit us and are pinned here:

* market **buys** on OKX spot default to interpreting ``amount`` as *quote*
  currency. ``tgtCcy=base_ccy`` forces it to base for both sides, so a buy and a
  sell of the same ``amount`` move the same number of coins;
* ``create_order`` returns before the fill is populated, so every order is read
  back with ``fetch_order`` until it closes — the returned `Fill` carries the
  price and fee that actually happened, not the ones requested.
* OKX's ``conditional`` order silently ignores take-profit when stop-loss is
  supplied too. A two-sided protective exit must therefore be an ``oco`` algo;
  a single stop or target remains ``conditional``.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import ccxt
from loguru import logger

from cq.core.types import Fill, Side
from cq.data.okx import BROWSER_UA, RETRYABLE
from cq.live.config import OkxCredentials
from cq.live.protocols import ProtectiveOrder


class TradeError(RuntimeError):
    """An order could not be placed or did not fill as required."""


def to_symbol(inst_id: str) -> str:
    """OKX native id (``DOGE-USDT``) to ccxt unified symbol (``DOGE/USDT``)."""
    parts = inst_id.split("-")
    if len(parts) != 2:
        raise ValueError(
            f"{inst_id!r} is not a spot instrument id; only spot (BASE-QUOTE) is supported here"
        )
    return f"{parts[0]}/{parts[1]}"


def base_currency(inst_id: str) -> str:
    """The coin a spot instrument is denominated in (``DOGE`` of ``DOGE-USDT``)."""
    return inst_id.split("-")[0]


def quote_currency(inst_id: str) -> str:
    """The settlement currency of a spot instrument (``USDT`` of ``DOGE-USDT``)."""
    return inst_id.split("-")[1]


class OkxTradeClient:
    """ccxt-backed OKX client for authenticated spot trading, with retries.

    Reads market metadata once at construction (``load_markets``) so quantities
    round to the venue's real lot grid rather than a guess.
    """

    def __init__(
        self,
        credentials: OkxCredentials,
        timeout_ms: int = 30_000,
        max_retries: int = 5,
        backoff_base_s: float = 1.0,
        trust_env: bool = True,
        fill_poll_attempts: int = 10,
        fill_poll_interval_s: float = 0.5,
    ):
        self.max_retries = max_retries
        self.backoff_base_s = backoff_base_s
        self.demo = credentials.demo
        self.fill_poll_attempts = fill_poll_attempts
        self.fill_poll_interval_s = fill_poll_interval_s
        self._ex = ccxt.okx(
            {
                "apiKey": credentials.api_key,
                "secret": credentials.secret,
                "password": credentials.passphrase,
                "enableRateLimit": True,
                "timeout": timeout_ms,
                # Force `amount` to base currency on market buys too (see module docstring).
                "options": {"createMarketBuyOrderRequiresPrice": False},
            }
        )
        # Same proxy/UA workaround as the public client: ccxt disables trust_env,
        # which drops HTTPS_PROXY, and OKX 403s the default requests user agent.
        session = self._ex.session
        if session is None:  # pragma: no cover - ccxt always builds one
            raise RuntimeError("ccxt did not create a requests session to configure")
        session.trust_env = trust_env
        self._ex.headers = {"User-Agent": BROWSER_UA}
        # Demo trading before any authenticated call, so no request ever leaves
        # for the live venue by accident.
        self._ex.set_sandbox_mode(credentials.demo)
        self._ex.load_markets()

    @property
    def exchange(self) -> ccxt.okx:
        return self._ex

    def milliseconds(self) -> int:
        return self._ex.milliseconds()

    # ---- retry wrapper ------------------------------------------------

    def _call(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> Any:
        """Invoke an authenticated endpoint, retrying only transient failures.

        Authentication and insufficient-funds errors are not retried: hammering
        them changes nothing and only delays the real message.
        """
        last: Exception | None = None
        for attempt in range(self.max_retries):
            try:
                return fn(*args, **kwargs)
            except RETRYABLE as exc:
                last = exc
                delay = self.backoff_base_s * (2**attempt)
                logger.warning(
                    "OKX trade call failed ({}), retry {}/{} in {:.1f}s",
                    type(exc).__name__,
                    attempt + 1,
                    self.max_retries,
                    delay,
                )
                time.sleep(delay)
        if last is None:  # pragma: no cover - only with max_retries <= 0
            raise RuntimeError(f"no attempt was made: max_retries={self.max_retries}")
        raise last

    # ---- account reads ------------------------------------------------

    def free_balance(self, ccy: str) -> float:
        """Available (non-frozen) balance of `ccy`."""
        balance = self._call(self._ex.fetch_balance)
        free = balance.get("free", {})
        return float(free.get(ccy, 0.0) or 0.0)

    def base_holding(self, inst_id: str) -> float:
        """Free balance of a spot instrument's base coin — its held position.

        Spot has no signed position: the coins are simply owned, so the holding
        is the free balance of the base currency and never negative.
        """
        return self.free_balance(base_currency(inst_id))

    def last_price(self, inst_id: str) -> float:
        """Most recent traded price, for sizing a notional into a quantity."""
        ticker = self._call(self._ex.fetch_ticker, to_symbol(inst_id))
        price = ticker.get("last") or ticker.get("close")
        if not price or price <= 0:
            raise TradeError(f"{inst_id}: no usable last price in ticker")
        return float(price)

    def round_amount(self, inst_id: str, quantity: float) -> float:
        """Snap a quantity to the venue's lot grid, towards zero."""
        rounded = self._ex.amount_to_precision(to_symbol(inst_id), quantity)
        return float(rounded) if rounded is not None else 0.0

    # ---- ordering -----------------------------------------------------

    def market_order(self, inst_id: str, side: Side, quantity: float, reason: str = "") -> Fill:
        """Place a market order for `quantity` base coins and return its fill.

        `quantity` is always base currency (see the module docstring). The order
        is read back until it closes so the returned `Fill` reflects the actual
        average price and fee, converted to quote terms for the accounting.
        """
        if quantity <= 0:
            raise ValueError(f"market order quantity must be positive, got {quantity}")
        symbol = to_symbol(inst_id)
        order = self._call(
            self._ex.create_order,
            symbol,
            "market",
            side.value,
            quantity,
            None,
            {"tgtCcy": "base_ccy"},
        )
        settled = self._await_fill(order["id"], symbol)
        return self._to_fill(inst_id, side, settled, reason)

    def place_protective_order(
        self,
        inst_id: str,
        side: Side,
        quantity: float,
        stop_loss: float | None = None,
        take_profit: float | None = None,
    ) -> str:
        """Place a market-on-trigger protective algo and return its OKX id.

        One level uses OKX's ``conditional`` order. Supplying both uses ``oco``
        so whichever level triggers first cancels the other. Trigger prices and
        size are formatted through the loaded market metadata before the native
        endpoint is called.
        """
        if quantity <= 0:
            raise ValueError(f"protective order quantity must be positive, got {quantity}")
        if stop_loss is None and take_profit is None:
            raise ValueError("protective order requires a stop loss or take profit")

        symbol = to_symbol(inst_id)
        size = self._ex.amount_to_precision(symbol, quantity)
        if size is None or float(size) <= 0:
            raise TradeError(f"{inst_id}: protective quantity {quantity} rounds below one lot")
        request = {
            "instId": inst_id,
            "tdMode": "cash",
            "side": side.value,
            "ordType": (
                "oco" if stop_loss is not None and take_profit is not None else "conditional"
            ),
            "sz": size,
        }
        if stop_loss is not None:
            request.update(
                {
                    "slTriggerPx": self._ex.price_to_precision(symbol, stop_loss),
                    "slOrdPx": "-1",
                    "slTriggerPxType": "last",
                }
            )
        if take_profit is not None:
            request.update(
                {
                    "tpTriggerPx": self._ex.price_to_precision(symbol, take_profit),
                    "tpOrdPx": "-1",
                    "tpTriggerPxType": "last",
                }
            )

        response = self._call(self._ex.private_post_trade_order_algo, request)
        item = self._algo_result(response, "place protective order")
        algo_id = str(item.get("algoId") or "")
        if not algo_id:
            raise TradeError(f"{inst_id}: OKX accepted protective order without an algoId")
        return algo_id

    def cancel_algo_order(self, inst_id: str, algo_id: str) -> None:
        """Cancel one protective algo; an already-final order is success.

        A trigger can fill between reconciliation and cancellation. OKX maps
        "does not exist", "already canceled", and "already completed" to
        ``OrderNotFound`` through ccxt; all three mean there is no resting order
        left to race the replacement.
        """
        if not algo_id:
            raise ValueError("algo_id must not be blank")
        try:
            response = self._call(
                self._ex.private_post_trade_cancel_algos,
                [{"algoId": algo_id, "instId": inst_id}],
            )
        except ccxt.OrderNotFound:
            return
        self._algo_result(response, "cancel protective order")

    def pending_protective_orders(self, inst_id: str) -> list[ProtectiveOrder]:
        """Return every untriggered conditional/OCO algo for one instrument."""
        orders: list[ProtectiveOrder] = []
        for order_type in ("conditional", "oco"):
            response = self._call(
                self._ex.private_get_trade_orders_algo_pending,
                {"ordType": order_type, "instId": inst_id},
            )
            if str(response.get("code", "")) != "0":
                message = response.get("msg") or "unknown OKX error"
                raise TradeError(f"could not list protective orders: {message}")
            for raw in response.get("data") or []:
                if not isinstance(raw, dict):
                    raise TradeError(f"{inst_id}: malformed pending algo {raw!r}")
                if raw.get("instId") != inst_id:
                    continue
                try:
                    side = Side(str(raw.get("side")))
                    quantity = float(raw.get("sz") or 0.0)
                except (TypeError, ValueError) as exc:
                    raise TradeError(f"{inst_id}: malformed pending algo {raw!r}") from exc
                algo_id = str(raw.get("algoId") or "")
                if not algo_id or quantity <= 0:
                    raise TradeError(f"{inst_id}: malformed pending algo {raw!r}")
                orders.append(
                    ProtectiveOrder(
                        algo_id=algo_id,
                        quantity=quantity,
                        stop_loss=self._optional_price(raw.get("slTriggerPx")),
                        take_profit=self._optional_price(raw.get("tpTriggerPx")),
                        side=side,
                    )
                )
        return sorted(orders, key=lambda order: order.algo_id)

    def protective_order_state(self, inst_id: str, algo_id: str) -> str:
        """Return OKX's current/terminal state for one known protective algo."""
        response = self._call(
            self._ex.private_get_trade_order_algo,
            {"algoId": algo_id},
        )
        if str(response.get("code", "")) != "0":
            message = response.get("msg") or "unknown OKX error"
            raise TradeError(f"could not read protective order {algo_id}: {message}")
        data = response.get("data") or []
        raw = data[0] if data and isinstance(data[0], dict) else {}
        if raw.get("instId") != inst_id or not raw.get("state"):
            raise TradeError(f"{inst_id}: malformed algo detail for {algo_id}: {raw!r}")
        return str(raw["state"])

    @staticmethod
    def _optional_price(value: Any) -> float | None:
        """An optional positive price from an OKX string field."""
        if value in (None, ""):
            return None
        try:
            price = float(value)
        except (TypeError, ValueError) as exc:
            raise TradeError(f"invalid protective trigger price {value!r}") from exc
        if price <= 0:
            raise TradeError(f"invalid protective trigger price {value!r}")
        return price

    @staticmethod
    def _algo_result(response: dict, operation: str) -> dict:
        """Return the one per-order result, rejecting partial API failures."""
        code = str(response.get("code", ""))
        data = response.get("data") or []
        item = data[0] if data and isinstance(data[0], dict) else {}
        subcode = str(item.get("sCode", ""))
        if code != "0" or subcode != "0":
            message = item.get("sMsg") or response.get("msg") or "unknown OKX error"
            raise TradeError(f"could not {operation}: {message} (code {subcode or code})")
        return item

    def _await_fill(self, order_id: str, symbol: str) -> dict:
        """Poll one order until it is closed, or give up with what it shows."""
        settled = {}
        for _ in range(self.fill_poll_attempts):
            settled = self._call(self._ex.fetch_order, order_id, symbol)
            if settled.get("status") == "closed" and (settled.get("filled") or 0) > 0:
                return settled
            time.sleep(self.fill_poll_interval_s)
        filled = settled.get("filled") or 0
        if filled <= 0:
            raise TradeError(
                f"order {order_id} on {symbol} did not fill within "
                f"{self.fill_poll_attempts} polls (status {settled.get('status')!r})"
            )
        return settled

    def _to_fill(self, inst_id: str, side: Side, order: dict, reason: str) -> Fill:
        """Turn a settled ccxt order into an engine `Fill`, fees in quote terms."""
        filled = float(order["filled"])
        raw_price = order.get("average") or order.get("price")
        if raw_price is None:
            raise TradeError(f"{inst_id}: settled order carries no fill price")
        price = float(raw_price)
        fee_quote = self._fee_in_quote(inst_id, order, price)
        ts = int(order.get("timestamp") or self.milliseconds())
        return Fill(
            ts=ts,
            inst_id=inst_id,
            side=side,
            quantity=filled,
            price=price,
            fee=fee_quote,
            reason=reason,
        )

    def _fee_in_quote(self, inst_id: str, order: dict, price: float) -> float:
        """Total fee expressed in the quote currency.

        OKX charges a spot fee in whatever currency was received — base on a buy,
        quote on a sell — so a base-denominated fee is converted at the fill
        price to keep equity in one unit.
        """
        base = base_currency(inst_id)
        total = 0.0
        fees = order.get("fees") or ([order["fee"]] if order.get("fee") else [])
        for fee in fees:
            cost = abs(float(fee.get("cost") or 0.0))
            if fee.get("currency") == base:
                total += cost * price
            else:
                total += cost
        return total
