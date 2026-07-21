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
* create requests are never blindly retried. With a deterministic client id,
  a transient failure is resolved by polling the corresponding read endpoint;
  if no order becomes visible, the result stays explicitly unknown.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, cast

import ccxt
from loguru import logger

from cq.core.types import Fill, Side
from cq.data.okx import BROWSER_UA, RETRYABLE
from cq.live.config import OkxCredentials
from cq.live.protocols import (
    AccountEvent,
    AccountEventKind,
    CollateralBalance,
    MarginMode,
    ProtectiveOrder,
    SwapPosition,
)


class TradeError(RuntimeError):
    """An order could not be placed or did not fill as required."""


def to_symbol(inst_id: str) -> str:
    """OKX native spot/swap id to its ccxt unified symbol."""
    parts = inst_id.split("-")
    if len(parts) == 2 and all(parts):
        return f"{parts[0]}/{parts[1]}"
    if len(parts) == 3 and parts[2] == "SWAP" and all(parts[:2]):
        return f"{parts[0]}/{parts[1]}:{parts[1]}"
    raise ValueError(
        f"{inst_id!r} is not a supported BASE-QUOTE spot or BASE-QUOTE-SWAP id"
    )


def is_swap(inst_id: str) -> bool:
    """Whether an OKX-native id names a perpetual swap."""
    parts = inst_id.split("-")
    return len(parts) == 3 and parts[2] == "SWAP"


def base_currency(inst_id: str) -> str:
    """The base coin (``DOGE`` of spot or ``DOGE-USDT-SWAP``)."""
    to_symbol(inst_id)
    return inst_id.split("-")[0]


def quote_currency(inst_id: str) -> str:
    """The quote/settlement currency (``USDT`` in supported markets)."""
    to_symbol(inst_id)
    return inst_id.split("-")[1]


