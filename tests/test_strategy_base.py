"""Tests for strategy base module."""

import unittest
from decimal import Decimal

from strategy.base import Signal, SignalType, Position, StrategyContext
from data.models import OHLCVCandle


class TestSignalType(unittest.TestCase):
    """Tests for SignalType enum."""

    def test_signal_types_exist(self):
        self.assertEqual(SignalType.LONG.value, 1)
        self.assertEqual(SignalType.SHORT.value, 2)
        self.assertEqual(SignalType.CLOSE_LONG.value, 3)
        self.assertEqual(SignalType.CLOSE_SHORT.value, 4)
        self.assertEqual(SignalType.HOLD.value, 5)


class TestSignal(unittest.TestCase):
    """Tests for Signal dataclass."""

    def test_basic_signal(self):
        signal = Signal(
            signal_type=SignalType.LONG,
            pair="BTC/USDT",
            timestamp=1234567890000,
            price=Decimal('50000')
        )
        self.assertEqual(signal.signal_type, SignalType.LONG)
        self.assertEqual(signal.pair, "BTC/USDT")
        self.assertEqual(signal.price, Decimal('50000'))
        self.assertEqual(signal.confidence, Decimal('0.5'))

    def test_signal_with_metadata(self):
        signal = Signal(
            signal_type=SignalType.LONG,
            pair="BTC/USDT",
            timestamp=1234567890000,
            price=Decimal('50000'),
            confidence=Decimal('0.8'),
            metadata={"reason": "sma_cross", "fast_period": 10}
        )
        self.assertEqual(signal.confidence, Decimal('0.8'))
        self.assertEqual(signal.metadata["reason"], "sma_cross")

    def test_is_entry(self):
        long_signal = Signal(SignalType.LONG, "BTC/USDT", 123, Decimal('50000'))
        short_signal = Signal(SignalType.SHORT, "BTC/USDT", 123, Decimal('50000'))
        close_signal = Signal(SignalType.CLOSE_LONG, "BTC/USDT", 123, Decimal('50000'))
        hold_signal = Signal(SignalType.HOLD, "BTC/USDT", 123, Decimal('50000'))

        self.assertTrue(long_signal.is_entry())
        self.assertTrue(short_signal.is_entry())
        self.assertFalse(close_signal.is_entry())
        self.assertFalse(hold_signal.is_entry())

    def test_is_exit(self):
        close_long = Signal(SignalType.CLOSE_LONG, "BTC/USDT", 123, Decimal('50000'))
        close_short = Signal(SignalType.CLOSE_SHORT, "BTC/USDT", 123, Decimal('50000'))
        long_signal = Signal(SignalType.LONG, "BTC/USDT", 123, Decimal('50000'))

        self.assertTrue(close_long.is_exit())
        self.assertTrue(close_short.is_exit())
        self.assertFalse(long_signal.is_exit())

    def test_is_hold(self):
        hold_signal = Signal(SignalType.HOLD, "BTC/USDT", 123, Decimal('50000'))
        long_signal = Signal(SignalType.LONG, "BTC/USDT", 123, Decimal('50000'))

        self.assertTrue(hold_signal.is_hold())
        self.assertFalse(long_signal.is_hold())

    def test_datetime_property(self):
        signal = Signal(
            signal_type=SignalType.LONG,
            pair="BTC/USDT",
            timestamp=1609459200000,
            price=Decimal('50000')
        )
        dt = signal.datetime
        self.assertEqual(dt.year, 2021)
        self.assertEqual(dt.month, 1)
        self.assertEqual(dt.day, 1)


class TestPosition(unittest.TestCase):
    """Tests for Position dataclass."""

    def test_basic_position(self):
        position = Position(
            pair="BTC/USDT",
            side="long",
            size=Decimal('0.1'),
            entry_price=Decimal('50000'),
            entry_time=1234567890000
        )
        self.assertEqual(position.pair, "BTC/USDT")
        self.assertEqual(position.side, "long")
        self.assertEqual(position.size, Decimal('0.1'))

    def test_is_long(self):
        long_pos = Position("BTC/USDT", "long", Decimal('0.1'), Decimal('50000'), 123)
        short_pos = Position("BTC/USDT", "short", Decimal('0.1'), Decimal('50000'), 123)

        self.assertTrue(long_pos.is_long)
        self.assertFalse(short_pos.is_long)

    def test_is_short(self):
        long_pos = Position("BTC/USDT", "long", Decimal('0.1'), Decimal('50000'), 123)
        short_pos = Position("BTC/USDT", "short", Decimal('0.1'), Decimal('50000'), 123)

        self.assertFalse(long_pos.is_short)
        self.assertTrue(short_pos.is_short)

    def test_is_flat(self):
        flat_pos = Position("BTC/USDT", "long", Decimal('0'), Decimal('50000'), 123)
        active_pos = Position("BTC/USDT", "long", Decimal('0.1'), Decimal('50000'), 123)

        self.assertTrue(flat_pos.is_flat)
        self.assertFalse(active_pos.is_flat)


