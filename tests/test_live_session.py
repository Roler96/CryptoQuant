"""The paper loop: closed-bar decisions, round trips, warmup, bounded runs."""

from dataclasses import dataclass
from pathlib import Path

import pytest

from cq.context import Bar, Context
from cq.core.types import Fill, Intent, MarketSpec, Side
from cq.engine.sizing import target_delta
from cq.live.broker import LiveBroker
from cq.live.commands import _event_row
from cq.live.probe import HeartbeatProbe
from cq.live.recovery import CHECKPOINT_VERSION, SessionResume
from cq.live.session import PaperEvent, run_paper

INST = "DOGE-USDT"
TF = "1h"
HOUR = 3_600_000
SPEC = MarketSpec(INST, "spot", lot_size=1e-06)


class FakeTradeClient:
    """Balances evolve as orders fill, so reconcile() sees prior trades."""

    def __init__(self, cash=1000.0, held=0.0, fail_sells=False):
        self.cash = cash
        self.held = held
        self.fail_sells = fail_sells
        self.orders = []
        self.algo_orders = []
        self.canceled_algos = []
        self.actions = []
        self.market_client_order_ids = []

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

    def market_order(self, inst_id, side, quantity, reason="", client_order_id=None):
        self.market_client_order_ids.append(client_order_id)
        price = 0.073
        if self.fail_sells and side is Side.SELL:
            self.actions.append(("market-error", side))
            raise RuntimeError("uncertain sell result")
        if side is Side.BUY:
            self.held += quantity
            self.cash -= quantity * price
        else:
            self.held -= quantity
            self.cash += quantity * price
        fill = Fill(0, inst_id, side, quantity, price, 0.0, reason)
        self.orders.append(fill)
        self.actions.append(("market", side))
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
        self.algo_orders.append(
            (algo_id, inst_id, side, quantity, stop_loss, take_profit, client_order_id)
        )
        self.actions.append(("protect", algo_id))
        return algo_id

    def cancel_algo_order(self, inst_id, algo_id):
        self.canceled_algos.append((inst_id, algo_id))
        self.actions.append(("cancel", algo_id))

    def pending_protective_orders(self, inst_id):
        return []

    def protective_order_state(self, inst_id, algo_id):
        return "canceled"


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


# ---- protective exits -------------------------------------------------


@dataclass
class _ProtectedRoundTrip:
    name = "protected-round-trip"
    warmup_bars = 1

    def __post_init__(self):
        self.step = 0

    def reset(self):
        self.step = 0

    def on_bar(self, ctx: Context) -> Intent:
        self.step += 1
        if self.step == 1:
            return Intent(
                target=0.05,
                stop_loss=0.06,
                take_profit=0.08,
                reason="entry",
            )
        return Intent(target=0.0, reason="exit")


def test_protection_covers_the_fill_and_is_canceled_before_target_exit():
    client = FakeTradeClient()
    events = collect(
        strategy=_ProtectedRoundTrip(),
        broker=broker(client),
        feed=bars(2),
        inst_id=INST,
        timeframe=TF,
        max_bars=2,
    )

    first = events[0].protection
    first_fill = events[0].fill
    assert first is not None
    assert first_fill is not None
    assert first.quantity == pytest.approx(first_fill.quantity)
    assert (first.stop_loss, first.take_profit) == (0.06, 0.08)
    assert events[1].protection is None
    assert client.actions == [
        ("market", Side.BUY),
        ("protect", "algo-1"),
        ("cancel", "algo-1"),
        ("market", Side.SELL),
    ]


def test_session_log_records_the_resting_algo_id_and_levels():
    event = collect(
        strategy=_ProtectedRoundTrip(),
        broker=broker(),
        feed=bars(1),
        inst_id=INST,
        timeframe=TF,
        max_bars=1,
    )[0]

    protection = event.protection
    assert protection is not None
    assert _event_row(event)["protection"] == {
        "algo_id": "algo-1",
        "quantity": protection.quantity,
        "stop_loss": 0.06,
        "take_profit": 0.08,
        "side": "sell",
        "client_order_id": protection.client_order_id,
    }


