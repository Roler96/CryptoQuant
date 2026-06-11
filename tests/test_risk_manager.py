"""Tests for RiskManager."""
import time

import pytest

from cryptoquant.risk.manager import RiskManager


@pytest.fixture
def rm():
    return RiskManager(
        max_positions=3,
        max_daily_trades=5,
        max_daily_loss_pct=5.0,
        max_daily_loss_abs=500.0,
        max_drawdown_pct=20.0,
        min_balance=50.0,
        initial_balance=10000.0,
        emergency_cooldown_minutes=1,  # Short for testing
    )


class TestCanEnter:
    def test_all_clear(self, rm):
        allowed, reason = rm.can_enter("BTC/USDT", 1, 10000.0)
        assert allowed
        assert reason == "ok"

    def test_max_positions(self, rm):
        rm.record_entry("BTC/USDT", "long")
        rm.record_entry("ETH/USDT", "long")
        rm.record_entry("SOL/USDT", "long")
        allowed, reason = rm.can_enter("DOGE/USDT", 1, 10000.0, current_positions=3)
        assert not allowed
        assert "max positions" in reason

    def test_already_holding(self, rm):
        rm.record_entry("BTC/USDT", "long")
        allowed, reason = rm.can_enter("BTC/USDT", 1, 10000.0)
        assert not allowed
        assert "already holding" in reason

    def test_daily_trade_limit(self, rm):
        for i in range(5):
            rm.record_exit(f"SYM{i}/USDT", 0.1, 1.0)
        allowed, reason = rm.can_enter("BTC/USDT", 1, 10000.0)
        assert not allowed
        assert "daily trade limit" in reason

    def test_daily_loss_limit_abs(self, rm):
        rm.record_exit("X/USDT", -10.0, -600.0)
        allowed, reason = rm.can_enter("BTC/USDT", 1, 10000.0)
        assert not allowed
        assert "daily loss limit" in reason

    def test_balance_below_min(self, rm):
        allowed, reason = rm.can_enter("BTC/USDT", 1, 10.0)
        assert not allowed
        assert "below minimum" in reason
        assert rm.is_emergency_stop()

    def test_drawdown_triggers_emergency(self, rm):
        rm.update_balance(7000.0)
        rm.reset_daily(7000.0)
        rm._peak_balance = 10000.0
        allowed, reason = rm.can_enter("BTC/USDT", 1, 7000.0)
        assert not allowed
        assert "drawdown" in reason
        assert rm.is_emergency_stop()


class TestEmergencyStop:
    def test_blocks_all(self, rm):
        rm._trigger_emergency("test")
        allowed, reason = rm.can_enter("BTC/USDT", 1, 10000.0)
        assert not allowed
        assert "emergency" in reason

    def test_cooldown_recovery(self, rm):
        rm._emergency_triggered_at = time.time() - 120  # 2 minutes ago
        rm.is_emergency_stop()  # Should recover (cooldown=1min)
        assert not rm._emergency_stop

    def test_clear_emergency(self, rm):
        rm._trigger_emergency("test")
        rm.clear_emergency()
        assert not rm._emergency_stop


class TestRecordExit:
    def test_updates_stats(self, rm):
        rm.record_exit("BTC/USDT", 2.5, 250.0)
        stats = rm.get_daily_stats()
        assert stats.total_trades == 1
        assert stats.wins == 1
        assert stats.total_pnl_pct == 2.5

    def test_loss_recorded(self, rm):
        rm.record_exit("BTC/USDT", -1.5, -150.0)
        stats = rm.get_daily_stats()
        assert stats.losses == 1


class TestBalanceTracking:
    def test_peak_tracking(self, rm):
        rm.update_balance(12000.0)
        assert rm._peak_balance == 12000.0
        rm.update_balance(11000.0)
        assert rm._peak_balance == 12000.0  # Peak unchanged

    def test_calibrate(self, rm):
        rm.update_balance(10050.0, calibrate=True)
        assert rm._daily_stats.current_balance == 10050.0


class TestResetDaily:
    def test_reset(self, rm):
        rm.record_exit("X/USDT", 1.0, 100.0)
        rm.reset_daily(10100.0)
        stats = rm.get_daily_stats()
        assert stats.total_trades == 0
        assert stats.start_balance == 10100.0
