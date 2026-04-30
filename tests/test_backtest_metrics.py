"""Tests for backtest metrics module."""

import unittest
from decimal import Decimal

from backtest.metrics import (
    SHARPE_THRESHOLD,
    MAX_DRAWDOWN_THRESHOLD,
    WIN_RATE_THRESHOLD,
    calculate_sharpe_ratio,
    calculate_max_drawdown,
    calculate_win_rate,
    calculate_profit_factor,
    calculate_annualized_return,
    calculate_volatility,
    calculate_average_trade,
    calculate_calmar_ratio,
    generate_performance_report,
    get_threshold_status,
)


class TestSharpeRatio(unittest.TestCase):
    """Tests for Sharpe ratio calculation."""

    def test_basic_sharpe_calculation(self):
        """Test basic Sharpe ratio calculation."""
        # Equity curve with steady growth
        equity = [Decimal("10000")]
        for i in range(1, 100):
            # 0.1% daily return with some noise
            equity.append(Decimal("10000") * Decimal(str(1 + 0.001 * i)))

        sharpe = calculate_sharpe_ratio(equity)
        self.assertIsNotNone(sharpe)
        self.assertGreater(sharpe, Decimal("0"))

    def test_insufficient_data(self):
        """Test Sharpe ratio with insufficient data."""
        equity = [Decimal("10000"), Decimal("10001")]
        sharpe = calculate_sharpe_ratio(equity)
        self.assertIsNone(sharpe)

    def test_flat_equity(self):
        """Test Sharpe ratio with no returns."""
        equity = [Decimal("10000")] * 100
        sharpe = calculate_sharpe_ratio(equity)
        self.assertIsNone(sharpe)


class TestMaxDrawdown(unittest.TestCase):
    """Tests for maximum drawdown calculation."""

    def test_peak_to_trough_drawdown(self):
        """Test max drawdown calculation."""
        # Equity: rises to 12000, then drops to 8000 (33.3% drawdown)
        equity = [Decimal(str(v)) for v in [10000, 11000, 12000, 11500, 10000, 9000, 8000]]
        max_dd = calculate_max_drawdown(equity)
        self.assertAlmostEqual(float(max_dd), 0.3333, places=2)

    def test_no_drawdown(self):
        """Test with no drawdown."""
        equity = [Decimal(str(v)) for v in [10000, 10100, 10200, 10300]]
        max_dd = calculate_max_drawdown(equity)
        self.assertEqual(float(max_dd), 0.0)

    def test_insufficient_data(self):
        """Test with insufficient data."""
        equity = [Decimal("10000")]
        max_dd = calculate_max_drawdown(equity)
        self.assertEqual(max_dd, Decimal("0"))


class TestWinRate(unittest.TestCase):
    """Tests for win rate calculation."""

    def test_win_rate_calculation(self):
        """Test win rate calculation."""
        trades = [
            {"pnl": 100},
            {"pnl": -50},
            {"pnl": 200},
            {"pnl": -100},
            {"pnl": 150},
        ]
        win_rate = calculate_win_rate(trades)
        # 3 wins out of 5 = 60%
        self.assertAlmostEqual(float(win_rate), 0.6)

    def test_all_winners(self):
        """Test with all winning trades."""
        trades = [{"pnl": 100}, {"pnl": 200}, {"pnl": 300}]
        win_rate = calculate_win_rate(trades)
        self.assertEqual(float(win_rate), 1.0)

    def test_no_trades(self):
        """Test with no trades."""
        trades = []
        win_rate = calculate_win_rate(trades)
        self.assertEqual(win_rate, Decimal("0"))


class TestProfitFactor(unittest.TestCase):
    """Tests for profit factor calculation."""

    def test_profit_factor_calculation(self):
        """Test profit factor calculation."""
        trades = [
            {"pnl": 100},
            {"pnl": -50},
            {"pnl": 200},
            {"pnl": -100},
            {"pnl": 150},
        ]
        pf = calculate_profit_factor(trades)
        # Gross profit: 450, Gross loss: 150, PF: 3.0
        self.assertAlmostEqual(float(pf), 3.0)

    def test_no_losers(self):
        """Test with only winning trades."""
        trades = [{"pnl": 100}, {"pnl": 200}]
        pf = calculate_profit_factor(trades)
        # Should be None (infinite profit factor)
        self.assertIsNone(pf)

    def test_no_trades(self):
        """Test with no trades."""
        trades = []
        pf = calculate_profit_factor(trades)
        self.assertIsNone(pf)


