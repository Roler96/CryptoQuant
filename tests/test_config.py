"""Tests for cryptoquant.config module."""
import pytest

from cryptoquant.config import (
    AppConfig,
    load_config,
    invalidate_config_cache,
    get_data_config,
    DataConfig,
    DataCacheConfig,
    FetchConfig,
    TradingConfig,
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
        assert config.data.cache.max_size == 128
        assert config.data.cache.ttl_seconds == 300
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
    def test_cache_max_size_must_be_positive(self):
        with pytest.raises(Exception):
            DataCacheConfig(max_size=0)

    def test_cache_ttl_must_be_non_negative(self):
        with pytest.raises(Exception):
            DataCacheConfig(ttl_seconds=-1)

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
