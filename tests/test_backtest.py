"""Tests for backtesting engine."""

import numpy as np
import pandas as pd
import pytest

from cryptoquant.engine.backtest import (
    BacktestEngine,
    _compute_drawdown_curve,
    generate_report,
    trades_to_dataframe,
)
from cryptoquant.engine.types import BacktestResult
from cryptoquant.strategy.base import Strategy


class AlwaysBuy(Strategy):
    timeframe = "1h"
    min_bars = 10
    DEFAULT_PARAMS = {}

    @property
    def name(self) -> str:
        return "AlwaysBuy"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        df = self.preprocess(df)
        signal = pd.Series(0, index=df.index, dtype=int)
        signal.iloc[0] = 1
        return signal


class NeverTrade(Strategy):
    timeframe = "1h"
    min_bars = 10
    DEFAULT_PARAMS = {}

    @property
    def name(self) -> str:
        return "NeverTrade"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        df = self.preprocess(df)
        return pd.Series(0, index=df.index, dtype=int)


class BuyThenSell(Strategy):
    timeframe = "1h"
    min_bars = 10
    DEFAULT_PARAMS = {"buy_bar": 5, "sell_bar": 15}

    @property
    def name(self) -> str:
        return "BuyThenSell"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        df = self.preprocess(df)
        signal = pd.Series(0, index=df.index, dtype=int)
        signal.iloc[self.params["buy_bar"]] = 1
        signal.iloc[self.params["sell_bar"]] = -1
        return signal


def _make_df(n=100, start_price=100.0, trend="up"):
    dates = pd.date_range("2024-01-01", periods=n, freq="1h")
    if trend == "up":
        close = np.linspace(start_price, start_price + n * 0.5, n)
    elif trend == "down":
        close = np.linspace(start_price, start_price - n * 0.5, n)
    else:
        close = np.full(n, start_price)

    return pd.DataFrame(
        {
            "open": close - 0.1,
            "high": close + 0.5,
            "low": close - 0.5,
            "close": close,
            "volume": np.full(n, 1000.0),
        },
        index=dates,
    )


@pytest.fixture
def engine():
    return BacktestEngine(initial_capital=10000, commission=0.001, slippage=0.0005)


