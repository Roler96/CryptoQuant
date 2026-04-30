"""Tests for backtest engine module."""

import unittest


from backtest.engine import BacktestConfig, BacktestEngine, BacktestResult


class TestBacktestConfig(unittest.TestCase):
    """Tests for BacktestConfig dataclass."""

    def test_default_values(self):
        """Test default configuration values."""
        config = BacktestConfig()
        self.assertEqual(config.initial_cash, 10000.0)
        self.assertEqual(config.commission, 0.001)
        self.assertEqual(config.slippage, 0.0005)
        self.assertTrue(config.plot_results)
        self.assertEqual(config.log_path, "logs")

    def test_custom_values(self):
        """Test custom configuration values."""
        config = BacktestConfig(
            initial_cash=50000.0,
            commission=0.002,
            slippage=0.001,
            plot_results=False,
            log_path="custom_logs",
        )
        self.assertEqual(config.initial_cash, 50000.0)
        self.assertEqual(config.commission, 0.002)
        self.assertEqual(config.slippage, 0.001)
        self.assertFalse(config.plot_results)
        self.assertEqual(config.log_path, "custom_logs")


class TestBacktestResult(unittest.TestCase):
    """Tests for BacktestResult dataclass."""

    def test_basic_result(self):
        """Test basic result creation."""
        result = BacktestResult(
            strategy_name="test_strategy",
            pair="BTC/USDT",
            timeframe="1h",
            initial_value=10000.0,
            final_value=11000.0,
            total_return=0.1,
        )
        self.assertEqual(result.strategy_name, "test_strategy")
        self.assertEqual(result.pair, "BTC/USDT")
        self.assertEqual(result.initial_value, 10000.0)
        self.assertEqual(result.final_value, 11000.0)
        self.assertEqual(result.total_return, 0.1)

    def test_to_dict(self):
        """Test conversion to dictionary."""
        result = BacktestResult(
            strategy_name="test_strategy",
            pair="BTC/USDT",
            timeframe="1h",
            initial_value=10000.0,
            final_value=11000.0,
            total_return=0.1,
            trades=[{"pnl": 100}, {"pnl": 200}],
            sharpe_ratio=1.5,
        )
        d = result.to_dict()
        self.assertEqual(d["strategy_name"], "test_strategy")
        self.assertEqual(d["total_trades"], 2)
        self.assertEqual(d["sharpe_ratio"], 1.5)


class TestBacktestEngine(unittest.TestCase):
    """Tests for BacktestEngine."""

    def test_initialization(self):
        """Test engine initialization."""
        config = BacktestConfig()
        engine = BacktestEngine(config)
        self.assertEqual(engine.config, config)

    def test_default_initialization(self):
        """Test engine with default config."""
        engine = BacktestEngine()
        self.assertEqual(engine.config.initial_cash, 10000.0)

    def test_available_strategies(self):
        """Test listing available strategies."""
        engine = BacktestEngine()
        strategies = engine.get_available_strategies()
        self.assertIn("cta", strategies)
        self.assertIn("trend_following", strategies)
        self.assertIn("trend", strategies)

    def test_load_strategy_valid(self):
        """Test loading valid strategy."""
        engine = BacktestEngine()
        strategy = engine.load_strategy("cta")
        self.assertEqual(strategy.name, "cta")

    def test_load_strategy_invalid(self):
        """Test loading invalid strategy."""
        engine = BacktestEngine()
        with self.assertRaises(ValueError) as ctx:
            engine.load_strategy("unknown_strategy")
        self.assertIn("Unknown strategy", str(ctx.exception))

    def test_load_strategy_case_insensitive(self):
        """Test case-insensitive strategy loading."""
        engine = BacktestEngine()
        strategy = engine.load_strategy("CTA")
        self.assertEqual(strategy.name, "CTA")


if __name__ == "__main__":
    unittest.main()
