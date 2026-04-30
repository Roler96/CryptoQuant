"""Tests for risk management modules."""

import unittest
from decimal import Decimal

from risk.position_sizing import PositionSizer, PositionLimits
from risk.stop_loss import StopLossManager, StopLossMethod


class TestPositionSizer(unittest.TestCase):
    """Tests for PositionSizer."""

    def setUp(self):
        self.sizer = PositionSizer()

    def test_fixed_pct_basic(self):
        result = self.sizer.fixed_pct(
            portfolio_value=Decimal('10000'),
            risk_pct=Decimal('0.02'),
            price=Decimal('50000')
        )
        self.assertEqual(result.method, "fixed_pct")
        self.assertEqual(result.risk_amount, Decimal('200'))
        self.assertEqual(result.size, Decimal('200') / Decimal('50000'))
        self.assertTrue(result.is_valid)

    def test_fixed_pct_zero_price(self):
        result = self.sizer.fixed_pct(
            portfolio_value=Decimal('10000'),
            risk_pct=Decimal('0.02'),
            price=Decimal('0')
        )
        self.assertFalse(result.is_valid)
        self.assertIn("Price must be positive", result.validation_errors)

    def test_fixed_pct_negative_price(self):
        result = self.sizer.fixed_pct(
            portfolio_value=Decimal('10000'),
            risk_pct=Decimal('0.02'),
            price=Decimal('-100')
        )
        self.assertFalse(result.is_valid)

    def test_volatility_based(self):
        result = self.sizer.volatility_based(
            portfolio_value=Decimal('10000'),
            risk_pct=Decimal('0.02'),
            price=Decimal('50000'),
            recent_volatility=Decimal('0.03'),
            target_volatility=Decimal('0.02')
        )
        self.assertEqual(result.method, "volatility_based")
        self.assertTrue(result.is_valid)

    def test_volatility_based_high_vol(self):
        result = self.sizer.volatility_based(
            portfolio_value=Decimal('10000'),
            risk_pct=Decimal('0.02'),
            price=Decimal('50000'),
            recent_volatility=Decimal('0.04'),
            target_volatility=Decimal('0.02')
        )
        self.assertEqual(result.method, "volatility_based")
        self.assertTrue(result.size > Decimal('0'))

    def test_kelly_basic(self):
        result = self.sizer.kelly(
            portfolio_value=Decimal('10000'),
            win_rate=Decimal('0.6'),
            win_loss_ratio=Decimal('2'),
            price=Decimal('50000'),
            kelly_fraction=Decimal('0.5')
        )
        self.assertEqual(result.method, "kelly")
        self.assertTrue(result.size > Decimal('0'))

    def test_kelly_invalid_win_rate(self):
        result = self.sizer.kelly(
            portfolio_value=Decimal('10000'),
            win_rate=Decimal('1.5'),
            win_loss_ratio=Decimal('2'),
            price=Decimal('50000')
        )
        self.assertFalse(result.is_valid)

    def test_kelly_negative_expectancy(self):
        result = self.sizer.kelly(
            portfolio_value=Decimal('10000'),
            win_rate=Decimal('0.3'),
            win_loss_ratio=Decimal('1'),
            price=Decimal('50000')
        )
        self.assertFalse(result.is_valid)

    def test_validate_position_within_limits(self):
        is_valid, errors = self.sizer.validate_position(
            position_size=Decimal('0.01'),
            portfolio_value=Decimal('10000')
        )
        self.assertTrue(is_valid)
        self.assertEqual(len(errors), 0)

    def test_validate_position_exceeds_max_pct(self):
        sizer = PositionSizer(limits=PositionLimits(max_position_pct=Decimal('0.1')))
        is_valid, errors = sizer.validate_position(
            position_size=Decimal('2000'),
            portfolio_value=Decimal('10000')
        )
        self.assertFalse(is_valid)

    def test_validate_position_below_min(self):
        sizer = PositionSizer(limits=PositionLimits(min_position_size=Decimal('0.01')))
        is_valid, errors = sizer.validate_position(
            position_size=Decimal('0.001'),
            portfolio_value=Decimal('10000')
        )
        self.assertFalse(is_valid)

    def test_validate_zero_position(self):
        is_valid, errors = self.sizer.validate_position(
            position_size=Decimal('0'),
            portfolio_value=Decimal('10000')
        )
        self.assertTrue(is_valid)


class TestPositionLimits(unittest.TestCase):
    """Tests for PositionLimits."""

    def test_default_values(self):
        limits = PositionLimits()
        self.assertEqual(limits.max_position_pct, Decimal('0.3'))
        self.assertEqual(limits.max_leverage, Decimal('2.0'))
        self.assertEqual(limits.min_position_size, Decimal('0.001'))
        self.assertIsNone(limits.max_position_size)

    def test_custom_values(self):
        limits = PositionLimits(
            max_position_pct=Decimal('0.1'),
            max_leverage=Decimal('1.5'),
            min_position_size=Decimal('0.005'),
            max_position_size=Decimal('100')
        )
        self.assertEqual(limits.max_position_pct, Decimal('0.1'))
        self.assertEqual(limits.max_leverage, Decimal('1.5'))
        self.assertEqual(limits.min_position_size, Decimal('0.005'))
        self.assertEqual(limits.max_position_size, Decimal('100'))


