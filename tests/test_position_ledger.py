"""Tests for ManagedPositionLedger — FIFO cost basis and realized PnL."""

import pytest

from cryptoquant.position import (
    ManagedPositionLedger,
)


class TestRecordBuy:
    def test_single_buy(self):
        ledger = ManagedPositionLedger()
        ledger.record_buy("BTC/USDT", 0.1, 50000.0, timestamp=1000)

        pos = ledger.get_position("BTC/USDT")
        assert pos is not None
        assert pos.amount == 0.1
        assert pos.avg_entry_price == 50000.0

    def test_multiple_buys_average_price(self):
        ledger = ManagedPositionLedger()
        ledger.record_buy("BTC/USDT", 0.1, 50000.0, timestamp=1000)
        ledger.record_buy("BTC/USDT", 0.1, 60000.0, timestamp=2000)

        pos = ledger.get_position("BTC/USDT")
        assert pos.amount == 0.2
        # (0.1*50000 + 0.1*60000) / 0.2 = 55000
        assert pos.avg_entry_price == pytest.approx(55000.0)

    def test_multi_symbol_independent(self):
        ledger = ManagedPositionLedger()
        ledger.record_buy("BTC/USDT", 0.1, 50000.0)
        ledger.record_buy("ETH/USDT", 1.0, 3000.0)

        btc = ledger.get_position("BTC/USDT")
        eth = ledger.get_position("ETH/USDT")
        assert btc.amount == 0.1
        assert eth.amount == 1.0

    def test_zero_amount_raises(self):
        ledger = ManagedPositionLedger()
        with pytest.raises(ValueError):
            ledger.record_buy("BTC/USDT", 0.0, 50000.0)

    def test_negative_amount_raises(self):
        ledger = ManagedPositionLedger()
        with pytest.raises(ValueError):
            ledger.record_buy("BTC/USDT", -0.1, 50000.0)


class TestRecordSell:
    def test_full_sell(self):
        ledger = ManagedPositionLedger()
        ledger.record_buy("BTC/USDT", 0.1, 50000.0, fee=5.0, timestamp=1000)

        trade = ledger.record_sell(
            "BTC/USDT", 0.1, 51000.0, fee=5.0, timestamp=2000,
            exit_reason="take_profit",
        )

        # PnL: exit (0.1*51000) - entry (0.1*50000) - fees (5+5)
        # = 5100 - 5000 - 10 = 90
        assert trade.realized_pnl == pytest.approx(90.0)
        assert trade.realized_pnl_pct == pytest.approx(90.0 / 5005.0 * 100, rel=1e-6)
        assert trade.exit_reason == "take_profit"
        assert trade.symbol == "BTC/USDT"
        assert trade.amount == 0.1

        # Position should be closed
        assert not ledger.has_position("BTC/USDT")
        assert ledger.get_position("BTC/USDT") is None

    def test_partial_sell_fifo(self):
        """Sell part of position — consumes oldest lot first."""
        ledger = ManagedPositionLedger()
        ledger.record_buy("BTC/USDT", 0.1, 50000.0, timestamp=1000)  # lot 1
        ledger.record_buy("BTC/USDT", 0.1, 60000.0, timestamp=2000)  # lot 2

        trade = ledger.record_sell("BTC/USDT", 0.1, 55000.0, timestamp=3000)

        # Sells lot 1 (50000): exit 5500 - entry 5000 = 500 profit
        assert trade.realized_pnl == pytest.approx(500.0)
        assert trade.entry_price == pytest.approx(50000.0)

        # Remaining position: lot 2 (0.1 @ 60000)
        pos = ledger.get_position("BTC/USDT")
        assert pos.amount == 0.1
        assert pos.avg_entry_price == 60000.0

    def test_partial_sell_crosses_lots(self):
        """Sell 0.15 when holding 0.1+0.1 = 0.2."""
        ledger = ManagedPositionLedger()
        ledger.record_buy("BTC/USDT", 0.1, 50000.0, timestamp=1000)
        ledger.record_buy("BTC/USDT", 0.1, 60000.0, timestamp=2000)

        trade = ledger.record_sell("BTC/USDT", 0.15, 55000.0, timestamp=3000)

        # Consumes: 0.1 from lot1 + 0.05 from lot2
        # entry_cost = 0.1*50000 + 0.05*60000 = 5000 + 3000 = 8000
        # exit_proceeds = 0.15*55000 = 8250
        # pnl = 8250 - 8000 = 250
        assert trade.realized_pnl == pytest.approx(250.0)
        # avg entry = 8000/0.15 = 53333.33...
        assert trade.entry_price == pytest.approx(8000.0 / 0.15)

        # Remaining: 0.05 from lot2 at 60000
        pos = ledger.get_position("BTC/USDT")
        assert pos.amount == pytest.approx(0.05)
        assert pos.avg_entry_price == pytest.approx(60000.0)

    def test_sell_more_than_held_raises(self):
        ledger = ManagedPositionLedger()
        ledger.record_buy("BTC/USDT", 0.1, 50000.0)

        with pytest.raises(ValueError, match="Insufficient position"):
            ledger.record_sell("BTC/USDT", 0.2, 50000.0)

    def test_sell_unknown_symbol_raises(self):
        ledger = ManagedPositionLedger()
        with pytest.raises(ValueError, match="Insufficient position"):
            ledger.record_sell("BTC/USDT", 0.1, 50000.0)


