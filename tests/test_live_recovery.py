"""Restart reconciliation: durable state must agree with the exchange."""

import json

import pytest

from cq.core.types import Fill, MarketSpec, Side
from cq.live.broker import LiveBroker
from cq.live.protocols import CollateralBalance, ProtectiveOrder, SwapPosition
from cq.live.recovery import (
    CHECKPOINT_VERSION,
    PaperCheckpoint,
    RecoveryError,
    load_latest_checkpoint,
    reconcile_restart,
)

INST = "DOGE-USDT"
TF = "1h"
SPEC = MarketSpec(INST, "spot", lot_size=1e-06)
SWAP_INST = "DOGE-USDT-SWAP"
SWAP_SPEC = MarketSpec(
    SWAP_INST,
    "swap",
    lot_size=100.0,
    max_leverage=2.0,
    contract_size=100.0,
)


class RecoveryClient:
    def __init__(self, held=100.0, cash=900.0, pending=()):
        self.held = held
        self.cash = cash
        self.pending = list(pending)
        self.placed = []
        self.algo_states = {}

    def milliseconds(self):
        return 0

    def free_balance(self, ccy):
        return self.cash

    def base_holding(self, inst_id):
        return self.held

    def last_price(self, inst_id):
        return 1.0

    def round_amount(self, inst_id, quantity):
        return quantity

    def market_order(self, inst_id, side, quantity, reason="", client_order_id=None):
        return Fill(0, inst_id, side, quantity, 1.0, 0.0, reason)

    def place_protective_order(
        self,
        inst_id,
        side,
        quantity,
        stop_loss=None,
        take_profit=None,
        client_order_id=None,
    ):
        algo_id = f"replacement-{len(self.placed) + 1}"
        order = ProtectiveOrder(
            algo_id,
            quantity,
            stop_loss,
            take_profit,
            side,
            client_order_id,
        )
        self.placed.append(order)
        self.pending = [order]
        return algo_id

    def cancel_algo_order(self, inst_id, algo_id):
        self.pending = [order for order in self.pending if order.algo_id != algo_id]

    def pending_protective_orders(self, inst_id):
        return list(self.pending)

    def protective_order_state(self, inst_id, algo_id):
        return self.algo_states[algo_id]

    def configure_swap(self, inst_id, leverage, margin_mode="cross"):
        return None

    def swap_position(self, inst_id):
        return SwapPosition(
            self.held,
            0.073 if self.held else None,
            0.073,
            None,
            2.0,
            "cross",
        )

    def collateral_balance(self, ccy):
        return CollateralBalance(self.cash, self.cash, self.cash)

    def swap_account_events(self, inst_id, begin_ms, end_ms):
        return []


def make_broker(client, spec=SPEC):
    minimum = 100.0 if spec.market_type == "swap" else 1.0
    return LiveBroker(client=client, spec=spec, min_base_amount=minimum)


def checkpoint(tmp_path, protection=None, held=100.0, average_entry=0.073):
    return PaperCheckpoint(
        ts=123,
        inst_id=INST,
        timeframe=TF,
        strategy="heartbeat-probe",
        target=0.05,
        held=held,
        cash=900.0,
        average_entry=average_entry,
        strategy_state={"count": 7, "weight": 0.05, "period": 1},
        protection=protection,
        source=tmp_path / "prior.jsonl",
    )


def checkpoint_row():
    return {
        "checkpoint_version": CHECKPOINT_VERSION,
        "ts": 123,
        "inst_id": INST,
        "timeframe": TF,
        "strategy": "heartbeat-probe",
        "target": 0.05,
        "held_after": 100.0,
        "cash_after": 900.0,
        "average_entry": 0.073,
        "strategy_state": {"count": 7, "weight": 0.05, "period": 1},
        "protection": None,
    }


def test_loader_uses_the_last_complete_checkpoint_after_a_torn_line(tmp_path):
    path = tmp_path / f"{INST}_{TF}_20260721T000000Z.jsonl"
    path.write_text(json.dumps(checkpoint_row()) + "\n{\"broken\":", encoding="utf-8")

    loaded = load_latest_checkpoint(tmp_path, INST, TF)

    assert loaded is not None
    assert loaded.ts == 123
    assert loaded.strategy_state == {"count": 7, "weight": 0.05, "period": 1}


def test_legacy_log_is_not_misread_as_a_resumable_checkpoint(tmp_path):
    path = tmp_path / f"{INST}_{TF}_20260721T000000Z.jsonl"
    path.write_text('{"ts": 123, "held": 100}\n', encoding="utf-8")

    assert load_latest_checkpoint(tmp_path, INST, TF) is None


def test_swap_checkpoint_accepts_signed_position_and_restores_bill_cursor(tmp_path):
    row = {
        **checkpoint_row(),
        "inst_id": SWAP_INST,
        "target": -0.2,
        "held_after": -300.0,
        "account_event_cursor": 456,
    }
    path = tmp_path / f"{SWAP_INST}_{TF}_20260721T000000Z.jsonl"
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")

    loaded = load_latest_checkpoint(tmp_path, SWAP_INST, TF)

    assert loaded is not None
    assert loaded.held == -300.0
    assert loaded.account_event_cursor == 456


def test_matching_position_and_pending_algo_are_adopted(tmp_path):
    protection = ProtectiveOrder("algo-1", 100.0, 0.06, 0.08)
    client = RecoveryClient(pending=[protection])
    broker = make_broker(client)

    resume = reconcile_restart(
        "heartbeat-probe", broker, checkpoint(tmp_path, protection=protection)
    )

    assert resume is not None
    assert resume.average_entry == 0.073
    assert resume.strategy_state == {"count": 7, "weight": 0.05, "period": 1}
    assert broker.active_protection == protection
    assert client.placed == []


