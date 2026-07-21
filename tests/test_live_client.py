"""OKX-native protective algo requests, without touching the network."""

import ccxt
import pytest

from cq.core.types import Side
from cq.live.client import OkxTradeClient, TradeError

INST = "DOGE-USDT"


class FakeExchange:
    def __init__(self):
        self.placed = []
        self.canceled = []
        self.pending_requests = []
        self.pending_by_type = {"conditional": [], "oco": []}
        self.algo_details = {}
        self.cancel_error: Exception | None = None

    def amount_to_precision(self, symbol, quantity):
        assert symbol == "DOGE/USDT"
        return f"{quantity:.6f}"

    def price_to_precision(self, symbol, price):
        assert symbol == "DOGE/USDT"
        return f"{price:.5f}"

    def private_post_trade_order_algo(self, request):
        self.placed.append(request)
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
        return {
            "code": "0",
            "data": [self.algo_details[request["algoId"]]],
            "msg": "",
        }


def make_client(exchange):
    client = object.__new__(OkxTradeClient)
    client.max_retries = 1
    client.backoff_base_s = 0.0
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
        }
    ]
    client = make_client(exchange)

    orders = client.pending_protective_orders(INST)

    assert [order.algo_id for order in orders] == ["10", "20"]
    assert (orders[0].stop_loss, orders[0].take_profit) == (0.05, 0.09)
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
