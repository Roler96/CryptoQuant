"""LiveBroker: sizing parity, reconciliation, and resting protective exits."""

import pytest

from cq.core.types import CostModel, MarketSpec, Side
from cq.engine.sim import SimBroker
from cq.live.broker import (
    LiveBroker,
    Reconciliation,
    min_base_amount_of,
    spec_from_market,
)
from cq.live.client import TradeError
from cq.live.protocols import AccountEvent, CollateralBalance, SwapPosition

INST = "DOGE-USDT"
SWAP_INST = "DOGE-USDT-SWAP"

# A DOGE-USDT spot market as ccxt reports it on OKX.
MARKET = {
    "precision": {"amount": 1e-06, "price": 5e-05},
    "limits": {"amount": {"min": 1.0, "max": None}, "cost": {"min": None}},
}
SWAP_MARKET = {
    "type": "swap",
    "swap": True,
    "contract": True,
    "linear": True,
    "settle": "USDT",
    "contractSize": 100.0,
    "precision": {"amount": 1.0, "price": 5e-05},
    "limits": {"amount": {"min": 1.0, "max": None}, "cost": {"min": None}},
}


class FakeTradeClient:
    """A deterministic venue: balances move as orders fill, nothing is random."""

    def __init__(self, cash=1000.0, held=0.0, price=0.073, fee_bps=10.0):
        self.cash = cash
        self.held = held
        self.price = price
        self.fee_bps = fee_bps
        self.orders = []
        self.algo_orders = []
        self.canceled_algos = []
        self.actions = []
        self.swap_position_value = SwapPosition(
            held, 0.073 if held else None, 0.074, None, 2.0, "cross"
        )
        self.collateral = CollateralBalance(cash, cash + 5.0, cash - 10.0)
        self.events: list[AccountEvent] = []

    def milliseconds(self):
        return 0

    def free_balance(self, ccy):
        return self.cash

    def base_holding(self, inst_id):
        return self.held

    def last_price(self, inst_id):
        return self.price

    def round_amount(self, inst_id, quantity):
        return quantity

    def market_order(self, inst_id, side, quantity, reason="", client_order_id=None):
        notional = quantity * self.price
        fee = notional * self.fee_bps / 10_000
        if side is Side.BUY:
            self.held += quantity
            self.cash -= notional + fee
        else:
            self.held -= quantity
            self.cash += notional - fee
        from cq.core.types import Fill

        fill = Fill(0, inst_id, side, quantity, self.price, fee, reason)
        self.orders.append(fill)
        self.actions.append(("market", side, quantity))
        return fill

    def place_protective_order(
        self,
        inst_id,
        side,
        quantity,
        stop_loss=None,
        take_profit=None,
        client_order_id=None,
    ):
        algo_id = f"algo-{len(self.algo_orders) + 1}"
        order = {
            "algo_id": algo_id,
            "inst_id": inst_id,
            "side": side,
            "quantity": quantity,
            "stop_loss": stop_loss,
            "take_profit": take_profit,
            "client_order_id": client_order_id,
        }
        self.algo_orders.append(order)
        self.actions.append(("protect", algo_id))
        return algo_id

    def cancel_algo_order(self, inst_id, algo_id):
        self.canceled_algos.append((inst_id, algo_id))
        self.actions.append(("cancel", algo_id))

    def pending_protective_orders(self, inst_id):
        return []

    def protective_order_state(self, inst_id, algo_id):
        return "canceled"

    def configure_swap(self, inst_id, leverage, margin_mode="cross"):
        return None

    def swap_position(self, inst_id):
        return self.swap_position_value

    def collateral_balance(self, ccy):
        return self.collateral

    def swap_account_events(self, inst_id, begin_ms, end_ms):
        return list(self.events)


def make_broker(client=None, min_amount=1.0):
    return LiveBroker(
        client=client or FakeTradeClient(),
        spec=spec_from_market(MARKET, INST),
        min_base_amount=min_amount,
    )


# ---- market metadata ---------------------------------------------------


