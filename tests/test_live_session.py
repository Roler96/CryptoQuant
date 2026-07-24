"""The paper loop: closed-bar decisions, round trips, warmup, bounded runs."""

from dataclasses import dataclass
from pathlib import Path

import pytest

from cq.context import Bar, Context
from cq.core.types import Fill, Intent, MarketSpec, Side, Sizing
from cq.engine.sizing import target_delta
from cq.live.broker import LiveBroker
from cq.live.commands import _event_row
from cq.live.probe import HeartbeatProbe
from cq.live.protocols import AccountEvent, CollateralBalance, SwapPosition
from cq.live.recovery import CHECKPOINT_VERSION, RecoveryError, SessionResume
from cq.live.session import PaperEvent, run_paper

INST = "DOGE-USDT"
TF = "1h"
HOUR = 3_600_000
SPEC = MarketSpec(INST, "spot", lot_size=1e-06)
SWAP_INST = "DOGE-USDT-SWAP"
SWAP_SPEC = MarketSpec(
    SWAP_INST,
    "swap",
    lot_size=100.0,
    max_leverage=2.0,
    contract_size=100.0,
)


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

    def milliseconds(self) -> int:
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

    def configure_swap(self, inst_id, leverage, margin_mode="cross"):
        return None

    def swap_position(self, inst_id) -> SwapPosition:
        raise AssertionError("spot test unexpectedly requested a swap position")

    def collateral_balance(self, ccy) -> CollateralBalance:
        raise AssertionError("spot test unexpectedly requested collateral")

    def swap_account_events(self, inst_id, begin_ms, end_ms) -> list[AccountEvent]:
        raise AssertionError("spot test unexpectedly requested swap bills")


class SwapTradeClient(FakeTradeClient):
    """A net-position derivative venue whose collateral is not spent on entry."""

    def __init__(self):
        super().__init__(cash=1000.0, held=0.0)
        self.clock = 0
        self.average_entry = None
        self.event_calls = []
        self.events = [
            AccountEvent(
                bill_id="funding-1",
                ts=1500,
                kind="funding",
                amount=-0.25,
                currency="USDT",
                price=0.073,
                quantity=200.0,
                subtype="173",
            )
        ]

    def milliseconds(self):
        self.clock += 1000
        return self.clock

    def market_order(self, inst_id, side, quantity, reason="", client_order_id=None):
        self.market_client_order_ids.append(client_order_id)
        self.held += side.sign * quantity
        self.average_entry = 0.073 if self.held else None
        fill = Fill(0, inst_id, side, quantity, 0.073, 0.0, reason)
        self.orders.append(fill)
        self.actions.append(("market", side))
        return fill

    def swap_position(self, inst_id):
        return SwapPosition(
            self.held,
            self.average_entry,
            0.073,
            0.2 if self.held < 0 else None,
            2.0,
            "cross",
        )

    def collateral_balance(self, ccy):
        return CollateralBalance(self.cash, 1000.0, 900.0)

    def swap_account_events(self, inst_id, begin_ms, end_ms):
        self.event_calls.append((begin_ms, end_ms))
        return [event for event in self.events if begin_ms <= event.ts <= end_ms]


def broker(client=None):
    return LiveBroker(client=client or FakeTradeClient(), spec=SPEC, min_base_amount=1.0)


def swap_broker(client):
    return LiveBroker(client=client, spec=SWAP_SPEC, min_base_amount=100.0)


