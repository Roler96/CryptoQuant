"""OKX-native protective algo requests, without touching the network."""

import ccxt
import pytest

from cq.core.types import Side
from cq.live.client import OkxTradeClient, TradeError, to_symbol

INST = "DOGE-USDT"


class FakeExchange:
    def __init__(self):
        self.placed = []
        self.market_placed = []
        self.canceled = []
        self.pending_requests = []
        self.pending_by_type = {"conditional": [], "oco": []}
        self.algo_details = {}
        self.cancel_error: Exception | None = None
        self.algo_create_error: Exception | None = None
        self.market_create_error: Exception | None = None
        self.algo_by_client_id = {}
        self.order_by_client_id = {}
        self.account_config = {"acctLv": "2", "posMode": "net_mode"}
        self.position_mode_requests = []
        self.leverage_requests = []
        self.positions = []
        self.balance_details = []
        self.bills = []
        self.bill_requests = []
        self.filled = 100.0

    def market(self, symbol):
        if symbol == "DOGE/USDT:USDT":
            return {
                "contract": True,
                "swap": True,
                "linear": True,
                "settle": "USDT",
                "contractSize": 100.0,
            }
        raise KeyError(symbol)

    def amount_to_precision(self, symbol, quantity):
        assert symbol in ("DOGE/USDT", "DOGE/USDT:USDT")
        return f"{quantity:.6f}"

    def price_to_precision(self, symbol, price):
        assert symbol in ("DOGE/USDT", "DOGE/USDT:USDT")
        return f"{price:.5f}"

    def private_post_trade_order_algo(self, request):
        self.placed.append(request)
        if self.algo_create_error is not None:
            raise self.algo_create_error
        return {
            "code": "0",
            "data": [{"algoId": "12345", "sCode": "0", "sMsg": ""}],
            "msg": "",
        }

    def private_post_trade_cancel_algos(self, request):
        self.canceled.append(request)
        if self.cancel_error is not None:
            raise self.cancel_error
        return {
            "code": "0",
            "data": [{"algoId": "12345", "sCode": "0", "sMsg": ""}],
            "msg": "",
        }

    def private_get_trade_orders_algo_pending(self, request):
        self.pending_requests.append(request)
        return {
            "code": "0",
            "data": self.pending_by_type[request["ordType"]],
            "msg": "",
        }

    def private_get_trade_order_algo(self, request):
        if "algoClOrdId" in request:
            item = self.algo_by_client_id.get(request["algoClOrdId"])
            if item is None:
                raise ccxt.OrderNotFound("not visible yet")
            return {"code": "0", "data": [item], "msg": ""}
        return {
            "code": "0",
            "data": [self.algo_details[request["algoId"]]],
            "msg": "",
        }

    def create_order(self, symbol, order_type, side, quantity, price, params):
        self.market_placed.append((symbol, order_type, side, quantity, price, params))
        if self.market_create_error is not None:
            raise self.market_create_error
        return {"id": "market-1"}

    def private_get_trade_order(self, request):
        item = self.order_by_client_id.get(request["clOrdId"])
        if item is None:
            raise ccxt.OrderNotFound("not visible yet")
        return {"code": "0", "data": [item], "msg": ""}

    def fetch_order(self, order_id, symbol):
        return {
            "id": order_id,
            "status": "closed",
            "filled": self.filled,
            "average": 0.073,
            "timestamp": 123,
            "fees": [],
        }

    def private_get_account_config(self):
        return {"code": "0", "data": [self.account_config], "msg": ""}

    def private_post_account_set_position_mode(self, request):
        self.position_mode_requests.append(request)
        self.account_config["posMode"] = request["posMode"]
        return {"code": "0", "data": [{"posMode": request["posMode"]}], "msg": ""}

    def private_post_account_set_leverage(self, request):
        self.leverage_requests.append(request)
        return {
            "code": "0",
            "data": [
                {
                    "instId": request["instId"],
                    "lever": request["lever"],
                    "mgnMode": request["mgnMode"],
                    "posSide": request.get("posSide", "net"),
                }
            ],
            "msg": "",
        }

    def private_get_account_positions(self, request):
        return {"code": "0", "data": self.positions, "msg": ""}

    def private_get_account_balance(self, request):
        return {
            "code": "0",
            "data": [{"details": self.balance_details}],
            "msg": "",
        }

    def private_get_account_bills(self, request):
        self.bill_requests.append(request)
        return {
            "code": "0",
            "data": [row for row in self.bills if row.get("type") == request["type"]],
            "msg": "",
        }


