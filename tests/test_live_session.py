"""The paper loop: closed-bar decisions, round trips, warmup, bounded runs."""

from dataclasses import dataclass

import pytest

from cq.context import Bar, Context
from cq.core.types import Fill, Intent, MarketSpec, Side
from cq.engine.sizing import target_delta
from cq.live.broker import LiveBroker
from cq.live.probe import HeartbeatProbe
from cq.live.session import PaperEvent, run_paper

INST = "DOGE-USDT"
TF = "1h"
HOUR = 3_600_000
SPEC = MarketSpec(INST, "spot", lot_size=1e-06)


class FakeTradeClient:
    """Balances evolve as orders fill, so reconcile() sees prior trades."""

    def __init__(self, cash=1000.0, held=0.0):
        self.cash = cash
        self.held = held
        self.orders = []

    def milliseconds(self):
        return 0

    def free_balance(self, ccy):
        return self.cash

    def base_holding(self, inst_id):
        return self.held

    def last_price(self, inst_id):
        return 0.073

    def round_amount(self, inst_id, quantity):
        return quantity

    def market_order(self, inst_id, side, quantity, reason=""):
        price = 0.073
        if side is Side.BUY:
            self.held += quantity
            self.cash -= quantity * price
        else:
            self.held -= quantity
            self.cash += quantity * price
        fill = Fill(0, inst_id, side, quantity, price, 0.0, reason)
        self.orders.append(fill)
        return fill


def broker(client=None):
    return LiveBroker(client=client or FakeTradeClient(), spec=SPEC, min_base_amount=1.0)


def bars(n, start_close=0.073):
    return [
        Bar(ts=i * HOUR, open=start_close, high=start_close, low=start_close,
            close=start_close, volume=100.0)
        for i in range(n)
    ]


def collect(**kwargs):
    events: list[PaperEvent] = []
    run_paper(on_event=events.append, **kwargs)
    return events


# ---- round trips -------------------------------------------------------


def test_probe_produces_alternating_round_trips():
    client = FakeTradeClient()
    events = collect(
        strategy=HeartbeatProbe(weight=0.05, period=1),
        broker=broker(client),
        feed=bars(4),
        inst_id=INST,
        timeframe=TF,
        warmup=[Bar(-HOUR, 0.073, 0.073, 0.073, 0.073, 100.0)],
        max_bars=4,
    )
    assert len(events) == 4
    sides = [e.fill.side for e in events if e.fill]
    assert sides == [Side.BUY, Side.SELL, Side.BUY, Side.SELL]
    # A buy then a sell of the same size leaves the account flat again.
    assert client.held == pytest.approx(0.0, abs=1e-6)


def test_targets_follow_the_probe_square_wave():
    events = collect(
        strategy=HeartbeatProbe(weight=0.05, period=1),
        broker=broker(),
        feed=bars(4),
        inst_id=INST,
        timeframe=TF,
        max_bars=4,
    )
    assert [e.target for e in events] == [0.05, 0.0, 0.05, 0.0]


# ---- sizing is the shared sizing, at the close -------------------------


def test_order_quantity_is_sized_from_the_close_by_shared_sizing():
    client = FakeTradeClient(cash=1000.0, held=0.0)
    b = broker(client)
    close = 0.073
    events = collect(
        strategy=HeartbeatProbe(weight=0.05, period=1),
        broker=b,
        feed=[Bar(0, close, close, close, close, 100.0)],
        inst_id=INST,
        timeframe=TF,
        max_bars=1,
    )
    expected = target_delta(SPEC, b.costs, 0.05, close, 1000.0, 0.0, 1000.0, b.dust_fraction)
    assert events[0].fill is not None
    assert events[0].fill.quantity == pytest.approx(abs(expected))
    assert events[0].close == close


# ---- warmup and bounds -------------------------------------------------


@dataclass
class _NeedsThreeBars:
    """A strategy that must not be asked to decide before three bars exist."""

    def __post_init__(self):
        self.seen = 0

    name = "needs-three"
    warmup_bars = 3

    def on_bar(self, ctx: Context) -> Intent:
        self.seen += 1
        # Reading three bars must not raise: proof the gate held.
        ctx.close(3)
        return Intent(target=0.0)


def test_strategy_is_not_asked_to_decide_before_warmup():
    strat = _NeedsThreeBars()
    events = collect(
        strategy=strat,
        broker=broker(),
        feed=bars(5),
        inst_id=INST,
        timeframe=TF,
        max_bars=None,
    )
    # Five bars, warmup 3 → decisions only on bars 3, 4, 5.
    assert len(events) == 3
    assert strat.seen == 3


def test_max_bars_bounds_the_run():
    events = collect(
        strategy=HeartbeatProbe(),
        broker=broker(),
        feed=bars(50),
        inst_id=INST,
        timeframe=TF,
        max_bars=2,
    )
    assert len(events) == 2


def test_equity_is_marked_at_the_close():
    client = FakeTradeClient(cash=1000.0, held=0.0)
    events = collect(
        strategy=HeartbeatProbe(weight=0.05, period=1),
        broker=broker(client),
        feed=[Bar(0, 0.073, 0.073, 0.073, 0.073, 100.0)],
        inst_id=INST,
        timeframe=TF,
        max_bars=1,
    )
    # Before the first order the account is all cash, so equity == cash.
    assert events[0].equity == pytest.approx(1000.0)