class OkxTradeClient:
    """ccxt-backed OKX client for authenticated spot/swap trading.

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
        self._swap_settings: dict[str, tuple[float, MarginMode]] = {}
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

    def _contract_size(self, inst_id: str) -> float:
        """Base units in one venue order unit; one for spot."""
        if not is_swap(inst_id):
            return 1.0
        market = self._ex.market(to_symbol(inst_id))
        if not market.get("contract") or not market.get("swap") or not market.get("linear"):
            raise TradeError(f"{inst_id}: only linear perpetual contracts are supported")
        if market.get("settle") != quote_currency(inst_id):
            raise TradeError(f"{inst_id}: swap is not settled in its quote currency")
        try:
            contract_size = float(market["contractSize"])
        except (KeyError, TypeError, ValueError) as exc:
            raise TradeError(f"{inst_id}: market has no usable contract size") from exc
        if contract_size <= 0:
            raise TradeError(f"{inst_id}: market has no usable contract size")
        return contract_size

    def _order_params(self, inst_id: str, protective: bool = False) -> dict[str, Any]:
        """Explicit trade mode for spot or a previously configured swap."""
        if not is_swap(inst_id):
            return {"tdMode": "cash"} if protective else {"tgtCcy": "base_ccy"}
        settings = self._swap_settings.get(inst_id)
        if settings is None:
            raise TradeError(
                f"{inst_id}: configure_swap() must verify mode and leverage before ordering"
            )
        params: dict[str, Any] = {"tdMode": settings[1], "posSide": "net"}
        if protective:
            params["reduceOnly"] = True
        return params

    @staticmethod
    def _response_data(response: Any, operation: str) -> list[dict[str, Any]]:
        if not isinstance(response, dict) or str(response.get("code", "")) != "0":
            message = response.get("msg") if isinstance(response, dict) else repr(response)
            raise TradeError(f"could not {operation}: {message or 'unknown OKX error'}")
        data = response.get("data") or []
        if not isinstance(data, list) or any(not isinstance(item, dict) for item in data):
            raise TradeError(f"could not {operation}: malformed OKX response {response!r}")
        return data

    @classmethod
    def _one_data(cls, response: Any, operation: str) -> dict[str, Any]:
        data = cls._response_data(response, operation)
        if len(data) != 1:
            raise TradeError(f"could not {operation}: expected one OKX result, got {len(data)}")
        return data[0]

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
        if is_swap(inst_id):
            raise ValueError("base_holding is only valid for spot instruments")
        return self.free_balance(base_currency(inst_id))

    def configure_swap(
        self,
        inst_id: str,
        leverage: float,
        margin_mode: MarginMode = "cross",
    ) -> None:
        """Enforce net position mode and explicit leverage for one linear swap."""
        if not is_swap(inst_id):
            raise ValueError(f"{inst_id!r} is not a swap instrument")
        if margin_mode not in ("cross", "isolated"):
            raise ValueError(f"unsupported swap margin mode {margin_mode!r}")
        if not 1 <= leverage <= 125:
            raise ValueError(f"swap leverage must be in [1, 125], got {leverage}")
        self._contract_size(inst_id)

        config = self._one_data(
            self._call(self._ex.private_get_account_config),
            "read account configuration",
        )
        account_level = str(config.get("acctLv") or "")
        if account_level == "1":
            raise TradeError(
                "OKX account is in Spot mode; select Futures, Multi-currency, "
                "or another supported derivatives mode before trading swaps"
            )
        if account_level == "4":
            raise TradeError(
                "OKX Portfolio margin does not expose the fixed leverage "
                "required by this runner; use Futures or Multi-currency margin"
            )
        if account_level not in ("2", "3"):
            raise TradeError(f"unknown OKX account mode {account_level!r}")

        if config.get("posMode") != "net_mode":
            changed = self._one_data(
                self._call(
                    self._ex.private_post_account_set_position_mode,
                    {"posMode": "net_mode"},
                ),
                "set net position mode",
            )
            if changed.get("posMode") != "net_mode":
                raise TradeError("OKX did not confirm net position mode")

        request: dict[str, Any] = {
            "instId": inst_id,
            "lever": format(leverage, "g"),
            "mgnMode": margin_mode,
        }
        if margin_mode == "isolated":
            request["posSide"] = "net"
        configured = self._one_data(
            self._call(self._ex.private_post_account_set_leverage, request),
            "set swap leverage",
        )
        confirmed_raw = configured.get("lever")
        if confirmed_raw is None:
            raise TradeError(f"OKX returned malformed leverage result {configured!r}")
        try:
            confirmed_leverage = float(confirmed_raw)
        except (TypeError, ValueError) as exc:
            raise TradeError(f"OKX returned malformed leverage result {configured!r}") from exc
        if (
            configured.get("instId") != inst_id
            or configured.get("mgnMode") != margin_mode
            or abs(confirmed_leverage - leverage) > 1e-12
        ):
            raise TradeError(f"OKX did not confirm requested swap configuration: {configured!r}")
        self._swap_settings[inst_id] = (leverage, margin_mode)

    def swap_position(self, inst_id: str) -> SwapPosition:
        """Read the net swap position and normalize contracts to base units."""
        contract_size = self._contract_size(inst_id)
        response = self._call(
            self._ex.private_get_account_positions,
            {"instType": "SWAP", "instId": inst_id},
        )
        rows = self._response_data(response, "read swap position")
        matching = [row for row in rows if row.get("instId") == inst_id]
        if any(row.get("posSide") != "net" for row in matching):
            raise TradeError(f"{inst_id}: OKX returned a non-net position")
        try:
            active = [row for row in matching if float(row.get("pos") or 0.0) != 0.0]
        except (TypeError, ValueError) as exc:
            raise TradeError(f"{inst_id}: malformed position response {matching!r}") from exc
        if len(active) > 1:
            raise TradeError(f"{inst_id}: multiple net positions returned by OKX")
        if not active:
            return SwapPosition(0.0, None, None, None, None, None)

        raw = active[0]
        try:
            contracts = float(raw["pos"])
            raw_margin_mode = str(raw["mgnMode"])
        except (KeyError, TypeError, ValueError) as exc:
            raise TradeError(f"{inst_id}: malformed position response {raw!r}") from exc
        if raw_margin_mode not in ("cross", "isolated"):
            raise TradeError(f"{inst_id}: unknown margin mode {raw_margin_mode!r}")
        margin_mode = cast(MarginMode, raw_margin_mode)
        settings = self._swap_settings.get(inst_id)
        if settings is not None and margin_mode != settings[1]:
            raise TradeError(
                f"{inst_id}: position margin mode {margin_mode!r} does not match "
                f"configured {settings[1]!r}"
            )
        average_entry = self._optional_positive(raw.get("avgPx"))
        mark_price = self._optional_positive(raw.get("markPx"))
        position_leverage = self._optional_positive(raw.get("lever"))
        if average_entry is None or mark_price is None:
            raise TradeError(f"{inst_id}: active position has no usable entry/mark price")
        if settings is not None and (
            position_leverage is None
            or abs(position_leverage - settings[0]) > 1e-12
        ):
            raise TradeError(
                f"{inst_id}: position leverage {position_leverage!r} does not match "
                f"configured {settings[0]!r}"
            )
        return SwapPosition(
            quantity=contracts * contract_size,
            average_entry=average_entry,
            mark_price=mark_price,
            liquidation_price=self._optional_positive(raw.get("liqPx")),
            leverage=position_leverage,
            margin_mode=margin_mode,
        )

    def collateral_balance(self, ccy: str) -> CollateralBalance:
        """Settlement cash, equity and available balance from OKX account data."""
        response = self._call(self._ex.private_get_account_balance, {"ccy": ccy})
        account = self._one_data(response, "read collateral balance")
        details = account.get("details") or []
        raw = next(
            (item for item in details if isinstance(item, dict) and item.get("ccy") == ccy),
            None,
        )
        if raw is None:
            raise TradeError(f"OKX returned no {ccy} collateral balance")
        cash_raw = raw.get("cashBal")
        equity_raw = raw.get("eq")
        if cash_raw in (None, "") or equity_raw in (None, ""):
            raise TradeError(f"malformed {ccy} collateral balance {raw!r}")
        try:
            return CollateralBalance(
                cash=float(cash_raw),
                equity=float(equity_raw),
                available=float(raw.get("availBal") or 0.0),
            )
        except (TypeError, ValueError) as exc:
            raise TradeError(f"malformed {ccy} collateral balance {raw!r}") from exc

    def swap_account_events(
        self,
        inst_id: str,
        begin_ms: int,
        end_ms: int,
    ) -> list[AccountEvent]:
        """Funding, liquidation and ADL bills in one closed interval."""
        if begin_ms < 0 or end_ms < begin_ms:
            raise ValueError(f"invalid account-event interval [{begin_ms}, {end_ms}]")
        contract_size = self._contract_size(inst_id)
        response = self._call(
            self._ex.private_get_account_bills,
            {
                "instType": "SWAP",
                "instId": inst_id,
                "type": "5,8,9",
                "begin": str(begin_ms),
                "end": str(end_ms),
                "limit": "100",
            },
        )
        rows = self._response_data(response, "read swap account events")
        if len(rows) >= 100:
            raise TradeError(
                f"{inst_id}: account-event page reached 100 rows; refusing to skip pagination"
            )
        kinds = {"5": "liquidation", "8": "funding", "9": "adl"}
        events: list[AccountEvent] = []
        for raw in rows:
            event_type = str(raw.get("type") or "")
            if raw.get("instId") != inst_id or event_type not in kinds:
                continue
            try:
                bill_id = str(raw["billId"])
                ts = int(raw["ts"])
                amount = float(raw.get("balChg") or raw.get("posBalChg") or 0.0)
            except (KeyError, TypeError, ValueError) as exc:
                raise TradeError(f"{inst_id}: malformed account bill {raw!r}") from exc
            quantity = self._optional_event_value(raw.get("sz"))
            events.append(
                AccountEvent(
                    bill_id=bill_id,
                    ts=ts,
                    kind=cast(AccountEventKind, kinds[event_type]),
                    amount=amount,
                    currency=str(raw.get("ccy") or ""),
                    price=self._optional_event_value(raw.get("px")),
                    quantity=None if quantity is None else quantity * contract_size,
                    subtype=str(raw.get("subType") or ""),
                )
            )
        return sorted(events, key=lambda event: (event.ts, event.bill_id))

    def last_price(self, inst_id: str) -> float:
        """Most recent traded price, for sizing a notional into a quantity."""
        ticker = self._call(self._ex.fetch_ticker, to_symbol(inst_id))
        price = ticker.get("last") or ticker.get("close")
        if not price or price <= 0:
            raise TradeError(f"{inst_id}: no usable last price in ticker")
        return float(price)

    def round_amount(self, inst_id: str, quantity: float) -> float:
        """Snap a quantity to the venue's lot grid, towards zero."""
        contract_size = self._contract_size(inst_id)
        rounded = self._ex.amount_to_precision(
            to_symbol(inst_id), quantity / contract_size
        )
        return float(rounded) * contract_size if rounded is not None else 0.0

    # ---- ordering -----------------------------------------------------

    def market_order(
        self,
        inst_id: str,
        side: Side,
        quantity: float,
        reason: str = "",
        client_order_id: str | None = None,
    ) -> Fill:
        """Place a market order for `quantity` base coins and return its fill.

        `quantity` is always base currency (see the module docstring). The order
        is read back until it closes so the returned `Fill` reflects the actual
        average price and fee, converted to quote terms for the accounting.
        """
        if quantity <= 0:
            raise ValueError(f"market order quantity must be positive, got {quantity}")
        self._validate_client_order_id(client_order_id)
        symbol = to_symbol(inst_id)
        contract_size = self._contract_size(inst_id)
        venue_quantity = quantity / contract_size
        params = self._order_params(inst_id)
        if client_order_id is not None:
            params["clOrdId"] = client_order_id
        try:
            order = self._ex.create_order(
                symbol,
                "market",
                side.value,
                venue_quantity,
                None,
                params,
            )
            order_id = str(order["id"])
        except RETRYABLE as exc:
            order_id = self._recover_order_id(inst_id, client_order_id)
            if order_id is None:
                raise TradeError(
                    f"{inst_id}: market order result is unknown after {type(exc).__name__}; "
                    "the create request was not resent"
                ) from exc
        except ccxt.InvalidOrder:
            order_id = self._recover_order_id(inst_id, client_order_id)
            if order_id is None:
                raise
        settled = self._await_fill(order_id, symbol)
        return self._to_fill(inst_id, side, settled, reason, contract_size)

    def place_protective_order(
        self,
        inst_id: str,
        side: Side,
        quantity: float,
        stop_loss: float | None = None,
        take_profit: float | None = None,
        client_order_id: str | None = None,
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
        self._validate_client_order_id(client_order_id)

        symbol = to_symbol(inst_id)
        contract_size = self._contract_size(inst_id)
        size = self._ex.amount_to_precision(symbol, quantity / contract_size)
        if size is None or float(size) <= 0:
            raise TradeError(f"{inst_id}: protective quantity {quantity} rounds below one lot")
        request: dict[str, Any] = {
            "instId": inst_id,
            "side": side.value,
            "ordType": (
                "oco" if stop_loss is not None and take_profit is not None else "conditional"
            ),
            "sz": size,
        }
        request.update(self._order_params(inst_id, protective=True))
        if client_order_id is not None:
            request["algoClOrdId"] = client_order_id
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

        try:
            response = self._ex.private_post_trade_order_algo(request)
            item = self._algo_result(response, "place protective order")
            algo_id = str(item.get("algoId") or "")
        except RETRYABLE as exc:
            algo_id = self._recover_algo_id(inst_id, client_order_id)
            if algo_id is None:
                raise TradeError(
                    f"{inst_id}: protective order result is unknown after "
                    f"{type(exc).__name__}; the create request was not resent"
                ) from exc
        except ccxt.InvalidOrder:
            algo_id = self._recover_algo_id(inst_id, client_order_id)
            if algo_id is None:
                raise
        if not algo_id:
            raise TradeError(f"{inst_id}: OKX accepted protective order without an algoId")
        return algo_id

    def _recover_order_id(self, inst_id: str, client_order_id: str | None) -> str | None:
        """Poll by clOrdId after an ambiguous create, without resending it."""
        if client_order_id is None:
            return None
        request = {"instId": inst_id, "clOrdId": client_order_id}
        return self._poll_created_id(
            self._ex.private_get_trade_order,
            request,
            "ordId",
            "clOrdId",
            client_order_id,
            inst_id=inst_id,
        )

    def _recover_algo_id(self, inst_id: str, client_order_id: str | None) -> str | None:
        """Poll by algoClOrdId after an ambiguous create, without resending it."""
        if client_order_id is None:
            return None
        request = {"algoClOrdId": client_order_id}
        return self._poll_created_id(
            self._ex.private_get_trade_order_algo,
            request,
            "algoId",
            "algoClOrdId",
            client_order_id,
            inst_id=inst_id,
            required_state="live",
        )

    def _poll_created_id(
        self,
        endpoint: Callable[..., Any],
        request: dict,
        id_field: str,
        client_id_field: str,
        client_order_id: str,
        inst_id: str | None = None,
        required_state: str | None = None,
    ) -> str | None:
        """Resolve one uncertain create through its read endpoint only."""
        for attempt in range(self.max_retries):
            try:
                response = endpoint(request)
            except (ccxt.OrderNotFound, *RETRYABLE):
                response = None
            if response is not None and str(response.get("code", "")) == "0":
                data = response.get("data") or []
                item = data[0] if data and isinstance(data[0], dict) else {}
                same_instrument = inst_id is None or item.get("instId") == inst_id
                usable_state = required_state is None or item.get("state") == required_state
                if (
                    item.get(client_id_field) == client_order_id
                    and same_instrument
                    and usable_state
                ):
                    recovered = str(item.get(id_field) or "")
                    if recovered:
                        return recovered
            if attempt + 1 < self.max_retries:
                delay = self.backoff_base_s * (2**attempt)
                logger.warning(
                    "OKX create result unresolved for client id {}, poll {}/{} in {:.1f}s",
                    client_order_id,
                    attempt + 1,
                    self.max_retries,
                    delay,
                )
                time.sleep(delay)
        return None

    @staticmethod
    def _validate_client_order_id(client_order_id: str | None) -> None:
        if client_order_id is None:
            return
        if (
            not 1 <= len(client_order_id) <= 32
            or not client_order_id.isascii()
            or not client_order_id.isalnum()
        ):
            raise ValueError(
                "client_order_id must contain 1-32 alphanumeric characters, "
                f"got {client_order_id!r}"
            )

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
                    quantity = float(raw.get("sz") or 0.0) * self._contract_size(inst_id)
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
                        client_order_id=str(raw.get("algoClOrdId") or "") or None,
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
        return OkxTradeClient._optional_positive(value)

    @staticmethod
    def _optional_event_value(value: Any) -> float | None:
        """A positive bill field, treating OKX's zero placeholder as absent."""
        if value in (None, "", "0", "0.0", 0, 0.0):
            return None
        return OkxTradeClient._optional_positive(value)

    @staticmethod
    def _optional_positive(value: Any) -> float | None:
        """An optional positive number from an OKX string field."""
        if value in (None, ""):
            return None
        try:
            number = float(value)
        except (TypeError, ValueError) as exc:
            raise TradeError(f"invalid positive OKX value {value!r}") from exc
        if number <= 0:
            raise TradeError(f"invalid positive OKX value {value!r}")
        return number

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

    def _to_fill(
        self,
        inst_id: str,
        side: Side,
        order: dict,
        reason: str,
        contract_size: float = 1.0,
    ) -> Fill:
        """Turn a settled ccxt order into an engine `Fill`, fees in quote terms."""
        filled = float(order["filled"]) * contract_size
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