def make_client(exchange):
    client = object.__new__(OkxTradeClient)
    client.max_retries = 1
    client.backoff_base_s = 0.0
    client.fill_poll_attempts = 1
    client.fill_poll_interval_s = 0.0
    client._swap_settings = {}
    client._ex = exchange
    return client


def test_two_levels_place_one_oco_with_market_on_trigger_legs():
    exchange = FakeExchange()
    client = make_client(exchange)

    algo_id = client.place_protective_order(
        INST,
        Side.SELL,
        123.456789,
        stop_loss=0.06,
        take_profit=0.08,
    )

    assert algo_id == "12345"
    assert exchange.placed == [
        {
            "instId": INST,
            "tdMode": "cash",
            "side": "sell",
            "ordType": "oco",
            "sz": "123.456789",
            "slTriggerPx": "0.06000",
            "slOrdPx": "-1",
            "slTriggerPxType": "last",
            "tpTriggerPx": "0.08000",
            "tpOrdPx": "-1",
            "tpTriggerPxType": "last",
        }
    ]


def test_one_level_uses_conditional_instead_of_oco():
    exchange = FakeExchange()
    client = make_client(exchange)

    client.place_protective_order(INST, Side.SELL, 100.0, stop_loss=0.06)

    request = exchange.placed[0]
    assert request["ordType"] == "conditional"
    assert "tpTriggerPx" not in request


def test_market_order_attaches_client_id_and_reads_fill():
    exchange = FakeExchange()
    client = make_client(exchange)

    fill = client.market_order(
        INST,
        Side.BUY,
        100.0,
        reason="entry",
        client_order_id="123456",
    )

    assert fill.quantity == 100.0
    assert exchange.market_placed == [
        (
            "DOGE/USDT",
            "market",
            "buy",
            100.0,
            None,
            {"tgtCcy": "base_ccy", "clOrdId": "123456"},
        )
    ]


def test_swap_symbol_uses_ccxt_settlement_suffix():
    assert to_symbol("DOGE-USDT-SWAP") == "DOGE/USDT:USDT"


def test_swap_configuration_enforces_net_mode_and_explicit_leverage():
    exchange = FakeExchange()
    exchange.account_config["posMode"] = "long_short_mode"
    client = make_client(exchange)

    client.configure_swap("DOGE-USDT-SWAP", leverage=3.0, margin_mode="isolated")

    assert exchange.position_mode_requests == [{"posMode": "net_mode"}]
    assert exchange.leverage_requests == [
        {
            "instId": "DOGE-USDT-SWAP",
            "lever": "3",
            "mgnMode": "isolated",
            "posSide": "net",
        }
    ]


def test_swap_configuration_rejects_spot_only_account_mode():
    exchange = FakeExchange()
    exchange.account_config["acctLv"] = "1"
    client = make_client(exchange)

    with pytest.raises(TradeError, match="account is in Spot mode"):
        client.configure_swap("DOGE-USDT-SWAP", leverage=1.0)

    assert exchange.leverage_requests == []


def test_swap_configuration_rejects_portfolio_margin_without_fixed_leverage():
    exchange = FakeExchange()
    exchange.account_config["acctLv"] = "4"
    client = make_client(exchange)

    with pytest.raises(TradeError, match="Portfolio margin"):
        client.configure_swap("DOGE-USDT-SWAP", leverage=1.0)

    assert exchange.leverage_requests == []


def test_swap_market_order_converts_base_quantity_to_contracts_and_back():
    exchange = FakeExchange()
    exchange.filled = 2.0
    client = make_client(exchange)
    client.configure_swap("DOGE-USDT-SWAP", leverage=2.0)

    fill = client.market_order(
        "DOGE-USDT-SWAP",
        Side.SELL,
        200.0,
        client_order_id="123456",
    )

    assert fill.quantity == 200.0
    assert exchange.market_placed[-1] == (
        "DOGE/USDT:USDT",
        "market",
        "sell",
        2.0,
        None,
        {"tdMode": "cross", "posSide": "net", "clOrdId": "123456"},
    )


