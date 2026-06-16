"""Tests for RiskManager."""
import time

import pytest

from cryptoquant.risk.manager import DrawdownTier, RiskManager


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
        emergency_cooldown_minutes=1,
        drawdown_tier1_pct=10.0,
        drawdown_tier2_pct=15.0,
        drawdown_tier3_pct=20.0,
        tier_cooldown_minutes=1,
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
        rm._emergency_triggered_at = time.time() - 120
        rm.is_emergency_stop()
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
        assert rm._peak_balance == 12000.0

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


class TestDrawdownTiers:
    def test_9pct_dd_normal(self, rm):
        rm._peak_balance = 10000.0
        rm.update_balance(9100.0)
        tier = rm.current_tier()
        assert tier == DrawdownTier.NORMAL
        assert rm.position_size_multiplier() == pytest.approx(1.0)

    def test_12pct_dd_reduce_half(self, rm):
        rm._peak_balance = 10000.0
        rm.update_balance(8800.0)
        tier = rm.current_tier()
        assert tier == DrawdownTier.REDUCE_HALF
        assert rm.position_size_multiplier() == pytest.approx(0.5)

    def test_17pct_dd_reduce_quarter(self, rm):
        rm._peak_balance = 10000.0
        rm.update_balance(8300.0)
        tier = rm.current_tier()
        assert tier == DrawdownTier.REDUCE_QUARTER
        assert rm.position_size_multiplier() == pytest.approx(0.25)

    def test_25pct_dd_halt(self, rm):
        rm._peak_balance = 10000.0
        rm.update_balance(7500.0)
        tier = rm.current_tier()
        assert tier == DrawdownTier.HALT
        assert rm.position_size_multiplier() == pytest.approx(0.0)

    def test_halt_blocks_entry(self, rm):
        rm.reset_daily(8000.0)
        rm._peak_balance = 10000.0
        rm.update_balance(8000.0)
        allowed, reason = rm.can_enter("BTC/USDT", 1, 8000.0)
        assert not allowed
        assert "halt" in reason

    def test_reduce_half_allows_entry_with_multiplier(self, rm):
        rm.reset_daily(8800.0)
        rm._peak_balance = 10000.0
        rm.update_balance(8800.0)
        allowed, reason = rm.can_enter("BTC/USDT", 1, 8800.0)
        assert allowed
        assert "multiplier=0.5" in reason

    def test_recovery_reduces_tier(self, rm):
        rm._peak_balance = 10000.0
        rm.update_balance(7500.0)
        assert rm.current_tier() == DrawdownTier.HALT
        rm.update_balance(10000.0)
        assert rm.current_tier() == DrawdownTier.NORMAL

    def test_tier_cooldown_before_downgrade(self, rm):
        rm._peak_balance = 10000.0
        rm.update_balance(8800.0)
        assert rm.current_tier() == DrawdownTier.REDUCE_HALF
        rm.update_balance(9100.0)
        assert rm.current_tier() == DrawdownTier.REDUCE_HALF
        rm._tier_triggered_at = time.time() - 120
        assert rm.current_tier() == DrawdownTier.NORMAL

    def test_tier1_threshold_exact(self, rm):
        rm._peak_balance = 10000.0
        rm.update_balance(9000.0)
        assert rm.current_tier() == DrawdownTier.REDUCE_HALF

    def test_tier2_threshold_exact(self, rm):
        rm._peak_balance = 10000.0
        rm.update_balance(8500.0)
        assert rm.current_tier() == DrawdownTier.REDUCE_QUARTER

    def test_tier3_threshold_exact(self, rm):
        rm._peak_balance = 10000.0
        rm.update_balance(8000.0)
        assert rm.current_tier() == DrawdownTier.HALT


class TestCVaR:
    def test_cvar_blocks_entry(self, rm):
        rm.max_daily_trades = 100
        rm.max_daily_loss_abs = 50000.0
        rm.cvar_threshold_pct = 5.0
        for _ in range(20):
            rm.record_exit("BTC/USDT", -10.0, -1000.0)
        allowed, reason = rm.can_enter("BTC/USDT", 1, 10000.0)
        assert not allowed
        assert "CVaR" in reason

    def test_cvar_allows_entry_when_safe(self, rm):
        rm.max_daily_trades = 100
        rm.max_daily_loss_abs = 50000.0
        rm.cvar_threshold_pct = 5.0
        for _ in range(20):
            rm.record_exit("BTC/USDT", 1.0, 100.0)
        allowed, reason = rm.can_enter("BTC/USDT", 1, 10000.0)
        assert allowed
        assert reason == "ok"

    def test_cvar_threshold_custom(self, rm):
        rm.max_daily_trades = 100
        rm.max_daily_loss_abs = 50000.0
        rm.cvar_threshold_pct = 20.0
        for _ in range(20):
            rm.record_exit("BTC/USDT", -10.0, -1000.0)
        allowed, reason = rm.can_enter("BTC/USDT", 1, 10000.0)
        assert allowed
        assert reason == "ok"

    def test_no_returns_skips_cvar_check(self, rm):
        rm.cvar_threshold_pct = 5.0
        allowed, reason = rm.can_enter("BTC/USDT", 1, 10000.0)
        assert allowed
        assert reason == "ok"


class TestAdaptive:
    def test_adaptive_disabled_by_default(self, rm):
        assert not rm._adaptive

    def test_set_adaptive_enabled(self, rm):
        rm.set_adaptive(True, lookback=30)
        assert rm._adaptive is True
        assert rm._adaptive_lookback == 30

    def test_feed_trades_no_adjust_when_not_adaptive(self, rm):
        rm.feed_trades([{"pnl_pct": 1.0}, {"pnl_pct": -1.0}])
        assert rm.max_daily_trades == rm._base_max_daily_trades

    def test_high_win_rate_relaxes_limit(self, rm):
        rm.set_adaptive(True, lookback=10)
        trades = [{"pnl_pct": 1.0}] * 9 + [{"pnl_pct": -1.0}]
        rm.feed_trades(trades)
        assert rm.max_daily_trades == int(rm._base_max_daily_trades * 1.2)

    def test_low_win_rate_tightens_limit(self, rm):
        rm.set_adaptive(True, lookback=10)
        trades = [{"pnl_pct": -1.0}] * 9 + [{"pnl_pct": 1.0}]
        rm.feed_trades(trades)
        assert rm.max_daily_trades == int(rm._base_max_daily_trades * 0.7)

    def test_neutral_win_rate_resets_limit(self, rm):
        rm.set_adaptive(True, lookback=10)
        rm.feed_trades([{"pnl_pct": 1.0}] * 9)
        assert rm.max_daily_trades > rm._base_max_daily_trades
        rm.feed_trades([{"pnl_pct": -1.0}] * 5)
        assert rm.max_daily_trades == rm._base_max_daily_trades

    def test_insufficient_trades_no_adjust(self, rm):
        rm.set_adaptive(True, lookback=50)
        rm.feed_trades([{"pnl_pct": 1.0}] * 5)
        assert rm.max_daily_trades == rm._base_max_daily_trades

    def test_feed_trades_appends_history(self, rm):
        rm.feed_trades([{"pnl_pct": 1.0}, {"pnl_pct": 2.0}])
        assert len(rm._trade_history) == 2