def test_same_bar_intent_uses_stable_distinct_market_and_protection_ids():
    first_client = FakeTradeClient()
    second_client = FakeTradeClient()

    first = collect(
        strategy=_ProtectedRoundTrip(),
        broker=broker(first_client),
        feed=bars(1),
        inst_id=INST,
        timeframe=TF,
        max_bars=1,
    )[0]
    second = collect(
        strategy=_ProtectedRoundTrip(),
        broker=broker(second_client),
        feed=bars(1),
        inst_id=INST,
        timeframe=TF,
        max_bars=1,
    )[0]

    assert first.client_order_id == second.client_order_id
    assert first.protection is not None
    assert second.protection is not None
    assert first.protection.client_order_id == second.protection.client_order_id
    assert first.client_order_id != first.protection.client_order_id
    assert first_client.market_client_order_ids == [first.client_order_id]
    assert _event_row(first)["client_order_id"] == first.client_order_id


def test_failed_target_exit_restores_protection_for_the_remaining_holding():
    client = FakeTradeClient(fail_sells=True)
    b = broker(client)
    events: list[PaperEvent] = []

    with pytest.raises(RuntimeError, match="uncertain sell result"):
        run_paper(
            strategy=_ProtectedRoundTrip(),
            broker=b,
            feed=bars(2),
            inst_id=INST,
            timeframe=TF,
            on_event=events.append,
            max_bars=2,
        )

    protection = b.active_protection
    assert protection is not None
    assert protection.quantity == pytest.approx(client.held)
    assert (protection.stop_loss, protection.take_profit) == (0.06, 0.08)
    assert client.actions == [
        ("market", Side.BUY),
        ("protect", "algo-1"),
        ("cancel", "algo-1"),
        ("market-error", Side.SELL),
        ("protect", "algo-2"),
    ]


# ---- restart checkpoints ---------------------------------------------


def test_event_checkpoint_records_post_trade_cost_and_strategy_state():
    event = collect(
        strategy=HeartbeatProbe(weight=0.05, period=1),
        broker=broker(),
        feed=bars(1),
        inst_id=INST,
        timeframe=TF,
        max_bars=1,
    )[0]
    row = _event_row(event)

    assert row["checkpoint_version"] == CHECKPOINT_VERSION
    assert row["inst_id"] == INST
    assert row["timeframe"] == TF
    assert row["strategy"] == "heartbeat-probe"
    assert row["held_after"] > 0
    assert row["cash_after"] < 1000.0
    assert row["average_entry"] == pytest.approx(0.073)
    assert row["strategy_state"] == {"count": 1, "weight": 0.05, "period": 1}


def test_probe_phase_and_cost_basis_continue_from_a_checkpoint():
    client = FakeTradeClient()
    first = collect(
        strategy=HeartbeatProbe(weight=0.05, period=1),
        broker=broker(client),
        feed=bars(1),
        inst_id=INST,
        timeframe=TF,
        max_bars=1,
    )[0]
    assert first.strategy_state is not None
    resume = SessionResume(
        checkpoint_ts=first.ts,
        average_entry=first.average_entry,
        strategy_state=first.strategy_state,
        source=Path("prior.jsonl"),
    )

    second = collect(
        strategy=HeartbeatProbe(weight=0.05, period=1),
        broker=broker(client),
        feed=[bars(2)[1]],
        inst_id=INST,
        timeframe=TF,
        max_bars=1,
        resume=resume,
    )[0]

    assert second.target == 0.0
    assert second.fill is not None
    assert second.fill.side is Side.SELL
    assert second.average_entry is None
    assert second.strategy_state == {"count": 2, "weight": 0.05, "period": 1}