class TestStrategyContext(unittest.TestCase):
    """Tests for StrategyContext dataclass."""

    def test_basic_context(self):
        context = StrategyContext(
            pair="BTC/USDT",
            timeframe="1h",
            current_price=Decimal('50000')
        )
        self.assertEqual(context.pair, "BTC/USDT")
        self.assertEqual(context.timeframe, "1h")
        self.assertEqual(context.current_price, Decimal('50000'))

    def test_context_with_positions(self):
        position = Position(
            pair="BTC/USDT",
            side="long",
            size=Decimal('0.1'),
            entry_price=Decimal('50000'),
            entry_time=1234567890000
        )
        context = StrategyContext(
            pair="BTC/USDT",
            timeframe="1h",
            current_price=Decimal('52000'),
            positions={"BTC/USDT": position}
        )
        self.assertEqual(len(context.positions), 1)
        self.assertTrue(context.positions["BTC/USDT"].is_long)

    def test_context_with_candles(self):
        candle1 = OHLCVCandle(
            timestamp=1000,
            open_price=Decimal('50000'),
            high_price=Decimal('51000'),
            low_price=Decimal('49000'),
            close_price=Decimal('50500'),
            volume=Decimal('100'),
            pair="BTC/USDT",
            timeframe="1h"
        )
        candle2 = OHLCVCandle(
            timestamp=2000,
            open_price=Decimal('50500'),
            high_price=Decimal('52000'),
            low_price=Decimal('50000'),
            close_price=Decimal('51500'),
            volume=Decimal('150'),
            pair="BTC/USDT",
            timeframe="1h"
        )
        context = StrategyContext(
            pair="BTC/USDT",
            timeframe="1h",
            current_price=Decimal('51500'),
            candles=[candle1, candle2]
        )
        self.assertEqual(len(context.candles), 2)

    def test_get_position(self):
        position = Position(
            pair="BTC/USDT",
            side="long",
            size=Decimal('0.1'),
            entry_price=Decimal('50000'),
            entry_time=1234567890000
        )
        context = StrategyContext(
            pair="BTC/USDT",
            timeframe="1h",
            current_price=Decimal('52000'),
            positions={"BTC/USDT": position}
        )
        pos = context.get_position()
        self.assertIsNotNone(pos)
        self.assertEqual(pos.pair, "BTC/USDT")

    def test_get_position_other_pair(self):
        btc_pos = Position("BTC/USDT", "long", Decimal('0.1'), Decimal('50000'), 123)
        eth_pos = Position("ETH/USDT", "long", Decimal('1'), Decimal('3000'), 123)
        context = StrategyContext(
            pair="BTC/USDT",
            timeframe="1h",
            current_price=Decimal('52000'),
            positions={"BTC/USDT": btc_pos, "ETH/USDT": eth_pos}
        )
        pos = context.get_position("ETH/USDT")
        self.assertIsNotNone(pos)
        self.assertEqual(pos.pair, "ETH/USDT")

    def test_get_position_none(self):
        context = StrategyContext(
            pair="BTC/USDT",
            timeframe="1h",
            current_price=Decimal('52000')
        )
        pos = context.get_position()
        self.assertIsNone(pos)

    def test_context_with_balances(self):
        context = StrategyContext(
            pair="BTC/USDT",
            timeframe="1h",
            current_price=Decimal('50000'),
            balances={"USDT": Decimal('10000'), "BTC": Decimal('0.5')}
        )
        self.assertEqual(context.balances["USDT"], Decimal('10000'))
        self.assertEqual(context.balances["BTC"], Decimal('0.5'))


if __name__ == "__main__":
    unittest.main()