def bars(n, start_close=0.073):
    return [
        Bar(
            ts=i * HOUR,
            open=start_close,
            high=start_close,
            low=start_close,
            close=start_close,
            volume=100.0,
        )
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


@dataclass
class _RepeatedTarget:
    name = "repeated-target"
    warmup_bars = 1

    def on_bar(self, ctx: Context) -> Intent:
        return Intent(target=0.2)


@dataclass
class _CheckpointRepeatedTarget:
    name = "checkpoint-repeated-target"
    warmup_bars = 1
    count: int = 0

    def on_bar(self, ctx: Context) -> Intent:
        self.count += 1
        return Intent(target=0.2)

    def snapshot_state(self) -> dict[str, object]:
        return {"count": self.count}

    def restore_state(self, state: dict[str, object]) -> None:
        count = state["count"]
        if isinstance(count, bool) or not isinstance(count, int):
            raise ValueError("invalid count")
        self.count = count


def test_on_entry_sizes_once_while_rebalance_resizes_the_same_target():
    moving = [
        Bar(0, 0.073, 0.073, 0.073, 0.073, 100.0),
        Bar(HOUR, 0.146, 0.146, 0.146, 0.146, 100.0),
    ]
    on_entry = collect(
        strategy=_RepeatedTarget(),
        broker=broker(),
        feed=moving,
        inst_id=INST,
        timeframe=TF,
        max_bars=2,
        sizing=Sizing.ON_ENTRY,
    )
    rebalance = collect(
        strategy=_RepeatedTarget(),
        broker=broker(),
        feed=moving,
        inst_id=INST,
        timeframe=TF,
        max_bars=2,
        sizing=Sizing.REBALANCE,
    )

    assert [event.fill is not None for event in on_entry] == [True, False]
    assert [event.fill is not None for event in rebalance] == [True, True]
    assert [event.sizing for event in on_entry] == ["on_entry", "on_entry"]
    assert [event.active_target_before for event in on_entry] == [0.0, 0.2]
    assert [event.active_target_after for event in on_entry] == [0.2, 0.2]


def test_on_entry_retries_a_target_transition_after_rejection():
    client = FakeTradeClient()
    rejecting = LiveBroker(client=client, spec=SPEC, min_base_amount=10_000.0)

    events = collect(
        strategy=_RepeatedTarget(),
        broker=rejecting,
        feed=bars(2),
        inst_id=INST,
        timeframe=TF,
        max_bars=2,
        sizing=Sizing.ON_ENTRY,
    )

    assert [event.rejected for event in events] == [1, 1]
    assert [event.active_target_after for event in events] == [0.0, 0.0]


def test_on_entry_resume_restores_active_target_without_rebalancing():
    client = FakeTradeClient()
    first = collect(
        strategy=_CheckpointRepeatedTarget(),
        broker=broker(client),
        feed=bars(1),
        inst_id=INST,
        timeframe=TF,
        max_bars=1,
        sizing=Sizing.ON_ENTRY,
    )[0]
    assert first.fill is not None
    assert first.strategy_state is not None
    resume = SessionResume(
        checkpoint_ts=first.ts,
        average_entry=first.average_entry,
        strategy_state=first.strategy_state,
        source=Path("prior.jsonl"),
        sizing=Sizing.ON_ENTRY,
        active_target=first.active_target_after,
    )

    second = collect(
        strategy=_CheckpointRepeatedTarget(),
        broker=broker(client),
        feed=[Bar(HOUR, 0.146, 0.146, 0.146, 0.146, 100.0)],
        inst_id=INST,
        timeframe=TF,
        max_bars=1,
        resume=resume,
        sizing=Sizing.ON_ENTRY,
    )[0]

    assert second.fill is None
    assert second.active_target_before == 0.2
    assert second.active_target_after == 0.2


def test_fresh_on_entry_session_refuses_unexplained_holding():
    with pytest.raises(RecoveryError, match="requires a flat"):
        collect(
            strategy=_RepeatedTarget(),
            broker=broker(FakeTradeClient(held=100.0)),
            feed=bars(1),
            inst_id=INST,
            timeframe=TF,
            sizing=Sizing.ON_ENTRY,
        )


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


@dataclass
class _ProtectedShort:
    name = "protected-short"
    warmup_bars = 1

    def on_bar(self, ctx: Context) -> Intent:
        return Intent(target=-0.2, stop_loss=0.08, take_profit=0.06, reason="short")


def test_swap_session_uses_signed_position_equity_and_logs_exchange_events():
    client = SwapTradeClient()

    event = collect(
        strategy=_ProtectedShort(),
        broker=swap_broker(client),
        feed=bars(1),
        inst_id=SWAP_INST,
        timeframe=TF,
        max_bars=1,
    )[0]
    row = _event_row(event)

    assert event.fill is not None
    assert event.fill.side is Side.SELL
    assert event.held_after < 0
    assert event.cash_after == 1000.0
    assert event.equity == 1000.0
    assert event.average_entry == 0.073
    assert event.protection is not None
    assert event.protection.side is Side.BUY
    assert client.event_calls == [(1001, 2000)]
    assert event.account_event_cursor == 2000
    assert row["account_events"] == [
        {
            "bill_id": "funding-1",
            "ts": 1500,
            "kind": "funding",
            "amount": -0.25,
            "currency": "USDT",
            "price": 0.073,
            "quantity": 200.0,
            "subtype": "173",
        }
    ]


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
    assert row["open"] == event.close
    assert row["high"] == event.close
    assert row["low"] == event.close
    assert row["volume"] == 100.0
    assert row["held_after"] > 0
    assert row["cash_after"] < 1000.0
    assert row["average_entry"] == pytest.approx(0.073)
    assert row["strategy_state"] == {"count": 1, "weight": 0.05, "period": 1}
    assert row["sizing"] == "rebalance"
    assert row["active_target_before"] == 0.0
    assert row["active_target_after"] == 0.05


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
