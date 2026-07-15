"""Phase 1 behavioral regression tests.

These tests encode the desired behavior from the review. Tests that FAIL
indicate unresolved P0/P1 issues; tests that PASS represent behavior already
correct (or already fixed in Phase 0).

See docs/review-2026-07-10.md for the full list of issues.
"""

import ccxt
import numpy as np
import pandas as pd
import pytest
from unittest.mock import MagicMock, patch

from cryptoquant.data.closed_bar import BarFetchMeta
from cryptoquant.engine.backtest import BacktestEngine
from cryptoquant.engine.live import LiveEngine, TickAction
from cryptoquant.exceptions import ExecutionError, OrderRejectedError
from cryptoquant.execution.broker import Broker
from cryptoquant.execution.order import (
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
)
from cryptoquant.position.ledger import ManagedPositionLedger
from cryptoquant.strategy.base import Strategy


# ═══════════════════════════════════════════════════════════════════════════
# Test helpers
# ═══════════════════════════════════════════════════════════════════════════


def _raw_order(order_id: str = "test-123") -> dict:
    """A filled market buy as ccxt would report it."""
    return {
        "id": order_id,
        "symbol": "BTC/USDT",
        "side": "buy",
        "type": "market",
        "amount": 1.0,
        "price": 50000.0,
        "filled": 1.0,
        "remaining": 0.0,
        "cost": 50000.0,
        "fee": None,
        "status": "closed",
        "timestamp": 1704067200000,
    }


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
    """LiveEngine must trust its data_feed's closed-bar metadata rather than
    inferring "new bar" from a raw timestamp change — otherwise a still-
    forming candle can produce a signal that later repaints.

    Fixed by wiring ClosedBarFeed into LiveEngine (see cryptoquant/data/closed_bar.py,
    whose own stripping logic is covered by tests/test_closed_bar.py).

    See review 2.1: "实盘用尚未闭合的 K 线生成信号"
    """

    def test_no_signal_when_no_new_closed_bar(self):
        """When data_feed reports no new closed bar, the engine must not
        generate an entry signal even though a new (unclosed) candle exists
        in the fetched data."""
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

        df = pd.DataFrame(
            {
                "open": [100.0], "high": [101.0], "low": [99.0],
                "close": [100.5], "volume": [1000.0],
            },
            index=pd.DatetimeIndex([pd.Timestamp("2024-01-01 00:00")]),
        )

        data_feed = MagicMock()
        # ClosedBarFeed already stripped the still-forming bar and reports
        # no new closed bar since the last fetch.
        data_feed.fetch.return_value = (df, BarFetchMeta(has_new_closed=False, stripped=1))
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

        assert result.signal == 0, (
            f"Expected no signal without a new closed bar, got signal={result.signal}"
        )
        broker.market_buy.assert_not_called()


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
        data_feed.fetch.return_value = (df, BarFetchMeta(has_new_closed=True, stripped=0))
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
        data_feed.fetch.return_value = (df_t1, BarFetchMeta(has_new_closed=True, stripped=0))
        broker.get_position.side_effect = RuntimeError("exchange timeout")
        broker.market_buy.return_value = _mock_order()
        result1 = engine.tick()
        assert result1.action == TickAction.SKIP
        assert "unknown" in result1.reason.lower()

        # Tick 2: new bar, position fetch succeeds
        data_feed.fetch.return_value = (df_t2, BarFetchMeta(has_new_closed=True, stripped=0))
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

    Backed by ManagedPositionLedger (cryptoquant/position/ledger.py); FIFO
    lot consumption on sells is covered exhaustively in
    tests/test_position_ledger.py, not duplicated here.

    See review 2.2: "现货持仓没有策略所有权"
    """

    def test_no_holdings_returns_none(self):
        """Even if exchange has free balance, no strategy holdings → None."""
        mock_exchange = MagicMock()
        broker = Broker.__new__(Broker)
        broker.exchange = mock_exchange
        broker.account_type = "spot"
        broker.position_ledger = ManagedPositionLedger()

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
        broker.position_ledger = ManagedPositionLedger()
        broker.position_ledger.record_buy("BTC/USDT", 0.1, 48000.0, fee=0.0, timestamp=0)

        mock_exchange.fetch_ticker.return_value = {"last": 50000.0}

        pos = broker._get_spot_position("BTC/USDT")

        assert pos is not None
        assert pos.amount == 0.1, f"Expected 0.1, got {pos.amount}"
        assert pos.entry_price == 48000.0, (
            f"Expected entry_price 48000.0, got {pos.entry_price}"
        )
        assert pos.side == "long"


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
# P1: annualized return must never be NaN once equity is wiped out
# ═══════════════════════════════════════════════════════════════════════════


class TestAnnualizedReturnOnBlowup:
    """(1 + r) ** (1 / years) takes a negative base once equity goes
    negative, and numpy answers with a bare NaN that flows into the report
    and dashboard. Spot long-only can't get there; a short can.
    """

    @staticmethod
    def _rally(n_bars: int = 300) -> pd.DataFrame:
        """An 11x rally — enough to wipe out a 1x short."""
        dates = pd.date_range("2024-01-01", periods=n_bars, freq="1h")
        close = np.linspace(100.0, 1100.0, n_bars)
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

    def test_blown_up_short_does_not_report_nan(self):
        engine = BacktestEngine(initial_capital=10000, commission=0.0, slippage=0.0)
        # sell_bar with no buy_bar opens a short into the rally.
        result = engine.run(self._rally(), BuyThenSell({"buy_bar": 999, "sell_bar": 10}))
        metrics = result.metrics

        assert metrics.total_return_pct <= -100, (
            f"setup must actually wipe equity out, got "
            f"{metrics.total_return_pct:.2f}%"
        )
        assert not np.isnan(metrics.annualized_return_pct), (
            "annualized return is NaN — it will flow into the report unnoticed"
        )
        assert metrics.annualized_return_pct == -100.0

    def test_surviving_loss_still_computes_normally(self):
        """The guard must not swallow ordinary losses. Held long through a
        20% decline lasting exactly one year, so the annualized figure has
        to come back as the total return itself."""
        df = _make_ohlcv(8760, start_price=100.0, trend="down")
        engine = BacktestEngine(initial_capital=10000, commission=0.0, slippage=0.0)
        metrics = engine.run(df, BuyOnNewBar()).metrics

        assert -100 < metrics.total_return_pct < 0
        assert not np.isnan(metrics.annualized_return_pct)
        assert metrics.annualized_return_pct == pytest.approx(
            metrics.total_return_pct, abs=0.01
        )


# ═══════════════════════════════════════════════════════════════════════════
# P1-6: NetworkError retry actually happens 3 times
# ═══════════════════════════════════════════════════════════════════════════


@pytest.fixture
def _no_backoff_sleep():
    """Collapse the retry backoff so these tests don't sleep for real."""
    with patch("cryptoquant.utils.time.sleep"):
        yield