def test_spec_reads_the_venue_lot_grid():
    spec = spec_from_market(MARKET, INST)
    assert spec.inst_id == INST
    assert spec.market_type == "spot"
    assert spec.lot_size == 1e-06
    assert spec.max_leverage == 1.0


def test_min_base_amount_reads_the_venue_floor():
    assert min_base_amount_of(MARKET) == 1.0
    assert min_base_amount_of({"limits": {"amount": {"min": None}}}) == 0.0


def test_swap_spec_converts_contract_grid_to_base_and_caps_leverage():
    spec = spec_from_market(SWAP_MARKET, SWAP_INST, max_leverage=3.0)

    assert spec.market_type == "swap"
    assert spec.contract_size == 100.0
    assert spec.lot_size == 100.0
    assert min_base_amount_of(SWAP_MARKET) == 100.0
    assert spec.max_leverage == 3.0
    assert spec.to_venue_quantity(250.0) == 2.5
    assert spec.from_venue_quantity(2.5) == 250.0


def test_swap_spec_rejects_inverse_or_wrong_settlement_contracts():
    inverse = {**SWAP_MARKET, "linear": False}
    wrong_settle = {**SWAP_MARKET, "settle": "DOGE"}

    with pytest.raises(ValueError, match="linear"):
        spec_from_market(inverse, SWAP_INST)
    with pytest.raises(ValueError, match="quote-settled"):
        spec_from_market(wrong_settle, SWAP_INST)


# ---- reconciliation ----------------------------------------------------


def test_reconcile_reads_held_and_cash_from_the_client():
    broker = make_broker(FakeTradeClient(cash=500.0, held=42.0))
    state = broker.reconcile()
    assert state == Reconciliation(held=42.0, cash=500.0)


def test_equity_marks_holdings_to_price():
    state = Reconciliation(held=100.0, cash=200.0)
    assert state.equity(2.0) == 400.0


def test_swap_reconcile_uses_signed_position_and_exchange_equity():
    client = FakeTradeClient(cash=500.0, held=-300.0)
    broker = LiveBroker(
        client=client,
        spec=spec_from_market(SWAP_MARKET, SWAP_INST, max_leverage=2.0),
        min_base_amount=min_base_amount_of(SWAP_MARKET),
    )

    state = broker.reconcile()

    assert state.held == -300.0
    assert state.cash == 500.0
    assert state.average_entry == 0.073
    assert state.mark_price == 0.074
    assert state.equity(999.0) == 505.0


# ---- sizing parity with the backtest -----------------------------------


def test_sizing_matches_the_simulated_broker_bit_for_bit():
    # The whole point of the shared `target_delta`: same inputs, same order.
    spec = spec_from_market(MARKET, INST)
    costs = CostModel()
    sim = SimBroker(spec, costs)
    live = make_broker()

    args = (0.5, 0.073, 1000.0, 0.0, 1000.0)  # target, price, equity, held, cash
    assert live.quantity_for_target(*args) == sim.quantity_for_target(*args)


# ---- execution ---------------------------------------------------------


def test_execute_places_a_buy_and_returns_the_fill():
    client = FakeTradeClient()
    broker = make_broker(client)
    fill = broker.execute(100.0, ts=123, reason="test")
    assert fill is not None
    assert fill.side is Side.BUY
    assert fill.quantity == 100.0
    assert client.held == 100.0
    assert broker.rejections == []


def test_execute_sells_a_negative_delta():
    client = FakeTradeClient(held=100.0)
    broker = make_broker(client)
    fill = broker.execute(-40.0, ts=1)
    assert fill is not None
    assert fill.side is Side.SELL
    assert fill.quantity == 40.0
    assert client.held == 60.0


def test_execute_rejects_below_the_venue_minimum():
    client = FakeTradeClient()
    broker = make_broker(client, min_amount=1.0)
    fill = broker.execute(0.5, ts=7)  # half a DOGE, under the 1-DOGE floor
    assert fill is None
    assert client.orders == []
    assert len(broker.rejections) == 1
    assert broker.rejections[0].ts == 7
    assert "minimum" in broker.rejections[0].reason


