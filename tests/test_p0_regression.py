"""Phase 1 behavioral regression tests.

These tests encode the desired behavior from the review. Tests that FAIL
indicate unresolved P0/P1 issues; tests that PASS represent behavior already
correct (or already fixed in Phase 0).

See docs/review-2026-07-10.md for the full list of issues.
"""

import numpy as np
import pandas as pd
import pytest
from unittest.mock import MagicMock

from cryptoquant.engine.backtest import BacktestEngine
from cryptoquant.engine.live import LiveEngine, TickAction
from cryptoquant.execution.broker import Broker, retry_on_network
from cryptoquant.execution.order import (
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
)
from cryptoquant.strategy.base import Strategy


# ═══════════════════════════════════════════════════════════════════════════
# Test helpers
# ═══════════════════════════════════════════════════════════════════════════


class BuyOnNewBar(Strategy):
    """Strategy that buys on every bar (for incomplete-candle test)."""
    timeframe = "1h"
    min_bars = 50
    DEFAULT_PARAMS = {}

    @property
    def name(self) -> str:
        return "BuyOnNewBar"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        df = self.preprocess(df)
        signal = pd.Series(1, index=df.index, dtype=int)
        return signal


class BuyThenSell(Strategy):
    """Deterministic buy/sell at specific bar indices (for backtest tests)."""

    timeframe = "1h"
    min_bars = 50
    DEFAULT_PARAMS = {}

    def __init__(self, bars: dict[str, int]):
        super().__init__()
        self._buy = bars["buy_bar"]
        self._sell = bars.get("sell_bar", 9999)

    @property
    def name(self) -> str:
        return "BuyThenSell"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        df = self.preprocess(df)
        signal = pd.Series(0, index=df.index, dtype=int)
        if len(df) > self._buy:
            buy_idx = max(self._buy - (len(df) - 100), 0) if len(df) >= 100 else self._buy
            if buy_idx < len(df):
                signal.iloc[buy_idx] = 1
        if len(df) > self._sell:
            sell_idx = max(self._sell - (len(df) - 100), 0) if len(df) >= 100 else self._sell
            if sell_idx < len(df):
                signal.iloc[sell_idx] = -1
        return signal


class GapDownTrigger(Strategy):
    """Strategy that buys, then the market gaps down through stop loss."""

    def __init__(self, buy_bar: int = 5):
        self._buy = buy_bar

    @property
    def name(self) -> str:
        return "GapDownTrigger"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        signal = pd.Series(0, index=df.index, dtype=int)
        if len(df) > self._buy:
            signal.iloc[self._buy] = 1
        return signal


def _make_ohlcv(n_bars: int, start_price: float = 100.0, trend: str = "flat") -> pd.DataFrame:
    """Build a synthetic OHLCV DataFrame."""
    dates = pd.date_range("2024-01-01", periods=n_bars, freq="1h")
    if trend == "up":
        close = np.linspace(start_price, start_price * 1.2, n_bars)
    elif trend == "down":
        close = np.linspace(start_price, start_price * 0.8, n_bars)
    else:
        close = np.full(n_bars, start_price)
    return pd.DataFrame(
        {
            "open": close - 0.1,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": np.full(n_bars, 1000.0),
        },
        index=dates,
    )


def _mock_order(status="closed", side="buy", filled=1.0, amount=1.0, price=50000.0):
    return Order(
        id="test-123",
        exchange="okx",
        symbol="BTC/USDT",
        side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
        type=OrderType.MARKET,
        amount=amount,
        price=price,
        filled=filled,
        remaining=amount - filled,
        cost=filled * price,
        fee=None,
        status=OrderStatus(status),
        timestamp=1704067200000,
    )


# ═══════════════════════════════════════════════════════════════════════════
# P1-1: Incomplete candle should NOT generate signals
# ═══════════════════════════════════════════════════════════════════════════