@pytest.fixture
def retry_broker(_no_backoff_sleep):
    """A Broker whose ccxt exchange is a mock, but whose ccxt exception
    types are the real ones — the retry path keys off those types."""
    with patch("cryptoquant.execution.broker.ccxt") as mock_ccxt:
        mock_exchange = MagicMock()
        mock_ccxt.okx = MagicMock(return_value=mock_exchange)
        for name in (
            "NetworkError",
            "RateLimitExceeded",
            "AuthenticationError",
            "InsufficientFunds",
            "InvalidOrder",
            "OrderNotFound",
            "ExchangeError",
        ):
            setattr(mock_ccxt, name, getattr(ccxt, name))
        yield Broker(exchange="okx", testnet=True), mock_exchange


class TestNetworkRetryCount:
    """Broker's @retry_on_network must actually retry the underlying ccxt call.

    See review 3.4: "网络重试装饰器实际没有重试 Broker 调用"

    The bug: _handle_ccxt_error() converted ccxt.NetworkError into
    ExecutionError before the decorator could see it, so retries never
    happened. Asserting on the decorator in isolation passes either way —
    these tests drive real Broker methods, which is where the bug lived.
    """

    def test_get_balance_retries_network_error(self, retry_broker):
        broker, exchange = retry_broker
        exchange.fetch_balance.side_effect = ccxt.NetworkError("Connection reset")

        with pytest.raises(ExecutionError, match="network error"):
            broker.get_balance("USDT")

        assert exchange.fetch_balance.call_count == 4, (  # 1 initial + 3 retries
            f"Expected 4 calls, got {exchange.fetch_balance.call_count}"
        )

    def test_get_balance_recovers_after_blip(self, retry_broker):
        broker, exchange = retry_broker
        exchange.fetch_balance.side_effect = [
            ccxt.NetworkError("timeout"),
            ccxt.NetworkError("timeout"),
            {"USDT": {"free": 10000.0}},
        ]

        assert broker.get_balance("USDT") == 10000.0
        assert exchange.fetch_balance.call_count == 3

    def test_rate_limit_is_retried(self, retry_broker):
        """RateLimitExceeded subclasses NetworkError, so it backs off too."""
        broker, exchange = retry_broker
        exchange.fetch_ticker.side_effect = ccxt.RateLimitExceeded("slow down")

        with pytest.raises(ExecutionError):
            broker.get_ticker("BTC/USDT")

        assert exchange.fetch_ticker.call_count == 4

    def test_auth_error_is_not_retried(self, retry_broker):
        """Permanent failures must fail fast rather than burn the backoff budget."""
        broker, exchange = retry_broker
        exchange.fetch_balance.side_effect = ccxt.AuthenticationError("bad key")

        with pytest.raises(ExecutionError, match="authentication"):
            broker.get_balance("USDT")

        assert exchange.fetch_balance.call_count == 1

    def test_swap_position_query_retries(self, retry_broker):
        """A flat report on an unreachable exchange would invite a double entry."""
        broker, exchange = retry_broker
        broker.account_type = "swap"
        exchange.fetch_positions.side_effect = ccxt.NetworkError("timeout")

        with pytest.raises(ExecutionError, match="network error"):
            broker.get_position("BTC/USDT")

        assert exchange.fetch_positions.call_count == 4

    def test_cancel_order_retries(self, retry_broker):
        broker, exchange = retry_broker
        exchange.cancel_order.side_effect = ccxt.NetworkError("timeout")

        with pytest.raises(ExecutionError, match="network error"):
            broker.cancel_order("order-1", "BTC/USDT")

        assert exchange.cancel_order.call_count == 3  # 1 initial + 2 retries