def test_execute_rejects_a_sub_lot_delta():
    spec = MarketSpec(INST, "spot", lot_size=1.0)
    broker = LiveBroker(client=FakeTradeClient(), spec=spec, min_base_amount=0.0)
    fill = broker.execute(0.4, ts=9)  # rounds to zero lots
    assert fill is None
    assert broker.rejections[0].reason == "below lot size"


def test_a_full_close_never_oversells():
    # round_quantity is towards zero, so closing a held position cannot ask for
    # more coins than are held.
    client = FakeTradeClient(held=123.456789)
    broker = make_broker(client)
    delta = broker.quantity_for_target(0.0, 0.073, client.held * 0.073, client.held, 0.0)
    assert delta <= 0
    assert abs(delta) <= client.held


# ---- protective exits -------------------------------------------------


def test_sync_protection_places_an_exit_for_the_reconciled_holding():
    client = FakeTradeClient(held=123.456789)
    broker = make_broker(client)

    protection = broker.sync_protection(client.held, stop_loss=0.06, take_profit=0.08)

    assert protection is not None
    assert protection.algo_id == "algo-1"
    assert protection.quantity == 123.456789
    assert client.algo_orders == [
        {
            "algo_id": "algo-1",
            "inst_id": INST,
            "side": Side.SELL,
            "quantity": 123.456789,
            "stop_loss": 0.06,
            "take_profit": 0.08,
            "client_order_id": None,
        }
    ]


def test_swap_short_protection_is_a_reduce_only_buy_quantity():
    client = FakeTradeClient(cash=500.0, held=-300.0)
    broker = LiveBroker(
        client=client,
        spec=spec_from_market(SWAP_MARKET, SWAP_INST, max_leverage=2.0),
        min_base_amount=100.0,
    )

    protection = broker.sync_protection(-300.0, stop_loss=0.08, take_profit=0.06)

    assert protection is not None
    assert protection.side is Side.BUY
    assert protection.quantity == 300.0
    assert client.algo_orders[0]["side"] is Side.BUY


def test_execute_and_protection_forward_client_order_ids():
    client = FakeTradeClient()
    broker = make_broker(client)

    broker.execute(100.0, ts=123, client_order_id="101")
    protection = broker.sync_protection(
        client.held,
        stop_loss=0.06,
        take_profit=0.08,
        client_order_id="202",
    )

    assert protection is not None
    assert protection.client_order_id == "202"
    assert client.algo_orders[0]["client_order_id"] == "202"


def test_unchanged_protection_is_retained_but_a_new_level_replaces_it():
    client = FakeTradeClient(held=100.0)
    broker = make_broker(client)
    first = broker.sync_protection(100.0, stop_loss=0.06, take_profit=0.08)

    same = broker.sync_protection(100.0, stop_loss=0.06, take_profit=0.08)
    replacement = broker.sync_protection(100.0, stop_loss=0.065, take_profit=0.08)

    assert same is first
    assert replacement is not None
    assert replacement.algo_id == "algo-2"
    assert client.canceled_algos == [(INST, "algo-1")]
    assert client.actions == [
        ("protect", "algo-1"),
        ("cancel", "algo-1"),
        ("protect", "algo-2"),
    ]


def test_flat_or_unprotected_intent_cancels_the_active_exit():
    client = FakeTradeClient(held=100.0)
    broker = make_broker(client)
    broker.sync_protection(100.0, stop_loss=0.06, take_profit=None)

    assert broker.sync_protection(0.0, stop_loss=0.06, take_profit=None) is None
    assert broker.active_protection is None
    assert client.canceled_algos == [(INST, "algo-1")]


def test_a_too_small_holding_is_not_silently_left_unprotected():
    broker = make_broker(FakeTradeClient(held=0.5), min_amount=1.0)

    with pytest.raises(TradeError, match="refusing to run unprotected"):
        broker.sync_protection(0.5, stop_loss=0.06, take_profit=None)
