"""Global configuration management with pydantic-settings."""
from pathlib import Path

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class OKXConfig(BaseSettings):
    """OKX-specific configuration."""
    testnet: bool = True
    rate_limit: bool = True


class BinanceConfig(BaseSettings):
    """Binance-specific configuration."""
    testnet: bool = True


class ExchangeConfig(BaseSettings):
    """Exchange configuration."""
    default: str = "okx"
    okx: OKXConfig = OKXConfig()
    binance: BinanceConfig = BinanceConfig()


class FetchConfig(BaseSettings):
    """Data fetch configuration."""
    max_candles_per_request: int = Field(default=300, ge=1, le=1000)
    chunk_days: int = Field(default=7, ge=1)
    timeout_ms: int = Field(default=30_000, ge=1000)


class DataConfig(BaseSettings):
    """Data layer configuration."""
    db_path: str = "data/cryptoquant.db"
    fetch: FetchConfig = FetchConfig()


class RiskConfig(BaseSettings):
    """Risk management configuration."""
    max_positions: int = 3
    max_daily_trades: int = 20
    max_daily_loss_pct: float = 5.0
    max_daily_loss_abs: float = 500.0
    max_per_trade_risk_pct: float = 2.0
    max_drawdown_pct: float = 20.0
    min_balance: float = 50.0
    emergency_cooldown_minutes: int = 60
    drawdown_tier1_pct: float = 10.0
    drawdown_tier2_pct: float = 15.0
    drawdown_tier3_pct: float = 20.0
    tier_cooldown_minutes: int = 30


class TradingConfig(BaseSettings):
    """Trading configuration."""
    default_quote: str = "USDT"
    default_timeframe: str = "5m"
    min_order_usdt: float = Field(default=10.0, gt=0)
    max_order_usdt: float = Field(default=1000.0, gt=0)
    order_timeout: int = Field(default=30, ge=5)
    cooldown_bars: int = Field(default=1, ge=0)
    account_type: str = "spot"
    stop_loss_pct: float | None = None
    trailing_stop_pct: float | None = None
    take_profit_pct: float | None = None
    max_hold_hours: float | None = None
    strategy: str = ""
    sizer_method: str = "atr"
    sizer_config: dict = Field(default_factory=lambda: {
        "base_risk_pct": 10.0,
        "atr_period": 14,
        "multiplier": 1.0,
        "min_order": 10.0,
        "max_pct": 100.0,
    })


class PaperTradingConfig(BaseSettings):
    """Paper trading simulation configuration."""
    enabled: bool = False
    initial_balance: float = 10000.0
    slippage_bps: float = 1.0
    latency_ms: int = 300
    commission_bps: float = 10.0


class AlertConfig(BaseSettings):
    """Alert configuration."""
    webhook_url: str = ""
    alert_levels: tuple[str, ...] = ("CRITICAL",)


class LoggingConfig(BaseSettings):
    """Logging configuration."""
    level: str = "INFO"
    dir: str = "logs/"
    format: str = "{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} | {message}"


class AppConfig(BaseSettings):
    """Root application configuration."""
    model_config = SettingsConfigDict(
        env_prefix="",
        env_nested_delimiter="__",
    )
    exchange: ExchangeConfig = ExchangeConfig()
    data: DataConfig = DataConfig()
    trading: TradingConfig = TradingConfig()
    risk: RiskConfig = RiskConfig()
    paper_trading: PaperTradingConfig = PaperTradingConfig()
    logging: LoggingConfig = LoggingConfig()
    alert: AlertConfig = AlertConfig()

    # Sensitive fields via environment variables
    okx_api_key: str = ""
    okx_api_secret: str = ""
    okx_passphrase: str = ""


_config_cache: AppConfig | None = None


def load_config(config_path: str | Path | None = None, *, use_cache: bool = True) -> AppConfig:
    """Load configuration from YAML + .env overlay.

    Uses pydantic-settings for type safety, auto-conversion, and env override.

    Args:
        config_path: YAML path, defaults to <project_root>/config.yaml
        use_cache: True to cache config (recommended), False to reload each time

    Returns:
        AppConfig instance (type-safe, IDE autocomplete)
    """
    global _config_cache
    if use_cache and _config_cache is not None:
        return _config_cache

    if config_path is None:
        config_path = Path(__file__).parent.parent / "config.yaml"

    yaml_data: dict = {}
    if Path(config_path).exists():
        with open(config_path) as f:
            yaml_data = yaml.safe_load(f) or {}

    # Load .env if present
    from dotenv import load_dotenv
    env_path = Path(__file__).parent.parent / ".env"
    if env_path.exists():
        load_dotenv(env_path)

    config = AppConfig(**yaml_data)

    if use_cache:
        _config_cache = config

    return config


def invalidate_config_cache() -> None:
    """Clear config cache, forcing next load_config() to reload."""
    global _config_cache
    _config_cache = None


def get_data_config(config: AppConfig | None = None) -> DataConfig:
    """Extract data sub-config. Type-safe, no manual get chains."""
    if config is None:
        config = load_config()
    return config.data
