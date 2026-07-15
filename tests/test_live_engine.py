"""Tests for LiveEngine — all mocked."""

import numpy as np
import pandas as pd
import pytest
from unittest.mock import MagicMock

from cryptoquant.data.closed_bar import BarFetchMeta
from cryptoquant.data.quality import QualityReport
from cryptoquant.engine.live import LiveEngine, TickAction
from cryptoquant.exceptions import DataValidationError
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


class FlatPositionStrategy(MockStrategy):
    """Position-style: signal 0 means target flat, i.e. close what we hold."""

    signal_is_position = True


class HoldPositionStrategy(MockStrategy):
    """Position-style: signal 1 means stay long."""

    signal_is_position = True

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        df = self.preprocess(df)
        return pd.Series(1, index=df.index, dtype=int)


def _long_position(entry_price=100.0):
    return Position(
        symbol="BTC/USDT",
        side="long",
        amount=1.0,
        entry_price=entry_price,
        current_price=entry_price,
        unrealized_pnl=0.0,
        unrealized_pnl_abs=0.0,
        timestamp=1704067200000,
    )


@pytest.fixture
def mock_broker():
    broker = MagicMock()
    broker.exchange_name = "okx"
    broker.testnet = True
    broker.account_type = "spot"
    broker.can_short = False
    broker.get_balance.return_value = 10000.0
    broker.get_position.return_value = None
    broker.normalize_order_amount.side_effect = (
        lambda symbol, amount, price=None: round(amount, 8)
    )
    return broker


@pytest.fixture
def mock_data_feed():
    data_feed = MagicMock()
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
    data_feed.fetch.return_value = (df, BarFetchMeta(has_new_closed=True, stripped=0))
    data_feed.last_quality_report = None
    return data_feed


@pytest.fixture
def mock_state_mgr(tmp_path):
    from cryptoquant.engine.state import StateManager

    return StateManager(state_dir=str(tmp_path))


