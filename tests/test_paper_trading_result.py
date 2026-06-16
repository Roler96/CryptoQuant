"""Tests for PaperTradingResult dataclass."""

import pandas as pd
import pytest

from cryptoquant.engine.types import PaperTradingResult, Trade


class TestPaperTradingResult:
    def test_can_instantiate_with_required_fields(self):
        result = PaperTradingResult(
            strategy_name="TestStrategy",
            symbol="BTC/USDT",
            timeframe="1h",
            initial_balance=10000.0,
            final_balance=10500.0,
            total_trades=10,
            win_rate_pct=60.0,
            total_slippage_bps=50.0,
            total_latency_ms=5000,
            sim_start_time=1704067200000,
            sim_end_time=1706659200000,
            trade_log=[],
            balance_curve=pd.Series([10000.0, 10100.0, 10500.0]),
        )
        assert isinstance(result, PaperTradingResult)

    def test_fields_are_correctly_set(self):
        trade = Trade(
            id=1,
            symbol="BTC/USDT",
            side="long",
            entry_time=1704067200000,
            entry_price=100.0,
            entry_signal=1,
            exit_time=1704153600000,
            exit_price=105.0,
            exit_reason="take_profit",
            pnl_pct=5.0,
            pnl_abs=500.0,
            hold_bars=10,
            hold_hours=10.0,
            mae_pct=-1.0,
            mfe_pct=6.0,
        )
        curve = pd.Series([10000.0, 10500.0])
        result = PaperTradingResult(
            strategy_name="Momentum",
            symbol="ETH/USDT",
            timeframe="4h",
            initial_balance=5000.0,
            final_balance=4800.0,
            total_trades=3,
            win_rate_pct=33.33,
            total_slippage_bps=15.0,
            total_latency_ms=1500,
            sim_start_time=1704067200000,
            sim_end_time=1706659200000,
            trade_log=[trade],
            balance_curve=curve,
        )
        assert result.strategy_name == "Momentum"
        assert result.symbol == "ETH/USDT"
        assert result.timeframe == "4h"
        assert result.initial_balance == 5000.0
        assert result.final_balance == 4800.0
        assert result.total_trades == 3
        assert result.win_rate_pct == 33.33
        assert result.total_slippage_bps == 15.0
        assert result.total_latency_ms == 1500
        assert result.sim_start_time == 1704067200000
        assert result.sim_end_time == 1706659200000
        assert len(result.trade_log) == 1
        assert result.trade_log[0].id == 1
        assert result.balance_curve.equals(curve)

    def test_default_trade_log_is_empty_list(self):
        result = PaperTradingResult(
            strategy_name="S",
            symbol="BTC/USDT",
            timeframe="1h",
            initial_balance=10000.0,
            final_balance=10000.0,
            total_trades=0,
            win_rate_pct=0.0,
            total_slippage_bps=0.0,
            total_latency_ms=0,
            sim_start_time=0,
            sim_end_time=0,
            trade_log=[],
            balance_curve=pd.Series([10000.0]),
        )
        assert result.trade_log == []
