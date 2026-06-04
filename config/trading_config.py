
"""
Production Trading System Configuration.
Single source of truth for all trading parameters.
"""
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional
import json
from pathlib import Path


@dataclass
class StrategyConfig:
    """Per-pair strategy configuration."""
    pair: str
    strategy_name: str  # 'ma_state', 'mean_reversion', 'trend_following'
    params: Dict
    enabled: bool = True
    allocation_pct: float = 0.5  # % of portfolio allocated

@dataclass  
class RiskConfig:
    max_drawdown_pct: float = 15.0
    risk_per_trade_pct: float = 2.0
    max_positions: int = 3
    max_leverage: float = 1.0
    daily_loss_limit_pct: float = 5.0
    require_confirmation: bool = True

@dataclass
class ExecutionConfig:
    sandbox: bool = True
    initial_capital: float = 10000.0
    commission: float = 0.001
    slippage: float = 0.0005
    min_order_value: float = 10.0

@dataclass
class DataConfig:
    timeframe: str = "1h"
    lookback_bars: int = 500  # bars to fetch for strategy
    refresh_interval_sec: int = 60  # how often to check for new data
    db_path: str = "db/cryptoquant.db"

@dataclass
class AlertConfig:
    telegram_enabled: bool = False
    console_enabled: bool = True
    log_file: str = "logs/trading.log"


# -------- Default Production Config --------

PRODUCTION_CONFIG = {
    "strategies": [
        {
            "pair": "TON/USDT",
            "strategy_name": "ma_state",
            "params": {
                "fast_ma_period": 15,
                "slow_ma_period": 60,
                "ma_type": "sma",
                "use_stop_loss": False
            },
            "enabled": True,
            "allocation_pct": 0.80
        },
        {
            "pair": "BTC/USDT",
            "strategy_name": "ma_state",
            "params": {
                "fast_ma_period": 100,
                "slow_ma_period": 300,
                "ma_type": "sma",
                "use_stop_loss": False
            },
            "enabled": True,
            "allocation_pct": 0.20
        },
    ],
    "risk": {
        "max_drawdown_pct": 15.0,
        "risk_per_trade_pct": 2.0,
        "max_positions": 2,
        "daily_loss_limit_pct": 5.0,
    },
    "execution": {
        "sandbox": True,
        "initial_capital": 10000,
        "commission": 0.001,
        "slippage": 0.0005,
    },
    "data": {
        "timeframe": "1h",
        "lookback_bars": 500,
        "refresh_interval_sec": 60,
    }
}


def load_config(path: Optional[str] = None) -> Dict:
    """Load trading config from file or use built-in defaults."""
    if path and Path(path).exists():
        with open(path) as f:
            return json.load(f)
    return PRODUCTION_CONFIG