class TestRealizedPnl:
    def test_total_realized_pnl(self):
        ledger = ManagedPositionLedger()
        # Trade 1: buy 50000, sell 51000 → +100 (no fees)
        ledger.record_buy("BTC/USDT", 0.1, 50000.0)
        ledger.record_sell("BTC/USDT", 0.1, 51000.0)
        # Trade 2: buy 60000, sell 55000 → -500
        ledger.record_buy("BTC/USDT", 0.1, 60000.0)
        ledger.record_sell("BTC/USDT", 0.1, 55000.0)

        assert ledger.get_realized_pnl() == pytest.approx(-400.0)
        assert ledger.get_realized_pnl("BTC/USDT") == pytest.approx(-400.0)
        assert ledger.get_realized_pnl("ETH/USDT") == 0.0

    def test_trade_history(self):
        ledger = ManagedPositionLedger()
        ledger.record_buy("BTC/USDT", 0.1, 50000.0, timestamp=1000)
        ledger.record_sell("BTC/USDT", 0.1, 51000.0, timestamp=2000)

        trades = ledger.closed_trades
        assert len(trades) == 1
        assert trades[0].entry_time == 1000
        assert trades[0].exit_time == 2000

    def test_entry_time_is_earliest_lot_when_sell_spans_lots(self):
        """A sell consuming several FIFO lots dates the trade from the oldest
        lot, so entry_time measures how long the position was actually held.
        Single-lot tests can't see this — min and max agree there.
        """
        ledger = ManagedPositionLedger()
        ledger.record_buy("BTC/USDT", 0.1, 50000.0, timestamp=1000)
        ledger.record_buy("BTC/USDT", 0.1, 52000.0, timestamp=5000)

        trade = ledger.record_sell("BTC/USDT", 0.15, 53000.0, timestamp=9000)

        assert trade.entry_time == 1000


class TestFees:
    def test_entry_fee_reduces_realized_pnl(self):
        ledger = ManagedPositionLedger()
        ledger.record_buy("BTC/USDT", 0.1, 50000.0, fee=50.0)
        trade = ledger.record_sell("BTC/USDT", 0.1, 50000.0, fee=50.0)

        # Flat market, only fees: -100
        assert trade.realized_pnl == pytest.approx(-100.0)

    def test_fee_proration_on_partial_sell(self):
        """When selling part of a lot, fee is prorated."""
        ledger = ManagedPositionLedger()
        ledger.record_buy("BTC/USDT", 0.1, 50000.0, fee=100.0)

        trade = ledger.record_sell("BTC/USDT", 0.05, 51000.0, fee=0.0)

        # Half the lot → half the entry fee: 50
        # pnl = 0.05*51000 - 0.05*50000 - 50 = 2550 - 2500 - 50 = 0
        assert trade.entry_fee == pytest.approx(50.0)
        assert trade.realized_pnl == pytest.approx(0.0)


class TestPositionSnapshot:
    def test_empty_position(self):
        ledger = ManagedPositionLedger()
        assert ledger.get_position("BTC/USDT") is None
        assert not ledger.has_position("BTC/USDT")
        assert ledger.get_total_held("BTC/USDT") == 0.0

    def test_active_symbols(self):
        ledger = ManagedPositionLedger()
        ledger.record_buy("BTC/USDT", 0.1, 50000.0)
        ledger.record_buy("ETH/USDT", 1.0, 3000.0)

        syms = ledger.active_symbols
        assert sorted(syms) == ["BTC/USDT", "ETH/USDT"]

    def test_sell_all_removes_from_active(self):
        ledger = ManagedPositionLedger()
        ledger.record_buy("BTC/USDT", 0.1, 50000.0)
        ledger.record_sell("BTC/USDT", 0.1, 50000.0)

        assert ledger.active_symbols == []

    def test_cost_basis_includes_fees(self):
        ledger = ManagedPositionLedger()
        ledger.record_buy("BTC/USDT", 0.1, 50000.0, fee=50.0)

        pos = ledger.get_position("BTC/USDT")
        assert pos.total_fees == 50.0
        assert pos.cost_basis == pytest.approx(5000.0 + 50.0)


class TestSerialization:
    def test_roundtrip(self):
        ledger = ManagedPositionLedger()
        ledger.record_buy("BTC/USDT", 0.1, 50000.0, fee=5.0, timestamp=1000)
        ledger.record_buy("ETH/USDT", 1.0, 3000.0, timestamp=2000)
        ledger.record_sell("BTC/USDT", 0.05, 51000.0, timestamp=3000,
                           exit_reason="take_profit")

        data = ledger.to_dict()
        restored = ManagedPositionLedger.from_dict(data)

        # Verify position
        btc = restored.get_position("BTC/USDT")
        assert btc.amount == 0.05
        assert btc.avg_entry_price == 50000.0

        eth = restored.get_position("ETH/USDT")
        assert eth.amount == 1.0

        # Verify closed trade
        assert len(restored.closed_trades) == 1
        assert restored.closed_trades[0].exit_reason == "take_profit"
        assert restored.closed_trades[0].realized_pnl == pytest.approx(47.5)

    def test_empty_roundtrip(self):
        data = ManagedPositionLedger().to_dict()
        restored = ManagedPositionLedger.from_dict(data)
        assert restored.active_symbols == []
        assert restored.closed_trades == []
        assert restored.get_realized_pnl() == 0.0

    def test_restore_mutates_in_place(self):
        """restore() must update the existing instance, not return a new one —
        Broker/ExecutionLifecycle/LiveEngine share a single ledger by reference."""
        source = ManagedPositionLedger()
        source.record_buy("BTC/USDT", 0.1, 50000.0, fee=5.0, timestamp=1000)
        data = source.to_dict()

        shared = ManagedPositionLedger()
        other_ref = shared  # simulates Broker holding the same object

        shared.restore(data)

        assert other_ref.get_position("BTC/USDT").amount == 0.1
        assert other_ref is shared
