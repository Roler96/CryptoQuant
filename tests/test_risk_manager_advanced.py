"""Tests for RiskManager daily reset and tier cooldown behavior."""

import time
from datetime import date, timedelta


from cryptoquant.risk.manager import DrawdownTier, RiskManager


def make_risk_manager(initial_balance: float = 10000.0) -> RiskManager:
    return RiskManager(
        initial_balance=initial_balance,
        max_daily_trades=5,
        max_daily_loss_pct=10.0,
        max_daily_loss_abs=1000.0,
        max_drawdown_pct=20.0,
        drawdown_tier1_pct=5.0,
        drawdown_tier2_pct=10.0,
        drawdown_tier3_pct=15.0,
        tier_cooldown_minutes=30,
    )


class TestDailyReset:
    """Daily reset boundary tests."""

    def test_no_reset_same_day(self):
        rm = make_risk_manager()
        rm.record_entry("BTC/USDT", "long")
        rm.record_exit("BTC/USDT", pnl_pct=2.0, pnl_abs=20.0)

        assert rm.check_daily_reset() is False
        stats = rm.get_daily_stats()
        assert stats.total_trades == 1
        assert stats.total_pnl_pct > 0

    def test_daily_reset_triggers_on_new_day(self):
        rm = make_risk_manager()
        rm.record_entry("BTC/USDT", "long")
        rm.record_exit("BTC/USDT", pnl_pct=2.0, pnl_abs=20.0)

        # Simulate date change
        tomorrow = date.today() + timedelta(days=1)
        tomorrow.isoformat()

        # Force the daily stats date to yesterday
        rm._daily_stats.date = (date.today() - timedelta(days=1)).isoformat()

        assert rm.check_daily_reset() is True
        stats = rm.get_daily_stats()
        assert stats.total_trades == 0
        assert stats.total_pnl_pct == 0.0
        assert stats.date == date.today().isoformat()

    def test_daily_reset_preserves_balance(self):
        rm = make_risk_manager(initial_balance=5000.0)
        rm.update_balance(6000.0)
        rm._daily_stats.date = (date.today() - timedelta(days=1)).isoformat()

        rm.check_daily_reset()
        stats = rm.get_daily_stats()
        assert stats.current_balance == 6000.0
        assert stats.start_balance == 6000.0

    def test_blocked_after_daily_trade_limit(self):
        rm = make_risk_manager()
        # Simulate hitting daily limit
        rm._daily_stats.total_trades = 5
        allowed, reason = rm.can_enter("BTC/USDT", 1, 10000.0, 0)
        assert not allowed
        assert "daily trade limit" in reason.lower()


class TestDrawdownTiers:
    """Drawdown tier progression and cooldown tests."""

    def test_normal_at_start(self):
        rm = make_risk_manager(10000.0)
        tier = rm.current_tier(10000.0)
        assert tier == DrawdownTier.NORMAL
        assert rm.position_size_multiplier(10000.0) == 1.0

    def test_reduce_half_on_tier1(self):
        rm = make_risk_manager(10000.0)
        # Balance drops 8% → tier1
        tier = rm.current_tier(9200.0)
        assert tier == DrawdownTier.REDUCE_HALF
        assert rm.position_size_multiplier(9200.0) == 0.5

    def test_reduce_quarter_on_tier2(self):
        rm = make_risk_manager(10000.0)
        # Balance drops 12% → tier2
        tier = rm.current_tier(8800.0)
        assert tier == DrawdownTier.REDUCE_QUARTER
        assert rm.position_size_multiplier(8800.0) == 0.25

    def test_halt_on_tier3(self):
        rm = make_risk_manager(10000.0)
        # Balance drops 18% → tier3 (halt)
        tier = rm.current_tier(8200.0)
        assert tier == DrawdownTier.HALT
        assert rm.position_size_multiplier(8200.0) == 0.0
        allowed, reason = rm.can_enter("BTC/USDT", 1, 8200.0, 0)
        assert not allowed
        assert "halt" in reason.lower()

    def test_recovery_resets_tier(self):
        rm = make_risk_manager(10000.0)
        # First drop to tier1
        rm.current_tier(9200.0)
        assert rm._current_drawdown_tier == DrawdownTier.REDUCE_HALF

        # Then recover
        rm.update_balance(11000.0)
        assert rm._current_drawdown_tier == DrawdownTier.NORMAL
        assert rm.position_size_multiplier(11000.0) == 1.0

    def test_tier_cooldown_expires(self):
        """Tier cooldown expires after balance recovers above threshold."""
        rm = make_risk_manager(10000.0)
        rm.drawdown_tier1_pct = 3.0
        rm.tier_cooldown_minutes = 0  # Immediate cooldown after recovery

        # Drop to tier1
        rm.current_tier(9600.0)  # 4% drawdown → REDUCE_HALF
        assert rm._current_drawdown_tier == DrawdownTier.REDUCE_HALF

        # Recover: raise peak then check
        rm.update_balance(10100.0)  # new peak = 10100
        tier = rm.current_tier(10100.0)  # drawdown = 0% → NORMAL
        assert tier == DrawdownTier.NORMAL


class TestEmergencyStop:
    """Emergency stop tests."""

    def test_balance_below_min_triggers_emergency(self):
        rm = make_risk_manager()
        rm.min_balance = 100.0
        allowed, _ = rm.can_enter("BTC/USDT", 1, 50.0, 0)
        assert not allowed
        assert rm.is_emergency_stop()

    def test_emergency_cooldown_expires(self):
        rm = make_risk_manager()
        rm.emergency_cooldown_minutes = 1
        rm._trigger_emergency("test")
        assert rm.is_emergency_stop() is True

        # Force trigger time to be in the past
        rm._emergency_triggered_at = time.time() - 1000

        assert rm.is_emergency_stop() is False

    def test_clear_emergency_manually(self):
        rm = make_risk_manager()
        rm._trigger_emergency("test")
        rm.clear_emergency()
        assert rm.is_emergency_stop() is False


class TestAdaptiveRisk:
    """Adaptive risk parameter tests."""

    def test_adaptive_win_rate_high(self):
        rm = make_risk_manager()
        rm.set_adaptive(True, lookback=20)

        # Feed winning trades
        trades = [{"pnl_pct": 1.0}] * 15 + [{"pnl_pct": -0.5}] * 5
        rm.feed_trades(trades)

        assert rm.max_daily_trades >= rm._base_max_daily_trades

    def test_adaptive_win_rate_low(self):
        rm = make_risk_manager()
        rm.set_adaptive(True, lookback=20)

        # Feed losing trades
        trades = [{"pnl_pct": -1.0}] * 15 + [{"pnl_pct": 0.5}] * 5
        rm.feed_trades(trades)

        assert rm.max_daily_trades <= rm._base_max_daily_trades