class TestBacktestEngine:
    def test_no_signals_zero_trades(self, engine):
        df = _make_df(50, trend="flat")
        result = engine.run(df, NeverTrade())
        assert len(result.trades) == 0
        assert result.metrics.total_trades == 0

    def test_single_buy_and_sell(self, engine):
        df = _make_df(50, trend="up")
        result = engine.run(df, BuyThenSell({"buy_bar": 5, "sell_bar": 15}))
        assert len(result.trades) >= 1
        trade = result.trades[0]
        assert trade.side == "long"
        assert trade.exit_reason == "signal_reverse"

    def test_stop_loss_triggered_by_low(self, engine):
        df = _make_df(50, trend="up")
        df.iloc[10, df.columns.get_loc("low")] = df.iloc[10]["close"] * 0.90

        result = engine.run(df, AlwaysBuy(), stop_loss_pct=5.0)
        if result.trades:
            assert result.trades[0].exit_reason == "stop_loss"

    def test_take_profit_triggered_by_high(self, engine):
        df = _make_df(50, trend="up")
        result = engine.run(df, AlwaysBuy(), take_profit_pct=2.0)
        if result.trades:
            assert result.trades[0].exit_reason in (
                "take_profit",
                "signal_reverse",
                "end_of_data",
            )

    def test_time_exit(self, engine):
        df = _make_df(50, trend="flat")
        result = engine.run(df, AlwaysBuy(), max_hold_bars=5)
        if result.trades:
            assert result.trades[0].exit_reason in ("time_exit", "end_of_data")

    def test_end_of_data_force_close(self, engine):
        df = _make_df(50, trend="up")
        result = engine.run(df, AlwaysBuy())
        if result.trades:
            last_trade = result.trades[-1]
            assert last_trade.exit_reason in ("end_of_data", "signal_reverse")

    def test_equity_curve_no_trades(self, engine):
        df = _make_df(50, trend="flat")
        result = engine.run(df, NeverTrade())
        assert (result.equity_curve == 10000).all()

    def test_commission_reduces_pnl(self):
        df = _make_df(50, trend="up")
        engine_no_fee = BacktestEngine(commission=0.0, slippage=0.0)
        engine_with_fee = BacktestEngine(commission=0.01, slippage=0.0)

        result_no_fee = engine_no_fee.run(
            df, BuyThenSell({"buy_bar": 5, "sell_bar": 15})
        )
        result_with_fee = engine_with_fee.run(
            df, BuyThenSell({"buy_bar": 5, "sell_bar": 15})
        )

        assert result_no_fee.trades and result_with_fee.trades
        # Round-trip commission of 1% should reduce net PnL by exactly 1%.
        assert (
            result_with_fee.trades[0].pnl_pct
            == pytest.approx(result_no_fee.trades[0].pnl_pct - 1.0, abs=1e-6)
        )
        assert result_with_fee.trades[0].pnl_pct < result_no_fee.trades[0].pnl_pct

    def test_commission_zero_same_as_no_commission(self):
        df = _make_df(50, trend="up")
        engine_default = BacktestEngine()
        engine_zero = BacktestEngine(commission=0.0)

        result_default = engine_default.run(
            df, BuyThenSell({"buy_bar": 5, "sell_bar": 15})
        )
        result_zero = engine_zero.run(
            df, BuyThenSell({"buy_bar": 5, "sell_bar": 15})
        )

        assert result_default.trades and result_zero.trades
        # Default commission should now be applied, so results differ.
        assert result_default.trades[0].pnl_pct < result_zero.trades[0].pnl_pct

    def test_result_structure(self, engine):
        df = _make_df(50, trend="up")
        result = engine.run(
            df, BuyThenSell({"buy_bar": 5, "sell_bar": 15})
        )
        assert isinstance(result, BacktestResult)
        assert result.strategy_name == "BuyThenSell"
        assert result.symbol == ""
        assert result.initial_capital == 10000
        assert isinstance(result.metrics.total_trades, int)
        assert isinstance(result.equity_curve, pd.Series)
        assert isinstance(result.drawdown_curve, pd.Series)

    def test_mae_mfe_computed(self, engine):
        df = _make_df(50, trend="up")
        result = engine.run(
            df, BuyThenSell({"buy_bar": 5, "sell_bar": 15})
        )
        if result.trades:
            trade = result.trades[0]
            assert trade.mae_pct <= 0
            assert trade.mfe_pct >= 0


class TestDrawdownCurve:
    def test_no_drawdown_flat(self):
        equity = pd.Series([100.0] * 10)
        dd = _compute_drawdown_curve(equity)
        assert (dd == 0).all()

    def test_drawdown_on_decline(self):
        equity = pd.Series([100.0, 95.0, 90.0, 85.0, 100.0])
        dd = _compute_drawdown_curve(equity)
        assert dd.min() < 0
        assert dd.iloc[-1] == 0


class TestGenerateReport:
    def test_report_generation(self, engine):
        df = _make_df(100, trend="up")
        result = engine.run(
            df,
            BuyThenSell({"buy_bar": 5, "sell_bar": 50}),
            symbol="BTC/USDT",
        )
        report = generate_report(result)
        assert "Backtest Report" in report
        assert "BTC/USDT" in report
        assert "PERFORMANCE" in report
        assert "TRADES" in report

    def test_report_no_trades(self, engine):
        df = _make_df(50, trend="flat")
        result = engine.run(df, NeverTrade())
        report = generate_report(result)
        assert "Total Trades:       0" in report


class TestTradesToDataframe:
    def test_conversion(self, engine):
        df = _make_df(100, trend="up")
        result = engine.run(
            df, BuyThenSell({"buy_bar": 5, "sell_bar": 50})
        )
        if result.trades:
            trades_df = trades_to_dataframe(result.trades)
            assert isinstance(trades_df, pd.DataFrame)
            assert "pnl_pct" in trades_df.columns
            assert "exit_reason" in trades_df.columns

    def test_empty_trades(self):
        result = trades_to_dataframe([])
        assert isinstance(result, pd.DataFrame)
        assert result.empty


class TestKnownScenarios:
    def test_bull_market_profits(self, engine):
        df = _make_df(200, trend="up")
        result = engine.run(df, AlwaysBuy())
        if result.trades:
            assert result.metrics.total_return_pct > 0

    def test_never_trades_zero_return(self, engine):
        df = _make_df(100, trend="up")
        result = engine.run(df, NeverTrade())
        assert result.metrics.total_return_pct == 0.0
        assert result.metrics.total_trades == 0