class TestStopLossManager(unittest.TestCase):
    """Tests for StopLossManager."""

    def setUp(self):
        self.manager = StopLossManager()

    def test_percentage_stop_long(self):
        stop = self.manager.percentage_stop(
            entry_price=Decimal('50000'),
            stop_pct=Decimal('0.05'),
            side="long"
        )
        self.assertEqual(stop, Decimal('47500'))

    def test_percentage_stop_short(self):
        stop = self.manager.percentage_stop(
            entry_price=Decimal('50000'),
            stop_pct=Decimal('0.05'),
            side="short"
        )
        self.assertEqual(stop, Decimal('52500'))

    def test_percentage_stop_invalid_price(self):
        with self.assertRaises(ValueError):
            self.manager.percentage_stop(
                entry_price=Decimal('-100'),
                stop_pct=Decimal('0.05'),
                side="long"
            )

    def test_percentage_stop_invalid_side(self):
        with self.assertRaises(ValueError):
            self.manager.percentage_stop(
                entry_price=Decimal('50000'),
                stop_pct=Decimal('0.05'),
                side="invalid"
            )

    def test_calculate_stop_percentage(self):
        result = self.manager.calculate_stop(
            entry_price=Decimal('50000'),
            method="percentage",
            stop_pct=Decimal('0.05'),
            side="long"
        )
        self.assertEqual(result.method, StopLossMethod.PERCENTAGE)
        self.assertEqual(result.stop_price, Decimal('47500'))
        self.assertFalse(result.is_triggered)

    def test_calculate_stop_trailing(self):
        result = self.manager.calculate_stop(
            entry_price=Decimal('50000'),
            method="trailing",
            stop_pct=Decimal('0.05'),
            side="long"
        )
        self.assertEqual(result.method, StopLossMethod.TRAILING)
        self.assertEqual(result.stop_price, Decimal('47500'))

    def test_calculate_stop_volatility(self):
        result = self.manager.calculate_stop(
            entry_price=Decimal('50000'),
            method="volatility",
            stop_pct=Decimal('0.05'),
            side="long",
            recent_volatility=Decimal('1000'),
            multiplier=Decimal('2')
        )
        self.assertEqual(result.method, StopLossMethod.VOLATILITY)
        self.assertEqual(result.stop_price, Decimal('48000'))

    def test_calculate_stop_invalid_method(self):
        with self.assertRaises(ValueError):
            self.manager.calculate_stop(
                entry_price=Decimal('50000'),
                method="invalid",
                stop_pct=Decimal('0.05')
            )

    def test_check_trigger_long_triggered(self):
        triggered = self.manager.check_trigger(
            current_price=Decimal('47000'),
            stop_price=Decimal('47500'),
            side="long"
        )
        self.assertTrue(triggered)

    def test_check_trigger_long_not_triggered(self):
        triggered = self.manager.check_trigger(
            current_price=Decimal('48000'),
            stop_price=Decimal('47500'),
            side="long"
        )
        self.assertFalse(triggered)

    def test_check_trigger_short_triggered(self):
        triggered = self.manager.check_trigger(
            current_price=Decimal('53000'),
            stop_price=Decimal('52500'),
            side="short"
        )
        self.assertTrue(triggered)

    def test_trailing_stop_update(self):
        result = self.manager.trailing_stop(
            current_price=Decimal('52000'),
            highest_price=Decimal('52000'),
            trail_pct=Decimal('0.05'),
            side="long"
        )
        self.assertEqual(result.stop_price, Decimal('49400'))

    def test_initialize_trailing_state(self):
        state = self.manager.initialize_trailing_state(
            position_id="pos_1",
            entry_price=Decimal('50000'),
            trail_pct=Decimal('0.05'),
            side="long"
        )
        self.assertEqual(state.entry_price, Decimal('50000'))
        self.assertEqual(state.highest_price, Decimal('50000'))
        self.assertEqual(state.current_stop, Decimal('47500'))

    def test_update_trailing_state(self):
        self.manager.initialize_trailing_state(
            position_id="pos_1",
            entry_price=Decimal('50000'),
            trail_pct=Decimal('0.05'),
            side="long"
        )
        state = self.manager.update_trailing_state(
            position_id="pos_1",
            current_price=Decimal('52000'),
            trail_pct=Decimal('0.05')
        )
        self.assertEqual(state.highest_price, Decimal('52000'))
        self.assertEqual(state.current_stop, Decimal('49400'))

    def test_validate_position_valid(self):
        is_valid, errors = self.manager.validate_position({
            'entry_price': Decimal('50000'),
            'stop_price': Decimal('47500'),
            'side': 'long'
        })
        self.assertTrue(is_valid)

    def test_validate_position_no_stop(self):
        is_valid, errors = self.manager.validate_position({
            'entry_price': Decimal('50000'),
            'side': 'long'
        })
        self.assertFalse(is_valid)
        self.assertIn("stop_price is required", errors[0])

    def test_validate_position_wrong_stop_direction(self):
        is_valid, errors = self.manager.validate_position({
            'entry_price': Decimal('50000'),
            'stop_price': Decimal('51000'),
            'side': 'long'
        })
        self.assertFalse(is_valid)

    def test_calculate_risk_amount(self):
        risk = self.manager.calculate_risk_amount(
            entry_price=Decimal('50000'),
            stop_price=Decimal('47500'),
            position_size=Decimal('0.1')
        )
        self.assertEqual(risk, Decimal('250'))

    def test_calculate_risk_pct(self):
        pct = self.manager.calculate_risk_pct(
            entry_price=Decimal('50000'),
            stop_price=Decimal('47500')
        )
        self.assertEqual(pct, Decimal('0.05'))


if __name__ == "__main__":
    unittest.main()