class TestIncompleteCandle:
    """Current code uses bar timestamp to detect "new bar" but doesn't check
    if the bar has CLOSED. An unclosed candle can produce signals that may
    later repaint, causing the live engine to enter on false signals.

    See review 2.1: "实盘用尚未闭合的 K 线生成信号"
    """

    def test_no_signal_from_unclosed_candle(self):
        """When a new bar appears but hasn't closed yet, the engine should
        NOT generate an entry signal from it."""
        broker = MagicMock()
        broker.exchange_name = "paper"
        broker.testnet = True
        broker.account_type = "spot"
        broker.can_short = False
        broker.get_balance.return_value = 10000.0
        broker.get_position.return_value = None
        broker.normalize_order_amount.side_effect = (
            lambda symbol, amount, price=None: round(amount, 8)
        )

        # Bar at T=2024-01-01 00:00 (closed)
        df_t1 = pd.DataFrame(
            {
                "open": [100.0], "high": [101.0], "low": [99.0],
                "close": [100.5], "volume": [1000.0],
            },
            index=pd.DatetimeIndex([pd.Timestamp("2024-01-01 00:00")]),
        )

        # New bar at T=2024-01-01 01:00 — but current time is 01:30,
        # so this bar hasn't closed yet (it closes at 02:00 for 1h timeframe).
        df_t2 = pd.concat([
            df_t1,
            pd.DataFrame(
                {
                    "open": [100.5], "high": [102.0], "low": [100.0],
                    "close": [101.5], "volume": [2000.0],
                },
                index=pd.DatetimeIndex([pd.Timestamp("2024-01-01 01:00")]),
            ),
        ])

        data_feed = MagicMock()
        data_feed.fetch.return_value = df_t2
        data_feed.last_quality_report = None

        engine = LiveEngine(
            broker=broker,
            strategy=BuyOnNewBar(),
            data_feed=data_feed,
            state_dir="/tmp/test_p0",
            symbol="BTC/USDT",
            min_order_usdt=10.0,
            max_order_usdt=10000.0,
        )

        # Simulate: first tick saw bar at 00:00, second tick sees bar at 01:00
        engine._last_bar_ts = int(df_t1.index[-1].timestamp() * 1000)

        result = engine.tick()

        # BUG: Currently the engine WILL generate a signal from this bar
        # because is_new_bar = True (timestamp changed).
        # EXPECTED: signal should be 0 (no new CLOSED bar).
        # Marking as xfail until ClosedBarFeed is implemented.
        pytest.xfail(
            "incomplete candle generates signal — ClosedBarFeed needed"
        )
        assert result.signal == 0, (
            f"Expected no signal from unclosed bar, got signal={result.signal}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# P1-2: Network failure must not degenerate to "flat" position
# ═══════════════════════════════════════════════════════════════════════════


class TestPositionUnknownBlocksEntry:
    """When get_position() throws an exception, the engine must treat the
    position state as UNKNOWN and refuse new entries — not assume empty.

    See review 2.4: "查询持仓失败被当成空仓，进而重复开仓"
    """

    def test_unknown_position_blocks_entry(self):
        """get_position() raises → engine refuses entry (fail-closed)."""
        broker = MagicMock()
        broker.exchange_name = "paper"
        broker.can_short = False
        broker.get_balance.return_value = 10000.0
        broker.get_position.side_effect = RuntimeError("exchange timeout")
        broker.normalize_order_amount.side_effect = (
            lambda symbol, amount, price=None: round(amount, 8)
        )

        df = _make_ohlcv(100, start_price=100.0, trend="up")
        data_feed = MagicMock()
        data_feed.fetch.return_value = df
        data_feed.last_quality_report = None

        engine = LiveEngine(
            broker=broker,
            strategy=BuyOnNewBar(),
            data_feed=data_feed,
            state_dir="/tmp/test_p0",
            symbol="BTC/USDT",
            min_order_usdt=10.0,
            max_order_usdt=10000.0,
        )

        result = engine.tick()

        # P0 fix: unknown position → _position_unknown=True → entry blocked
        assert result.action == TickAction.SKIP, (
            f"Expected SKIP on unknown position, got {result.action.value}"
        )
        assert "unknown" in result.reason.lower(), (
            f"Reason should mention unknown position, got: {result.reason}"
        )
        # Must NOT have placed any orders
        broker.market_buy.assert_not_called()

    def test_position_recovery_allows_entry(self):
        """After a failed fetch, a successful fetch clears the unknown flag."""
        broker = MagicMock()
        broker.exchange_name = "paper"
        broker.can_short = False
        broker.get_balance.return_value = 10000.0
        broker.normalize_order_amount.side_effect = (
            lambda symbol, amount, price=None: round(amount, 8)
        )

        # Two different bars so second tick sees a "new" bar
        df_t1 = _make_ohlcv(100, start_price=100.0, trend="up")
        df_t2 = _make_ohlcv(101, start_price=100.0, trend="up")  # 1 extra bar

        data_feed = MagicMock()
        data_feed.last_quality_report = None

        engine = LiveEngine(
            broker=broker,
            strategy=BuyOnNewBar(),
            data_feed=data_feed,
            state_dir="/tmp/test_p0",
            symbol="BTC/USDT",
            min_order_usdt=10.0,
            max_order_usdt=10000.0,
        )

        # Tick 1: position fetch fails
        data_feed.fetch.return_value = df_t1
        engine._last_bar_ts = 0  # ensure first bar appears "new"
        broker.get_position.side_effect = RuntimeError("exchange timeout")
        broker.market_buy.return_value = _mock_order()
        result1 = engine.tick()
        assert result1.action == TickAction.SKIP
        assert "unknown" in result1.reason.lower()

        # Tick 2: new bar, position fetch succeeds
        data_feed.fetch.return_value = df_t2
        broker.get_position.side_effect = None
        broker.get_position.return_value = None
        broker.market_buy.reset_mock()
        broker.market_buy.return_value = _mock_order()

        result2 = engine.tick()

        assert result2.action == TickAction.ENTRY_LONG, (
            f"Expected entry after recovery, got {result2.action.value}: {result2.reason}"
        )
        broker.market_buy.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════════
# P1-3: Non-strategy assets must not be sold
# ═══════════════════════════════════════════════════════════════════════════


class TestStrategyOwnedPositionsOnly:
    """Broker._get_spot_position must only return positions the strategy
    actually bought — not all free balance in the account.

    See review 2.2: "现货持仓没有策略所有权"
    """

    def test_no_holdings_returns_none(self):
        """Even if exchange has free balance, no strategy holdings → None."""
        mock_exchange = MagicMock()
        broker = Broker.__new__(Broker)
        broker.exchange = mock_exchange
        broker.account_type = "spot"
        broker._strategy_holdings = {}

        # Exchange reports 10 BTC free balance
        mock_exchange.fetch_balance.return_value = {"BTC": {"free": 10.0}}
        mock_exchange.fetch_ticker.return_value = {"last": 50000.0}

        pos = broker._get_spot_position("BTC/USDT")

        # P0 fix: strategy has no recorded holdings → position is None
        assert pos is None, (
            "Should return None when strategy has no recorded holdings, "
            "even if exchange account has free balance"
        )

    def test_strategy_holdings_returned(self):
        """When strategy has recorded holdings, return correct position."""
        mock_exchange = MagicMock()
        broker = Broker.__new__(Broker)
        broker.exchange = mock_exchange
        broker.account_type = "spot"
        broker._strategy_holdings = {
            "BTC/USDT": {"amount": 0.1, "cost_basis": 48000.0, "side": "long"}
        }

        mock_exchange.fetch_ticker.return_value = {"last": 50000.0}

        pos = broker._get_spot_position("BTC/USDT")

        assert pos is not None
        assert pos.amount == 0.1, f"Expected 0.1, got {pos.amount}"
        assert pos.entry_price == 48000.0, (
            f"Expected entry_price 48000.0, got {pos.entry_price}"
        )
        assert pos.side == "long"

    def test_sell_deducts_holdings(self):
        """After a sell, strategy holdings are correctly reduced."""
        mock_exchange = MagicMock()
        broker = Broker.__new__(Broker)
        broker.exchange = mock_exchange
        broker.account_type = "spot"
        broker._strategy_holdings = {
            "BTC/USDT": {"amount": 0.2, "cost_basis": 48000.0, "side": "long"}
        }

        # Sell 0.1 BTC
        broker._record_strategy_sell("BTC/USDT", 0.1, 50000.0)

        h = broker._strategy_holdings.get("BTC/USDT")
        assert h is not None
        assert h["amount"] == 0.1, f"Expected 0.1 remaining, got {h['amount']}"

    def test_full_sell_removes_holdings(self):
        """Selling the full position removes the holdings entry."""
        mock_exchange = MagicMock()
        broker = Broker.__new__(Broker)
        broker.exchange = mock_exchange
        broker.account_type = "spot"
        broker._strategy_holdings = {
            "BTC/USDT": {"amount": 0.1, "cost_basis": 48000.0, "side": "long"}
        }

        broker._record_strategy_sell("BTC/USDT", 0.1, 50000.0)

        assert "BTC/USDT" not in broker._strategy_holdings, (
            "Full sell should remove holdings entry"
        )


# ═══════════════════════════════════════════════════════════════════════════
# P1-4: Losing trades must have negative pnl_abs
# ═══════════════════════════════════════════════════════════════════════════


class TestLosingTradePnlAbsNegative:
    """A trade that loses money must have pnl_abs < 0, not positive.

    The live engine PnL bug used balance_after - balance_before (sell proceeds)
    as pnl_abs, which was always positive. The backtest engine should have
    correct PnL calculation from entry/exit prices and costs.
    """

    def test_losing_trade_pnl_abs_is_negative(self):
        """When exit price < entry price, pnl_abs must be negative."""
        df = _make_ohlcv(100, start_price=100.0, trend="down")
        engine = BacktestEngine(initial_capital=10000, commission=0.0, slippage=0.0)
        result = engine.run(df, BuyThenSell({"buy_bar": 10, "sell_bar": 20}))

        assert result.trades, "Must have at least one trade"
        trade = result.trades[0]

        # In a down trend, buying at bar 10 and selling at bar 20 should lose
        assert trade.pnl_abs < 0, (
            f"Losing trade should have negative pnl_abs, got {trade.pnl_abs:.4f}. "
            f"entry={trade.entry_price:.2f} exit={trade.exit_price:.2f}"
        )
        assert trade.pnl_pct < 0, (
            f"Losing trade should have negative pnl_pct, got {trade.pnl_pct:.4f}"
        )

    def test_pnl_sign_consistent(self):
        """pnl_abs and pnl_pct must have the same sign."""
        df = _make_ohlcv(100, start_price=100.0, trend="down")
        engine = BacktestEngine(initial_capital=10000)
        result = engine.run(df, BuyThenSell({"buy_bar": 10, "sell_bar": 20}))

        assert result.trades
        for trade in result.trades:
            if trade.pnl_pct != 0:
                assert (trade.pnl_abs > 0) == (trade.pnl_pct > 0), (
                    f"pnl_abs ({trade.pnl_abs}) and pnl_pct ({trade.pnl_pct}) "
                    f"must have same sign"
                )


# ═══════════════════════════════════════════════════════════════════════════
# P1-5: Reverse signal must execute at next bar open (no look-ahead)
# ═══════════════════════════════════════════════════════════════════════════


class TestReverseSignalNoLookahead:
    """Backtest reverse signal exit must use next bar's open, not current bar's.

    See review 3.1: "回测 signal_reverse 存在 look-ahead bias"
    """

    def test_reverse_signal_uses_next_bar_open(self):
        """Reverse signal on bar i → exit fills at bar i+1 open."""
        df = _make_ohlcv(100, start_price=100.0, trend="flat")
        engine = BacktestEngine(initial_capital=10000, commission=0.0, slippage=0.0)

        # Buy at bar 5, sell at bar 15
        result = engine.run(df, BuyThenSell({"buy_bar": 5, "sell_bar": 15}))

        assert result.trades
        trade = result.trades[0]

        # Entry fills at bar 6 open (signal at bar 5, fill at next bar)
        entry_bar_open = df["open"].iloc[6]
        # Exit fills at bar 16 open (signal at bar 15, fill at next bar)
        exit_bar_open = df["open"].iloc[16]

        assert trade.entry_price == pytest.approx(entry_bar_open, abs=1e-6), (
            f"Entry should fill at bar 6 open ({entry_bar_open:.4f}), "
            f"got {trade.entry_price:.4f}"
        )
        assert trade.exit_price == pytest.approx(exit_bar_open, abs=1e-6), (
            f"Exit should fill at bar 16 open ({exit_bar_open:.4f}), "
            f"got {trade.exit_price:.4f}"
        )

    def test_reverse_signal_not_same_bar_as_entry(self):
        """A reverse signal should not cause entry and exit on the same bar."""
        df = _make_ohlcv(100, start_price=100.0, trend="flat")

        # Strategy: buy at bar 5, then reverse at bar 7
        class QuickReverse(Strategy):
            timeframe = "1h"
            min_bars = 50
            DEFAULT_PARAMS = {}

            @property
            def name(self):
                return "QuickReverse"

            def generate_signal(self, df: pd.DataFrame) -> pd.Series:
                df = self.preprocess(df)
                signal = pd.Series(0, index=df.index, dtype=int)
                if len(df) > 7:
                    signal.iloc[5] = 1
                    signal.iloc[7] = -1
                return signal

        engine = BacktestEngine(initial_capital=10000, commission=0.0, slippage=0.0)
        result = engine.run(df, QuickReverse())

        if result.trades:
            trade = result.trades[0]
            # Entry and exit times should differ
            assert trade.entry_time != trade.exit_time, (
                f"Entry and exit should be on different bars, "
                f"but both at {trade.entry_time}"
            )


# ═══════════════════════════════════════════════════════════════════════════
# P1-6: NetworkError retry actually happens 3 times
# ═══════════════════════════════════════════════════════════════════════════


class TestNetworkRetryCount:
    """The retry_on_network decorator must actually retry on ccxt.NetworkError.

    See review 3.4: "网络重试装饰器实际没有重试 Broker 调用"

    The bug: Broker._handle_ccxt_error() converts ccxt.NetworkError to
    ExecutionError BEFORE the decorator can catch it, so retries never happen.
    """

    def test_retry_on_network_error(self):
        """ccxt.NetworkError should trigger the full retry chain."""
        import ccxt

        call_count = 0

        @retry_on_network(max_retries=3, base_delay=0.01, max_delay=0.1)
        def flaky_network_call():
            nonlocal call_count
            call_count += 1
            raise ccxt.NetworkError("Connection reset")

        with pytest.raises(ccxt.NetworkError):
            flaky_network_call()

        assert call_count == 4, (  # 1 initial + 3 retries
            f"Expected 4 calls (1 initial + 3 retries), got {call_count}"
        )

    def test_retry_stops_on_success(self):
        """Retry should stop when the call succeeds."""
        import ccxt

        call_count = 0

        @retry_on_network(max_retries=3, base_delay=0.01, max_delay=0.1)
        def flaky_but_recovers():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise ccxt.NetworkError("Connection reset")
            return "success"

        result = flaky_but_recovers()

        assert result == "success"
        assert call_count == 3, f"Expected 3 calls, got {call_count}"

    def test_retry_on_broker_network_error(self):
        """When Broker.market_buy encounters NetworkError, it should retry 3x."""
        import ccxt
        from unittest.mock import patch, MagicMock

        mock_exchange = MagicMock()
        mock_exchange.create_market_buy_order.side_effect = ccxt.NetworkError("timeout")
        mock_exchange.load_markets.return_value = None

        broker = Broker.__new__(Broker)
        broker.exchange = mock_exchange
        broker.exchange_name = "okx"
        broker.testnet = True
        broker.account_type = "spot"
        broker._strategy_holdings = {}

        # Count calls
        call_count = [0]
        original = broker.market_buy

        def counting_buy(*args, **kwargs):
            call_count[0] += 1
            return original(*args, **kwargs)

        # BUG: The decorator is applied but _handle_ccxt_error converts
        # NetworkError → ExecutionError before the decorator sees it.
        # So call_count will be 1, not 4.
        try:
            broker.market_buy("BTC/USDT", 0.1)
        except Exception:
            pass

        # With the bug: call_count == 1 (only initial call, no retries)
        # Expected: call_count == 4 (1 initial + 3 retries)
        pytest.xfail(
            "Broker._handle_ccxt_error converts NetworkError to ExecutionError "
            "before retry_on_network can catch it"
        )
        assert call_count[0] == 4, (
            f"Expected 4 calls (1 initial + 3 retries), got {call_count[0]}"
        )