def test_swap_protection_converts_contracts_and_is_explicitly_reduce_only():
    exchange = FakeExchange()
    client = make_client(exchange)
    client.configure_swap("DOGE-USDT-SWAP", leverage=2.0)

    client.place_protective_order(
        "DOGE-USDT-SWAP",
        Side.BUY,
        300.0,
        stop_loss=0.08,
    )

    assert exchange.placed[-1] == {
        "instId": "DOGE-USDT-SWAP",
        "side": "buy",
        "ordType": "conditional",
        "sz": "3.000000",
        "tdMode": "cross",
        "posSide": "net",
        "reduceOnly": True,
        "slTriggerPx": "0.08000",
        "slOrdPx": "-1",
        "slTriggerPxType": "last",
    }


def test_swap_order_refuses_to_inherit_unverified_account_defaults():
    client = make_client(FakeExchange())

    with pytest.raises(TradeError, match="configure_swap"):
        client.market_order("DOGE-USDT-SWAP", Side.BUY, 100.0)


def test_swap_position_and_collateral_are_normalized_from_okx_fields():
    exchange = FakeExchange()
    exchange.positions = [
        {
            "instId": "DOGE-USDT-SWAP",
            "posSide": "net",
            "pos": "-3",
            "avgPx": "0.073",
            "markPx": "0.071",
            "liqPx": "0.12",
            "lever": "2",
            "mgnMode": "cross",
        }
    ]
    exchange.balance_details = [
        {"ccy": "USDT", "cashBal": "1000", "eq": "1000.6", "availBal": "900"}
    ]
    client = make_client(exchange)
    client.configure_swap("DOGE-USDT-SWAP", leverage=2.0)

    position = client.swap_position("DOGE-USDT-SWAP")
    balance = client.collateral_balance("USDT")

    assert position.quantity == -300.0
    assert position.average_entry == 0.073
    assert position.mark_price == 0.071
    assert position.liquidation_price == 0.12
    assert balance.cash == 1000.0
    assert balance.equity == 1000.6
    assert balance.available == 900.0


def test_swap_position_rejects_leverage_that_drifted_from_configuration():
    exchange = FakeExchange()
    exchange.positions = [
        {
            "instId": "DOGE-USDT-SWAP",
            "posSide": "net",
            "pos": "1",
            "avgPx": "0.073",
            "markPx": "0.071",
            "liqPx": "",
            "lever": "3",
            "mgnMode": "cross",
        }
    ]
    client = make_client(exchange)
    client.configure_swap("DOGE-USDT-SWAP", leverage=2.0)

    with pytest.raises(TradeError, match="position leverage"):
        client.swap_position("DOGE-USDT-SWAP")


def test_missing_swap_collateral_currency_fails_closed():
    client = make_client(FakeExchange())

    with pytest.raises(TradeError, match="no USDT collateral"):
        client.collateral_balance("USDT")


def test_swap_account_events_preserve_exchange_side_balance_changes():
    exchange = FakeExchange()
    exchange.bills = [
        {
            "billId": "2",
            "ts": "2000",
            "type": "5",
            "subType": "104",
            "instId": "DOGE-USDT-SWAP",
            "balChg": "-1.25",
            "ccy": "USDT",
            "px": "0.05",
            "sz": "2",
        },
        {
            "billId": "1",
            "ts": "1000",
            "type": "8",
            "subType": "173",
            "instId": "DOGE-USDT-SWAP",
            "balChg": "-0.2",
            "ccy": "USDT",
            "px": "0.07",
            "sz": "3",
        },
    ]
    client = make_client(exchange)

    events = client.swap_account_events("DOGE-USDT-SWAP", 1, 3000)

    assert [event.kind for event in events] == ["funding", "liquidation"]
    assert events[0].amount == -0.2
    assert events[0].quantity == 300.0
    assert events[1].price == 0.05
    assert [request["type"] for request in exchange.bill_requests] == ["5", "8", "9"]