def test_matching_swap_short_and_buy_protection_are_adopted(tmp_path):
    protection = ProtectiveOrder("algo-short", 300.0, 0.08, 0.06, Side.BUY)
    client = RecoveryClient(held=-300.0, pending=[protection])
    broker = make_broker(client, SWAP_SPEC)
    saved = PaperCheckpoint(
        ts=123,
        inst_id=SWAP_INST,
        timeframe=TF,
        strategy="heartbeat-probe",
        target=-0.2,
        held=-300.0,
        cash=900.0,
        average_entry=0.073,
        strategy_state={"count": 7, "weight": 0.05, "period": 1},
        protection=protection,
        source=tmp_path / "prior.jsonl",
        account_event_cursor=456,
    )

    resume = reconcile_restart("heartbeat-probe", broker, saved)

    assert resume is not None
    assert resume.average_entry == 0.073
    assert resume.account_event_cursor == 456
    assert broker.active_protection == protection


def test_swap_short_rejects_a_sell_protective_algo(tmp_path):
    wrong = ProtectiveOrder("wrong-side", 300.0, 0.08, 0.06, Side.SELL)
    broker = make_broker(RecoveryClient(held=-300.0, pending=[wrong]), SWAP_SPEC)

    with pytest.raises(RecoveryError, match="does not reduce"):
        reconcile_restart("heartbeat-probe", broker, None)


def test_missing_logged_protection_is_rebuilt_for_actual_holding(tmp_path):
    logged = ProtectiveOrder("old-algo", 100.0, 0.06, 0.08)
    client = RecoveryClient(pending=[])
    client.algo_states["old-algo"] = "canceled"
    broker = make_broker(client)

    reconcile_restart("heartbeat-probe", broker, checkpoint(tmp_path, protection=logged))

    assert broker.active_protection is not None
    assert broker.active_protection.algo_id == "replacement-1"
    assert broker.active_protection.client_order_id is not None
    assert (broker.active_protection.stop_loss, broker.active_protection.take_profit) == (
        0.06,
        0.08,
    )


def test_recovery_adopts_its_already_placed_replacement_after_a_second_crash(tmp_path):
    logged = ProtectiveOrder("old-algo", 100.0, 0.06, 0.08)
    first_client = RecoveryClient(pending=[])
    first_client.algo_states["old-algo"] = "canceled"
    first_broker = make_broker(first_client)
    saved = checkpoint(tmp_path, protection=logged)

    reconcile_restart("heartbeat-probe", first_broker, saved)
    replacement = first_broker.active_protection
    assert replacement is not None

    second_client = RecoveryClient(pending=[replacement])
    second_broker = make_broker(second_client)
    reconcile_restart("heartbeat-probe", second_broker, saved)

    assert second_broker.active_protection == replacement
    assert second_client.placed == []


def test_triggered_but_not_reconciled_algo_is_not_duplicated(tmp_path):
    logged = ProtectiveOrder("triggered", 100.0, 0.06, 0.08)
    client = RecoveryClient(pending=[])
    client.algo_states["triggered"] = "effective"
    broker = make_broker(client)

    with pytest.raises(RecoveryError, match="absent from pending orders"):
        reconcile_restart(
            "heartbeat-probe", broker, checkpoint(tmp_path, protection=logged)
        )

    assert client.placed == []


def test_unexplained_nonflat_exchange_position_is_rejected():
    broker = make_broker(RecoveryClient(held=100.0))

    with pytest.raises(RecoveryError, match="no resumable checkpoint"):
        reconcile_restart("heartbeat-probe", broker, None)


def test_holding_mismatch_is_rejected(tmp_path):
    broker = make_broker(RecoveryClient(held=90.0))

    with pytest.raises(RecoveryError, match="does not match checkpoint"):
        reconcile_restart("heartbeat-probe", broker, checkpoint(tmp_path))


def test_unknown_pending_algo_is_rejected(tmp_path):
    unknown = ProtectiveOrder("unknown", 100.0, 0.05, None)
    broker = make_broker(RecoveryClient(pending=[unknown]))

    with pytest.raises(RecoveryError, match="absent from checkpoint"):
        reconcile_restart("heartbeat-probe", broker, checkpoint(tmp_path))


def test_wrong_protection_size_is_rejected_even_when_algo_id_matches(tmp_path):
    logged = ProtectiveOrder("algo-1", 90.0, 0.06, 0.08)
    venue = ProtectiveOrder("algo-1", 90.0, 0.06, 0.08)
    broker = make_broker(RecoveryClient(held=100.0, pending=[venue]))

    with pytest.raises(RecoveryError, match="does not cover exchange holding"):
        reconcile_restart(
            "heartbeat-probe", broker, checkpoint(tmp_path, protection=logged)
        )


def test_a_triggered_exit_can_resume_flat_with_no_cost_basis(tmp_path):
    broker = make_broker(RecoveryClient(held=0.0, cash=1005.0))

    resume = reconcile_restart(
        "heartbeat-probe",
        broker,
        checkpoint(
            tmp_path,
            protection=ProtectiveOrder("filled", 100.0, 0.06, 0.08),
        ),
    )

    assert resume is not None
    assert resume.average_entry is None
    assert resume.strategy_state == {"count": 7, "weight": 0.05, "period": 1}
