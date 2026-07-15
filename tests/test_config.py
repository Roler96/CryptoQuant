"""Tests for cryptoquant.config module."""
import inspect
from pathlib import Path

import pytest
import yaml

from cryptoquant.engine.backtest import BacktestEngine
from cryptoquant.config import (
    AppConfig,
    load_config,
    invalidate_config_cache,
    get_data_config,
    DataConfig,
    FetchConfig,
    TradingConfig,
    PaperTradingConfig,
)


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear config cache before each test."""
    invalidate_config_cache()
    yield
    invalidate_config_cache()


class TestLoadConfig:
    def test_returns_app_config(self):
        config = load_config()
        assert isinstance(config, AppConfig)

    def test_default_exchange_is_okx(self):
        config = load_config()
        assert config.exchange.default == "okx"

    def test_data_config_defaults(self):
        config = load_config()
        assert config.data.db_path == "data/cryptoquant.db"
        assert config.data.fetch.max_candles_per_request == 300
        assert config.data.fetch.chunk_days == 7

    def test_trading_config_defaults(self):
        config = load_config()
        assert config.trading.default_quote == "USDT"
        assert config.trading.min_order_usdt == 10.0

    def test_logging_config_defaults(self):
        config = load_config()
        assert config.logging.level == "INFO"
        assert config.logging.dir == "logs/"

    def test_caching_works(self):
        config1 = load_config()
        config2 = load_config()
        assert config1 is config2

    def test_no_cache_returns_new_instance(self):
        config1 = load_config(use_cache=False)
        config2 = load_config(use_cache=False)
        assert config1 is not config2

    def test_invalidate_cache(self):
        config1 = load_config()
        invalidate_config_cache()
        config2 = load_config()
        assert config1 is not config2

    def test_nonexistent_config_path_uses_defaults(self, tmp_path):
        config = load_config(str(tmp_path / "nonexistent.yaml"))
        assert isinstance(config, AppConfig)
        assert config.exchange.default == "okx"


class TestGetDataConfig:
    def test_returns_data_config(self):
        data_config = get_data_config()
        assert isinstance(data_config, DataConfig)

    def test_with_explicit_config(self):
        config = load_config()
        data_config = get_data_config(config)
        assert data_config is config.data


class TestFieldConstraints:
    def test_fetch_max_candles_range(self):
        with pytest.raises(Exception):
            FetchConfig(max_candles_per_request=0)
        with pytest.raises(Exception):
            FetchConfig(max_candles_per_request=1001)

    def test_min_order_must_be_positive(self):
        with pytest.raises(Exception):
            TradingConfig(min_order_usdt=0)
        with pytest.raises(Exception):
            TradingConfig(min_order_usdt=-1)


class TestPaperTradingConfig:
    def test_default_values(self):
        config = PaperTradingConfig()
        assert config.enabled is False
        assert config.initial_balance == 10000.0
        assert config.slippage_bps == 1.0
        assert config.commission_bps == 10.0
        assert config.latency_ms == 300

    def test_custom_values(self):
        config = PaperTradingConfig(
            enabled=True, initial_balance=5000.0, slippage_bps=10.0, latency_ms=1000
        )
        assert config.enabled is True
        assert config.initial_balance == 5000.0
        assert config.slippage_bps == 10.0
        assert config.latency_ms == 1000

    def test_app_config_includes_paper_trading(self):
        config = load_config()
        assert isinstance(config.paper_trading, PaperTradingConfig)
        assert config.paper_trading.enabled is True
        assert config.paper_trading.initial_balance == 10000.0

    def test_yaml_override(self, tmp_path):
        yaml_content = """
paper_trading:
  enabled: true
  initial_balance: 25000.0
  slippage_bps: 2.0
  latency_ms: 200
"""
        config_path = tmp_path / "test_config.yaml"
        config_path.write_text(yaml_content)
        config = load_config(str(config_path), use_cache=False)
        assert config.paper_trading.enabled is True
        assert config.paper_trading.initial_balance == 25000.0
        assert config.paper_trading.slippage_bps == 2.0
        assert config.paper_trading.latency_ms == 200


class TestShippedConfigsMatchBacktest:
    """Live must not run exit rules the backtest cannot model.

    BacktestEngine.run() takes stop_loss_pct / take_profit_pct /
    max_hold_bars — there is no trailing stop. LiveEngine has one, wired
    from trading.trailing_stop_pct. A config that sets it puts live on a
    strategy no backtest ever validated, which is the same class of bug as
    the signal_exit divergence fixed on 2026-07-14.
    """

    @staticmethod
    def _configs() -> list[Path]:
        return sorted(Path(__file__).resolve().parent.parent.glob("config*.yaml"))

    def test_configs_exist(self):
        assert self._configs(), "glob found no configs — this guard would be vacuous"

    @pytest.mark.parametrize("field", ["trailing_stop_pct"])
    def test_backtest_cannot_model_field_is_disabled(self, field):
        offenders = []
        for path in self._configs():
            raw = yaml.safe_load(path.read_text()) or {}
            value = (raw.get("trading") or {}).get(field)
            if value is not None:
                offenders.append(f"{path.name}: {field}={value}")

        assert not offenders, (
            f"{field} is set in {', '.join(offenders)}, but BacktestEngine "
            f"cannot model it — live would run an unvalidated exit rule. "
            f"Implement it in the backtest and re-run the research protocol "
            f"before enabling."
        )

    def test_backtest_run_still_lacks_trailing_stop(self):
        """If the backtest grows a trailing stop, the guard above is stale."""
        params = inspect.signature(BacktestEngine.run).parameters
        assert "trailing_stop_pct" not in params, (
            "BacktestEngine.run now models a trailing stop — drop this guard "
            "and let configs enable trailing_stop_pct again."
        )
