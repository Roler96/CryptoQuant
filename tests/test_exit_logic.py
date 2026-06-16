"""Tests for exit logic pure functions."""

from cryptoquant.engine.exit_logic import (
    ExitCheck,
    check_signal_reverse,
    check_stop_loss,
    check_take_profit,
    check_time_exit,
    determine_exit,
)


class TestCheckStopLoss:
    def test_long_hit(self):
        result = check_stop_loss(
            "long", 110.0, 95.0, 100.0, use_lows_for_stops=True
        )
        assert result.should_exit
        assert result.reason == "stop_loss"

    def test_long_not_hit(self):
        result = check_stop_loss(
            "long", 110.0, 101.0, 100.0, use_lows_for_stops=True
        )
        assert not result.should_exit

    def test_short_hit(self):
        result = check_stop_loss(
            "short", 105.0, 90.0, 100.0, use_lows_for_stops=True
        )
        assert result.should_exit
        assert result.reason == "stop_loss"

    def test_short_not_hit(self):
        result = check_stop_loss(
            "short", 99.0, 90.0, 100.0, use_lows_for_stops=True
        )
        assert not result.should_exit

    def test_none_price(self):
        result = check_stop_loss(
            "long", 110.0, 95.0, None, use_lows_for_stops=True
        )
        assert not result.should_exit

    def test_use_lows_false(self):
        result = check_stop_loss(
            "long", 110.0, 95.0, 100.0, use_lows_for_stops=False
        )
        assert not result.should_exit


class TestCheckTakeProfit:
    def test_long_hit(self):
        result = check_take_profit("long", 110.0, 95.0, 105.0)
        assert result.should_exit
        assert result.reason == "take_profit"

    def test_long_not_hit(self):
        result = check_take_profit("long", 104.0, 95.0, 105.0)
        assert not result.should_exit

    def test_short_hit(self):
        result = check_take_profit("short", 110.0, 95.0, 96.0)
        assert result.should_exit
        assert result.reason == "take_profit"

    def test_short_not_hit(self):
        result = check_take_profit("short", 110.0, 97.0, 96.0)
        assert not result.should_exit

    def test_none_price(self):
        result = check_take_profit("long", 110.0, 95.0, None)
        assert not result.should_exit


class TestCheckTimeExit:
    def test_hit(self):
        result = check_time_exit(0, 10, 5)
        assert result.should_exit
        assert result.reason == "time_exit"

    def test_not_hit(self):
        result = check_time_exit(0, 4, 5)
        assert not result.should_exit

    def test_none_max(self):
        result = check_time_exit(0, 10, None)
        assert not result.should_exit

    def test_exact_boundary(self):
        result = check_time_exit(0, 5, 5)
        assert result.should_exit


class TestCheckSignalReverse:
    def test_reverse_long(self):
        result = check_signal_reverse(-1, 1)
        assert result.should_exit
        assert result.reason == "signal_reverse"

    def test_reverse_short(self):
        result = check_signal_reverse(1, -1)
        assert result.should_exit
        assert result.reason == "signal_reverse"

    def test_same_signal(self):
        result = check_signal_reverse(1, 1)
        assert not result.should_exit

    def test_no_signal(self):
        result = check_signal_reverse(0, 1)
        assert not result.should_exit


class TestDetermineExit:
    def test_priority_stop_over_tp(self):
        sl = ExitCheck(True, "stop_loss")
        tp = ExitCheck(True, "take_profit")
        result = determine_exit(sl, tp)
        assert result.should_exit
        assert result.reason == "stop_loss"

    def test_priority_tp_over_time(self):
        tp = ExitCheck(True, "take_profit")
        time_ = ExitCheck(True, "time_exit")
        result = determine_exit(tp, time_)
        assert result.should_exit
        assert result.reason == "take_profit"

    def test_priority_time_over_signal(self):
        time_ = ExitCheck(True, "time_exit")
        sig = ExitCheck(True, "signal_reverse")
        result = determine_exit(time_, sig)
        assert result.should_exit
        assert result.reason == "time_exit"

    def test_no_exit(self):
        sl = ExitCheck(False, "stop_loss")
        tp = ExitCheck(False, "take_profit")
        result = determine_exit(sl, tp)
        assert not result.should_exit

    def test_all_false(self):
        result = determine_exit(
            ExitCheck(False, "stop_loss"),
            ExitCheck(False, "take_profit"),
            ExitCheck(False, "time_exit"),
            ExitCheck(False, "signal_reverse"),
        )
        assert not result.should_exit

    def test_single_true(self):
        result = determine_exit(ExitCheck(True, "time_exit"))
        assert result.should_exit
        assert result.reason == "time_exit"

    def test_all_true_priority_order(self):
        sl = ExitCheck(True, "stop_loss")
        tp = ExitCheck(True, "take_profit")
        time_ = ExitCheck(True, "time_exit")
        sig = ExitCheck(True, "signal_reverse")
        result = determine_exit(sl, tp, time_, sig)
        assert result.should_exit
        assert result.reason == "stop_loss"