class TestAnnualizedReturn(unittest.TestCase):
    """Tests for annualized return calculation."""

    def test_annualized_return(self):
        """Test annualized return calculation."""
        # 20% return over 365 days (daily data points)
        equity = [Decimal("10000")]
        for i in range(1, 366):
            equity.append(Decimal("10000") * Decimal(str(1 + 0.2 * i / 365)))

        annual_ret = calculate_annualized_return(equity)
        self.assertIsNotNone(annual_ret)
        self.assertGreater(annual_ret, Decimal("0"))

    def test_insufficient_data(self):
        """Test with insufficient data."""
        equity = [Decimal("10000")]
        annual_ret = calculate_annualized_return(equity)
        self.assertIsNone(annual_ret)


class TestVolatility(unittest.TestCase):
    """Tests for volatility calculation."""

    def test_volatility_calculation(self):
        """Test volatility calculation."""
        import random
        random.seed(42)

        equity = [Decimal("10000")]
        for _ in range(1, 100):
            ret = Decimal(str(random.uniform(-0.02, 0.02)))
            equity.append(equity[-1] * (Decimal("1") + ret))

        vol = calculate_volatility(equity)
        self.assertIsNotNone(vol)
        self.assertGreater(vol, Decimal("0"))


class TestAverageTrade(unittest.TestCase):
    """Tests for average trade calculation."""

    def test_average_trade(self):
        """Test average trade calculation."""
        trades = [
            {"pnl": 100},
            {"pnl": -50},
            {"pnl": 200},
        ]
        avg = calculate_average_trade(trades)
        # (100 - 50 + 200) / 3 = 83.33
        self.assertAlmostEqual(float(avg), 83.33, places=1)


class TestCalmarRatio(unittest.TestCase):
    """Tests for Calmar ratio calculation."""

    def test_calmar_calculation(self):
        """Test Calmar ratio calculation."""
        equity = [Decimal(str(v)) for v in [10000, 11000, 12000, 11500, 13000, 12500, 14000]]
        calmar = calculate_calmar_ratio(equity)
        self.assertIsNotNone(calmar)


class TestPerformanceReport(unittest.TestCase):
    """Tests for performance report generation."""

    def test_complete_report(self):
        """Test complete performance report."""
        trades = [
            {"pnl": 100},
            {"pnl": -50},
            {"pnl": 200},
        ]
        equity = [Decimal("10000"), Decimal("10100"), Decimal("10050"), Decimal("10250")]
        initial = Decimal("10000")

        report = generate_performance_report(trades, equity, initial)

        self.assertIn("summary", report)
        self.assertIn("returns", report)
        self.assertIn("risk_metrics", report)
        self.assertIn("trade_metrics", report)
        self.assertIn("thresholds", report)

        self.assertEqual(report["summary"]["total_trades"], 3)
        self.assertEqual(report["summary"]["winning_trades"], 2)
        self.assertEqual(report["summary"]["losing_trades"], 1)

    def test_thresholds_in_report(self):
        """Test that thresholds are included in report."""
        trades = [{"pnl": 100}, {"pnl": 200}, {"pnl": 300}]
        equity = [Decimal("10000"), Decimal("10200"), Decimal("10400"), Decimal("10600")]
        initial = Decimal("10000")

        report = generate_performance_report(trades, equity, initial)

        self.assertIn("thresholds", report)
        self.assertIn("sharpe_ratio", report["thresholds"])
        self.assertIn("max_drawdown", report["thresholds"])
        self.assertIn("win_rate", report["thresholds"])
        self.assertIn("overall_pass", report["thresholds"])


class TestThresholdStatus(unittest.TestCase):
    """Tests for threshold status function."""

    def test_sharpe_threshold(self):
        """Test Sharpe ratio threshold check."""
        status = get_threshold_status("sharpe", Decimal("1.5"))
        self.assertTrue(status["pass"])
        self.assertEqual(status["threshold"], float(SHARPE_THRESHOLD))

    def test_sharpe_threshold_fail(self):
        """Test Sharpe ratio threshold failure."""
        status = get_threshold_status("sharpe", Decimal("0.5"))
        self.assertFalse(status["pass"])

    def test_max_drawdown_threshold(self):
        """Test max drawdown threshold."""
        status = get_threshold_status("max_drawdown", Decimal("0.15"))
        self.assertTrue(status["pass"])
        self.assertEqual(status["threshold"], float(MAX_DRAWDOWN_THRESHOLD))

    def test_max_drawdown_threshold_fail(self):
        """Test max drawdown threshold failure."""
        status = get_threshold_status("max_drawdown", Decimal("0.25"))
        self.assertFalse(status["pass"])

    def test_win_rate_threshold(self):
        """Test win rate threshold."""
        status = get_threshold_status("win_rate", Decimal("0.5"))
        self.assertTrue(status["pass"])
        self.assertEqual(status["threshold"], float(WIN_RATE_THRESHOLD))


if __name__ == "__main__":
    unittest.main()