@pytest.fixture
def engine(mock_broker, mock_data_feed, mock_state_mgr):
    return LiveEngine(
        broker=mock_broker,
        strategy=MockStrategy(),
        data_feed=mock_data_feed,
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
    def test_no_signal_is_noop(self, engine, mock_broker, mock_data_feed):
        mock_broker.get_position.return_value = None
        result = engine.tick()
        assert result.action == TickAction.NOOP
        assert result.signal == 0

    def test_entry_on_buy_signal(
        self, mock_broker, mock_data_feed, mock_state_mgr
    ):
        engine = LiveEngine(
            broker=mock_broker,
            strategy=BuySignalStrategy(),
            data_feed=mock_data_feed,
            state_dir=str(mock_state_mgr.state_dir),
            symbol="BTC/USDT",
            max_order_usdt=10000.0,
        )
        mock_broker.get_position.return_value = None
        mock_broker.market_buy.return_value = _make_order()

        result = engine.tick()
        assert result.action == TickAction.ENTRY_LONG
        mock_broker.market_buy.assert_called_once()
        amount = mock_broker.market_buy.call_args.args[1]
        assert amount == pytest.approx(5000.0 / 110.0)

    def test_exit_on_reverse_signal(
        self, mock_broker, mock_data_feed, mock_state_mgr
    ):
        engine = LiveEngine(
            broker=mock_broker,
            strategy=SellSignalStrategy(),
            data_feed=mock_data_feed,
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

    def test_skip_on_insufficient_data(self, engine, mock_data_feed):
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
        mock_data_feed.fetch.return_value = (df, BarFetchMeta(has_new_closed=True, stripped=0))

        result = engine.tick()
        assert result.action == TickAction.SKIP
        assert "insufficient data" in result.reason

    def test_paper_fill_uses_forming_bar_open_hint(
        self, engine, mock_data_feed, mock_broker
    ):
        frame, _meta = mock_data_feed.fetch.return_value
        mock_data_feed.fetch.return_value = (
            frame,
            BarFetchMeta(
                has_new_closed=True,
                stripped=1,
                execution_price=123.45,
            ),
        )

        engine.tick()

        mock_broker.update_price.assert_called_once_with("BTC/USDT", 123.45)

    def test_skip_on_data_validation_error(self, engine, mock_data_feed, mock_broker):
        mock_data_feed.fetch.side_effect = DataValidationError("gap detected")

        result = engine.tick()

        assert result.action == TickAction.SKIP
        assert "data error" in result.reason
        mock_broker.market_buy.assert_not_called()

    def test_primary_data_error_does_not_block_existing_position_time_exit(
        self, mock_broker, mock_data_feed, mock_state_mgr
    ):
        engine = LiveEngine(
            broker=mock_broker,
            strategy=MockStrategy(),
            data_feed=mock_data_feed,
            state_dir=str(mock_state_mgr.state_dir),
            symbol="BTC/USDT",
            max_hold_hours=12,
        )
        position = _long_position()
        position.timestamp = 0
        mock_broker.get_position.return_value = position
        mock_broker.market_sell.return_value = _make_order(side="sell")
        mock_data_feed.fetch.side_effect = DataValidationError("primary gap")

        result = engine.tick()

        assert result.action == TickAction.EXIT
        assert "time_exit" in result.reason
        mock_broker.market_sell.assert_called_once()

    def test_skip_on_unhealthy_quality_report(self, engine, mock_data_feed, mock_broker):
        mock_data_feed.last_quality_report = QualityReport(
            is_healthy=False,
            gap_count=0,
            stale_bars=1,
            outlier_count=0,
            volume_anomaly_count=0,
        )

        result = engine.tick()

        assert result.action == TickAction.SKIP
        assert result.reason == "data quality unhealthy"
        mock_broker.market_buy.assert_not_called()

    def test_cooldown_skips_ticks(self, engine, mock_broker):
        engine._cooldown_remaining = 2
        result = engine.tick()
        assert result.action == TickAction.SKIP
        assert "cooldown" in result.reason
        assert engine._cooldown_remaining == 1

    @pytest.mark.parametrize("gate", ["quality", "cooldown", "balance"])
    def test_entry_gate_does_not_block_existing_position_time_exit(
        self, gate, mock_broker, mock_data_feed, mock_state_mgr
    ):
        engine = LiveEngine(
            broker=mock_broker,
            strategy=MockStrategy(),
            data_feed=mock_data_feed,
            state_dir=str(mock_state_mgr.state_dir),
            symbol="BTC/USDT",
            max_hold_hours=12,
        )
        position = _long_position()
        position.timestamp = 0
        mock_broker.get_position.return_value = position
        mock_broker.market_sell.return_value = _make_order(side="sell")
        if gate == "quality":
            mock_data_feed.last_quality_report = QualityReport(
                is_healthy=False,
                gap_count=1,
                stale_bars=0,
                outlier_count=0,
                volume_anomaly_count=0,
            )
        elif gate == "cooldown":
            engine._cooldown_remaining = 2
        else:
            mock_broker.get_balance.side_effect = RuntimeError("balance down")

        result = engine.tick()

        assert result.action == TickAction.EXIT
        assert "time_exit" in result.reason
        mock_broker.market_sell.assert_called_once()

    def test_persisted_decision_watermark_prevents_restart_replay(
        self, mock_broker, mock_data_feed, mock_state_mgr
    ):
        frame, _meta = mock_data_feed.fetch.return_value
        bar_ts = int(frame.index[-1].value // 1_000_000)
        mock_data_feed.fetch.return_value = (
            frame,
            BarFetchMeta(
                has_new_closed=True,
                stripped=0,
                common_bar_ts=bar_ts,
                decision_ready=True,
            ),
        )
        mock_broker.get_position.return_value = None
        mock_broker.market_buy.return_value = _make_order()
        first = LiveEngine(
            broker=mock_broker,
            strategy=BuySignalStrategy(),
            data_feed=mock_data_feed,
            state_dir=str(mock_state_mgr.state_dir),
            symbol="BTC/USDT",
            max_order_usdt=10000.0,
        )

        assert first.tick().action == TickAction.ENTRY_LONG
        first._save_state()
        restarted = LiveEngine(
            broker=mock_broker,
            strategy=BuySignalStrategy(),
            data_feed=mock_data_feed,
            state_dir=str(mock_state_mgr.state_dir),
            symbol="BTC/USDT",
            max_order_usdt=10000.0,
        )

        assert restarted.tick().action == TickAction.NOOP
        assert mock_broker.market_buy.call_count == 1


class TestPositionStyleSignalExit:
    """Strategies with signal_is_position=True return a target position, so a
    0 while holding must close. The backtest has always done this; live read 0
    as "no action" and rode positions that the backtest had already exited."""

    def _engine(self, strategy, mock_broker, mock_data_feed, mock_state_mgr):
        return LiveEngine(
            broker=mock_broker,
            strategy=strategy,
            data_feed=mock_data_feed,
            state_dir=str(mock_state_mgr.state_dir),
            symbol="BTC/USDT",
            max_order_usdt=10000.0,
        )

    def test_flat_signal_closes_position(
        self, mock_broker, mock_data_feed, mock_state_mgr
    ):
        engine = self._engine(
            FlatPositionStrategy(), mock_broker, mock_data_feed, mock_state_mgr
        )
        mock_broker.get_position.return_value = _long_position()
        mock_broker.market_sell.return_value = _make_order(side="sell")

        result = engine.tick()

        assert result.action == TickAction.EXIT
        assert "signal_exit" in result.reason
        mock_broker.market_sell.assert_called_once()

    def test_stale_bar_does_not_close_position(
        self, mock_broker, mock_data_feed, mock_state_mgr
    ):
        """Without a new bar the engine forces signal to 0. Treating that as
        "target flat" would liquidate the position on every poll."""
        engine = self._engine(
            FlatPositionStrategy(), mock_broker, mock_data_feed, mock_state_mgr
        )
        df, _ = mock_data_feed.fetch.return_value
        mock_data_feed.fetch.return_value = (
            df,
            BarFetchMeta(has_new_closed=False, stripped=0),
        )
        mock_broker.get_position.return_value = _long_position()

        result = engine.tick()

        assert result.action == TickAction.NOOP
        mock_broker.market_sell.assert_not_called()

    def test_holding_signal_keeps_position(
        self, mock_broker, mock_data_feed, mock_state_mgr
    ):
        engine = self._engine(
            HoldPositionStrategy(), mock_broker, mock_data_feed, mock_state_mgr
        )
        mock_broker.get_position.return_value = _long_position()

        result = engine.tick()

        assert result.action == TickAction.NOOP
        mock_broker.market_sell.assert_not_called()

    def test_pulse_strategy_ignores_zero_signal(
        self, mock_broker, mock_data_feed, mock_state_mgr
    ):
        """Pulse-style strategies emit 0 constantly to mean "no action", so
        the flat rule must stay opt-in."""
        assert MockStrategy.signal_is_position is False
        engine = self._engine(
            MockStrategy(), mock_broker, mock_data_feed, mock_state_mgr
        )
        mock_broker.get_position.return_value = _long_position()

        result = engine.tick()

        assert result.action == TickAction.NOOP
        mock_broker.market_sell.assert_not_called()

    def test_stop_loss_outranks_flat_signal(
        self, mock_broker, mock_data_feed, mock_state_mgr
    ):
        """Both fire on the same bar; the reported reason should be the stop."""
        engine = LiveEngine(
            broker=mock_broker,
            strategy=FlatPositionStrategy(),
            data_feed=mock_data_feed,
            state_dir=str(mock_state_mgr.state_dir),
            symbol="BTC/USDT",
            max_order_usdt=10000.0,
            stop_loss_pct=1.0,
        )
        # Feed closes run 100..110, so an entry at 1000 is far through the stop.
        mock_broker.get_position.return_value = _long_position(entry_price=1000.0)
        mock_broker.market_sell.return_value = _make_order(side="sell")

        result = engine.tick()

        assert result.action == TickAction.EXIT
        assert "stop_loss" in result.reason


class TestLiveExitPriceWindow:
    def _engine(self, mock_broker, mock_data_feed, mock_state_mgr):
        return LiveEngine(
            broker=mock_broker,
            strategy=MockStrategy(),
            data_feed=mock_data_feed,
            state_dir=str(mock_state_mgr.state_dir),
            symbol="BTC/USDT",
            stop_loss_pct=5.0,
            take_profit_pct=5.0,
        )

    def test_stale_candle_extrema_before_entry_do_not_trigger_exit(
        self, mock_broker, mock_data_feed, mock_state_mgr
    ):
        engine = self._engine(mock_broker, mock_data_feed, mock_state_mgr)
        df, _ = mock_data_feed.fetch.return_value
        df.loc[df.index[-1], ["high", "low"]] = [120.0, 80.0]
        mock_data_feed.fetch.return_value = (
            df,
            BarFetchMeta(has_new_closed=False, stripped=0),
        )
        position = _long_position()
        position.timestamp = int(df.index[-1].value // 1_000_000) + 1
        mock_broker.get_position.return_value = position
        mock_broker.get_ticker.return_value = {"last": 100.0}

        result = engine.tick()

        assert result.action == TickAction.NOOP
        mock_broker.market_sell.assert_not_called()

    def test_entry_candle_extrema_do_not_trigger_exit(
        self, mock_broker, mock_data_feed, mock_state_mgr
    ):
        engine = self._engine(mock_broker, mock_data_feed, mock_state_mgr)
        df, _ = mock_data_feed.fetch.return_value
        df.loc[df.index[-1], ["high", "low"]] = [120.0, 80.0]
        position = _long_position()
        position.timestamp = int(df.index[-1].value // 1_000_000) + 1
        mock_broker.get_position.return_value = position
        mock_broker.get_ticker.return_value = {"last": 100.0}

        result = engine.tick()

        assert result.action == TickAction.NOOP
        mock_broker.market_sell.assert_not_called()

    def test_current_ticker_can_trigger_stop_without_new_bar(
        self, mock_broker, mock_data_feed, mock_state_mgr
    ):
        engine = self._engine(mock_broker, mock_data_feed, mock_state_mgr)
        df, _ = mock_data_feed.fetch.return_value
        mock_data_feed.fetch.return_value = (
            df,
            BarFetchMeta(has_new_closed=False, stripped=0),
        )
        mock_broker.get_position.return_value = _long_position()
        mock_broker.get_ticker.return_value = {"last": 94.0}
        mock_broker.market_sell.return_value = _make_order(side="sell")

        result = engine.tick()

        assert result.action == TickAction.EXIT
        assert "stop_loss" in result.reason
        mock_broker.market_sell.assert_called_once()


class TestPositionSizing:
    def test_calculate_with_risk_manager(
        self, mock_broker, mock_data_feed, mock_state_mgr
    ):
        from cryptoquant.risk.manager import RiskManager
        from cryptoquant.risk.sizer import FixedSizer

        risk_mgr = RiskManager(
            sizer=FixedSizer(risk_pct=50.0),
            max_per_trade_risk_pct=100.0,
        )
        engine = LiveEngine(
            broker=mock_broker,
            strategy=BuySignalStrategy(),
            data_feed=mock_data_feed,
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

    def test_quote_to_base_amount(self, engine):
        amount = engine._quote_to_base_amount(5500.0, 110.0)
        assert amount == pytest.approx(50.0)

    def test_drawdown_multiplier_reduces_position_size(
        self, mock_broker, mock_data_feed, mock_state_mgr
    ):
        from cryptoquant.risk.manager import RiskManager

        risk_mgr = RiskManager(
            initial_balance=10000.0,
            max_per_trade_risk_pct=100.0,
        )
        risk_mgr._peak_balance = 10000.0
        risk_mgr.update_balance(8800.0)
        engine = LiveEngine(
            broker=mock_broker,
            strategy=BuySignalStrategy(),
            data_feed=mock_data_feed,
            risk_manager=risk_mgr,
            state_dir=str(mock_state_mgr.state_dir),
            symbol="BTC/USDT",
            max_order_usdt=10000.0,
        )

        amount = engine._calculate_position_size(8800.0, mock_data_feed.fetch.return_value[0])
        assert amount == pytest.approx(4312.0)

    def test_external_sizer_is_still_capped_by_trade_risk(
        self, mock_broker, mock_data_feed, mock_state_mgr
    ):
        from cryptoquant.risk.manager import RiskManager
        from cryptoquant.risk.sizer import FixedSizer

        risk_mgr = RiskManager(
            initial_balance=10000.0,
            max_per_trade_risk_pct=2.0,
        )
        engine = LiveEngine(
            broker=mock_broker,
            strategy=BuySignalStrategy(),
            data_feed=mock_data_feed,
            risk_manager=risk_mgr,
            state_dir=str(mock_state_mgr.state_dir),
            symbol="BTC/USDT",
            sizer=FixedSizer(risk_pct=50.0),
            max_order_usdt=10000.0,
        )

        assert engine._calculate_position_size(10000.0) == pytest.approx(200.0)


class TestRiskManagerHooks:
    def test_entry_records_risk_position(
        self, mock_broker, mock_data_feed, mock_state_mgr
    ):
        from cryptoquant.risk.manager import RiskManager

        risk_mgr = RiskManager(initial_balance=10000.0)
        engine = LiveEngine(
            broker=mock_broker,
            strategy=BuySignalStrategy(),
            data_feed=mock_data_feed,
            risk_manager=risk_mgr,
            state_dir=str(mock_state_mgr.state_dir),
            symbol="BTC/USDT",
            max_order_usdt=10000.0,
        )
        mock_broker.get_position.return_value = None
        mock_broker.market_buy.return_value = _make_order(filled=1.0, amount=1.0)

        result = engine.tick()

        assert result.action == TickAction.ENTRY_LONG
        assert risk_mgr.get_positions() == {"BTC/USDT": "long"}

    def test_balance_failure_blocks_entry(
        self, mock_broker, mock_data_feed, mock_state_mgr
    ):
        engine = LiveEngine(
            broker=mock_broker,
            strategy=BuySignalStrategy(),
            data_feed=mock_data_feed,
            state_dir=str(mock_state_mgr.state_dir),
            symbol="BTC/USDT",
        )
        mock_broker.get_position.return_value = None
        mock_broker.get_balance.side_effect = RuntimeError("balance unavailable")

        result = engine.tick()

        assert result.action == TickAction.SKIP
        assert "balance state unknown" in result.reason
        mock_broker.market_buy.assert_not_called()

    def test_configured_quote_currency_is_used(
        self, mock_broker, mock_data_feed, mock_state_mgr
    ):
        engine = LiveEngine(
            broker=mock_broker,
            strategy=MockStrategy(),
            data_feed=mock_data_feed,
            state_dir=str(mock_state_mgr.state_dir),
            symbol="BTC/USDC",
            quote_currency="USDC",
        )

        engine.tick()

        mock_broker.get_balance.assert_called_with("USDC")

    def test_entry_skips_when_broker_rejects_amount(
        self, mock_broker, mock_data_feed, mock_state_mgr
    ):
        from cryptoquant.exceptions import OrderRejectedError

        engine = LiveEngine(
            broker=mock_broker,
            strategy=BuySignalStrategy(),
            data_feed=mock_data_feed,
            state_dir=str(mock_state_mgr.state_dir),
            symbol="BTC/USDT",
            max_order_usdt=10000.0,
        )
        mock_broker.get_position.return_value = None
        mock_broker.normalize_order_amount.side_effect = OrderRejectedError(
            "below exchange min"
        )

        result = engine.tick()

        assert result.action == TickAction.SKIP
        assert "order rejected" in result.reason
        mock_broker.market_buy.assert_not_called()

    def test_exit_records_risk_stats(
        self, mock_broker, mock_data_feed, mock_state_mgr
    ):
        from cryptoquant.risk.manager import RiskManager

        risk_mgr = RiskManager(initial_balance=10000.0)
        risk_mgr.record_entry("BTC/USDT", "long")
        engine = LiveEngine(
            broker=mock_broker,
            strategy=SellSignalStrategy(),
            data_feed=mock_data_feed,
            risk_manager=risk_mgr,
            state_dir=str(mock_state_mgr.state_dir),
            symbol="BTC/USDT",
        )
        position = Position(
            symbol="BTC/USDT",
            side="long",
            amount=1.0,
            entry_price=100.0,
            current_price=110.0,
            unrealized_pnl=10.0,
            unrealized_pnl_abs=10.0,
            timestamp=1704067200000,
        )
        mock_broker.get_position.return_value = position
        mock_broker.get_balance.return_value = 10100.0
        mock_broker.market_sell.return_value = _make_order(
            side="sell", filled=1.0, amount=1.0
        )
        mock_broker.market_sell.return_value.price = 110.0

        result = engine.tick()

        assert result.action == TickAction.EXIT
        stats = risk_mgr.get_daily_stats()
        assert stats.total_trades == 1
        assert stats.wins == 1
        assert stats.total_pnl_abs == pytest.approx(10.0)

    def test_losing_exit_records_negative_absolute_pnl(
        self, mock_broker, mock_data_feed, mock_state_mgr
    ):
        from cryptoquant.risk.manager import RiskManager

        risk_mgr = RiskManager(initial_balance=10000.0)
        risk_mgr.record_entry("BTC/USDT", "long")
        engine = LiveEngine(
            broker=mock_broker,
            strategy=SellSignalStrategy(),
            data_feed=mock_data_feed,
            risk_manager=risk_mgr,
            state_dir=str(mock_state_mgr.state_dir),
            symbol="BTC/USDT",
        )
        position = _long_position(entry_price=100.0)
        position.current_price = 90.0
        mock_broker.get_position.return_value = position
        mock_broker.get_balance.return_value = 9990.0
        mock_broker.market_sell.return_value = _make_order(
            side="sell", filled=1.0, amount=1.0
        )
        mock_broker.market_sell.return_value.price = 90.0

        result = engine.tick()

        assert result.action == TickAction.EXIT
        stats = risk_mgr.get_daily_stats()
        assert stats.total_pnl_pct == pytest.approx(-10.0)
        assert stats.total_pnl_abs == pytest.approx(-10.0)


class TestStatePersistence:
    def test_save_state(self, engine, mock_broker, mock_state_mgr):
        mock_broker.get_position.return_value = None
        engine._save_state()
        restored = mock_state_mgr.load(engine.strategy.name, engine.symbol)
        assert restored is not None
        assert restored.strategy_name == engine.strategy.name
        assert restored.has_position is False
        assert restored.last_decision_bar_ts == engine._last_decision_bar_ts

    def test_restore_state(
        self, mock_broker, mock_data_feed, mock_state_mgr
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
            data_feed=mock_data_feed,
            state_dir=str(mock_state_mgr.state_dir),
            symbol="BTC/USDT",
        )
        assert engine._trades_count == 5
        assert engine._total_pnl_pct == 2.5

    def test_restore_rehydrates_shared_position_ledger(
        self, mock_broker, mock_data_feed, mock_state_mgr
    ):
        """A saved ledger_state must repopulate the ledger LiveEngine was
        constructed with, so Broker (sharing the same instance) sees it too."""
        from cryptoquant.position.ledger import ManagedPositionLedger

        source = ManagedPositionLedger()
        source.record_buy("BTC/USDT", 0.2, 48000.0, fee=1.0, timestamp=1000)

        engine1 = LiveEngine(
            broker=mock_broker,
            strategy=MockStrategy(),
            data_feed=mock_data_feed,
            state_dir=str(mock_state_mgr.state_dir),
            symbol="BTC/USDT",
            position_ledger=source,
        )
        engine1._save_state()

        fresh_ledger = ManagedPositionLedger()
        LiveEngine(
            broker=mock_broker,
            strategy=MockStrategy(),
            data_feed=mock_data_feed,
            state_dir=str(mock_state_mgr.state_dir),
            symbol="BTC/USDT",
            position_ledger=fresh_ledger,
        )

        pos = fresh_ledger.get_position("BTC/USDT")
        assert pos is not None
        assert pos.amount == 0.2
        assert pos.avg_entry_price == 48000.0

    def test_restore_rehydrates_risk_state(
        self, mock_broker, mock_data_feed, mock_state_mgr
    ):
        from cryptoquant.risk.manager import RiskManager

        source_risk = RiskManager(initial_balance=10000.0)
        source_risk.record_entry("BTC/USDT", "long")
        source_risk.record_exit("BTC/USDT", -3.0, -300.0)
        source_risk._trigger_emergency("test")
        engine1 = LiveEngine(
            broker=mock_broker,
            strategy=MockStrategy(),
            data_feed=mock_data_feed,
            risk_manager=source_risk,
            state_dir=str(mock_state_mgr.state_dir),
            symbol="BTC/USDT",
        )
        engine1._save_state()

        restored_risk = RiskManager(initial_balance=1.0)
        LiveEngine(
            broker=mock_broker,
            strategy=MockStrategy(),
            data_feed=mock_data_feed,
            risk_manager=restored_risk,
            state_dir=str(mock_state_mgr.state_dir),
            symbol="BTC/USDT",
        )

        stats = restored_risk.get_daily_stats()
        assert stats.total_trades == 1
        assert stats.total_pnl_abs == pytest.approx(-300.0)
        assert restored_risk.is_emergency_stop()
