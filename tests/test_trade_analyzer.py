"""Tests for TradeAnalyzer."""

import numpy as np
import pandas as pd
import pytest

from cryptoquant.analysis.trade_analyzer import TradeAnalyzer, TradeRecord


def _make_trades(pnls: list[float]) -> list[TradeRecord]:
    """Create trade records from PnL percentages."""
    base_time = 1704067200000
    trades = []
    for i, pnl in enumerate(pnls):
        entry = base_time + i * 3600000
        exit = entry + 1800000
        trades.append(TradeRecord(pnl_pct=pnl, entry_time=entry, exit_time=exit))
    return trades


class TestWinRate:
    def test_empty(self):
        analyzer = TradeAnalyzer([])
        assert analyzer.win_rate() == 0.0

    def test_all_wins(self):
        analyzer = TradeAnalyzer(_make_trades([1.0, 2.0, 3.0]))
        assert analyzer.win_rate() == 100.0

    def test_mixed(self):
        analyzer = TradeAnalyzer(_make_trades([1.0, -2.0, 3.0, -4.0]))
        assert analyzer.win_rate() == 50.0


class TestProfitFactor:
    def test_empty(self):
        analyzer = TradeAnalyzer([])
        assert analyzer.profit_factor() == 0.0

    def test_all_wins(self):
        analyzer = TradeAnalyzer(_make_trades([1.0, 2.0, 3.0]))
        assert analyzer.profit_factor() == float("inf")

    def test_mixed(self):
        analyzer = TradeAnalyzer(_make_trades([2.0, -1.0, 3.0, -1.0]))
        assert analyzer.profit_factor() == pytest.approx(5.0 / 2.0)


class TestSharpe:
    def test_empty(self):
        analyzer = TradeAnalyzer([])
        assert analyzer.sharpe() == 0.0

    def test_single_trade(self):
        analyzer = TradeAnalyzer(_make_trades([1.0]))
        assert analyzer.sharpe() == 0.0

    def test_known_values(self):
        analyzer = TradeAnalyzer(_make_trades([1.0, -1.0, 1.0, -1.0, 1.0]))
        result = analyzer.sharpe()
        assert result > 0


class TestSortino:
    def test_empty(self):
        analyzer = TradeAnalyzer([])
        assert analyzer.sortino() == 0.0

    def test_no_downside(self):
        analyzer = TradeAnalyzer(_make_trades([1.0, 2.0, 3.0]))
        assert analyzer.sortino() == 0.0

    def test_with_downside(self):
        analyzer = TradeAnalyzer(_make_trades([2.0, -1.0, 3.0, -2.0]))
        result = analyzer.sortino()
        assert result > 0


class TestMaxDrawdown:
    def test_empty(self):
        analyzer = TradeAnalyzer([])
        assert analyzer.max_drawdown_pct() == 0.0

    def test_no_drawdown(self):
        analyzer = TradeAnalyzer(_make_trades([1.0, 2.0, 3.0]))
        assert analyzer.max_drawdown_pct() == 0.0

    def test_with_drawdown(self):
        analyzer = TradeAnalyzer(_make_trades([5.0, -3.0, -2.0, 4.0]))
        result = analyzer.max_drawdown_pct()
        assert result > 0


class TestCVar:
    def test_empty(self):
        analyzer = TradeAnalyzer([])
        assert analyzer.cvar() == 0.0

    def test_known_values(self):
        analyzer = TradeAnalyzer(_make_trades([-5.0, -4.0, -3.0, 1.0, 2.0]))
        result = analyzer.cvar(alpha=0.2)
        assert result < 0


class TestStreaks:
    def test_empty(self):
        analyzer = TradeAnalyzer([])
        assert analyzer.streaks() == {"win_streak": 0, "loss_streak": 0}

    def test_win_streak(self):
        analyzer = TradeAnalyzer(_make_trades([1.0, 2.0, 3.0, -1.0, -2.0, 1.0]))
        result = analyzer.streaks()
        assert result["win_streak"] == 3
        assert result["loss_streak"] == 2


class TestTradeDistribution:
    def test_empty(self):
        analyzer = TradeAnalyzer([])
        result = analyzer.trade_distribution()
        assert len(result["counts"]) == 0
        assert len(result["edges"]) == 0

    def test_bins(self):
        analyzer = TradeAnalyzer(_make_trades([1.0, 2.0, 3.0, 4.0, 5.0]))
        result = analyzer.trade_distribution(bins=5)
        assert len(result["counts"]) == 5
        assert len(result["edges"]) == 6


class TestEquityCurve:
    def test_empty(self):
        analyzer = TradeAnalyzer([])
        result = analyzer.equity_curve()
        assert len(result) == 0

    def test_cumulative(self):
        trades = _make_trades([1.0, -2.0, 3.0])
        analyzer = TradeAnalyzer(trades)
        result = analyzer.equity_curve()
        assert len(result) == 3
        assert result.iloc[0] == pytest.approx(1.0)
        assert result.iloc[1] == pytest.approx(-1.0)
        assert result.iloc[2] == pytest.approx(2.0)
        assert list(result.index) == [t.exit_time for t in trades]
