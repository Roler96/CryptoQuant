"""LiveBroker: sizes exactly as the backtest, and reconciles from the venue."""

from cq.core.types import CostModel, MarketSpec, Side
from cq.engine.sim import SimBroker
from cq.live.broker import (
    LiveBroker,
    Reconciliation,
    min_base_amount_of,
    spec_from_market,
)

INST = "DOGE-USDT"

# A DOGE-USDT spot market as ccxt reports it on OKX.
MARKET = {
    "precision": {"amount": 1e-06, "price": 5e-05},
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

    def market_order(self, inst_id, side, quantity, reason=""):
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
        return fill


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


# ---- reconciliation ----------------------------------------------------


def test_reconcile_reads_held_and_cash_from_the_client():
    broker = make_broker(FakeTradeClient(cash=500.0, held=42.0))
    state = broker.reconcile()
    assert state == Reconciliation(held=42.0, cash=500.0)


def test_equity_marks_holdings_to_price():
    state = Reconciliation(held=100.0, cash=200.0)
    assert state.equity(2.0) == 400.0


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