def test_market_create_timeout_is_looked_up_without_resending():
    exchange = FakeExchange()
    exchange.market_create_error = ccxt.RequestTimeout("ambiguous create")
    exchange.order_by_client_id["123456"] = {
        "ordId": "accepted-1",
        "clOrdId": "123456",
        "instId": INST,
    }
    client = make_client(exchange)

    fill = client.market_order(INST, Side.BUY, 100.0, client_order_id="123456")

    assert fill.quantity == 100.0
    assert len(exchange.market_placed) == 1


def test_unresolved_market_create_is_not_resent():
    exchange = FakeExchange()
    exchange.market_create_error = ccxt.RequestTimeout("ambiguous create")
    client = make_client(exchange)

    with pytest.raises(TradeError, match="result is unknown"):
        client.market_order(INST, Side.BUY, 100.0, client_order_id="123456")

    assert len(exchange.market_placed) == 1


def test_protective_create_timeout_is_looked_up_without_resending():
    exchange = FakeExchange()
    exchange.algo_create_error = ccxt.RequestTimeout("ambiguous create")
    exchange.algo_by_client_id["654321"] = {
        "algoId": "accepted-algo",
        "algoClOrdId": "654321",
        "instId": INST,
        "state": "live",
    }
    client = make_client(exchange)

    algo_id = client.place_protective_order(
        INST,
        Side.SELL,
        100.0,
        stop_loss=0.06,
        client_order_id="654321",
    )

    assert algo_id == "accepted-algo"
    assert len(exchange.placed) == 1
    assert exchange.placed[0]["algoClOrdId"] == "654321"


def test_protective_lookup_does_not_reuse_a_historical_canceled_order():
    exchange = FakeExchange()
    exchange.algo_create_error = ccxt.RequestTimeout("ambiguous create")
    exchange.algo_by_client_id["654321"] = {
        "algoId": "old-algo",
        "algoClOrdId": "654321",
        "instId": INST,
        "state": "canceled",
    }
    client = make_client(exchange)

    with pytest.raises(TradeError, match="result is unknown"):
        client.place_protective_order(
            INST,
            Side.SELL,
            100.0,
            stop_loss=0.06,
            client_order_id="654321",
        )

    assert len(exchange.placed) == 1


def test_cancel_uses_okx_batch_shape_for_one_algo():
    exchange = FakeExchange()
    client = make_client(exchange)

    client.cancel_algo_order(INST, "12345")

    assert exchange.canceled == [[{"algoId": "12345", "instId": INST}]]


def test_canceling_an_already_completed_algo_is_idempotent():
    exchange = FakeExchange()
    exchange.cancel_error = ccxt.OrderNotFound("already completed")
    client = make_client(exchange)

    client.cancel_algo_order(INST, "12345")

    assert len(exchange.canceled) == 1


def test_per_order_api_failure_is_not_treated_as_success():
    response = {
        "code": "2",
        "data": [{"algoId": "", "sCode": "51000", "sMsg": "bad request"}],
        "msg": "partial failure",
    }

    with pytest.raises(TradeError, match="bad request"):
        OkxTradeClient._algo_result(response, "place protective order")


def test_pending_protective_orders_merge_conditional_and_oco():
    exchange = FakeExchange()
    exchange.pending_by_type["conditional"] = [
        {
            "algoId": "20",
            "instId": INST,
            "side": "sell",
            "sz": "100",
            "slTriggerPx": "0.06",
            "tpTriggerPx": "",
        }
    ]
    exchange.pending_by_type["oco"] = [
        {
            "algoId": "10",
            "instId": INST,
            "side": "sell",
            "sz": "200",
            "slTriggerPx": "0.05",
            "tpTriggerPx": "0.09",
            "algoClOrdId": "222",
        }
    ]
    client = make_client(exchange)

    orders = client.pending_protective_orders(INST)

    assert [order.algo_id for order in orders] == ["10", "20"]
    assert (orders[0].stop_loss, orders[0].take_profit) == (0.05, 0.09)
    assert orders[0].client_order_id == "222"
    assert exchange.pending_requests == [
        {"ordType": "conditional", "instId": INST},
        {"ordType": "oco", "instId": INST},
    ]


def test_protective_order_state_reads_terminal_algo_details():
    exchange = FakeExchange()
    exchange.algo_details["12345"] = {
        "algoId": "12345",
        "instId": INST,
        "state": "canceled",
    }
    client = make_client(exchange)

    assert client.protective_order_state(INST, "12345") == "canceled"
