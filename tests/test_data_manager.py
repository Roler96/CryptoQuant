"""Tests for data manager module."""

import unittest
from decimal import Decimal

from data.manager import RateLimiter, OKXAPIError, OKXRateLimitError, OKXAuthenticationError
from data.models import OHLCVCandle, Ticker, OrderBook, OrderBookLevel, AccountBalance, Balance


class TestRateLimiter(unittest.TestCase):
    """Tests for RateLimiter."""

    def test_initialization(self):
        limiter = RateLimiter(max_requests=20, time_window=2.0)
        self.assertEqual(limiter.max_requests, 20)
        self.assertEqual(limiter.time_window, 2.0)
        self.assertEqual(limiter.tokens, 20)

    def test_acquire_returns_zero_when_tokens_available(self):
        limiter = RateLimiter(max_requests=20, time_window=2.0)
        wait_time = limiter.acquire()
        self.assertEqual(wait_time, 0.0)
        self.assertEqual(limiter.tokens, 19)

    def test_custom_rate_limits(self):
        limiter = RateLimiter(max_requests=10, time_window=1.0)
        self.assertEqual(limiter.max_requests, 10)
        self.assertEqual(limiter.time_window, 1.0)


class TestOHLCVCandle(unittest.TestCase):
    """Tests for OHLCVCandle dataclass."""

    def test_basic_candle(self):
        candle = OHLCVCandle(
            timestamp=1234567890000,
            open_price=Decimal('50000'),
            high_price=Decimal('51000'),
            low_price=Decimal('49000'),
            close_price=Decimal('50500'),
            volume=Decimal('100'),
            pair="BTC/USDT",
            timeframe="1h"
        )
        self.assertEqual(candle.timestamp, 1234567890000)
        self.assertEqual(candle.open_price, Decimal('50000'))
        self.assertEqual(candle.pair, "BTC/USDT")

    def test_candle_is_frozen(self):
        candle = OHLCVCandle(
            timestamp=1234567890000,
            open_price=Decimal('50000'),
            high_price=Decimal('51000'),
            low_price=Decimal('49000'),
            close_price=Decimal('50500'),
            volume=Decimal('100'),
            pair="BTC/USDT",
            timeframe="1h"
        )
        with self.assertRaises(Exception):
            candle.close_price = Decimal('60000')

    def test_price_range(self):
        candle = OHLCVCandle(
            timestamp=1234567890000,
            open_price=Decimal('50000'),
            high_price=Decimal('51000'),
            low_price=Decimal('49000'),
            close_price=Decimal('50500'),
            volume=Decimal('100'),
            pair="BTC/USDT",
            timeframe="1h"
        )
        self.assertEqual(candle.price_range, Decimal('2000'))

    def test_price_change(self):
        candle = OHLCVCandle(
            timestamp=1234567890000,
            open_price=Decimal('50000'),
            high_price=Decimal('51000'),
            low_price=Decimal('49000'),
            close_price=Decimal('50500'),
            volume=Decimal('100'),
            pair="BTC/USDT",
            timeframe="1h"
        )
        self.assertEqual(candle.price_change, Decimal('500'))


class TestTicker(unittest.TestCase):
    """Tests for Ticker dataclass."""

    def test_basic_ticker(self):
        ticker = Ticker(
            pair="BTC/USDT",
            bid=Decimal('50000'),
            ask=Decimal('50100'),
            last=Decimal('50050'),
            high=Decimal('52000'),
            low=Decimal('48000'),
            volume=Decimal('1000'),
            timestamp=1234567890000
        )
        self.assertEqual(ticker.pair, "BTC/USDT")
        self.assertEqual(ticker.bid, Decimal('50000'))
        self.assertEqual(ticker.ask, Decimal('50100'))

    def test_spread_property(self):
        ticker = Ticker(
            pair="BTC/USDT",
            bid=Decimal('50000'),
            ask=Decimal('50100'),
            last=Decimal('50050'),
            high=Decimal('52000'),
            low=Decimal('48000'),
            volume=Decimal('1000'),
            timestamp=1234567890000
        )
        self.assertEqual(ticker.spread, Decimal('100'))

    def test_mid_price(self):
        ticker = Ticker(
            pair="BTC/USDT",
            bid=Decimal('50000'),
            ask=Decimal('50200'),
            last=Decimal('50100'),
            high=Decimal('52000'),
            low=Decimal('48000'),
            volume=Decimal('1000'),
            timestamp=1234567890000
        )
        self.assertEqual(ticker.mid_price, Decimal('50100'))


