"""Tests for LiveEngine — all mocked."""

import numpy as np
import pandas as pd
import pytest
from unittest.mock import MagicMock

from cryptoquant.engine.live import LiveEngine, TickAction
from cryptoquant.execution.order import (
    Order,
    OrderSide,
    OrderStatus,
    OrderType,
    Position,
)
from cryptoquant.strategy.base import Strategy


class MockStrategy(Strategy):
    timeframe = "1h"
    min_bars = 50
    DEFAULT_PARAMS = {}

    @property
    def name(self) -> str:
        return "MockStrategy"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        df = self.preprocess(df)
        return pd.Series(0, index=df.index, dtype=int)


class BuySignalStrategy(MockStrategy):
    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        df = self.preprocess(df)
        signal = pd.Series(0, index=df.index, dtype=int)
        signal.iloc[-1] = 1
        return signal


class SellSignalStrategy(MockStrategy):
    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        df = self.preprocess(df)
        signal = pd.Series(0, index=df.index, dtype=int)
        signal.iloc[-1] = -1
        return signal


@pytest.fixture
def mock_broker():
    broker = MagicMock()
    broker.exchange_name = "okx"
    broker.testnet = True
    broker.account_type = "spot"
    broker.can_short = False
    broker.get_balance.return_value = 10000.0
    broker.get_position.return_value = None
    return broker


@pytest.fixture
def mock_cache():
    cache = MagicMock()
    dates = pd.date_range("2024-01-01", periods=100, freq="1h")
    close = np.linspace(100, 110, 100)
    df = pd.DataFrame(
        {
            "open": close - 0.1,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": np.full(100, 1000.0),
        },
        index=dates,
    )
    cache.get_ohlcv.return_value = df
    return cache


@pytest.fixture
def mock_state_mgr(tmp_path):
    from cryptoquant.engine.state import StateManager

    return StateManager(state_dir=str(tmp_path))


@pytest.fixture
def engine(mock_broker, mock_cache, mock_state_mgr):
    return LiveEngine(
        broker=mock_broker,
        strategy=MockStrategy(),
        cache=mock_cache,
        state_dir=str(mock_state_mgr.state_dir),
        symbol="BTC/USDT",
        min_order_usdt=10.0,
        max_order_usdt=10000.0,
    )


def _make_order(status="closed", side="buy", filled=0.1, amount=0.1):
    return Order(
        id="test-123",
        exchange="okx",
        symbol="BTC/USDT",
        side=OrderSide.BUY if side == "buy" else OrderSide.SELL,
        type=OrderType.MARKET,
        amount=amount,
        price=50000.0,
        filled=filled,
        remaining=amount - filled,
        cost=filled * 50000.0,
        fee=None,
        status=OrderStatus(status),
        timestamp=1704067200000,
    )