class TestOrderPlacementIdempotency:
    """Retrying a market order is only safe under an idempotency key.

    A lost response is ambiguous: the order may already be live. Broker
    tags every order with a clientOrderId and looks that key up before
    re-sending, so a timeout can never open a second position.
    """

    def test_order_carries_client_order_id(self, retry_broker):
        broker, exchange = retry_broker
        exchange.create_market_buy_order.return_value = _raw_order()

        broker.market_buy("BTC/USDT", 1.0)

        params = exchange.create_market_buy_order.call_args[0][2]
        assert params["clientOrderId"].startswith("cq")

    def test_lost_response_adopts_the_live_order(self, retry_broker):
        """The order landed but the reply didn't — must adopt, not re-send."""
        broker, exchange = retry_broker
        exchange.create_market_buy_order.side_effect = ccxt.RequestTimeout("lost")
        exchange.fetch_order.return_value = _raw_order()

        order = broker.market_buy("BTC/USDT", 1.0)

        assert order.id == "test-123"
        assert exchange.create_market_buy_order.call_count == 1, (
            "re-sent an order that was already live — double position"
        )

    def test_order_never_landed_is_resent(self, retry_broker):
        broker, exchange = retry_broker
        exchange.create_market_buy_order.side_effect = [
            ccxt.RequestTimeout("lost"),
            _raw_order(),
        ]
        exchange.fetch_order.side_effect = ccxt.OrderNotFound("no such order")

        order = broker.market_buy("BTC/USDT", 1.0)

        assert order.id == "test-123"
        assert exchange.create_market_buy_order.call_count == 2

    def test_resend_uses_the_same_key(self, retry_broker):
        broker, exchange = retry_broker
        exchange.create_market_buy_order.side_effect = [
            ccxt.RequestTimeout("lost"),
            _raw_order(),
        ]
        exchange.fetch_order.side_effect = ccxt.OrderNotFound("no such order")

        broker.market_buy("BTC/USDT", 1.0)

        keys = {
            call[0][2]["clientOrderId"]
            for call in exchange.create_market_buy_order.call_args_list
        }
        assert len(keys) == 1, "a fresh key per attempt defeats the whole point"

    def test_unverifiable_order_is_not_resent(self, retry_broker):
        """If the lookup itself can't reach the exchange, "could not check"
        must not be read as "never placed"."""
        broker, exchange = retry_broker
        exchange.create_market_buy_order.side_effect = ccxt.RequestTimeout("lost")
        exchange.fetch_order.side_effect = ccxt.NetworkError("still down")
        exchange.fetch_open_orders.side_effect = ccxt.NetworkError("still down")
        exchange.fetch_closed_orders.side_effect = ccxt.NetworkError("still down")

        with pytest.raises(ExecutionError):
            broker.market_buy("BTC/USDT", 1.0)

        assert exchange.create_market_buy_order.call_count == 1

    def test_invalid_order_is_not_retried(self, retry_broker):
        broker, exchange = retry_broker
        exchange.create_market_buy_order.side_effect = ccxt.InvalidOrder("too small")

        with pytest.raises(OrderRejectedError):
            broker.market_buy("BTC/USDT", 1.0)

        assert exchange.create_market_buy_order.call_count == 1