class TestOrderBook(unittest.TestCase):
    """Tests for OrderBook dataclass."""

    def test_basic_orderbook(self):
        level1 = OrderBookLevel(price=Decimal('50000'), size=Decimal('1.0'))
        level2 = OrderBookLevel(price=Decimal('50010'), size=Decimal('0.5'))
        orderbook = OrderBook(
            pair="BTC/USDT",
            bids=[level1],
            asks=[level2],
            timestamp=1234567890000
        )
        self.assertEqual(orderbook.pair, "BTC/USDT")
        self.assertEqual(len(orderbook.bids), 1)
        self.assertEqual(len(orderbook.asks), 1)

    def test_best_bid(self):
        level1 = OrderBookLevel(price=Decimal('50000'), size=Decimal('1.0'))
        orderbook = OrderBook(
            pair="BTC/USDT",
            bids=[level1],
            asks=[],
            timestamp=1234567890000
        )
        self.assertEqual(orderbook.best_bid.price, Decimal('50000'))

    def test_spread_property(self):
        bid = OrderBookLevel(price=Decimal('50000'), size=Decimal('1.0'))
        ask = OrderBookLevel(price=Decimal('50100'), size=Decimal('0.5'))
        orderbook = OrderBook(
            pair="BTC/USDT",
            bids=[bid],
            asks=[ask],
            timestamp=1234567890000
        )
        self.assertEqual(orderbook.spread, Decimal('100'))


class TestAccountBalance(unittest.TestCase):
    """Tests for AccountBalance dataclass."""

    def test_basic_balance(self):
        usdt_balance = Balance(
            currency="USDT",
            free=Decimal('10000'),
            used=Decimal('0'),
            total=Decimal('10000')
        )
        btc_balance = Balance(
            currency="BTC",
            free=Decimal('0.5'),
            used=Decimal('0.1'),
            total=Decimal('0.6')
        )
        account = AccountBalance(
            balances={"USDT": usdt_balance, "BTC": btc_balance},
            timestamp=1234567890000
        )
        self.assertEqual(account.balances["USDT"].free, Decimal('10000'))
        self.assertEqual(account.balances["BTC"].total, Decimal('0.6'))

    def test_get_balance(self):
        usdt_balance = Balance(
            currency="USDT",
            free=Decimal('10000'),
            used=Decimal('0'),
            total=Decimal('10000')
        )
        account = AccountBalance(balances={"USDT": usdt_balance})
        self.assertEqual(account.get("USDT").free, Decimal('10000'))

    def test_non_zero_balances(self):
        usdt_balance = Balance(
            currency="USDT",
            free=Decimal('10000'),
            used=Decimal('0'),
            total=Decimal('10000')
        )
        zero_balance = Balance(
            currency="ETH",
            free=Decimal('0'),
            used=Decimal('0'),
            total=Decimal('0')
        )
        account = AccountBalance(balances={"USDT": usdt_balance, "ETH": zero_balance})
        non_zero = account.get_non_zero_balances()
        self.assertEqual(len(non_zero), 1)


class TestExceptions(unittest.TestCase):
    """Tests for OKX exception classes."""

    def test_okx_api_error(self):
        error = OKXAPIError("API error", error_code="50001")
        self.assertEqual(str(error), "API error")
        self.assertEqual(error.error_code, "50001")

    def test_rate_limit_error(self):
        error = OKXRateLimitError("Rate limit exceeded")
        self.assertIn("Rate limit", str(error))

    def test_auth_error(self):
        error = OKXAuthenticationError("Invalid credentials")
        self.assertIn("Invalid", str(error))

    def test_error_inheritance(self):
        rate_error = OKXRateLimitError("test")
        auth_error = OKXAuthenticationError("test")
        self.assertIsInstance(rate_error, OKXAPIError)
        self.assertIsInstance(auth_error, OKXAPIError)


if __name__ == "__main__":
    unittest.main()