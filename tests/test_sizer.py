"""Tests for position sizers."""
import numpy as np
import pandas as pd

from cryptoquant.risk.sizer import (
    ATRSizer,
    FixedSizer,
    KellySizer,
    SizerMethod,
    create_sizer,
)


class TestFixedSizer:
    def test_50pct(self):
        sizer = FixedSizer(risk_pct=50.0)
        assert sizer.calculate(10000, 50000) == 5000.0

    def test_100pct(self):
        sizer = FixedSizer(risk_pct=100.0)
        assert sizer.calculate(10000, 50000) == 10000.0

    def test_min_order(self):
        sizer = FixedSizer(risk_pct=0.01, min_order=10.0)
        assert sizer.calculate(100, 50000) == 10.0


class TestKellySizer:
    def test_positive_kelly(self):
        sizer = KellySizer(win_rate=0.6, avg_win_pct=3.0, avg_loss_pct=1.0, fraction=0.5)
        amount = sizer.calculate(10000, 50000)
        assert amount > 10.0  # Above min_order

    def test_zero_when_losing(self):
        sizer = KellySizer(win_rate=0.0, avg_win_pct=1.0, avg_loss_pct=1.0)
        amount = sizer.calculate(10000, 50000)
        assert amount == 10.0  # min_order (kelly=0)

    def test_update_from_trades(self):
        sizer = KellySizer(lookback_trades=10)
        trades = [{"pnl_pct": 2.0}] * 6 + [{"pnl_pct": -1.0}] * 4
        sizer.update_from_trades(trades)
        assert sizer.win_rate == 0.6

    def test_update_insufficient_trades(self):
        sizer = KellySizer(lookback_trades=50, win_rate=0.5)
        trades = [{"pnl_pct": 1.0}] * 5
        sizer.update_from_trades(trades)
        assert sizer.win_rate == 0.5  # Unchanged

    def test_feed_trades_when_adaptive(self):
        sizer = KellySizer(lookback_trades=10, adaptive=True, win_rate=0.5)
        trades = [{"pnl_pct": 2.0}] * 6 + [{"pnl_pct": -1.0}] * 4
        sizer.feed_trades(trades)
        assert sizer.win_rate == 0.6

    def test_feed_trades_when_not_adaptive(self):
        sizer = KellySizer(lookback_trades=10, adaptive=False, win_rate=0.5)
        trades = [{"pnl_pct": 2.0}] * 6 + [{"pnl_pct": -1.0}] * 4
        sizer.feed_trades(trades)
        assert sizer.win_rate == 0.5  # Unchanged


class TestATRSizer:
    def test_high_vol_reduces_size(self):
        sizer = ATRSizer(base_risk_pct=10.0)
        # High ATR scenario
        n = 50
        dates = pd.date_range("2024-01-01", periods=n, freq="1h")
        close = np.linspace(100, 120, n)
        df = pd.DataFrame(
            {
                "open": close - 2,
                "high": close + 5,
                "low": close - 5,
                "close": close,
                "volume": np.full(n, 1000.0),
            },
            index=dates,
        )
        amount = sizer.calculate(10000, 110, df=df)
        assert amount < 10000  # Should be less than full balance

    def test_no_data_fallback(self):
        sizer = ATRSizer(base_risk_pct=10.0)
        amount = sizer.calculate(10000, 50000, df=None)
        assert amount == 1000.0  # 10% of 10000


class TestCreateSizer:
    def test_fixed(self):
        sizer = create_sizer(SizerMethod.FIXED, risk_pct=50.0)
        assert isinstance(sizer, FixedSizer)

    def test_kelly(self):
        sizer = create_sizer(SizerMethod.KELLY)
        assert isinstance(sizer, KellySizer)

    def test_atr(self):
        sizer = create_sizer(SizerMethod.ATR)
        assert isinstance(sizer, ATRSizer)


class TestATRSizerConfig:
    def test_default_config_from_trading_config(self):
        from cryptoquant.config import TradingConfig

        config = TradingConfig()
        assert config.sizer_method == "atr"
        assert "base_risk_pct" in config.sizer_config
        assert "atr_period" in config.sizer_config
        sizer = create_sizer(
            SizerMethod.ATR,
            base_risk_pct=config.sizer_config["base_risk_pct"],
            atr_period=config.sizer_config["atr_period"],
            multiplier=config.sizer_config["multiplier"],
            min_order=config.sizer_config["min_order"],
            max_pct=config.sizer_config["max_pct"],
        )
        assert isinstance(sizer, ATRSizer)
        assert sizer.base_risk_pct == config.sizer_config["base_risk_pct"]