class TestLiveEngineTick:
    def test_no_signal_is_noop(self, engine, mock_broker, mock_cache):
        mock_broker.get_position.return_value = None
        result = engine.tick()
        assert result.action == TickAction.NOOP
        assert result.signal == 0

    def test_entry_on_buy_signal(
        self, mock_broker, mock_cache, mock_state_mgr
    ):
        engine = LiveEngine(
            broker=mock_broker,
            strategy=BuySignalStrategy(),
            cache=mock_cache,
            state_dir=str(mock_state_mgr.state_dir),
            symbol="BTC/USDT",
            max_order_usdt=10000.0,
        )
        mock_broker.get_position.return_value = None
        mock_broker.market_buy.return_value = _make_order()

        result = engine.tick()
        assert result.action == TickAction.ENTRY_LONG
        mock_broker.market_buy.assert_called_once()

    def test_exit_on_reverse_signal(
        self, mock_broker, mock_cache, mock_state_mgr
    ):
        engine = LiveEngine(
            broker=mock_broker,
            strategy=SellSignalStrategy(),
            cache=mock_cache,
            state_dir=str(mock_state_mgr.state_dir),
            symbol="BTC/USDT",
        )
        position = Position(
            symbol="BTC/USDT",
            side="long",
            amount=0.1,
            entry_price=50000.0,
            current_price=51000.0,
            unrealized_pnl=2.0,
            unrealized_pnl_abs=100.0,
            timestamp=1704067200000,
        )
        mock_broker.get_position.return_value = position
        mock_broker.market_sell.return_value = _make_order(side="sell")

        result = engine.tick()
        assert result.action == TickAction.EXIT
        mock_broker.market_sell.assert_called_once()

    def test_skip_on_insufficient_data(self, engine, mock_cache):
        dates = pd.date_range("2024-01-01", periods=10, freq="1h")
        df = pd.DataFrame(
            {
                "open": [100] * 10,
                "high": [101] * 10,
                "low": [99] * 10,
                "close": [100] * 10,
                "volume": [1000] * 10,
            },
            index=dates,
        )
        mock_cache.get_ohlcv.return_value = df

        result = engine.tick()
        assert result.action == TickAction.SKIP
        assert "insufficient data" in result.reason

    def test_cooldown_skips_ticks(self, engine, mock_broker):
        engine._cooldown_remaining = 2
        result = engine.tick()
        assert result.action == TickAction.SKIP
        assert "cooldown" in result.reason
        assert engine._cooldown_remaining == 1


class TestPositionSizing:
    def test_calculate_with_risk_manager(
        self, mock_broker, mock_cache, mock_state_mgr
    ):
        from cryptoquant.risk.manager import RiskManager
        from cryptoquant.risk.sizer import FixedSizer

        risk_mgr = RiskManager(sizer=FixedSizer(risk_pct=50.0))
        engine = LiveEngine(
            broker=mock_broker,
            strategy=BuySignalStrategy(),
            cache=mock_cache,
            risk_manager=risk_mgr,
            state_dir=str(mock_state_mgr.state_dir),
            symbol="BTC/USDT",
            max_order_usdt=10000.0,
        )

        amount = engine._calculate_position_size(10000.0)
        assert amount == 5000.0

    def test_calculate_without_risk_manager(self, engine):
        amount = engine._calculate_position_size(10000.0)
        assert amount == 5000.0


class TestPartialFill:
    def test_handle_90pct_fill(self, engine, mock_broker):
        order = _make_order(
            status="partially_filled", filled=0.091, amount=0.1
        )
        result = engine._handle_partial_fill(order)
        assert result.status == OrderStatus.CLOSED
        assert result.amount == 0.091

    def test_handle_low_fill_cancels(self, engine, mock_broker):
        order = _make_order(
            status="partially_filled", filled=0.05, amount=0.1
        )
        result = engine._handle_partial_fill(order)
        mock_broker.cancel_order.assert_called_once()
        assert result.amount == 0.05


class TestStatePersistence:
    def test_save_state(self, engine, mock_broker):
        mock_broker.get_position.return_value = None
        engine._save_state()

    def test_restore_state(
        self, mock_broker, mock_cache, mock_state_mgr
    ):
        from cryptoquant.engine.state import EngineState

        state = EngineState(
            timestamp=1704067200000,
            strategy_name="MockStrategy",
            symbol="BTC/USDT",
            balance=10000.0,
            initial_capital=10000.0,
            has_position=False,
            position_side="",
            position_entry_price=0.0,
            position_amount=0.0,
            position_entry_time=0,
            active_order_ids=[],
            total_trades=5,
            total_pnl_pct=2.5,
            last_signal=0,
            last_tick_time=1704067200000,
        )
        mock_state_mgr.save(state)

        engine = LiveEngine(
            broker=mock_broker,
            strategy=MockStrategy(),
            cache=mock_cache,
            state_dir=str(mock_state_mgr.state_dir),
            symbol="BTC/USDT",
        )
        assert engine._trades_count == 5
        assert engine._total_pnl_pct == 2.5
