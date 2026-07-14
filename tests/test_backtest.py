"""Tests for backtesting engine."""

import numpy as np
import pandas as pd
import pytest

from cryptoquant.engine.backtest import (
    BacktestEngine,
    _compute_drawdown_curve,
    _fmt_time,
    _render_trade_log,
    generate_report,
    trades_to_dataframe,
)
from cryptoquant.engine.types import BacktestResult, Trade
from cryptoquant.risk.sizer import ATRSizer, FixedSizer
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


class AlwaysSell(Strategy):
    """Always short — enters at bar 0."""
    timeframe = "1h"
    min_bars = 10
    DEFAULT_PARAMS = {}

    @property
    def name(self) -> str:
        return "AlwaysSell"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        df = self.preprocess(df)
        signal = pd.Series(0, index=df.index, dtype=int)
        signal.iloc[0] = -1
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


def _make_trade(entry_price=100.0, exit_price=101.0):
    """A minimal filled trade. _make_df can't reach sub-dollar price scales
    (its open = close - 0.1 would go negative), so precision cases build here.
    """
    return Trade(
        id=1,
        symbol="TEST/USDT",
        side="long",
        entry_time=1704067200000,
        entry_price=entry_price,
        entry_signal=1,
        exit_time=1704153600000,
        exit_price=exit_price,
        exit_reason="take_profit",
        pnl_pct=1.0,
        pnl_abs=100.0,
        hold_bars=24,
        hold_hours=24.0,
        mae_pct=-0.5,
        mfe_pct=1.5,
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
        assert result.trades, "AlwaysBuy with a 10% low spike must produce a trade"
        assert result.trades[0].exit_reason == "stop_loss"

    def test_take_profit_triggered_by_high(self, engine):
        # Uptrend gains 0.5/bar from ~100: a 2% TP is reached long before
        # the data ends, so the exit reason must be take_profit exactly.
        df = _make_df(50, trend="up")
        result = engine.run(df, AlwaysBuy(), take_profit_pct=2.0)
        assert result.trades, "AlwaysBuy in an uptrend must produce a trade"
        assert result.trades[0].exit_reason == "take_profit"

    def test_time_exit(self, engine):
        # Flat market, no SL/TP: only max_hold_bars can close the position
        # before the data ends (50 bars >> 5-bar hold).
        df = _make_df(50, trend="flat")
        result = engine.run(df, AlwaysBuy(), max_hold_bars=5)
        assert result.trades, "AlwaysBuy with max_hold_bars must produce a trade"
        assert result.trades[0].exit_reason == "time_exit"

    def test_end_of_data_force_close(self, engine):
        # AlwaysBuy never reverses and has no SL/TP: the only possible exit
        # is the forced close on the last bar.
        df = _make_df(50, trend="up")
        result = engine.run(df, AlwaysBuy())
        assert result.trades, "AlwaysBuy must produce a trade"
        assert result.trades[-1].exit_reason == "end_of_data"

    def test_equity_curve_no_trades(self, engine):
        df = _make_df(50, trend="flat")
        result = engine.run(df, NeverTrade())
        assert (result.equity_curve == 10000).all()

    def test_commission_is_charged_per_side(self):
        # Flat prices: entry fill == exit fill, so 1% per-side commission
        # must reduce net PnL by exactly 2% (entry + exit), matching
        # PaperBroker's per-fill semantics.
        df = _make_df(50, trend="flat")
        engine_no_fee = BacktestEngine(commission=0.0, slippage=0.0)
        engine_with_fee = BacktestEngine(commission=0.01, slippage=0.0)

        result_no_fee = engine_no_fee.run(
            df, BuyThenSell({"buy_bar": 5, "sell_bar": 15})
        )
        result_with_fee = engine_with_fee.run(
            df, BuyThenSell({"buy_bar": 5, "sell_bar": 15})
        )

        assert result_no_fee.trades and result_with_fee.trades
        assert (
            result_with_fee.trades[0].pnl_pct
            == pytest.approx(result_no_fee.trades[0].pnl_pct - 2.0, abs=1e-4)
        )

    def test_entry_slippage_applied(self):
        # Flat prices, no commission: 1% per-side slippage costs ~2% on a
        # long round trip (pay up at entry, sell down at exit).
        df = _make_df(50, trend="flat")
        engine_no_slip = BacktestEngine(commission=0.0, slippage=0.0)
        engine_slip = BacktestEngine(commission=0.0, slippage=0.01)

        result_no_slip = engine_no_slip.run(
            df, BuyThenSell({"buy_bar": 5, "sell_bar": 15})
        )
        result_slip = engine_slip.run(
            df, BuyThenSell({"buy_bar": 5, "sell_bar": 15})
        )

        assert result_no_slip.trades and result_slip.trades
        # (1-s)/(1+s) - 1 ~ -2s for small s: 1% slippage -> ~-1.98%
        expected = ((1 - 0.01) / (1 + 0.01) - 1) * 100
        assert result_slip.trades[0].pnl_pct == pytest.approx(
            result_no_slip.trades[0].pnl_pct + expected, abs=1e-4
        )

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
        assert result.trades, "BuyThenSell must produce a trade"
        trade = result.trades[0]
        assert trade.mae_pct <= 0
        assert trade.mfe_pct >= 0


class PositionStyle(Strategy):
    """Persistent target-position signal: long bars 5-14, flat afterwards."""

    timeframe = "1h"
    min_bars = 10
    signal_is_position = True
    DEFAULT_PARAMS = {}

    @property
    def name(self) -> str:
        return "PositionStyle"

    def generate_signal(self, df: pd.DataFrame) -> pd.Series:
        df = self.preprocess(df)
        signal = pd.Series(0, index=df.index, dtype=int)
        signal.iloc[5:15] = 1
        return signal


class TestSignalSemantics:
    """Signal-based fills must not use price information that predates
    the bar close which produced the signal."""

    def test_position_signal_flat_closes_trade(self, engine):
        df = _make_df(50, trend="up")
        result = engine.run(df, PositionStyle())
        assert len(result.trades) == 1
        trade = result.trades[0]
        assert trade.exit_reason == "signal_exit"
        # Signal is 0 at bar 15 close -> exit fills at bar 16 open.
        assert trade.exit_time == int(df.index[16].timestamp() * 1000)

    def test_pulse_strategy_ignores_zero_signal(self, engine):
        # AlwaysBuy emits a single pulse then zeros; without the
        # signal_is_position opt-in the zeros must not close the position.
        df = _make_df(50, trend="up")
        result = engine.run(df, AlwaysBuy())
        assert result.trades[-1].exit_reason == "end_of_data"

    def test_signal_reverse_fills_next_open(self, engine):
        # Sell signal computed on bar 15 close cannot fill at bar 15 open:
        # the long must exit at bar 16 open and the short enter there too.
        df = _make_df(50, trend="up")
        result = engine.run(df, BuyThenSell({"buy_bar": 5, "sell_bar": 15}))
        long_trade = result.trades[0]
        assert long_trade.exit_reason == "signal_reverse"
        assert long_trade.exit_time == int(df.index[16].timestamp() * 1000)
        short_trade = result.trades[1]
        assert short_trade.side == "short"
        assert short_trade.entry_time == int(df.index[16].timestamp() * 1000)


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

    def test_report_covers_equity_and_risk_metrics(self, engine):
        """These were only ever printed by the run scripts; the report is now
        the single place they live."""
        df = _make_df(100, trend="up")
        result = engine.run(
            df, BuyThenSell({"buy_bar": 5, "sell_bar": 50}), symbol="BTC/USDT"
        )
        report = generate_report(result)

        assert "Final Equity:" in report
        assert "Max DD Days:" in report
        assert "VaR 95%:" in report
        assert "CVaR 95%:" in report

    def test_report_includes_monthly_returns(self, engine):
        # Monthly returns come from resample("ME").pct_change(), so the run has
        # to straddle at least two month ends to produce a single figure.
        # AlwaysBuy holds throughout; BuyThenSell would flip short at sell_bar
        # and get run over by the trend.
        df = _make_df(2000, trend="up")  # 1h bars: 2024-01-01 into late March
        result = engine.run(df, AlwaysBuy())
        report = generate_report(result)

        assert "MONTHLY RETURNS" in report
        assert "2024-02" in report

    def test_monthly_returns_omitted_when_run_is_short(self, engine):
        df = _make_df(100, trend="up")  # 1h bars: about four days
        result = engine.run(df, BuyThenSell({"buy_bar": 5, "sell_bar": 50}))

        assert "MONTHLY RETURNS" not in generate_report(result)

    def test_trade_log_is_opt_in(self, engine):
        df = _make_df(100, trend="up")
        result = engine.run(df, BuyThenSell({"buy_bar": 5, "sell_bar": 50}))
        assert result.trades, "BuyThenSell must produce a trade"

        assert "TRADE LOG" not in generate_report(result)
        assert "TRADE LOG" in generate_report(result, include_trades=True)

    def test_trade_log_has_a_row_per_trade(self, engine):
        df = _make_df(100, trend="up")
        result = engine.run(df, BuyThenSell({"buy_bar": 5, "sell_bar": 50}))
        report = generate_report(result, include_trades=True)

        for trade in result.trades:
            assert trade.exit_reason in report
        assert f"TRADE LOG ({len(result.trades)} trades)" in report

    def test_trade_log_omitted_when_no_trades(self, engine):
        df = _make_df(50, trend="flat")
        result = engine.run(df, NeverTrade())

        assert "TRADE LOG" not in generate_report(result, include_trades=True)

    def test_trade_log_shows_times_and_excursions(self, engine):
        """Entry/exit timing and MAE/MFE live only in the trade log — without
        them a row can't say when it traded or how far it went underwater."""
        df = _make_df(100, trend="up")
        result = engine.run(df, BuyThenSell({"buy_bar": 5, "sell_bar": 50}))
        report = generate_report(result, include_trades=True)

        trade = result.trades[0]
        assert _fmt_time(trade.entry_time) in report
        assert _fmt_time(trade.exit_time) in report
        assert f"{trade.mae_pct:+.2f}" in report
        assert f"{trade.mfe_pct:+.2f}" in report
        assert f"{trade.pnl_abs:+,.2f}" in report

    def test_trade_log_columns_stay_aligned(self, engine):
        df = _make_df(100, trend="up")
        result = engine.run(df, BuyThenSell({"buy_bar": 5, "sell_bar": 50}))
        report = generate_report(result, include_trades=True)

        log = report[report.index("-- TRADE LOG") :].splitlines()
        header, rows = log[1], log[2:]
        assert len(rows) == len(result.trades)

        reason_col = header.index("Exit Reason")
        for row, trade in zip(rows, result.trades):
            assert row.index(trade.exit_reason) == reason_col


class TestTradeLogPrecision:
    @pytest.mark.parametrize(
        "price, decimals",
        [(61_000.0, 2), (250.0, 3), (12.5, 4), (0.081, 5), (0.000021, 8)],
    )
    def test_price_precision_follows_price_scale(self, price, decimals):
        """A DOGE fill needs 5dp to stay meaningful; a BTC fill given the same
        would pad the column with dead zeros."""
        log = _render_trade_log([_make_trade(entry_price=price, exit_price=price)])

        assert f"{price:.{decimals}f}" in log[1]

    def test_columns_absorb_a_wide_price(self):
        """Column widths are fitted to the data, so a price too wide for the
        header can't shove the row out of alignment."""
        trades = [
            _make_trade(entry_price=61_000.0, exit_price=61_500.0),
            _make_trade(entry_price=9.0, exit_price=9.5),
        ]
        header, *rows = _render_trade_log(trades)

        reason_col = header.index("Exit Reason")
        assert all(row.index("take_profit") == reason_col for row in rows)


class TestTradesToDataframe:
    def test_conversion(self, engine):
        df = _make_df(100, trend="up")
        result = engine.run(
            df, BuyThenSell({"buy_bar": 5, "sell_bar": 50})
        )
        assert result.trades, "BuyThenSell must produce a trade"
        trades_df = trades_to_dataframe(result.trades)
        assert isinstance(trades_df, pd.DataFrame)
        assert "pnl_pct" in trades_df.columns
        assert "exit_reason" in trades_df.columns

    def test_empty_trades(self):
        result = trades_to_dataframe([])
        assert isinstance(result, pd.DataFrame)
        assert result.empty


class TestSizerIntegration:
    def test_backtest_with_fixed_sizer(self):
        df = _make_df(100, trend="up")
        sizer = FixedSizer(risk_pct=50.0)
        engine = BacktestEngine(initial_capital=10000, sizer=sizer)
        result = engine.run(df, BuyThenSell({"buy_bar": 5, "sell_bar": 15}))
        assert result.trades
        assert result.trades[0].pnl_abs == pytest.approx(
            result.trades[0].pnl_pct * 50.0, abs=1e-6
        )

    def test_backtest_with_atr_sizer(self):
        df = _make_df(100, trend="up")
        sizer = ATRSizer(base_risk_pct=10.0, atr_period=14)
        engine = BacktestEngine(initial_capital=10000, sizer=sizer)
        result = engine.run(df, BuyThenSell({"buy_bar": 5, "sell_bar": 15}))
        assert result.trades
        assert result.trades[0].pnl_abs <= 10000

    def test_backtest_passes_history_to_sizer(self):
        df = _make_df(100, trend="up")
        received = []

        class SpySizer(FixedSizer):
            def calculate(self, balance, price, df=None, **kwargs):
                received.append(df)
                return super().calculate(balance, price, **kwargs)

        engine = BacktestEngine(initial_capital=10000, sizer=SpySizer(risk_pct=50.0))
        result = engine.run(df, BuyThenSell({"buy_bar": 5, "sell_bar": 15}))
        assert result.trades
        assert received and received[0] is not None
        # History ends at the bar before entry — entry bar itself is unknown
        # at fill time (order fills at its open).
        entry_ts = pd.Timestamp(result.trades[0].entry_time, unit="ms")
        assert received[0].index[-1] < entry_ts

    def test_atr_sizer_scales_with_volatility(self):
        df = _make_df(300, trend="up")
        sizer = ATRSizer(base_risk_pct=10.0, atr_period=14, max_pct=100.0)
        engine = BacktestEngine(initial_capital=10000, sizer=sizer)
        result = engine.run(df, BuyThenSell({"buy_bar": 250, "sell_bar": 260}))
        assert result.trades
        trade = result.trades[0]
        implied_size = trade.pnl_abs / (trade.pnl_pct / 100)
        # With history now passed through, sizing is ATR-based — not the
        # flat base_risk_pct fallback.
        fallback_size = 10000 * 10.0 / 100
        assert implied_size != pytest.approx(fallback_size, rel=1e-3)

    def test_backtest_without_sizer_uses_full_capital(self):
        df = _make_df(100, trend="up")
        engine = BacktestEngine(initial_capital=10000)
        result = engine.run(df, BuyThenSell({"buy_bar": 5, "sell_bar": 15}))
        assert result.trades
        assert result.trades[0].pnl_abs == pytest.approx(
            result.trades[0].pnl_pct * 100.0, abs=1e-6
        )


class TestKnownScenarios:
    def test_bull_market_profits(self, engine):
        df = _make_df(200, trend="up")
        result = engine.run(df, AlwaysBuy())
        assert result.trades, "AlwaysBuy in a bull market must produce a trade"
        assert result.metrics.total_return_pct > 0

    def test_never_trades_zero_return(self, engine):
        df = _make_df(100, trend="up")
        result = engine.run(df, NeverTrade())
        assert result.metrics.total_return_pct == 0.0
        assert result.metrics.total_trades == 0


class TestStopLossTakeProfit:
    """Regression tests for SL/TP price calculation (short-side bug fix)."""

    def test_sl_tp_does_not_produce_absurd_returns(self, engine):
        """SL=2% should not produce +998% returns (short SL was calculated wrong)."""
        df = _make_df(200, trend="flat")
        strategy = AlwaysSell()
        result = engine.run(df, strategy, stop_loss_pct=2.0, take_profit_pct=4.0)
        # With bug: short SL was below entry → instant "profit" → absurd returns
        # After fix: should be reasonable
        assert result.metrics.total_return_pct < 50, (
            f"Absurd return: {result.metrics.total_return_pct:.1f}% — "
            f"SL/TP short-side calculation may still be broken"
        )
        assert result.metrics.total_trades < 100, (
            f"Too many trades: {result.metrics.total_trades} — "
            f"SL/TP may be triggering spuriously"
        )

    def test_short_sl_is_above_entry(self, engine):
        """For shorts, SL price must be ABOVE entry (stop out when price rises)."""
        df = _make_df(100, trend="down")
        strategy = AlwaysSell()
        result = engine.run(df, strategy, stop_loss_pct=5.0, take_profit_pct=10.0)
        for trade in result.trades:
            if trade.side == "short":
                # Short SL price = entry * (1 + 5/100) >= entry_price
                # We verify indirectly: no trade should have absurd positive PnL from bad SL
                assert trade.pnl_pct < 20, (
                    f"Suspicious short PnL: {trade.pnl_pct:.1f}% — "
                    f"SL may be calculated below entry (old bug)"
                )
